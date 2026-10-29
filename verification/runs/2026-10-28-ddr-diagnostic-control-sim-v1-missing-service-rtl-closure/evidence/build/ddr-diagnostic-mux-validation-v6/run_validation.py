#!/usr/bin/env python3
"""Source-bound Icarus/Verilator controls for the private two-master mux leaf."""
import datetime, hashlib, json, pathlib, subprocess, time

HERE=pathlib.Path(__file__).resolve().parent
OUT=HERE/'results'
OUT.mkdir(parents=True,exist_ok=True)
SRC=HERE/'source/rk_ddr_diagnostic_mux.sv'
TB=HERE/'source/tb_ddr_diagnostic_mux.sv'
TB_BAD=HERE/'source/tb_ddr_diagnostic_mux_badparams.sv'
TIMEOUT=300
TOOLS={'iverilog':'/home/linuxbrew/.linuxbrew/bin/iverilog','vvp':'/home/linuxbrew/.linuxbrew/bin/vvp','verilator':'/home/linuxbrew/.linuxbrew/bin/verilator'}
CONFIGS=[('memory',31,512,4),('control',32,32,1)]
BAD_PARAMS=[('bad_data_granularity','BAD_DATA_WIDTH',10),('bad_data_odd','BAD_DATA_WIDTH',9)]
VERILATOR_EXTRA_BAD_PARAMS=[('bad_addr','BAD_ADDR_WIDTH',0),('bad_data_small','BAD_DATA_WIDTH',7),('bad_id','BAD_ID_WIDTH',0)]

