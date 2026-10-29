#!/usr/bin/env python3
"""Compare both acknowledged 3 MHz transports on retained CH1 SRAM configuration.

Writes only an 8 KiB scratch region at the end of virtual CH0, outside LFM2's
image. Does not reprogram, recalibrate, clear ECC counters or touch flash.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import numpy as np
import fedora_run_ch1_jtag_lfm2 as old
from fedora_run_ch1_jtag_lfm2_fast import CommandTransport,bridge_tcl
from fedora_run_vivado_native_jtag import NativeLink,VIVADO
from fedora_program_ch1_sram import stop_group
from opentpu.host import regs as R,memcal,ddrcal


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('build','core','ecc-preparation','out','previous-run'):
        ap.add_argument('--'+name,required=True,type=Path)
    ap.add_argument('--tck-hz',type=int,choices=(3000000,6000000),default=3000000)
    a=ap.parse_args();out=a.out.resolve();core=a.core.resolve()
    old.require(not out.exists(),'Choose a fresh result directory');out.mkdir(parents=True)
    record=dict(status='STARTING',started_utc=datetime.now(timezone.utc).isoformat(),
                hardware_accessed=False,physical_model_verified=False,flash_written=False,
                fpga_programmed=False,calibration_restarted=False,counters_cleared=False,
                tck_hz=a.tck_hz,scratch_virtual_channel=0,scratch_offset=(1<<30)-65536,bytes_per_transfer=8192,trials=[])
    hw=bridge=None
    def save():
        p=out/'manifest.json.tmp';p.write_text(json.dumps(record,indent=2)+'\n');p.replace(out/'manifest.json')
    try:
        save();previous=json.loads((a.previous_run/'manifest.json').read_text())
        prior_model=json.loads((a.previous_run/'model/manifest.json').read_text())
        old.require(previous['programming']=='PASS_NATIVE_CH1_SRAM_INIT_DONE_AND_MAILBOX' and
                    prior_model['matmul']['exact_match'] and not prior_model.get('actual_partial_token_ids'),
                    'Retained image must have passed matmul; model must not have emitted tokens')
        bit,qualified=old.qualify(a.build.resolve(),core,a.ecc_preparation.resolve(),out)
        old.require(qualified['bitstream']==previous['qualification']['bitstream'],'Retained image receipt differs')
        record['qualified_image']=qualified
        for name in ('hw_server','openFPGALoader','xsdb','fxload'):
            old.require(subprocess.run(['pgrep','-x',name],stdout=subprocess.DEVNULL).returncode==1,'Cable owner: '+name)
        for port in (3122,3741):
            with socket.socket() as sock:old.require(sock.connect_ex(('127.0.0.1',port))!=0,'Port already owned')
        usb=subprocess.check_output(['lsusb'],text=True)
        old.require(sum('ID 03fd:' in line for line in usb.splitlines())==1,'Exactly one DLC10 required')
        record['usb_at_start']=usb
        clock_command='set_property PARAM.FREQUENCY 3000000 [current_hw_target]'
        old.require(old.TCL.count(clock_command)==1,'Native clock setting differs')
        tcl=old.TCL.replace(clock_command,f'set_property PARAM.FREQUENCY {a.tck_hz} [current_hw_target]')
        (out/'bridge.tcl').write_text(bridge_tcl(tcl))
        with (out/'hw-server.log').open('w') as log:
            hw=subprocess.Popen([str(VIVADO/'hw_server'),'-s','tcp::3122'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        env=dict(os.environ,OTPU_NATIVE_READY=str(out/'native-ready.txt'))
        # Attach to the retained configuration; never pass OTPU_NATIVE_BIT.
        for key in ('OTPU_NATIVE_BIT','OTPU_NATIVE_PROGRAM_STATUS'):env.pop(key,None)
        with (out/'vivado.log').open('w') as log:
            bridge=subprocess.Popen([str(VIVADO/'vivado'),'-mode','batch','-nojournal','-nolog','-source',str(out/'bridge.tcl')],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        record.update(status='ATTACHING_RETAINED_CH1_IMAGE',hardware_accessed=True);save()
        deadline=time.monotonic()+300
        while not (out/'native-ready.txt').exists():
            old.require(hw.poll() is None and bridge.poll() is None and time.monotonic()<deadline,'Native attach failed');time.sleep(.5)
        rng=np.random.default_rng(42)
        for trial in range(3):
            for name,cls,link_cls in [('three_rpc',old.CalibratedJtagTransport,old.LfmNativeLink),
                                      ('one_rpc',CommandTransport,NativeLink)]:
                t=cls(link=link_cls(),calibration_data=core)
                try:
                    old.check_marker(t)
                    state=t.reg_read(R.R_STATUS)
                    old.require(state&(R.ST_CALIB0|R.ST_CALIB1)==R.ST_CALIB0|R.ST_CALIB1 and
                                not state&(R.ST_RUN|R.ST_LOADING),'Retained CH1 must be calibrated and idle')
                    t.arm_calibration_guard();csr=memcal.csr(t);ch=ddrcal.Chan(csr,1)
                    before={k:ch.r(k) for k in ('ecc_enable','ecc_sec_errors','ecc_ded_errors')}
                    old.require(before==dict(ecc_enable=1,ecc_sec_errors=0,ecc_ded_errors=0),'CH1 ECC not clean')
                    data=rng.integers(0,256,8192,dtype=np.uint8);off=record['scratch_offset']
                    start=time.monotonic();t.mem_write(0,off,data);write_seconds=time.monotonic()-start
                    start=time.monotonic();got=t.mem_read(0,off,len(data));read_seconds=time.monotonic()-start
                    old.require(np.array_equal(got,data),'Physical scratch readback differs')
                    after={k:ch.r(k) for k in before};old.require(after==before,'ECC errors during benchmark')
                    record['trials'].append(dict(trial=trial,mode=name,bytes=len(data),write_seconds=write_seconds,read_seconds=read_seconds,exact_match=True,ecc_after=after));save()
                finally:t.close()
        summary={}
        for mode in ('three_rpc','one_rpc'):
            rows=[x for x in record['trials'] if x['mode']==mode]
            summary[mode]=dict(write_bytes_per_second=sum(x['bytes'] for x in rows)/sum(x['write_seconds'] for x in rows),
                              read_bytes_per_second=sum(x['bytes'] for x in rows)/sum(x['read_seconds'] for x in rows))
        record.update(status='PASS_PHYSICAL_CH1_JTAG_RPC_COMPARISON',summary=summary,
                      write_speedup=summary['one_rpc']['write_bytes_per_second']/summary['three_rpc']['write_bytes_per_second']);return 0
    except Exception as e:
        record.update(status='FAIL',error=repr(e));print(record['error'],flush=True);return 1
    finally:
        if bridge is not None and bridge.poll() is None:
            try:
                link=NativeLink(timeout=5);link.command('QUIT');link.close();bridge.wait(timeout=15)
            except (OSError,subprocess.TimeoutExpired):pass
        record['vivado_exit']=stop_group(bridge);record['hw_server_exit']=stop_group(hw)
        record['finished_utc']=datetime.now(timezone.utc).isoformat();save()


if __name__=='__main__':raise SystemExit(main())
