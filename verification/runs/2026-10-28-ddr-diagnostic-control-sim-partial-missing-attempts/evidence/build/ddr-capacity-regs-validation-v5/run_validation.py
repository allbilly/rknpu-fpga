#!/usr/bin/env python3
"""Run source-bound private AXI-Lite register-bank tests with Icarus and Verilator."""
import datetime, hashlib, json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path('/home/fedora/rknpu-fpga')
HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / 'source/rk_ddr_capacity_regs.sv'
TB = HERE / 'source/tb_capacity_regs.sv'
OUT = HERE / 'results'
TIMEOUT = 300

def digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def run(name, argv, expected_rc=0, expected_text=None, forbidden_text=None):
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t0 = time.monotonic()
    p = subprocess.run(argv, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors='replace', timeout=TIMEOUT, check=False)
    elapsed = time.monotonic() - t0
    stdout_path = OUT / f'{name}.stdout.log'; stderr_path = OUT / f'{name}.stderr.log'
    stdout_path.write_text(p.stdout); stderr_path.write_text(p.stderr)
    combined = p.stdout + p.stderr
    if p.returncode != expected_rc:
        raise RuntimeError(f'{name}: return code {p.returncode}, expected {expected_rc}; stdout={stdout_path} stderr={stderr_path}')
    if expected_text and expected_text not in combined:
        raise RuntimeError(f'{name}: required diagnostic/marker missing; stdout={stdout_path} stderr={stderr_path}')
    if forbidden_text and forbidden_text in combined:
        raise RuntimeError(f'{name}: forbidden text present; stdout={stdout_path} stderr={stderr_path}')
    return {'name':name,'argv':argv,'cwd':str(HERE),'started_utc':start,
            'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'returncode':p.returncode,'expected_returncode':expected_rc,'wall_seconds':elapsed,
            'stdout_path':str(stdout_path),'stdout_sha256':digest(stdout_path),
            'stderr_path':str(stderr_path),'stderr_sha256':digest(stderr_path),
            'stdout':p.stdout,'stderr':p.stderr}

def main():
    manifest = json.loads((HERE/'frozen-inputs.json').read_text())
    for p, expected in manifest['inputs'].items():
        if digest(HERE/p) != expected:
            raise RuntimeError('frozen input changed before validation: '+p)
    report={'schema':'capacity-regs-private-validation-v1','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'status':'RUNNING','hardware_executed':False,'vivado_executed':False,
            'physical_capacity_qualified':False,'timeout_seconds_per_command':TIMEOUT,
            'frozen_inputs_sha256':digest(HERE/'frozen-inputs.json'),'commands':[],'case_summary':[]}
    (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    tools={'iverilog':'/home/linuxbrew/.linuxbrew/bin/iverilog','vvp':'/home/linuxbrew/.linuxbrew/bin/vvp',
           'verilator':'/home/linuxbrew/.linuxbrew/bin/verilator'}
    try:
        for simulator in ['iverilog','verilator']:
            version_argv=[tools[simulator],'-V'] if simulator=='iverilog' else [tools[simulator],'--version']
            if simulator=='iverilog':
                c=run('iverilog_version',version_argv); report['commands'].append(c)
                c=run('vvp_version',[tools['vvp'],'-V']); report['commands'].append(c)
                report['tool_versions']={'iverilog':c['stdout'] or c['stderr']}
                compile_argv=[tools['iverilog'],'-g2012','-Wall','-s','tb_capacity_regs','-o',str(OUT/'capacity_regs.vvp'),str(SRC),str(TB)]
                c=run('iverilog_compile_main',compile_argv); report['commands'].append(c)
                c=run('iverilog_main',[tools['vvp'],str(OUT/'capacity_regs.vvp')],expected_text='PASS capacity_regs checks=');
                report['commands'].append(c); report['case_summary'].append({'simulator':simulator,'kind':'main','marker':c['stdout'].splitlines()[-2]})
                for suffix,param in [('bad_base',"-Ptb_capacity_regs_badparams.BAD_BASE=1"),('bad_span',"-Ptb_capacity_regs_badparams.BAD_SPAN=2147483712")]:
                    obj=OUT/f'{suffix}.vvp'
                    c=run(f'iverilog_compile_{suffix}',[tools['iverilog'],'-g2012','-Wall','-s','tb_capacity_regs_badparams',param,'-o',str(obj),str(SRC),str(TB)]); report['commands'].append(c)
                    c=run(f'iverilog_{suffix}',[tools['vvp'],str(obj)],expected_rc=1,
                          expected_text='Capacity CSR metadata needs aligned nonempty31-bit span',forbidden_text='BAD_PARAMETER_TEST_FAILED_TO_FATAL')
                    report['commands'].append(c); report['case_summary'].append({'simulator':simulator,'kind':suffix,'expected_fatal':True})
            else:
                c=run('verilator_version',version_argv); report['commands'].append(c); report['tool_versions']={'verilator':c['stdout']}
                mdir=OUT/'verilator-main';
                compile_argv=[tools['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_regs','-j','2','--Mdir',str(mdir),str(SRC),str(TB)]
                c=run('verilator_compile_main',compile_argv); report['commands'].append(c)
                c=run('verilator_main',[str(mdir/'Vtb_capacity_regs')],expected_text='PASS capacity_regs checks=');
                report['commands'].append(c); report['case_summary'].append({'simulator':simulator,'kind':'main','marker':c['stdout'].splitlines()[-2]})
                for suffix,param in [('bad_base','-GBAD_BASE=1'),('bad_span','-GBAD_SPAN=2147483712')]:
                    mdir=OUT/f'verilator-{suffix}'
                    compile_argv=[tools['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_regs_badparams',param,'-j','2','--Mdir',str(mdir),str(SRC),str(TB)]
                    c=run(f'verilator_compile_{suffix}',compile_argv); report['commands'].append(c)
                    c=run(f'verilator_{suffix}',[str(mdir/'Vtb_capacity_regs_badparams')],expected_rc=1,
                          expected_text='Capacity CSR metadata needs aligned nonempty31-bit span',forbidden_text='BAD_PARAMETER_TEST_FAILED_TO_FATAL')
                    report['commands'].append(c); report['case_summary'].append({'simulator':simulator,'kind':suffix,'expected_fatal':True})
        for p, expected in manifest['inputs'].items():
            if digest(HERE/p) != expected:
                raise RuntimeError('frozen input changed during validation: '+p)
        report['sources_unchanged']=True; report['status']='PASS_PRIVATE_AXI_LITE_REGISTER_CONTRACT_SIMULATION';
    except Exception as exc:
        report['failure']=repr(exc); report['status']='FAIL_PRIVATE_AXI_LITE_REGISTER_CONTRACT_SIMULATION'
        raise
    finally:
        report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'commands':len(report['commands']),'cases':report['case_summary']},sort_keys=True))

if __name__=='__main__': main()