def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def run(name,argv,expected_rc=0,required=None,forbidden=None):
    start=datetime.datetime.now(datetime.timezone.utc).isoformat(); t=time.monotonic()
    p=subprocess.run(argv,cwd=HERE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',timeout=TIMEOUT,check=False)
    elapsed=time.monotonic()-t; op=OUT/f'{name}.stdout.log'; ep=OUT/f'{name}.stderr.log'; op.write_text(p.stdout);ep.write_text(p.stderr)
    text=p.stdout+p.stderr
    if p.returncode!=expected_rc: raise RuntimeError(f'{name}: returncode {p.returncode}, expected {expected_rc}; stdout={op} stderr={ep}')
    if required and required not in text: raise RuntimeError(f'{name}: required marker missing; stdout={op} stderr={ep}')
    if forbidden and forbidden in text: raise RuntimeError(f'{name}: forbidden marker present; stdout={op} stderr={ep}')
    return {'name':name,'argv':argv,'cwd':str(HERE),'started_utc':start,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'returncode':p.returncode,'expected_returncode':expected_rc,'wall_seconds':elapsed,'stdout_path':str(op),'stdout_sha256':sha(op),
      'stderr_path':str(ep),'stderr_sha256':sha(ep),'stdout':p.stdout,'stderr':p.stderr}

def main():
    manifest=json.loads((HERE/'frozen-inputs.json').read_text())
    for p,d in manifest['inputs'].items():
        if sha(HERE/p)!=d: raise RuntimeError('frozen input changed before run: '+p)
    report={'schema':'ddr-diagnostic-mux-private-validation-v1','status':'RUNNING','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'timeout_seconds_per_command':TIMEOUT,'frozen_inputs_sha256':sha(HERE/'frozen-inputs.json'),'commands':[],'main_results':[],'parameter_results':[],
      'hardware_executed':False,'vivado_executed':False,'physical_capacity_qualified':False,
      'scope':'Standalone mux leaf: combinational field/handshake routing only; selector ownership is external.'}
    (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    try:
      c=run('iverilog_version',[TOOLS['iverilog'],'-V']);report['commands'].append(c);report['tool_versions']={'iverilog':c['stdout'].splitlines()[0]}
      c=run('vvp_version',[TOOLS['vvp'],'-V']);report['commands'].append(c);report['tool_versions']['vvp']=c['stderr'].splitlines()[0]
      c=run('verilator_version',[TOOLS['verilator'],'--version']);report['commands'].append(c);report['tool_versions']['verilator']=c['stdout'].strip()
      for simulator in ['iverilog','verilator']:
        for cfg,aw,dw,iw in CONFIGS:
          name=f'{simulator}_{cfg}'
          if simulator=='iverilog':
            obj=OUT/f'{name}.vvp'
            argv=[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_ddr_diagnostic_mux',
              f'-Ptb_ddr_diagnostic_mux.ADDR_WIDTH={aw}',f'-Ptb_ddr_diagnostic_mux.DATA_WIDTH={dw}',f'-Ptb_ddr_diagnostic_mux.ID_WIDTH={iw}',
              '-o',str(obj),str(SRC),str(TB)]
          else:
            mdir=OUT/f'{name}-obj'
            argv=[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_ddr_diagnostic_mux','-j','2','--Mdir',str(mdir),
              f'-GADDR_WIDTH={aw}',f'-GDATA_WIDTH={dw}',f'-GID_WIDTH={iw}',str(SRC),str(TB)]
          c=run(name+'_compile',argv);report['commands'].append(c)
          exe=[TOOLS['vvp'],str(OUT/f'{name}.vvp')] if simulator=='iverilog' else [str(OUT/f'{name}-obj/Vtb_ddr_diagnostic_mux')]
          c=run(name+'_sim',exe,required=f'PASS diagnostic_mux checks=');report['commands'].append(c)
          marker=next(x for x in c['stdout'].splitlines() if x.startswith('PASS diagnostic_mux checks='))
          report['main_results'].append({'simulator':simulator,'configuration':cfg,'addr_width':aw,'data_width':dw,'id_width':iw,'marker':marker})
        bad_params=BAD_PARAMS + (VERILATOR_EXTRA_BAD_PARAMS if simulator=='verilator' else [])
        for label,param,value in bad_params:
          name=f'{simulator}_{label}'
          if simulator=='iverilog':
            obj=OUT/f'{name}.vvp'; override=f'-Ptb_ddr_diagnostic_mux_badparams.{param}={value}'
            argv=[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_ddr_diagnostic_mux_badparams',override,'-o',str(obj),str(SRC),str(TB_BAD)]
          else:
            mdir=OUT/f'{name}-obj'; override=f'-G{param}={value}'
            argv=[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_ddr_diagnostic_mux_badparams',override,'-j','2','--Mdir',str(mdir),str(SRC),str(TB_BAD)]
          c=run(name+'_compile',argv);report['commands'].append(c)
          exe=[TOOLS['vvp'],str(OUT/f'{name}.vvp')] if simulator=='iverilog' else [str(OUT/f'{name}-obj/Vtb_ddr_diagnostic_mux_badparams')]
          c=run(name+'_expected_fatal',exe,expected_rc=1,required='Diagnostic mux needs positive address/ID widths and byte-granular data',forbidden='BAD_PARAMETER_TEST_FAILED_TO_FATAL')
          report['commands'].append(c);report['parameter_results'].append({'simulator':simulator,'case':label,'parameter':param,'value':value,'compile_returncode':0,'expected_fatal_returncode':1})
      for p,d in manifest['inputs'].items():
        if sha(HERE/p)!=d:raise RuntimeError('frozen input changed during run: '+p)
      report['sources_unchanged']=True;report['status']='PASS_PRIVATE_DIAGNOSTIC_MUX_ROUTING_SIMULATION_ONLY'
    except Exception as e:
      report['failure']=repr(e);report['status']='FAIL_PRIVATE_DIAGNOSTIC_MUX_ROUTING_SIMULATION_ONLY';raise
    finally:
      report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
      (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'commands':len(report['commands']),'main_results':report['main_results'],'parameter_tests':len(report['parameter_results'])},sort_keys=True))

if __name__=='__main__':main()
