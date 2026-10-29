#!/usr/bin/env python3
"""Run all nine original raw-board modes on actual observable XC7 hardware.

No RTL arithmetic replacement, test-mode-derived golden, guessed tap, FSM
decode, skipped unknown-data mode or CPU execution fallback is provided.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from bind_mapped_board_bench import bind, WIDTHS
from prepare_observed_board import TOP, BENCH, verify_observations, verify_implementation_boundary
from test_fixed_array_board import verify_manifest, validate_result
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases
from pair_board_luts import implementation_module_aliases
from export_board_netlist import structural_board_verilog
from unisim_board_models import CACHE, COMMIT, selected_models, freeze_models

WRITES = ROOT / 'tests/cmac/array_data/writes.hex'
READS = ROOT / 'tests/cmac/array_data/reads.hex'
MODES = tuple(range(9))


def verify_mapping_report(report):
    assert report['status'] == 'PASS_OBSERVABLE_RAW_BOARD_PARTITIONED_XC7_MAPPING_ONLY', 'Completed observable mapping required'
    assert report['stage'] == 'complete'
    assert (report['channels'], report['kernels'], report['parallel_products'], report['mapped_kernel_instances']) == (32,16,512,16)
    assert (report['intended_part'], report['intended_clock_period_ns']) == ('xc7k480tffg1156-2',20)
    assert set(report['bindings']) == set(WIDTHS)
    assert report['imported_kernel_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    assert len(report['commands']) == 3
    assert [Path(c['log']).stem for c in report['commands']] == ['version','datadir','mapping']
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in report['commands'])
    assert report['cells'].get('RAMB36E1',0) + report['cells'].get('RAMB18E1',0) > 0
    assert report['dsp_count'] == 0, 'DSP primitive model contract not established for this candidate'
    for flag in ('numerical_netlist_acceptance','physical_fit_verified','bitstream_emitted','hardware_programmed'):
        assert report[flag] is False


def negative_golden(original):
    lines = original.splitlines(keepends=True)
    assert len(lines) == 64 and all(re.fullmatch('[0-9a-f]{12}\n', line) for line in lines), 'Changed board golden format'
    first = int(lines[0].strip(),16)
    result = f'{first ^ 1:012x}\n' + ''.join(lines[1:])
    changed = result.splitlines()
    assert int(changed[0],16) ^ first == 1 and int(changed[0],16) >> 16 == first >> 16
    assert result.splitlines(keepends=True)[1:] == lines[1:]
    return result


def verify_bound_bench(module, original, generated, edits):
    # Recompute the source-evidenced wire replacements. Every byte outside
    # those original references, including all forces/fatal checks/goldens,
    # must be unchanged; edited binding provenance is rejected as well.
    expected, expected_edits = bind(module, original)
    assert generated == expected and edits == expected_edits, 'Changed wire-only raw-board bench binding'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', required=True, type=Path)
    args = parser.parse_args()
    parent_path = args.mapping_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text()); verify_mapping_report(parent)
    verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
    mapped = parent_path.parent / 'mapped_hierarchy.json'
    assert str(mapped.relative_to(ROOT)) in parent['artifacts']['files']
    kernel = parent['preserved_kernel']
    design = json.loads(mapped.read_text())
    implementation = {'modules': {name: design['modules'][name] for name in (TOP,kernel)}}
    original_path = (ROOT / parent['parent_report']).resolve()
    assert original_path.is_relative_to(ROOT)
    original_report = json.loads(original_path.read_text())
    assert original_report['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    verify_manifest(original_report['source']); verify_manifest(original_report['artifacts'])
    partition = original_path.parent / 'cmac_partition.json'
    verify_implementation_boundary(implementation, json.loads(partition.read_text()), kernel)
    assert verify_observations(implementation['modules'][TOP], BENCH.read_text()) == parent['bindings']
    kinds = {c['type'] for body in implementation['modules'].values() for c in body['cells'].values()
             if c['type'] not in (kernel,'$scopeinfo')}
    pins = selected_models(kinds)  # Unknown or unpinned hardware fails before output creation.
    out = ROOT / f'build/rknpu-observable-mapped-board/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    module_export, module_aliases = implementation_module_aliases(implementation)
    exported, instance_aliases = hardware_instance_aliases(module_export)
    assert module_aliases.get(TOP,TOP) == TOP
    sv = out / 'mapped_board.v'; sv.write_text(structural_board_verilog(exported))
    bench = out / BENCH.name
    bound, edits = bind(implementation['modules'][TOP], BENCH.read_text())
    verify_bound_bench(implementation['modules'][TOP], BENCH.read_text(), bound, edits)
    bench.write_text(bound)
    edits_path = out / 'bench_reference_edits.json'; edits_path.write_text(json.dumps(edits,indent=2)+'\n')
    aliases = out / 'hardware_name_aliases.json'
    aliases.write_text(json.dumps({'modules':module_aliases,'instances':instance_aliases},indent=2)+'\n')
    _, frozen = freeze_models(out / 'models', kinds)
    negative_cwd = out / 'negative-golden-cwd'
    negative_data = negative_cwd / 'tests/cmac/array_data'; negative_data.mkdir(parents=True)
    negative_writes = negative_data / WRITES.name; negative_writes.write_text(negative_golden(WRITES.read_text()))
    negative_reads = negative_data / READS.name; negative_reads.write_bytes(READS.read_bytes())
    assert bound.count('$readmemh(') == 2
    assert '"tests/cmac/array_data/writes.hex"' in bound and '"tests/cmac/array_data/reads.hex"' in bound
    roundtrip, export_script = out / 'export_roundtrip.json', out / 'export.ys'
    export_script.write_text('read_verilog -sv '+json.dumps(str(sv))+';\nwrite_json '+json.dumps(str(roundtrip))+';\n')
    generated = [sv,bench,edits_path,aliases,export_script,*frozen,negative_writes,negative_reads]
    tracked = [parent_path,mapped,original_path,partition,BENCH,WRITES,READS,Path(__file__).resolve(),*pins,*generated,
        *(ROOT/name for name in parent['source']['files'])]
    tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
    report = dict(status='RUNNING',stage='export',started_utc=timestamp(),supervisor_pid=os.getpid(),
        source=fingerprint(tracked),mapping_report=str(parent_path.relative_to(ROOT)),commands=[],tests=[],
        channels=32,kernels=16,parallel_products=512,modes=list(MODES),upstream_model_commit=COMMIT,
        numerical_netlist_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        scope='Actual observable XC7 board hardware and unmodified pinned functional UNISIM models/default GSR. Exact source-bound wire-only rebinding of all original assertions, forces, raw K65 transactions, numeric/address oracle, resets and all nine modes, including unknown readback. Same compiled DUT/bench is required to reject a first-output golden-bit error in an isolated test cwd. No FPGA CPU fallback, RTL arithmetic substitution, guessed aliases, skipped cases, physical fit/timing/DRC, bitstream or RK acceptance.')

    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def terminate(signum,_frame): raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,terminate)
    def run(argv,label,cwd=ROOT,negative=False):
        log = out/(label+'.log'); step=dict(argv=list(map(str,argv)),cwd=str(cwd.relative_to(ROOT)) or '.',status='RUNNING',log=str(log.relative_to(ROOT)))
        report['commands'].append(step);save();started=time.monotonic()
        try:
            with log.open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid;save()
                    try: code=proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait();raise
            step['returncode']=code;text=log.read_text()
            assert code==(1 if negative else 0),text[-6000:]
            assert not re.search(r'(?im)\bwarning:|\berror:|\bsorry:',text),text[-6000:]
            if negative:
                assert 'board demo numerical/address mismatch output=0' in text and not re.search(r'^PASS ',text,re.M),text[-6000:]
            step['status']='PASS';return text
        except BaseException: step['status']='FAIL';raise
        finally: step['seconds']=round(time.monotonic()-started,3);save()

    save()
    try:
        for path in set(tracked):
            if path.suffix=='.json' and path.stat().st_size>1024*1024:continue
            dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
        report['yosys_version']=run(['yosys','-V'],'yosys_version').strip();assert report['yosys_version']==parent['tool_version']
        report['iverilog_version']=run(['iverilog','-V'],'iverilog_version').splitlines()[0]
        report['vvp_version']=run(['vvp','-V'],'vvp_version').splitlines()[0]
        assert run(['git','-C',CACHE,'rev-parse','HEAD'],'model_commit').strip()==COMMIT
        assert run(['git','-C',CACHE,'status','--porcelain','--untracked-files=all'],'model_clean')==''
        run(['yosys','-Q','-T','-s',export_script],'export')
        assert circuit_signature(json.loads(roundtrip.read_text()))==circuit_signature(exported),'Export changed hardware circuit'
        report['export_circuit_identity']='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        executable=out/'board.vvp';models=[p for p in frozen if p.suffix=='.v']
        compile_inputs=[*generated,roundtrip,WRITES,READS]
        report['compile_inputs']=fingerprint(compile_inputs);save();report['stage']='compile';save()
        run(['iverilog','-g2012','-Ttyp','-s','tb_cmac_array_bram_demo','-s','glbl','-o',executable,*models,sv,bench],'compile')
        assert fingerprint(compile_inputs)==report['compile_inputs']
        report['compiled_executable']=fingerprint([executable]);save()
        for label,mode,cwd in [('negative',0,negative_cwd),*(('mode'+str(mode),mode,ROOT) for mode in MODES)]:
            assert fingerprint(compile_inputs)==report['compile_inputs'] and fingerprint([executable])==report['compiled_executable']
            report['stage']=label;report.setdefault('execution_inputs',{})[label]=fingerprint([*compile_inputs,executable]);save()
            text=run(['vvp',executable,'+MODE='+str(mode)],label,cwd,negative=label=='negative')
            if label!='negative':report['tests'].append(dict(mode=mode,status='PASS',result=validate_result(text,mode)))
            assert fingerprint([*compile_inputs,executable])==report['execution_inputs'][label];save()
        assert {t['mode'] for t in report['tests']}==set(MODES) and len(report['tests'])==9
        assert fingerprint(tracked)==report['source'],'Changed raw-board inputs or tools'
        verify_manifest(parent['source']);verify_manifest(parent['artifacts'])
        report.update(status='PASS_OBSERVABLE_RAW_ARRAY_BOARD_FOUR_STATE_MAPPED_ONLY',stage='complete',numerical_netlist_acceptance=True,
            artifacts=fingerprint([*generated,roundtrip,executable,*(ROOT/c['log'] for c in report['commands'])]))
    except BaseException as exc:report.update(status='FAIL',reason=str(exc) or repr(exc));raise
    finally:report['finished_utc']=timestamp();save();print(out/'report.json')
    print(report['status'])


if __name__=='__main__':main()
