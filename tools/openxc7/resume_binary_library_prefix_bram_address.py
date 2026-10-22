#!/usr/bin/env python3
"""Source-bound binary library qualification and actual address SAT continuation.

Reuse, rehash and independently retrace the complete saved 557-cell/624-Q cone
from the failed UNISIM frontend attempt. Do not rescan or change the physical
input. Exhaustively compare every retained primitive instance's binary input
function between unchanged pinned UNISIM and the unchanged installed Yosys
library, including all ten independent CARRY4 inputs. Only then run the same
actual miter, normal SAT limits and exact real wrong-golden negative with the
qualified synthesis library. No four-state equivalence, sequential/startup,
numerical, physical implementation or hardware acceptance is claimed. All
five earlier failures and sources remain unchanged. No SHA256SUMS is emitted.
"""
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parent),
               str(Path(__file__).resolve().parents[1] / 'cmac')]
import resume_full_budget_prefix_bram_address as previous
from place_prefix_board import bind_report, verify_bindings
from evidence import source_revision
import unisim_board_models as models

base = previous.previous.base
ROOT = base.ROOT
FAILED = ROOT / 'build/openxc7/prefix-bram-address-full-budget-resume-1791437760192160498/report.json'
CONTROL = ROOT / 'tests/cmac/test_binary_library_prefix_bram_address_control.py'
LIBRARY = Path('/home/linuxbrew/.linuxbrew/share/yosys/xilinx/cells_sim.v')
PASS = 'PROVED_ACTUAL_FULL_PREFIX_COHERENT_BINARY_BRAM_ADDRESS_WITH_EXHAUSTIVELY_QUALIFIED_UNCHANGED_SYNTHESIS_LIBRARY_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
COUNTS = dict(CARRY4=28, INV=5, LUT2=169, LUT3=35, LUT4=43,
              LUT5=37, LUT6=210, MUXF7=27, MUXF8=3)
VALIDATE = previous.NAMESPACE['validate_cell']


def replay_cone(signals, nodes, cuts):
    """Independently retrace all saved semantic signals; no new opaque cuts."""
    drivers = {}
    def add(wire, record):
        assert type(wire) is int and wire >= 2 and wire not in drivers, 'Duplicate/unknown saved driver'
        drivers[wire] = record
    for name, cell in nodes.items():
        _, outputs = VALIDATE(cell)
        for pin in outputs:
            for bit, wire in enumerate(cell['connections'][pin]):
                add(wire, (name, cell, pin, bit))
    for wire, record in cuts.items():
        cell = record['original_primitive']
        assert cell['type'] == 'FDCE', 'Changed actual producer type'
        assert record['pin'] == 'Q' and record['bit'] == 0
        assert cell['connections']['Q'] == [wire]
        add(wire, (record['cell'], cell, record['pin'], record['bit']))
    def driver(wire):
        assert wire in drivers, 'Incomplete saved cone'
        return drivers[wire]
    actual_nodes, actual_cuts = previous.trace_coherent(signals, driver)
    assert actual_nodes == nodes and actual_cuts == cuts, 'Unreachable/changed saved cone record'
    return previous.NAMESPACE['miter'](signals, actual_nodes, actual_cuts)


def qualify_bench(nodes):
    """All actual parameters; every primitive input combination, no wire edits."""
    lines = ['`timescale 1ns/1ps', 'module binary_library_control;',
             'reg [9:0] stimulus;', 'integer vector, negative;', 'initial begin',
             'negative=0;', 'if ($value$plusargs("NEGATIVE=%d",negative)) begin end',
             "wait (glbl.GSR === 1'b0); #1;", 'for(vector=0;vector<1024;vector=vector+1) begin',
             'stimulus=vector; #1;',
             '$display("VECTOR %04d %h",vector,observed ^ ((negative && vector==0) ? 1 : 0));',
             'end', '$finish;', 'end']
    slices = []
    for i, (name, cell) in enumerate(sorted(nodes.items())):
        VALIDATE(cell)
        kind = cell['type']
        parameter = ''
        if kind.startswith('LUT'):
            init = cell['parameters']['INIT']
            parameter = ' #(.INIT(' + str(len(init)) + "'b" + init + '))'
            inputs = {f'I{j}': f'stimulus[{j}]' for j in range(int(kind[-1]))}
        elif kind == 'CARRY4':
            inputs = dict(CI='stimulus[0]', CYINIT='stimulus[1]',
                          DI='stimulus[5:2]', S='stimulus[9:6]')
        elif kind in ('MUXF7', 'MUXF8'):
            inputs = dict(I0='stimulus[0]', I1='stimulus[1]', S='stimulus[2]')
        elif kind == 'INV': inputs = dict(I='stimulus[0]')
        else: raise AssertionError('Unqualified primitive')
        width = 8 if kind == 'CARRY4' else 1
        signal_name = f'out_{i}'
        lines.append(f'wire [{width-1}:0] {signal_name};')
        outputs = dict(CO=signal_name+'[3:0]', O=signal_name+'[7:4]') if kind == 'CARRY4' else dict(O=signal_name)
        connections = {**inputs, **outputs}
        lines.append(kind + parameter + ' actual_' + str(i) + '(' + ','.join(
            '.' + pin + '(' + value + ')' for pin, value in sorted(connections.items())) + ');')
        slices.append((signal_name, width))
    assert slices
    width = sum(size for _, size in slices)
    lines += [f'wire [{width-1}:0] observed = '+'{'+','.join(name for name,_ in reversed(slices))+'};',
              'endmodule']
    return '\n'.join(lines)+'\n', width


