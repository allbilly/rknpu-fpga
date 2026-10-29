#!/usr/bin/env python3
"""Run the registered-RAM transfer/reset contract in both native simulators."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,time

def main():
    R=Path(__file__).resolve().parents[2];W=R/'build/tinystories-registered-memory'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');W.mkdir(parents=True)
    def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    files=[R/'rtl/tinystories/rk_shared_bram_regport.sv',R/'tests/tinystories/tb_shared_bram_regport.sv'];inputs={str(p):sha(p) for p in files}
    inputs[str(Path(__file__).resolve())]=sha(__file__)
    r=dict(status='RUNNING',scope='Registered shared RAM source/native only; no FPGA, timing or whole application claim',inputs=inputs,commands=[],hardware_accessed=False)
    def save():(W/'report.json').write_text(json.dumps(r,indent=2)+'\n')
    def run(name,argv,limit=600):
        assert all(sha(p)==h for p,h in inputs.items());start=time.monotonic()
        with (W/(name+'.log')).open('w') as log:
            child=subprocess.Popen(argv,cwd=R,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:rc=child.wait(timeout=limit)
            except BaseException:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                raise
        text=(W/(name+'.log')).read_text();r['commands'].append(dict(name=name,argv=argv,returncode=rc,seconds=time.monotonic()-start,log_sha256=sha(W/(name+'.log'))));save()
        assert rc==0,text[-5000:]
        assert not re.search(r'(?im)%Warning|warning:|error:|sorry:',text),text[-5000:]
        return text
    save()
    try:
        run('iverilog_version',['iverilog','-V']);run('vvp_version',['vvp','-V']);run('verilator_version',['verilator','--version'])
        run('iverilog_compile',['iverilog','-g2012','-Wall','-s','tb_shared_bram_regport','-o',str(W/'sim.vvp')]+list(map(str,files)))
        t=run('iverilog_run',['vvp',str(W/'sim.vvp')]);assert 'PASS shared_registered_bram transactions=134 stable_stalls reset_commit' in t
        run('verilator_compile',['verilator','--binary','--timing','--assert','-Wall','-j','2','--top-module','tb_shared_bram_regport','--Mdir',str(W/'obj'),'-o','sim']+list(map(str,files)))
        t=run('verilator_run',[str(W/'obj/sim')]);assert 'PASS shared_registered_bram transactions=133 stable_stalls reset_commit' in t
        assert all(sha(p)==h for p,h in inputs.items());r['status']='PASS_SHARED_REGISTERED_MEMORY_BOTH_SIMULATORS'
    except BaseException as error:r.update(status='FAIL',error=repr(error));raise
    finally:r['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save();(R/'build/current-tinystories-registered-memory.txt').write_text(str(W)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(W/'report.json'))))

if __name__=="__main__":
    main()
