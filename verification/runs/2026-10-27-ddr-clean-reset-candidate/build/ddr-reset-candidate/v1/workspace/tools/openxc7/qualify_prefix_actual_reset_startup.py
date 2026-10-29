#!/usr/bin/env python3
"""Qualify actual mapped reset/controller startup in a finite vendor fixture.

Revalidate the completed binary physical-BRAM proof and its exact full-size
parents. Freshly census the unchanged 503128-cell input and trace the three
actual zero-INIT reset FDCEs, their three clear inverters and mapped buffered
external reset boundary. Keep all original 1328 controller cells and fifty
unknown-INIT FDCEs. Instantiate literal primitives with unchanged vendor models
and default 100ns GSR; there is no local FDCE/async-clear fold here.
Hold all remaining producer values X in a test-only fixture. Check cold startup,
two full 4096-write prefixes and asynchronous restart at three phases, with a
genuine finite wrong-golden negative. This is selected-controller fixture
acceptance, not full-board startup/data-value independence or FPGA signoff.
No raw command/input/model/old gate/live job or SHA256SUMS is modified.
"""
from collections import Counter
import inspect
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import resume_prefix_actual_bram_barrier_core_write as proof
import unisim_board_models as models
from audit_empty_output_pairs import source_shaped
from audit_prefix_bram_outputs import module_ports
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PARENT=ROOT/'build/openxc7/prefix-actual-bram-core-write-1791453537307521260/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_actual_reset_startup_control.py'
BENCH=ROOT/'tests/cmac/tb_prefix_actual_reset_startup.sv'
BOARD=ROOT/'fpga/cmac/ypcb_cmac_array_top.sv'
PASS='QUALIFIED_ACTUAL_53_REGISTER_VENDOR_DEFAULT_GSR_CONTROLLER_INITIALIZATION_AND_ASYNC_RESTART_FIXTURE_NOT_FULL_BOARD_STARTUP_OR_FPGA_SIGNOFF'
GLOBAL_REGISTERS={'reset_delay':2,'reset_n':1}
REGISTERS={**proof.previous.REGISTERS,**GLOBAL_REGISTERS}
WIDTHS={**proof.previous.WIDTHS,**GLOBAL_REGISTERS,'SYS_RSTN':1}
OUTPUTS=(*proof.previous.OUTPUTS,'SYS_RSTN')


def admit(before):
    cone,library=proof.admit(before)
    r=json.loads(PARENT.read_text())
    assert r['status']==proof.PASS and r['stage']=='complete' and r['finished_utc']
    assert r['full_target_parallel_products']==512 and r['native_induction_length']==1
    assert all(r[k] is True for k in ('physical_pin_read_barrier_proved_binary','physical_pin_port_ownership_proved_binary','physical_core_write_gating_proved_binary','initialization_host_data_independence_proved_binary'))
    assert r['full_board_startup_independence_proved'] is False and r['bitstream_emitted'] is False
    bind_report(PARENT,r,before);verify_bindings(before);verify_bindings(r['execution_inputs'])
    root=PARENT.parent
    assert (root/'actual-BRAM-core-write-clocked-model.v').read_text()==proof.strengthened_model(cone)
    assert (root/'unchanged_selected_controller_cells.v').read_bytes()==library
    commands={c['label']:c for c in r['commands']}
    for label,negative in (('negative',True),('positive',False)):
        c=commands[label];text=Path(c['log']).read_text();length=proof.previous.completed.previous.validate(text,c['returncode'],negative)
        witness=root/(label+'-counterexample.json')
        assert (root/(label+'.ys')).read_text()==proof.previous.script(root/'unchanged_selected_controller_cells.v',root/'actual-BRAM-core-write-clocked-model.v',negative,witness)
        if negative:assert json.loads(json.dumps(proof.previous.negative_trace(text,json.loads(witness.read_text()))))==r['real_temporal_negative']
        else:assert length==1 and not witness.exists()
    return cone


def reset_boundary(cell,pin,bit,wire,external_port):
    assert cell['type']=='IBUF' and pin=='O' and bit==0
    assert cell['connections']=={'I':[external_port],'O':[wire]}
    assert cell['port_directions']=={'I':'input','O':'output'}
    assert set(cell['parameters'])<={'IOSTANDARD','IBUF_LOW_PWR'}
    assert cell['parameters'].get('IOSTANDARD','LVCMOS18')=='LVCMOS18'
    assert cell['parameters'].get('IBUF_LOW_PWR','TRUE') in ('TRUE','FALSE')
    return 'EXACT_MAPPED_IBUF_OUTPUT_RESET_FIXTURE_BOUNDARY_NOT_IO_OR_ELECTRICAL_QUALIFICATION'


