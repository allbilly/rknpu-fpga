#!/usr/bin/env python3
"""Validate the private complete capacity-service composition with modeled AXI slaves."""
import datetime,hashlib,json,pathlib,subprocess,time

HERE=pathlib.Path(__file__).resolve().parent
SRC=HERE/'source'
TB=SRC/'tb_ddr_capacity_service.sv'
OUT=HERE/'results';OUT.mkdir(parents=True,exist_ok=True)
TIMEOUT=300
TOOLS={'iverilog':'/home/linuxbrew/.linuxbrew/bin/iverilog','vvp':'/home/linuxbrew/.linuxbrew/bin/vvp','verilator':'/home/linuxbrew/.linuxbrew/bin/verilator'}
RTL=['rk_ddr_capacity_service.sv','rk_ddr_capacity_owner.sv','rk_ddr_capacity_regs.sv','rk_ddr_diagnostic_mux.sv',
     'rk_ddr_capacity_pattern.sv','rk_ddr_capacity_sweep.sv','rk_ddr_capacity_axi.sv','rk_mig_write_fence.sv',
     'rk_mig_ecc_monitor.sv','rk_ddr_capacity_bist.sv']
PROFILES=[('base0_256',0,256),('base1000_512',4096,512)]

def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def run(name,argv,expected_rc=0,required=None,forbidden=None):
    start=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.monotonic()
    p=subprocess.run(argv,cwd=HERE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',timeout=TIMEOUT,check=False)
    elapsed=time.monotonic()-t;op=OUT/f'{name}.stdout.log';ep=OUT/f'{name}.stderr.log';op.write_text(p.stdout);ep.write_text(p.stderr)
    text=p.stdout+p.stderr
    if p.returncode!=expected_rc:raise RuntimeError(f'{name}: returncode {p.returncode}, expected {expected_rc}; stdout={op} stderr={ep}')
    if required and required not in text:raise RuntimeError(f'{name}: required PASS marker missing; stdout={op} stderr={ep}')
    if forbidden and forbidden in text:raise RuntimeError(f'{name}: forbidden text present; stdout={op} stderr={ep}')
    return {'name':name,'argv':argv,'cwd':str(HERE),'started_utc':start,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'returncode':p.returncode,'expected_returncode':expected_rc,'wall_seconds':elapsed,'stdout_path':str(op),'stdout_sha256':sha(op),
      'stderr_path':str(ep),'stderr_sha256':sha(ep),'stdout':p.stdout,'stderr':p.stderr}

def main():
    frozen=json.loads((HERE/'frozen-inputs.json').read_text())
    for rel,digest in frozen['inputs'].items():
        if sha(HERE/rel)!=digest:raise RuntimeError('frozen source/bench/runner changed before run: '+rel)
    report={'schema':'ddr-capacity-service-integration-private-v1','status':'RUNNING',
      'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'timeout_seconds_per_command':TIMEOUT,
      'frozen_inputs_sha256':sha(HERE/'frozen-inputs.json'),'commands':[],'profiles':[],
      'hardware_executed':False,'vivado_executed':False,'physical_capacity_qualified':False,
      'scope':'Full private service/owner/regs/mux/BIST/fence/ECC composition against behavioral AXI memory and ECC-control models. Not actual MIG/PHY or physical DDR qualification.'}
    (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    try:
      c=run('iverilog_version',[TOOLS['iverilog'],'-V']);report['commands'].append(c);report['tool_versions']={'iverilog':c['stdout'].splitlines()[0]}
      c=run('vvp_version',[TOOLS['vvp'],'-V']);report['commands'].append(c);report['tool_versions']['vvp']=c['stderr'].splitlines()[0]
      c=run('verilator_version',[TOOLS['verilator'],'--version']);report['commands'].append(c);report['tool_versions']['verilator']=c['stdout'].strip()
      sources=[str(SRC/n) for n in RTL]+[str(TB)]
      for simulator in ['iverilog','verilator']:
        for profile,base,span in PROFILES:
          name=f'{simulator}_{profile}'
          if simulator=='iverilog':
            image=OUT/f'{name}.vvp'
            argv=[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_ddr_capacity_service',
              f'-Ptb_ddr_capacity_service.TB_BASE={base}',f'-Ptb_ddr_capacity_service.TB_SPAN={span}','-o',str(image)]+sources
          else:
            mdir=OUT/f'{name}-obj'
            argv=[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_ddr_capacity_service','-j','2','--Mdir',str(mdir),
              f"-GTB_BASE=31'd{base}",f"-GTB_SPAN=32'd{span}"]+sources
          c=run(name+'_compile',argv);report['commands'].append(c)
          exe=[TOOLS['vvp'],str(OUT/f'{name}.vvp')] if simulator=='iverilog' else [str(OUT/f'{name}-obj/Vtb_ddr_capacity_service')]
          c=run(name+'_simulation',exe,required='PASS capacity_service');report['commands'].append(c)
          marker=next(line for line in c['stdout'].splitlines() if line.startswith('PASS capacity_service'))
          report['profiles'].append({'simulator':simulator,'profile':profile,'base_addr':base,'span_bytes':span,'marker':marker})
      for rel,digest in frozen['inputs'].items():
        if sha(HERE/rel)!=digest:raise RuntimeError('frozen source/bench/runner changed during run: '+rel)
      report['sources_unchanged']=True;report['status']='PASS_PRIVATE_CAPACITY_SERVICE_MODELED_AXI_INTEGRATION'
    except Exception as e:
      report['failure']=repr(e);report['status']='FAIL_PRIVATE_CAPACITY_SERVICE_MODELED_AXI_INTEGRATION';raise
    finally:
      report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
      (HERE/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'commands':len(report['commands']),'profiles':report['profiles']},sort_keys=True))

if __name__=='__main__':main()
