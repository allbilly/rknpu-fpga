#!/usr/bin/env python3
"""Fresh full-working-memory primitive overwrite/startup-state qualification.

Use the two actual RAMB36E1 records, all actual parameter values and literal
data/parity/address/clock/constant-pin bindings from the full C32/K16 input.
Three test-only startup parameter views: unchanged mapped X, literal encoder
zero policy, and a counterfactual all-one assignment to only unknown INIT/
initial-output symbols. Preserve every unconsumed X input. Execute unchanged
pinned vendor models with default GSR and a real one-bit read-golden negative.
Sweep all 4096 words before/after host/core writes, READ_FIRST, concurrent
different-address reads, disabled-port retention and reinitialization.
This is qualification at actual primitive input pins, not board-controller
ownership/write-before-read/startup proof, numerical/physical or hardware
acceptance. No RTL/netlist/live job or old gate is edited. No SHA256SUMS.
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

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
from audit_prefix_memory_wiring import verify_wiring, CONSUMER, SELECTED, ROOT, ROM, MODEL
from audit_prefix_bram_control_wiring import PARENT as WIRING, control_roots, binary_control_contract
from audit_prefix_config_contract import bram_contract
from place_prefix_board import bind_report, verify_bindings
from pack_prefix_board import digest,timestamp
from evidence import source_revision
import unisim_board_models as models

CONTROL_PARENT=ROOT/'build/openxc7/prefix-bram-control-wiring-1791422081130315089/report.json'
ADDRESS=ROOT/'build/openxc7/prefix-bram-address-selected-binary-resume-1791439177232717008/report.json'
BENCH=ROOT/'tests/cmac/tb_prefix_working_bram_overwrite.sv'
CONTROL=ROOT/'tests/cmac/test_prefix_working_bram_overwrite_control.py'
MARKER='PASS actual working BRAM overwrite configurations=2 variants=3 default_gsr=100ns cold_words=4096 writes=12288 reads=20480 read_first=12288 retention=34; not board startup or physical acceptance'
PASS='PASS_ACTUAL_TWO_WORKING_BRAM_CONFIGURATIONS_THREE_STARTUP_VIEWS_COMPLETE_OVERWRITE_CORPUS_ONLY_NOT_BOARD_STARTUP_OR_SIGNOFF'


def params_for_view(cell,view):
    bram_contract(cell)
    assert view in ('mapped','zero','one')
    result=dict(cell['parameters'])
    changed={}
    for key,value in cell['parameters'].items():
        if re.fullmatch(r'INITP?_[0-9A-F]{2}|INIT_[AB]|SRVAL_[AB]',key):
            replacement=value if view=='mapped' else value.replace('x','0' if view=='zero' else '1')
            result[key]=replacement
            if replacement!=value:changed[key]=dict(original=value,replacement=replacement,unknown_bits=value.count('x'))
        else:assert result[key]==value
    return result,changed


def wrapper(brams,signals,controls,view):
    """Exact primitive pin incidence at an explicitly declared unit-test boundary."""
    assert len(brams)==2
    expressions={}
    def bus_alias(name,logical):
        for bit,wire in enumerate(signals[name]):
            assert wire not in expressions,'Aliased distinct primitive boundary inputs'
            expressions[wire]=logical+'['+str(bit)+']'
    for name,logical in (('demo.memory.host_index','host_index'),('demo.memory.host_wdata','host_wdata'),
                         ('demo.memory.translated','core_index'),('demo.mem_req_wdata','core_wdata'),
                         ('demo.memory.host_rdata','host_rdata'),('demo.mem_rsp_rdata','core_rdata')):
        bus_alias(name,logical)
    assert len(signals['demo.memory.clk'])==1
    expressions[signals['demo.memory.clk'][0]]='clk'
    expressions[controls['host_fire']]='host_enable';expressions[controls['core_fire']]='core_enable'
    first=next(iter(brams.values()))['connections']
    expressions[first['WEA'][0]]='host_we';expressions[first['WEBWE'][0]]='core_we'
    lines=['module actual_working_bram_'+view+'(',
        'input clk,host_enable,core_enable,host_we,core_we,',
        'input [11:0] host_index,core_index, input [15:0] host_wdata,core_wdata,',
        'output [15:0] host_rdata,core_rdata);']
    unused=set();observed=set();metadata={}
    for name,cell in sorted(brams.items()):
        bram_contract(cell)
        assert cell['connections']['WEA']==first['WEA'] and cell['connections']['WEBWE']==first['WEBWE']
        params,changed=params_for_view(cell,view);metadata[name]=changed
        for pin,bits in cell['connections'].items():
            for wire in bits:
                if type(wire) is not int:
                    assert wire in ('0','1','x'),'Unknown actual constant kind'
                    continue
                if cell['port_directions'][pin]=='input':assert wire in expressions,'Unbound actual primitive input'
                elif cell['port_directions'][pin]=='output':
                    assert wire not in observed,'Aliased actual BRAM output'
                    observed.add(wire)
                    if wire not in expressions:unused.add(wire)
                else:raise AssertionError('Unmodeled primitive pin direction')
    lines.extend('wire unused_'+str(wire)+';' for wire in sorted(unused))
    def symbol(w):
        if type(w) is not int:return "1'b"+w
        return expressions[w] if w in expressions else 'unused_'+str(w)
    def bus(bits):return '{'+','.join(symbol(w) for w in reversed(bits))+'}'
    for i,(name,cell) in enumerate(sorted(brams.items())):
        params,_=params_for_view(cell,view)
        def value(v):return str(len(v))+"'b"+v if re.fullmatch('[01x]+',v) else '"'+v+'"'
        lines.append('RAMB36E1 #('+','.join('.'+k+'('+value(v)+')' for k,v in sorted(params.items()))+') actual_'+str(i)+'('+','.join(
            '.'+pin+'('+bus(bits)+')' for pin,bits in sorted(cell['connections'].items()))+');')
    for name in ('demo.memory.host_rdata','demo.mem_rsp_rdata'):
        assert all(wire in observed for wire in signals[name]),'Missing consumed output lane'
    lines.append('endmodule')
    return '\n'.join(lines)+'\n',metadata


def render_bench(rom_path):
    text=BENCH.read_text()
    assert text.count('@ROM_PATH@')==1 and not any(c in str(rom_path) for c in '\n"')
    return text.replace('@ROM_PATH@',str(rom_path))


def validate_result(text,code,negative,bench,first_word):
    assert not re.search(r'(?im)\bwarning:|\berror:|\bsorry:|timeout',text),'Unaccepted primitive qualification diagnostic'
    if negative:
        marker=f'working BRAM mismatch phase=core_after_host_init index=0 got={first_word:04x}/{first_word:04x}/{first_word:04x} expected={first_word^1:04x}'
        assert code==1 and marker in text and MARKER not in text
        assert len([line for line in text.splitlines() if line.startswith('FATAL:')])==1
        assert all(marker in line for line in text.splitlines() if line.startswith('FATAL:'))
    else:
        finish=[i+1 for i,line in enumerate(bench.read_text().splitlines()) if line.strip()=='$finish;']
        assert len(finish)==1
        # 4096 probes + 12288 writes + 16384 read cycles + 17 retention
        # cycles, starting on the first falling edge after default 100ns GSR.
        expected_finish=f'{bench}:{finish[0]}: $finish called at 655812000 (1ps)'
        assert code==0 and text.splitlines()==[MARKER,expected_finish],text[-4000:]


def admitted_inputs(before):
    paths=(ADDRESS,CONTROL_PARENT,WIRING,CONSUMER)
    reports=[json.loads(path.read_text()) for path in paths]
    assert reports[0]['stage']=='complete' and reports[0]['address_decoder_binary_cut_proved'] is True
    assert reports[0]['mapped_core_fire_binary_cut_proved'] is True and reports[0]['finished_utc']
    assert reports[0]['status']=='PROVED_ACTUAL_FULL_PREFIX_COHERENT_BINARY_BRAM_ADDRESS_WITH_EXHAUSTIVELY_QUALIFIED_UNCHANGED_SYNTHESIS_LIBRARY_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
    assert reports[0]['full_target_parallel_products']==512
    counts=reports[0]['actual_full_primitive_counts']
    assert sum(counts.values())==503128 and counts['DSP48E1']==515 and counts['RAMB36E1']==6
    assert reports[1]['status']=='AUDITED_FULL_BRAM_ENABLE_AND_LOCAL_BINARY_WRITE_GATING_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
    assert reports[2]['status']=='AUDITED_FULL_ROM_AND_WORKING_RAM_ADDRESS_DATA_WIRING_NOT_STARTUP_OR_FASM_SIGNOFF'
    assert reports[3]['status']=='AUDITED_FULL_BRAM_OUTPUT_CONSUMERS_AND_INIT_WITH_STARTUP_GAP_NOT_FASM_OR_SIGNOFF'
    for path,report in zip(paths,reports):
        assert report['stage']=='complete' and report['finished_utc']
        bind_report(path,report,before)
    verify_bindings(before)
    inventory=json.loads(SELECTED.read_text())
    brams={name:cell for name,cell in inventory.items() if cell['type']=='RAMB36E1'}
    wiring=json.loads((WIRING.parent/'actual-memory-wire-bindings.json').read_text())
    control=json.loads((CONTROL_PARENT.parent/'actual-BRAM-control-cones.json').read_text())
    signals=wiring['logical_signal_physical_wires'];controls=control['logical_signal_physical_wires']
    checks=verify_wiring(brams,reports[3]['BRAM_memory_classification'],signals)
    drivers={int(wire):record for wire,record in control['actual_control_drivers'].items()}
    assert binary_control_contract(brams,reports[3]['BRAM_memory_classification'],controls,drivers)==control['checks']==reports[1]['checks']
    _,names=control_roots(brams,reports[3]['BRAM_memory_classification'],controls)
    actual={name:brams[name] for name in names}
    assert set(names)==set(checks['working_RAM_by_consumed_width'].values()) and len(actual)==2
    assert reports[3]['memory_bit_totals']['unknown_with_direct_consumer']==65536
    for name in names:
        assert not reports[3]['BRAM_memory_classification'][name]['readonly']
        assert set(reports[3]['BRAM_memory_classification'][name]['directly_consumed_memory_lanes'])==set(range(9 if name==checks['working_RAM_by_consumed_width']['9'] else 7))
    return actual,signals,controls


def main():
    out=ROOT/f'build/openxc7/prefix-working-bram-overwrite-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',started_utc=timestamp(),scope=__doc__,supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        retained_full_target_parallel_products=512,primitive_boundary_unit_test_only=True,
        working_BRAM_model_overwrite_fixture_acceptance=False,full_board_startup_independence_proved=False,
        temporal_port_ownership_proved=False,write_before_read_proved=False,full_board_numerical_acceptance=False,
        physical_fit_verified=False,timing_signoff=False,electrical_verified=False,drc_signoff=False,
        bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False,native_PNR_executed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv,negative=None):
        step=dict(label=label,argv=list(map(str,argv)),cwd=str(ROOT),log=str(out/(label+'.log')),status='RUNNING',timeout_seconds=180)
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(step['argv'],cwd=ROOT,
                stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid;save()
                try:code=process.wait(timeout=180)
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait();step['returncode']=process.returncode;raise
            step['returncode']=code;text=Path(step['log']).read_text()
            if negative is not None:validate_result(text,code,negative,bench,first_word)
            else:assert code==0 and not re.search(r'(?im)\bwarning:|\berror:|sorry:|^FAILED|^FATAL',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_WRONG_GOLDEN_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        before={};brams,signals,controls=admitted_inputs(before)
        pinned=models.selected_models({'RAMB36E1'})
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned model'
        files={Path(__file__).resolve(),BENCH,CONTROL,ROM,SELECTED,*pinned,Path(sys.executable).resolve(),
               *(Path(shutil.which(tool)).resolve() for tool in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        verify_bindings(before);report['source']=before
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        (out/'actual-working-BRAMs.json').write_text(json.dumps(brams,indent=2)+'\n')
        report['stage']='software_controls';save()
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        rom=out/'actual-source-ROM.hex';shutil.copyfile(ROM,rom)
        source=out/'actual-working-BRAM-configurations.v';views={};texts=[]
        for view in ('mapped','zero','one'):
            text,changed=wrapper(brams,signals,controls,view);texts.append(text);views[view]=changed
        source.write_text('\n'.join(texts));report['test_only_startup_parameter_views']=views
        bench=out/BENCH.name;bench.write_text(render_bench(rom))
        frozen=[]
        for path in pinned:
            target=out/'models'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        first_word=int(rom.read_text().splitlines()[0],16)&65535
        execution={str(path):digest(path) for path in (rom,source,bench,*frozen)}
        report['stage']='actual_pinned_primitive_compile';save();binary=out/'overwrite.vvp'
        run('compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_working_bram_overwrite','-s','glbl','-o',binary,*frozen,source,bench])
        execution[str(binary)]=digest(binary);report['execution_inputs']=execution
        for label,options,negative in (('negative',['+NEGATIVE=1'],True),('positive',[],False)):
            report['stage']=label;save();run(label,['vvp',binary,*options],negative)
            verify_bindings(execution);verify_bindings(before)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',working_BRAM_model_overwrite_fixture_acceptance=True,
            actual_working_BRAM_configurations=2,test_only_vendor_RAM_instances=6,startup_parameter_views=3,
            cold_words=4096,logical_write_transactions=12288,logical_read_transactions=20480,
            read_first_old_data_checks=12288,disabled_port_retention_checks=34,
            unknown_consumed_memory_bits_exercised=65536,default_vendor_GSR_unchanged=True,
            only_INIT_and_SRVAL_parameter_symbols_changed_in_test_counterfactuals=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