TRACE_NAMESPACE=dict(proof.previous.temporal.base.__dict__,REGISTERS=REGISTERS,WIDTHS=WIDTHS,OUTPUTS=OUTPUTS,reset_boundary=reset_boundary)
TRACE_SOURCE=source_shaped(proof.previous.temporal.TRACE_SOURCE,(
    ("        if cell['type'] in prior.state.coherent.RESET_PIN:\n",
     "        if wire==signals['SYS_RSTN'][0]:\n"
     "            role=reset_boundary(cell,pin,bit,wire,external_port)\n"
     "        elif cell['type'] in prior.state.coherent.RESET_PIN:\n"),
    ('def trace_controller(signals, driver, selected):','def trace_controller(signals, driver, selected, external_port):'),
    ("assert len(registers) == 50 and len({r['cell'] for r in registers}) == 50",
     "assert len(registers) == 53 and len({r['cell'] for r in registers}) == 53")))
exec(compile(TRACE_SOURCE,__file__+':strict-expanded-53-register-source-trace','exec'),TRACE_NAMESPACE)
trace_controller=TRACE_NAMESPACE['trace_controller']
ALIAS_NAMESPACE=dict(proof.previous.temporal.base.__dict__,WIDTHS={**proof.previous.SEMANTIC_WIDTHS,**GLOBAL_REGISTERS,'SYS_RSTN':1})
exec(compile(inspect.getsource(proof.previous.temporal.base.aliases),__file__+':literal-reset-aliases','exec'),ALIAS_NAMESPACE)


def aliases(logical,physical,original):
    result=ALIAS_NAMESPACE['aliases'](logical,physical)
    for name in proof.previous.temporal.WIDTHS:assert result[name]==original['signals'][name]
    for name in proof.previous.PIN_SIGNALS:result[name]=original['signals'][name]
    assert result['reset_delay']==[91958,91957] and result['reset_n']==result['demo.rst_n']==[15190]
    assert result['SYS_RSTN']==[9] and result['demo.memory.clk']==[8]
    return result


def reset_contract(cone,original):
    assert cone['controller_registers'][:50]==original['controller_registers']
    assert all(cone['cells'].get(n)==c for n,c in original['cells'].items())
    assert all(cone['producer_cuts'].get(w)==c for w,c in original['producer_cuts'].items())
    regs=cone['controller_registers'][50:]
    assert [(r['signal'],r['offset']) for r in regs]==[('reset_delay',0),('reset_delay',1),('reset_n',0)]
    clears=(63335,78349,78350)
    for r,q,d,clear in zip(regs,(91958,91957,15190),('1',91958,91957),clears):
        c=r['original_primitive'];proof.previous.temporal.base.validate_fold_register(c,[8])
        assert c['parameters']=={'INIT':'0'}
        assert c['connections']['Q']==[q] and c['connections']['D']==[d] and c['connections']['CE']==['1']
        assert c['connections']['CLR']==[clear]
    added=set(cone['cells'])-set(original['cells'])
    expected=dict(zip(('rk_mapped_cell_50988','rk_mapped_cell_64328','rk_mapped_cell_64329'),clears))
    assert added==set(expected)
    for name,clear in expected.items():
        cell=cone['cells'][name]
        assert cell['type']=='INV' and cell['parameters']=={}
        assert cell['connections']=={'I':[9],'O':[clear]} and cell['port_directions']=={'I':'input','O':'output'}
    assert len(cone['controller_registers'])==53
    return dict(reset_registers=regs,actual_clear_inverters=expected,buffered_external_reset_wire=9,
                reset_delay_lsb_first=[91958,91957],outer_reset_wire=15190,
                literal_global_INIT_zero=True,literal_controller_INIT_unknown=True,
                common_clock_wire=8,three_positive_edges_for_binary_release=True,
                physical_reset_pin_or_electrical_qualification=False)


