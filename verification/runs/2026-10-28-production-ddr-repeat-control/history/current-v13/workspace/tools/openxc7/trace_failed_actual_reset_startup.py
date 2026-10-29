#!/usr/bin/env python3
"""Replay the frozen startup failure with a read-only supplementary observer.

Keep every original primitive/model/bench input and original fatal expectation.
Only add an observer root which reads the selected controller at clock+1ns.
Do not repair the failed fixture, force a producer, or claim startup acceptance.
Bind and revalidate the immediate failed native bundle, not its whole upstream
proof chain. No hardware input, constraints, live job or SHA256SUMS is changed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]
from pack_prefix_board import ROOT,digest,timestamp
from place_prefix_board import verify_bindings
from evidence import source_revision

PARENT=ROOT/'build/openxc7/prefix-actual-reset-startup-1791455659250174969/report.json'


def observer(cone):
    q={r['original_primitive']['connections']['Q'][0] for r in cone['controller_registers']}
    free={w:i for i,w in enumerate(sorted(set(map(int,cone['producer_cuts']))-q-{9}))}
    assert len(free)==968 and free[50677]==778
    fault=cone['producer_cuts']['50677'];c=fault['original_primitive']
    assert fault['cell']=='rk_mapped_cell_65539' and c['type']=='FDCE' and c['parameters']=={'INIT':'x'}
    assert c['connections']=={'C':[8],'CE':['1'],'CLR':[78107],'D':[61789],'Q':[50677]}
    base='tb_prefix_actual_reset_startup.'
    def bit(w):
        if w in ('0','1'):return "1'b"+w
        if w in free:return base+'actual.producer_input['+str(free[w])+']'
        return base+'actual.w_'+str(w)
    ds=[r['original_primitive']['connections']['D'][0] for r in cone['controller_registers'][:4]]
    codes=(52415,52417,52416,52530,51837,51440,50675,52481)
    assert all(w in free for w in codes)
    values=[base+'reset_chain',base+'demo_state','{'+','.join(bit(w) for w in reversed(ds))+'}',
            base+'controller_state',bit(50677),'{'+','.join(bit(w) for w in reversed(codes))+'}',
            '{'+base+'host_enable,'+base+'host_we}', '{'+base+'core_enable,'+base+'core_we}']
    text='''`timescale 1ns/1ps
module read_only_actual_reset_observer;
always begin
    @(posedge tb_prefix_actual_reset_startup.clk); #1;
    $display("TRACE_SELECTED_CONTROLLER t=%0t reset=%b state=%b next_state=%b storage=%b fault_cut=%b saved_code_cuts=%b A=%b B=%b", $time, '''+', '.join(values)+''');
end
endmodule
'''
    assert not re.search(r'\b(?:assign|initial|force|release|deposit|fatal|finish|stop)\b',text)
    return text


def main():
    out=ROOT/f'build/openxc7/failed-reset-readonly-trace-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='immediate_frozen_failure_bundle_admission',scope=__doc__,started_utc=timestamp(),
                supervisor_pid=os.getpid(),source={},commands=[],production_source_before=source_revision(),
                entire_upstream_chain_revalidated=False,read_only_failure_reproduced=False,
                startup_acceptance=False,hardware_input_modified=False,electrical_verified=False,
                timing_signoff=False,drc_signoff=False,bitstream_emitted=False,hardware_programmed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv):
        step=dict(label=label,argv=list(map(str,argv)),log=str(out/(label+'.log')),status='RUNNING',timeout_seconds=180)
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as p:
                step['pid']=p.pid;save()
                try:code=p.wait(timeout=180)
                except BaseException:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    p.wait();raise
            step['returncode']=code;return code,Path(step['log']).read_text()
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    try:
        parent=json.loads(PARENT.read_text());assert parent['status']=='FAIL' and parent['finished_utc']
        assert parent['actual_registers']==53 and parent['actual_unknown_producers']==968 and parent['actual_cone_cells']==1331
        commands={c['label']:c for c in parent['commands']}
        assert commands['negative']['status']=='PASS_EXPECTED_REAL_FINITE_NEGATIVE'
        assert commands['positive']['returncode']==1 and commands['positive']['status']=='FAIL'
        expected=Path(commands['positive']['log']).read_text()
        assert 'state=1010 index=000000000000' in expected and 'Time: 172000 ' in expected
        before={str(PARENT):digest(PARENT),**parent['execution_inputs']}
        before.update({str(ROOT/p):sha for p,sha in parent['artifacts'].items()})
        for p in (Path(__file__).resolve(),Path(sys.executable).resolve(),*(Path(shutil.which(n)).resolve() for n in ('iverilog','vvp'))):before[str(p)]=digest(p)
        verify_bindings(before);assert source_revision()==parent['production_source_before']
        report['source']=before
        cone=json.loads((PARENT.parent/'actual-53-register-reset-controller-cone.json').read_text())
        src=out/'read_only_observer.sv';src.write_text(observer(cone));shutil.copyfile(__file__,out/'executed_source.py')
        argv=commands['vendor_compile']['argv'].copy();binary=out/'observer.vvp'
        old=argv.index('-o')+1;argv[old]=str(binary);argv+=['-s','read_only_actual_reset_observer',str(src)]
        report.update(stage='unchanged_native_fixture_plus_read_only_observer',execution_inputs={**parent['execution_inputs'],str(src):digest(src)})
        code,text=run('observer_compile',argv);assert code==0 and not re.search(r'(?im)warning:|error:|sorry:',text)
        report['commands'][-1]['status']='PASS_TOOL_EXECUTION_ONLY'
        report['execution_inputs'][str(binary)]=digest(binary)
        code,text=run('original_positive_failure_with_observer',['vvp',binary])
        traces=[line for line in text.splitlines() if line.startswith('TRACE_SELECTED_CONTROLLER ')]
        assert code==1 and text.endswith(expected) and len(traces)==9
        assert all('fault_cut=x saved_code_cuts=xxxxxxxx' in line for line in traces)
        assert 't=151000 reset=111 state=0000 ' in traces[-2]
        assert 't=171000 reset=111 state=1010 ' in traces[-1]
        assert not re.search(r'(?im)warning:|error:|sorry:|deadline|timeout',text)
        report['commands'][-1]['status']='EXPECTED_UNCHANGED_NATIVE_FAILURE_WITH_READ_ONLY_OBSERVER'
        verify_bindings(before);verify_bindings(report['execution_inputs'])
        report['production_source_after']=source_revision();assert report['production_source_before']==report['production_source_after']
        report.update(status='REPRODUCED_FROZEN_STARTUP_FAILURE_WITH_READ_ONLY_TRACE_NOT_STARTUP_OR_FPGA_ACCEPTANCE',stage='complete',
                      read_only_failure_reproduced=True,observed_trace=traces)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
