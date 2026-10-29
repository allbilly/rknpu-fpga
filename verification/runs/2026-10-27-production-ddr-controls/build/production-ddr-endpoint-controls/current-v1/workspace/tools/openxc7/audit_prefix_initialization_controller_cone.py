#!/usr/bin/env python3
"""Extract all actual demo/response controller storage and observed controls.

Keep the complete C32/K16 input and fresh full 503128-cell driver census.
Retain all 44 demo bits (state/index/watchdog/error), three memory-response
ownership bits and nine literal observed control outputs. Trace each actual
FDCE D/CE/CLR/Q without an opaque DSP shortcut. Only exact register Q and
fully audited RAM outputs form the binary producer boundary. Prepare a paired
host-data miter with every other producer shared; do not claim its proof,
register-fold qualification, temporal ownership or startup acceptance yet.
No RTL, model, input, old gate, live job or SHA256SUMS is changed.
"""
from collections import Counter
import hashlib
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

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1]/'cmac')]
import prove_prefix_initialization_state_independence as prior
import resume_binary_library_prefix_bram_address as binary_library
from place_prefix_board import bind_report, verify_bindings
from pack_prefix_board import ROOT, digest, timestamp
from evidence import source_revision

STATE_PROOF = ROOT/'build/openxc7/prefix-initialization-state-independence-1791444759482712816/report.json'
CONTROL = ROOT/'tests/cmac/test_prefix_initialization_controller_cone_control.py'
REGISTERS = {'demo.state':4, 'demo.index':12, 'demo.watchdog':20, 'demo.error_code':8,
             'demo.memory.rsp_valid':1, 'demo.memory.rsp_error':1, 'demo.memory.host_rsp_valid':1}
OUTPUTS = ('demo.host_valid', 'demo.host_write', 'demo.engine_rst_n', 'demo.pass', 'demo.fail',
           'demo.memory.host_ready', 'demo.memory.req_ready', 'demo.memory.host_fire', 'demo.memory.core_fire')
WIDTHS = {**REGISTERS, **dict.fromkeys(OUTPUTS, 1), 'demo.memory.host_rdata':16, 'demo.memory.clk':1}
PASS = 'EXTRACTED_ACTUAL_47_BIT_CONTROLLER_AND_NINE_CONTROL_CONE_FRONTEND_ONLY_NOT_DATA_INDEPENDENCE_OR_TEMPORAL_STARTUP_PROOF'
LIBRARY = binary_library.LIBRARY
COMBINATIONAL = {'INV', 'CARRY4', 'MUXF7', 'MUXF8', *('LUT'+str(i) for i in range(1,7))}


def admit(before):
    report = json.loads(STATE_PROOF.read_text())
    assert report['status'] == prior.PASS and report['stage'] == 'complete' and report['finished_utc']
    assert report['full_target_parallel_products'] == 512 and report['proof_is_binary_single_step_conditional_only']
    assert report['initialization_state_data_independence_proved']
    bind_report(STATE_PROOF, report, before)
    prior.admit(before)
    commands = {c['label']:c for c in report['commands']}
    bench = STATE_PROOF.parent/'binary_library_control.sv'
    footer = prior.results.expected_finish(bench, bench.read_text())
    vendor = Path(commands['vendor_test']['log']).read_text()
    assert prior.compare_corpora(vendor, Path(commands['synthesis_test']['log']).read_text(), 497, footer) == report['binary_library_qualification']
    prior.validate_wrong_corpus(vendor, Path(commands['synthesis_wrong_golden_test']['log']).read_text(), 497, footer)
    for label, negative in (('negative', True), ('positive', False)):
        c = commands[label]
        prior.state.raw.validate_result(Path(c['log']).read_text(), c['returncode'], negative)
    verify_bindings(before)
    return report['actual_full_primitive_counts']


def aliases(logical, physical):
    original, actual = prior.state.netname_region(logical), prior.state.netname_region(physical)
    result, translated = {}, {}
    for name, width in WIDTHS.items():
        record = prior.state.named_net(logical, name, original)
        assert record['hide_name'] == 0 and len(record['bits']) == width and len(set(record['bits'])) == width
        wires = []
        for bit in record['bits']:
            if bit not in translated:
                alias = prior.state.named_net(physical, 'n_'+str(bit), actual)
                assert len(alias['bits']) == 1
                translated[bit] = alias['bits'][0]
            wires.append(translated[bit])
        result[name] = wires
    assert len(set(translated.values())) == len(translated), 'Non-bijective controller alias translation'
    assert result['demo.state'] == prior.state.STATE_Q and result['demo.memory.clk'] == [8]
    return result