def vendor_module(cone):
    regs=cone['controller_registers'];q={r['original_primitive']['connections']['Q'][0] for r in regs}
    cuts=set(map(int,cone['producer_cuts']));external=cone['signals']['SYS_RSTN'][0]
    free={w:i for i,w in enumerate(sorted(cuts-q-{external}))};assert len(free)==968
    clock,=cone['signals']['demo.memory.clk']
    def bit(w):
        if w in ('0','1'):return "1'b"+w
        if w==clock:return 'clk'
        if w==external:return 'buffered_reset_n'
        if w in free:return 'producer_input['+str(free[w])+']'
        return 'w_'+str(w)
    def bus(bits):return '{'+','.join(bit(w) for w in reversed(bits))+'}'
    lines=['module actual_prefix_reset_controller(input clk,buffered_reset_n,input [967:0] producer_input,',
           'output [49:0] controller_state,output [2:0] reset_chain,output [3:0] demo_state,output [11:0] word_index,',
           'output host_enable,host_we,core_enable,core_we);']
    cells={**cone['cells'],**{r['cell']:r['original_primitive'] for r in regs}}
    wires={w for c in cells.values() for bits in c['connections'].values() for w in bits if type(w) is int and w not in free and w not in (clock,external)}
    lines.extend('wire w_'+str(w)+';' for w in sorted(wires))
    for i,(name,c) in enumerate(sorted(cells.items())):
        kind=c['type'];assert kind=='FDCE' or kind in models.PINS and kind not in ('FDPE','FDRE','FDSE','RAMB18E1','RAMB36E1')
        params=[]
        for key,value in sorted(c['parameters'].items()):
            assert re.fullmatch('[01x]+',value)
            params.append('.'+key+'('+str(len(value))+"'b"+value+')')
        parameter=' #('+','.join(params)+')' if params else ''
        lines.append(kind+parameter+' actual_'+str(i)+'('+','.join('.'+pin+'('+bus(bits)+')' for pin,bits in sorted(c['connections'].items()))+');')
    outputs={'controller_state':[r['original_primitive']['connections']['Q'][0] for r in regs[:50]],
             'reset_chain':cone['signals']['reset_delay']+cone['signals']['reset_n'],
             'demo_state':cone['signals']['demo.state'],'word_index':cone['signals']['demo.index'],
             'host_enable':cone['signals']['bram.host_enable'],'host_we':cone['signals']['bram.host_we'],
             'core_enable':cone['signals']['bram.core_enable'],'core_we':cone['signals']['bram.core_we']}
    lines.extend('assign '+name+'='+bus(bits)+';' for name,bits in outputs.items())
    text='\n'.join(lines+['endmodule'])+'\n'
    assert not re.search(r'\b(?:initial|force|assume|anyseq|anyconst)\b',text)
    assert text.count('FDCE #')==53
    return text,len(free)


def marker(count):
    return f'PASS actual selected controller vendor startup registers=53 unknown_producers={count} default_gsr=100ns physical_A_writes=10241 complete_prefixes=2 asynchronous_resets=3; not full-board startup or physical signoff'


def render_bench(count):
    text=BENCH.read_text();assert text.count('@OTHER_LAST@')==1 and text.count('@OTHER_BITS@')==1
    return text.replace('@OTHER_LAST@',str(count-1)).replace('@OTHER_BITS@',str(count))


def validate_native(text,code,negative,bench,count):
    assert not re.search(r'(?im)warning:|error:|sorry:|deadline|timeout',text)
    if negative:
        fatals=[line for line in text.splitlines() if line.startswith('FATAL:')]
        assert code==1 and len(fatals)==1 and 'actual reset startup mismatch phase=after_gsr got=000 expected=100' in fatals[0]
        assert marker(count) not in text and 'Time: 102000 ' in text
    else:
        finish=[i+1 for i,line in enumerate(bench.read_text().splitlines()) if line.strip()=='$finish;'];assert len(finish)==1
        assert code==0 and text.count(marker(count))==1 and not re.search(r'(?m)^FATAL:',text)
        assert len(text.splitlines())==2 and re.fullmatch(re.escape(str(bench))+':'+str(finish[0])+r': \$finish called at [0-9]+ \(1ps\)',text.splitlines()[1])