def vectors(text, width):
    assert not re.search(r'(?im)warning:|error:|sorry:|FATAL:|\bPASS\b', text)
    records = text.splitlines()
    assert len(records) == 1024, 'Incomplete binary model corpus'
    result = []
    for vector, line in enumerate(records):
        match = re.fullmatch(r'VECTOR (\d{4}) ([0-9a-f]+)', line)
        assert match and int(match[1]) == vector, 'Unknown, unordered or malformed binary result'
        assert len(match[2]) == (width+3)//4, 'Changed observed output width'
        value = int(match[2], 16)
        assert value < 1 << width, 'Nonzero unused display padding'
        result.append(value)
    return result


def compare_vectors(vendor, synthesis, width):
    a, b = vectors(vendor, width), vectors(synthesis, width)
    for vector, (left, right) in enumerate(zip(a, b)):
        if left != right:
            raise AssertionError('Binary model mismatch vector=' + str(vector))
    return dict(binary_stimulus_vectors=1024, retained_actual_instances=557,
                per_instance_binary_comparisons=557*1024,
                observed_binary_output_bits=width,
                all_retained_primitive_input_combinations_exhausted=True,
                four_state_library_equivalence=False)


def verify_failed(before):
    witness = previous.verify_failed(before)
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'actual_binary_SAT' and report['finished_utc']
    assert report['error'] == 'AssertionError()'
    assert [step['label'] for step in report['commands']] == ['software_controls','generated_check','yosys_version','negative']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'][:3])
    negative = report['commands'][-1]
    assert negative['returncode'] == 1 and negative['status'] == 'FAIL'
    log = Path(negative['log']).read_text()
    assert re.search(r'LUT1\.v:60: ERROR: syntax error, unexpected', log)
    assert base.SUCCESS not in log and base.FAILURE not in log
    assert report['actual_cone_cells'] == 557 and report['symbolic_binary_input_bits'] == 624
    assert report['actual_cone_primitive_counts'] == COUNTS
    assert 'address_decoder_binary_cut_proved' not in report
    bind_report(FAILED, report, before)
    verify_bindings(before)
    cone = json.loads((FAILED.parent / 'actual-address-cone.json').read_text())
    cuts = {int(wire): record for wire, record in report['actual_producer_cuts'].items()}
    assert len(cuts) == 624 and len(cone['cells']) == 557
    assert cone['full_primitive_counts'] == report['actual_full_primitive_counts']
    assert dict(Counter(c['type'] for c in cone['cells'].values())) == COUNTS
    miter = replay_cone(cone['signals'], cone['cells'], cuts)
    assert miter == (FAILED.parent / 'actual-address-miter.v').read_text(), 'Changed cached actual miter'
    return dict(**witness, preserved_UNISIM_frontend_failure_report=str(FAILED),
                previous_failure_not_relabelled=True, cached_full_driver_census_rehashed_not_rescanned=True,
                independent_saved_cone_retrace=True), cone, cuts, miter