def validate_fold_register(cell, clock):
    prior.state.coherent.validate_register(cell, 'Q', 0)
    assert cell['type'] == 'FDCE' and cell['connections']['C'] == clock, 'Unsupported actual controller register/clock'
    assert all(v == '0' for k,v in cell['parameters'].items() if k != 'INIT'), 'Unqualified controller register inversion'


def trace_controller(signals, driver, selected):
    assert set(signals) == set(WIDTHS) and all(len(signals[k]) == WIDTHS[k] for k in signals)
    nodes, cuts, registers, visited = {}, {}, [], set()
    def visit(wire, stack):
        if wire in ('0', '1') or wire in visited:
            return
        assert type(wire) is int and wire >= 2 and wire not in stack, 'Unknown/cyclic controller cone'
        name, cell, pin, bit = driver(wire)
        assert cell['connections'][pin][bit] == wire
        if cell['type'] in prior.state.coherent.RESET_PIN:
            prior.state.coherent.validate_register(cell, pin, bit)
            role = 'EXACT_REGISTER_Q_BINARY_VALUE_NOT_INITIALIZATION_OR_REACHABILITY'
        elif cell['type'] == 'RAMB36E1':
            assert name in selected and cell == selected[name], 'Changed actual controller RAM producer'
            prior.state.bram_contract(cell)
            assert pin in ('DOADO', 'DOBDO', 'DOPADOP', 'DOPBDOP') and cell['port_directions'][pin] == 'output'
            role = 'FULLY_AUDITED_RAM_OUTPUT_BINARY_VALUE_NOT_MEMORY_STARTUP_OR_TRANSITION'
        else:
            inputs, outputs = prior.state.coherent.validate_cell(cell)
            assert pin in outputs and (name not in nodes or nodes[name] == cell)
            nodes[name] = cell
            for port in inputs:
                for upstream in cell['connections'][port]:
                    visit(upstream, stack | {wire})
            visited.add(wire)
            return
        record = dict(cell=name, pin=pin, bit=bit, role=role, original_primitive=cell)
        assert wire not in cuts or cuts[wire] == record
        cuts[wire] = record
        visited.add(wire)
    for signal, width in REGISTERS.items():
        for offset, wire in enumerate(signals[signal]):
            name, cell, pin, bit = driver(wire)
            assert pin == 'Q' and bit == 0 and cell['connections']['Q'] == [wire]
            validate_fold_register(cell, signals['demo.memory.clk'])
            registers.append(dict(signal=signal, offset=offset, cell=name, original_primitive=cell))
            for port in ('Q', 'D', 'CE', 'CLR'):
                visit(cell['connections'][port][0], set())
    for name in OUTPUTS:
        visit(signals[name][0], set())
    for wire in signals['demo.memory.host_rdata']:
        visit(wire, set())
        assert cuts[wire]['original_primitive']['type'] == 'RAMB36E1' and cuts[wire]['pin'] in ('DOADO', 'DOPADOP')
    assert len(registers) == 47 and len({r['cell'] for r in registers}) == 47
    assert nodes and cuts and len(nodes) <= 503128 and len(cuts) <= 17519+432
    return dict(signals=signals, cells=nodes, producer_cuts={str(w):r for w,r in cuts.items()}, controller_registers=registers)