def main():
    out=ROOT/f'build/openxc7/prefix-actual-reset-startup-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),source={},commands=[],
                python_version=sys.version,seed=None,production_source_before=source_revision(),full_target_parallel_products=512,
                actual_vendor_controller_startup_fixture_passed=False,full_board_startup_independence_proved=False,
                four_state_library_equivalence=False,initialization_liveness_proved=False,RAM_data_value_independence_proved=False,
                full_board_numerical_acceptance=False,physical_fit_verified=False,timing_signoff=False,electrical_verified=False,
                drc_signoff=False,bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False,native_PNR_executed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv,negative=None):
        step=dict(label=label,argv=list(map(str,argv)),cwd=str(ROOT),log=str(out/(label+'.log')),timeout_seconds=180,status='RUNNING')
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid;save()
                try:code=process.wait(timeout=180)
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait();step['returncode']=process.returncode;raise
            step['returncode']=code;text=Path(step['log']).read_text()
            if negative is not None:validate_native(text,code,negative,bench,count)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_FINITE_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py');shutil.copyfile(BENCH,out/'executed_bench_template.sv')
        before={};original=admit(before)
        files={Path(__file__).resolve(),CONTROL,BENCH,BOARD,Path(sys.executable).resolve(),*(Path(shutil.which(n)).resolve() for n in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for p in files:
            sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        report['source']=before;verify_bindings(before)
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        for name in ('iverilog','vvp'):report[name+'_version']=run(name+'_version',[name,'-V']).splitlines()[0]
        report['stage']='fresh_full_census_and_53_register_reset_controller_trace';save();start=time.monotonic()
        prepared=json.loads(proof.previous.temporal.base.prior.state.raw.PREPARED.read_text());physical=ROOT/prepared['pack_input']
        selected=json.loads(proof.previous.wiring.SELECTED.read_text())
        hierarchy=proof.previous.wiring.HIERARCHY
        with hierarchy.open('rb') as a,mmap.mmap(a.fileno(),0,access=mmap.ACCESS_READ) as logical,physical.open('rb') as b,mmap.mmap(b.fileno(),0,access=mmap.ACCESS_READ) as actual:
            signals=aliases(logical,actual,original);drivers,census=proof.previous.temporal.base.prior.state.raw.driver_index(actual,original['full_primitive_counts'])
            ports=module_ports(actual);assert ports['SYS_RSTN']['direction']=='input' and len(ports['SYS_RSTN']['bits'])==1
            external,=ports['SYS_RSTN']['bits']
            def driver(w):
                assert w in drivers
                begin,end,name,pin,bit,direction=drivers[w];assert direction=='output'
                c=json.loads(b'{'+actual[begin+1:end]+b'}')[name];return name,c,pin,bit
            cone=trace_controller(signals,driver,selected,external)
        del drivers;cone['full_primitive_counts']=census
        contract=reset_contract(cone,original);module_text,count=vendor_module(cone)
        report.update(actual_registers=53,actual_unknown_producers=count,actual_cone_cells=len(cone['cells']),actual_full_primitive_counts=census,
                      actual_reset_contract=contract,actual_trace_seconds=round(time.monotonic()-start,3),stage='actual_vendor_controller_fixture')
        (out/'actual-53-register-reset-controller-cone.json').write_text(json.dumps(cone,indent=2,sort_keys=True)+'\n')
        source=out/'actual_vendor_controller.v';source.write_text(module_text)
        bench=out/'tb_prefix_actual_reset_startup.sv';bench.write_text(render_bench(count))
        kinds={c['type'] for c in cone['cells'].values()}|{'FDCE'}
        pinned=models.selected_models(kinds);copies=[]
        for p,sha in pinned.items():
            assert digest(p)==sha;before[str(p.resolve())]=sha
            target=out/'models'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
            if target.suffix=='.v':copies.append(target)
        binary=out/'controller.vvp';execution={str(p):digest(p) for p in (source,bench,*copies)};report['execution_inputs']=execution
        run('vendor_compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_actual_reset_startup','-s','glbl','-o',binary,*copies,source,bench])
        execution[str(binary)]=digest(binary)
        run('negative',['vvp',binary,'+NEGATIVE=1'],True);verify_bindings(before);verify_bindings(execution)
        run('positive',['vvp',binary],False);verify_bindings(before);verify_bindings(execution)
        report['production_source_after']=source_revision();assert report['production_source_before']==report['production_source_after']
        report.update(status=PASS,stage='complete',actual_vendor_controller_startup_fixture_passed=True,
                      literal_53_FDCE_instances_and_default_GSR_preserved=True,actual_completed_initialization_prefixes=2,
                      actual_initialization_writes_checked=10241,actual_asynchronous_reset_fixture_phases=3)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