def main():
    out = ROOT / f'build/openxc7/prefix-bram-address-binary-library-resume-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=base.timestamp(),
        supervisor_pid=os.getpid(), scope=__doc__, source={}, commands=[], seed=None,
        python_version=sys.version, production_source_before=source_revision(),
        symbolic_binary_input_bits=624, compared_output_bits=14, input_assumptions=[],
        full_target_parallel_products=512, hardware_input_modified=False,
        native_PNR_executed=False, four_state_library_equivalence=False,
        temporal_port_ownership_proved=False, write_before_read_proved=False,
        observable_startup_reset_independence_proved=False, full_board_numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, comparison_view_used_for_execution=False)
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label, argv, formal=None):
        step = dict(label=label, argv=list(map(str,argv)), cwd=str(ROOT),
                    log=str(out/(label+'.log')), status='RUNNING', timeout_seconds=180)
        report['commands'].append(step); save(); start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                step['pid']=process.pid; save()
                try: code=process.wait(timeout=180)
                except BaseException:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode']=process.returncode; raise
            step['returncode']=code; text=Path(step['log']).read_text()
            if formal is not None: base.validate_result(text,code,formal)
            else:
                assert code==0 and not re.search(r'(?im)^(?:WARNING|ERROR|FAILED|FATAL)\b|sorry:',text),text[-4000:]
            step['status']='PASS_EXPECTED_FORMAL_NEGATIVE' if formal else 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException: step['status']='FAIL'; raise
        finally: step['seconds']=round(time.monotonic()-start,3); save()
    save(); print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f: (_ for _ in ()).throw(SystemExit(128+s)))
    try:
        before={}
        witness,cone,cuts,miter=verify_failed(before)
        pinned=models.selected_models(set(COUNTS))
        for path, sha in pinned.items(): assert base.digest(path)==sha, 'Changed pinned vendor model'
        files={Path(__file__).resolve(), CONTROL, LIBRARY, *pinned,
               Path(sys.executable).resolve(),
               *(Path(shutil.which(tool)).resolve() for tool in ('yosys','iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=base.digest(path)
            assert str(path) not in before or before[str(path)]==sha
            before[str(path)]=sha
        verify_bindings(before)
        report.update(source=before, prior_failure_witness=witness,
                      actual_cone_cells=557,actual_cone_primitive_counts=COUNTS,
                      actual_full_primitive_counts=cone['full_primitive_counts'],
                      actual_producer_cuts={str(w):record for w,record in cuts.items()},
                      binary_library_path=str(LIBRARY),pinned_vendor_commit=models.COMMIT)
        shutil.copyfile(__file__,out/'executed_source.py'); shutil.copyfile(CONTROL,out/'executed_control_source.py')
        report['stage']='software_controls'; save()
        run('software_controls',[sys.executable,'-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        for label,argv in (('yosys_version',['yosys','-V']),('iverilog_version',['iverilog','-V']),('vvp_version',['vvp','-V'])):
            report[label]=run(label,argv).splitlines()[0]
        report['stage']='unchanged_libraries_actual_binary_qualification'; save()
        bench_text,width=qualify_bench(cone['cells'])
        bench=out/'binary_library_control.sv'; bench.write_text(bench_text)
        frozen_library=out/'unchanged_xilinx_cells_sim.v'; shutil.copyfile(LIBRARY,frozen_library)
        vendor_files=[]
        for path in pinned:
            if path.suffix=='.v':
                target=out/'vendor'/path.name; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,target); vendor_files.append(target)
        glbl=next(path for path in vendor_files if path.name=='glbl.v')
        execution={str(path):base.digest(path) for path in [bench,frozen_library,*vendor_files]}
        outputs={}
        for kind,library_files in (('vendor',vendor_files),('synthesis',[frozen_library,glbl])):
            binary=out/(kind+'.vvp')
            run(kind+'_compile',['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl','-o',binary,*library_files,bench])
            execution[str(binary)]=base.digest(binary)
            outputs[kind]=run(kind+'_binary_test',['vvp',binary])
        report['binary_library_qualification']=compare_vectors(outputs['vendor'],outputs['synthesis'],width)
        negative=run('synthesis_wrong_golden_test',['vvp',out/'synthesis.vvp','+NEGATIVE=1'])
        actual=vectors(outputs['vendor'],width); wrong=vectors(negative,width)
        assert wrong[0]==actual[0]^1 and wrong[1:]==actual[1:]
        try: compare_vectors(outputs['vendor'],negative,width)
        except AssertionError as error:
            assert str(error)=='Binary model mismatch vector=0'
            report['binary_library_real_wrong_golden_negative']='REJECTED_EXACT_FIRST_VECTOR_ONE_BIT_MUTATION'
        else: raise AssertionError('Wrong-golden library comparison accepted')
        verify_bindings(execution); verify_bindings(before)
        report['library_qualification_execution_inputs']=execution
        source=out/'actual-address-miter.v'; source.write_text(miter)
        (out/'actual-address-cone.json').write_text(json.dumps(cone,indent=2)+'\n')
        report['stage']='qualified_library_actual_binary_SAT'; save()
        for kind,negative_flag in (('negative',1),('positive',0)):
            script=out/(kind+'.ys')
            script.write_text('read_verilog '+str(frozen_library)+'\nread_verilog '+str(source)+'\n'
                'chparam -set NEGATIVE '+str(negative_flag)+' prefix_bram_address_miter\n'
                'hierarchy -check -top prefix_bram_address_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\n'
                'sat -verify -prove ok 1 -show-inputs -show-outputs -timeout 120 -dump_json '+str(out/(kind+'-counterexample.json'))+'\n')
            run(kind,['yosys','-Q','-T','-s',script],bool(negative_flag))
        verify_bindings(execution); verify_bindings(before)
        assert source.read_text()==miter==replay_cone(cone['signals'],cone['cells'],cuts)
        report['production_source_after']=source_revision()
        assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',address_decoder_binary_cut_proved=True,
                      mapped_core_fire_binary_cut_proved=True,
                      normal_error_on_invalid_address_gate_preserved=True)
    except BaseException as error: report.update(status='FAIL',error=repr(error)); raise
    finally:
        report['finished_utc']=base.timestamp()
        report['artifacts']={str(p.relative_to(ROOT)):base.digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save(); print(out/'report.json',flush=True)


if __name__=='__main__': main()