def miter(cone):
    nodes = cone['cells']; cuts = {int(w):r for w,r in cone['producer_cuts'].items()}
    host = {w:i for i,w in enumerate(cone['signals']['demo.memory.host_rdata'])}
    other = {w:i for i,w in enumerate(sorted(set(cuts)-set(host)))}
    registers = cone['controller_registers']
    assert len(host) == 16 and len(registers) == 47 and other
    assert set(host) <= set(cuts)
    assert all(w in other for name in REGISTERS for w in cone['signals'][name])
    def bit(w, copy):
        if w in ('0', '1'):
            return "1'b"+w
        if w in host:
            return 'host_'+str(copy)+'['+str(host[w])+']'
        if w in other:
            return 'producer_cut['+str(other[w])+']'
        return 'w'+str(copy)+'_'+str(w)
    def bus(bits, copy):
        return '{'+','.join(bit(w,copy) for w in reversed(bits))+'}'
    width = len(registers)+len(OUTPUTS)
    lines = ['module prefix_init_controller_miter #(parameter NEGATIVE=0)(',
             'input ['+str(len(other)-1)+':0] producer_cut,input [15:0] host_0,host_1,output ok);']
    for copy in (0,1):
        wires = {w for c in nodes.values() for b in c['connections'].values() for w in b if type(w) is int and w not in cuts}
        lines += ['wire '+bit(w,copy)+';' for w in sorted(wires)]
        for i,(name,cell) in enumerate(sorted(nodes.items())):
            _,outputs = prior.state.coherent.validate_cell(cell)
            assert not any(w in cuts for p in outputs for w in cell['connections'][p])
            parameter = ''
            if cell['type'].startswith('LUT'):
                init = cell['parameters']['INIT']; parameter = ' #(.INIT('+str(len(init))+"'b"+init+'))'
            lines.append(cell['type']+parameter+' actual_'+str(copy)+'_'+str(i)+'('+','.join(
                '.'+p+'('+bus(b,copy)+')' for p,b in sorted(cell['connections'].items()))+');')
        next_bits = []
        for record in registers:
            cell = record['original_primitive']; validate_fold_register(cell, cone['signals']['demo.memory.clk'])
            c = cell['connections']
            next_bits.append('('+bit(c['CLR'][0],copy)+" ? 1'b0 : "+bit(c['CE'][0],copy)+' ? '+bit(c['D'][0],copy)+' : '+bit(c['Q'][0],copy)+')')
        compared = next_bits + [bit(cone['signals'][name][0],copy) for name in OUTPUTS]
        lines.append('wire ['+str(width-1)+':0] compared_'+str(copy)+'={'+','.join(reversed(compared))+'};')
    lines += ['wire [3:0] state='+bus(cone['signals']['demo.state'],0)+';',
              "wire init_phase=(state <= 4'd2);",
              'assign ok=!init_phase || (compared_0 == (compared_1 ^ (NEGATIVE ? '+str(width)+"'h1 : "+str(width)+"'h0)));", 'endmodule']
    text = '\n'.join(lines)+'\n'
    assert not re.search(r'\b(?:assume|anyseq|anyconst|force)\b', text)
    return text


def selected_definitions(data, kinds):
    assert kinds and set(kinds) <= COMBINATIONAL, 'Unmodeled controller primitive class'
    header = data[:data.index(b'\nmodule VCC(')+1]
    assert header.startswith(b'/*') and b'copyright notice' in header and b'module ' not in header
    pattern = rb'(?m)^(?:\(\*[^\n]*\*\)\n)*module ([A-Za-z][A-Za-z0-9_]*)\b[^\n]*(?:\n(?!endmodule\b)[^\n]*)*\nendmodule\n'
    records = {}
    for match in re.finditer(pattern, data):
        kind = match[1].decode('ascii')
        if kind not in kinds:
            continue
        assert kind not in records and b'`' not in match[0], 'Duplicate/context-dependent controller definition'
        records[kind] = dict(offset=match.start(), length=len(match[0]), sha256=hashlib.sha256(match[0]).hexdigest())
    assert set(records) == set(kinds), 'Missing complete controller primitive definition'
    selected = header+b'\n'+b'\n'.join(data[r['offset']:r['offset']+r['length']] for r in sorted(records.values(),key=lambda r:r['offset']))
    assert set(re.findall(rb'(?m)^module (\w+)', selected)) == {k.encode('ascii') for k in kinds}
    assert len(re.findall(rb'(?m)^endmodule$', selected)) == len(kinds)
    for r in records.values():
        block = data[r['offset']:r['offset']+r['length']]
        assert selected.count(block) == 1 and hashlib.sha256(block).hexdigest() == r['sha256']
    return selected, records


def main():
    out = ROOT/f'build/openxc7/prefix-initialization-controller-cone-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', scope=__doc__, started_utc=timestamp(), supervisor_pid=os.getpid(),
        source={}, commands=[], seed=None, python_version=sys.version, production_source_before=source_revision(),
        full_target_parallel_products=512, controller_state_bits=47, observed_control_bits=9,
        initialization_controller_data_independence_proved=False, controller_binary_fold_qualified=False,
        controller_cone_binary_library_qualified=False, four_state_library_equivalence=False,
        temporal_port_ownership_proved=False, write_before_read_proved=False, full_board_startup_independence_proved=False,
        full_board_numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        hardware_input_modified=False, native_PNR_executed=False)
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    def run(label, argv):
        step = dict(label=label, argv=list(map(str,argv)), cwd=str(ROOT), log=str(out/(label+'.log')), status='RUNNING', timeout_seconds=180)
        report['commands'].append(step); save(); start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid; save()
                try:
                    code=process.wait(timeout=180)
                except BaseException:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode']=process.returncode; raise
            step['returncode']=code; text=Path(step['log']).read_text()
            assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]
            step['status']='PASS_TOOL_EXECUTION_ONLY_NOT_PROOF'
            return text
        except BaseException:
            step['status']='FAIL'; raise
        finally:
            step['seconds']=round(time.monotonic()-start,3); save()
    save(); print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py'); shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={}; counts=admit(before)
        prepared=json.loads(prior.state.raw.PREPARED.read_text()); physical=ROOT/prepared['pack_input']
        files={Path(__file__).resolve(), CONTROL, LIBRARY, prior.state.STATE_SOURCE, ROOT/'rtl/cmac/rk_cmac_demo_memory.sv',
               Path(sys.executable).resolve(), Path(shutil.which('yosys')).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path); assert str(path) not in before or before[str(path)]==sha; before[str(path)]=sha
        verify_bindings(before); report['source']=before
        assert prior.state.STATE_ENUM in prior.state.STATE_SOURCE.read_text()
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check']); report['yosys_version']=run('yosys_version',['yosys','-V']).strip()
        report['stage']='fresh_full_driver_census_and_47_bit_controller_cone'; save()
        selected=json.loads((ROOT/'build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
        with prior.state.HIERARCHY.open('rb') as a,mmap.mmap(a.fileno(),0,access=mmap.ACCESS_READ) as logical,physical.open('rb') as b,mmap.mmap(b.fileno(),0,access=mmap.ACCESS_READ) as actual:
            signals=aliases(logical,actual); drivers,census=prior.state.raw.driver_index(actual,counts)
            def driver(wire):
                assert wire in drivers,'Missing actual controller primitive driver'
                start,end,name,pin,bit,direction=drivers[wire]; assert direction=='output'
                cell=json.loads(b'{'+actual[start+1:end]+b'}')[name]
                return name,cell,pin,bit
            cone=trace_controller(signals,driver,selected)
        del drivers
        cone['full_primitive_counts']=census
        (out/'actual-initialization-controller-cone.json').write_text(json.dumps(cone,indent=2,sort_keys=True)+'\n')
        source=out/'actual-initialization-controller-miter.v'; source.write_text(miter(cone))
        kinds=set(c['type'] for c in cone['cells'].values())
        library_data,definitions=selected_definitions(LIBRARY.read_bytes(),kinds)
        library=out/'unchanged_selected_controller_cells.v'; library.write_bytes(library_data)
        report.update(actual_full_primitive_counts=census,actual_cone_cells=len(cone['cells']),
            actual_cone_primitive_counts=dict(Counter(c['type'] for c in cone['cells'].values())),actual_producer_bits=len(cone['producer_cuts']),
            shared_producer_bits=len(cone['producer_cuts'])-16,independent_host_bits_per_copy=16,
            actual_symbolic_input_bits=len(cone['producer_cuts'])+16,compared_output_bits=56,
            actual_register_type_counts=dict(Counter(r['original_primitive']['type'] for r in cone['controller_registers'])),
            selected_unchanged_library_definitions=definitions)
        script=out/'frontend_check.ys'
        script.write_text('read_verilog '+str(library)+'\nread_verilog '+str(source)+'\nhierarchy -check -top prefix_init_controller_miter\nproc\nflatten\nopt -full\ncheck -assert\nstat\n')
        execution={str(p):digest(p) for p in (source,library,script)}; report['execution_inputs']=execution
        report['stage']='actual_paired_controller_miter_frontend_check_only'; save()
        run('frontend_check',['yosys','-Q','-T','-s',script])
        verify_bindings(before); verify_bindings(execution)
        report['production_source_after']=source_revision(); assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete')
    except BaseException as error:
        report.update(status='FAIL',error=repr(error)); raise
    finally:
        report['finished_utc']=timestamp()
        report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save(); print(out/'report.json',flush=True)


if __name__=='__main__':
    main()
