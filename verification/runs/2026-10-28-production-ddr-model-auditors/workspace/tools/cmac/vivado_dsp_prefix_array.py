#!/usr/bin/env python3
"""Prepare, synthesize, or fully route the prefix-DSP raw-board profile.

Synthesis and route require this variant's completed native, mapped binary,
area and nine-mode four-state board reports. Both keep sixteen kernels/512
CMAC DSPs. Synthesis stops before placement/routing and makes no timing/DRC
claim. Route produces a review-required checkpoint only: no bitstream emission,
hardware connection or flash programming.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import map_dsp_prefix_board as gates
import test_dsp_prefix_mapped_array as mapped
import verify_dsp_prefix_clean_replay as clean_replay
from vivado_array import inputs as original_inputs, render as original_render, validate_full_vivado_version

PROFILE = 'dsp-prefix-c32k16'
ROUTED = 'ROUTED_DSP_PREFIX_ARRAY_CHECKPOINT_REVIEW_REQUIRED'
SYNTHESIZED = 'SYNTHESIZED_FULL_C32K16_DSP_PREFIX_ONLY_NOT_PHYSICAL_FIT_OR_SIGNOFF'
LABELS = ('verilator_version', 'cxx_version', 'yosys_version', 'datadir', 'export', 'roundtrip',
    'cell_compile', 'top_generate', 'top_compile', 'negative_test', 'actual_test')
GUARD = '''
# Preserve and count the actual CMAC hierarchy, independently of shell DSPs.
proc require_full_dsp_cmac {} {
    set kernels [get_cells -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix || REF_NAME == rk_cmac_fp16_cell_dsp_prefix}]
    if {[llength $kernels] != 16} { error "Expected sixteen full C32 DSP kernels." }
    set all_dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E1}]
    set owned {}
    foreach kernel $kernels {
        set prefix "[get_property NAME $kernel]/"
        set count 0
        foreach dsp $all_dsps {
            set name [get_property NAME $dsp]
            if {[string first $prefix $name] == 0} {
                if {[dict exists $owned $name]} { error "DSP belongs to duplicate CMAC kernels." }
                dict set owned $name 1
                incr count
            }
        }
        if {$count != 32} { error "Expected 32 DSP48E1 products in every C32 kernel." }
    }
    if {[dict size $owned] != 512} { error "Expected 512 retained parallel CMAC DSP products." }
}
require_full_dsp_cmac
'''


def tool_dependencies():
    """Walk this driver's referenced project modules, never caller-only imports.

    Imported functions/classes retain their defining module too. Keep explicit
    generated-source inputs separately; they need not be imported to be used.
    """
    pending = [sys.modules[__name__]]; found = {}
    while pending:
        module = pending.pop()
        name = getattr(module, '__file__', None)
        if not name: continue
        path = Path(name).resolve()
        if not path.is_relative_to(ROOT / 'tools') or path in found: continue
        found[path] = module
        for value in vars(module).values():
            dependency = value if isinstance(value, ModuleType) else sys.modules.get(getattr(value, '__module__', ''))
            if dependency is not None: pending.append(dependency)
    return sorted(found)


def inputs(directory):
    directory = directory.resolve(); assert directory.is_relative_to(ROOT)
    spec, tracked = original_inputs()
    join = directory / Path(gates.replay.preparation.JOIN).name
    assert join.read_text() == gates.replay.preparation.dsp_join((ROOT / gates.replay.preparation.JOIN).read_text())
    sources = gates.replay.preparation.simulation_sources(dict(spec, simulation_helpers=[]), join)
    assert all(p in sources for p in (gates.array.DSP_ARRAY, gates.array.DSP_CELL,
        gates.replay.preparation.LANE, gates.replay.preparation.HELPER))
    gates.array.validate_sources()
    spec = dict(spec, synthesis=[str(p.relative_to(ROOT)) for p in sources], source_profile=PROFILE)
    tracked += [*sources, join, ROOT / gates.replay.preparation.JOIN,
        gates.array.FIXED_ARRAY, gates.array.FIXED_CELL, Path(__file__).resolve()]
    tracked += list((ROOT / 'rtl/vendor/nvdla').glob('*.vlib'))
    tracked += [ROOT / 'rtl/vendor/nvdla' / name for name in
        ('LICENSE', 'assertion_header.h', 'assertion_task.h')]
    tracked += tool_dependencies()
    metadata = directory / 'profile_evidence.json'
    if metadata.exists():
        provenance = json.loads(metadata.read_text()); assert set(provenance) == {'area', 'native', 'board', 'mapped'}
        tracked += [metadata, *[gates.replay.workspace_path(p) for p in provenance.values()],
            *[directory / (n + '_snapshot.json') for n in provenance]]
    return spec, sorted(set(tracked))


def render(spec, out, sha, synthesis_only=False):
    assert spec['source_profile'] == PROFILE
    text = original_render(spec, out, sha)
    synth = 'synth_design -top ypcb_cmac_array_top -part xc7k480tffg1156-2 -generic LED_ACTIVE_LOW=$active_low'
    marker = 'write_checkpoint -force [file join $out post_synth.dcp]'
    assert text.count(synth) == text.count(marker) == text.count('\nroute_design\n') == 1
    text = text.replace(synth, synth + ' -flatten_hierarchy none')
    text = text.replace(marker, GUARD + '\n' + marker)
    text = text.replace('\nroute_design\n', '\nroute_design\nrequire_full_dsp_cmac\n')
    if synthesis_only:
        route_stage = '\nopt_design\n'
        assert text.count(route_stage) == 1
        text = text.split(route_stage, 1)[0] + '''
puts "C32/K16 synthesis checkpoint produced; no placement, routing, timing/DRC signoff, bitstream or programming."
'''
        for forbidden in ('place_design', 'phys_opt_design', 'route_design', 'report_timing_summary',
                          'check_timing', 'report_pulse_width', 'report_drc', 'write_bitstream'):
            assert forbidden not in text, 'Synthesis-only Tcl contains physical stage: ' + forbidden
    return text


def validate_mapped_metadata(report):
    if report['status'] == clean_replay.STATUS:
        clean_replay.validate_metadata(report)
        return
    assert report['status'] == 'PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_FIXTURES_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['frames'],
        report['expected_outputs'], report['seed']) == (32, 16, 512, 208, 3328, '0x35883216')
    assert report['numerical_netlist_binary_fixture_acceptance'] is True
    assert report['expected_result'] == report['result'] == mapped.EXPECTED
    assert report['kernel_cells']['DSP48E1'] == 32 and not any(
        count for kind, count in report['kernel_cells'].items() if kind.startswith('FD'))
    assert report['library_operations'] == ['combo_update', 'create']
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    assert [Path(s['log']).stem for s in report['commands']] == list(LABELS)
    for label, step in zip(LABELS, report['commands']):
        assert step['status'] == 'PASS'
        assert type(step['returncode']) is int, 'Missing or invalid command exit code: ' + label
        assert (step['returncode'] != 0 if label == 'negative_test' else step['returncode'] == 0), label
    for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance', 'physical_fit_verified',
        'bitstream_emitted', 'hardware_programmed'): assert report[name] is False


def verify_mapped(path, area_path, native_path, area, native):
    report = json.loads(path.read_text())
    if report['status'] == clean_replay.STATUS:
        return clean_replay.verify(path, area_path, native_path, area, native)
    validate_mapped_metadata(report)
    gates.replay.verify_evidence(report)
    assert report['parent_reports'] == {n: str(p.relative_to(ROOT)) for n, p in
        (('area', area_path), ('native', native_path))}
    assert report['parent_source_sha256'] == {'area': area['source']['sha256'], 'native': native['source']['sha256']}
    for name in ('area', 'native'):
        assert report['parent_reports'][name] in report['source']['files']
    assert str(Path(mapped.__file__).resolve().relative_to(ROOT)) in report['source']['files']
    assert report['export_tool_version'] == area['tool_version']
    for step in report['commands'][-2:]:
        text = gates.replay.workspace_path(step['log']).read_text()
        result = mapped.validate_result(text, step['returncode'], Path(step['log']).stem == 'negative_test')
        if result: assert result == report['result']
    return report


def validate_evidence(directory):
    provenance = json.loads((directory / 'profile_evidence.json').read_text())
    assert set(provenance) == {'area', 'native', 'board', 'mapped'}
    paths = {n: gates.replay.workspace_path(p) for n, p in provenance.items()}
    area, _, _ = gates.verify_area(paths['area'])
    native = gates.replay.verify_native(paths['native'])
    board, board_paths, _ = gates.verify_board(paths['board'], json.loads(gates.replay.preparation.SPEC.read_text()))
    assert board_paths['native'] == paths['native'], 'Board used a different native parent'
    binary = verify_mapped(paths['mapped'], paths['area'], paths['native'], area, native)
    parents = dict(area=area, native=native, board=board, mapped=binary)
    for name, parent in parents.items():
        assert json.loads((directory / (name + '_snapshot.json')).read_text()) == parent, 'Changed parent snapshot'
    return parents


def snapshot_parent_evidence(out, evidence):
    paths = {n: gates.replay.workspace_path(p) for n, p in evidence.items()}
    (out / 'profile_evidence.json').write_text(json.dumps(
        {n: str(p.relative_to(ROOT)) for n, p in paths.items()}, indent=2) + '\n')
    for name, path in paths.items(): (out / (name + '_snapshot.json')).write_bytes(path.read_bytes())
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'synth', 'run'))
    for name in ('area', 'native', 'board', 'mapped'): parser.add_argument('--' + name + '-report', type=Path)
    parser.add_argument('--vivado', default='vivado'); args = parser.parse_args()
    names = ('area', 'native', 'board', 'mapped')
    evidence = {n: getattr(args, n + '_report') for n in names}
    if args.action == 'prepare': assert all(p is None for p in evidence.values()), 'prepare claims no numerical evidence'
    else: assert all(p is not None for p in evidence.values()), 'synth/run require all four completed prefix variant reports'
    out = ROOT / f'build/rknpu-dsp-prefix-array-vivado/{args.action}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    join = out / Path(gates.replay.preparation.JOIN).name
    join.write_text(gates.replay.preparation.dsp_join((ROOT / gates.replay.preparation.JOIN).read_text()))
    if args.action in ('synth', 'run'):
        evidence = snapshot_parent_evidence(out, evidence)
    spec, tracked = inputs(out); before = fingerprint(tracked)
    report = dict(status='RUNNING', started_utc=timestamp(), action=args.action, source_profile=PROFILE,
        source=before, commands=[], channels=32, kernels=16, parallel_products=512,
        synthesis_completed=False, routed_checkpoint_produced=False, timing_signoff=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False, physical_fit_verified=False,
        implementation_settings={k: os.environ.get(k) for k in
            ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_LED_ACTIVE_LOW')},
        scope='Prepared DSP sources, source-gated full C32/K16 synthesis-only checkpoint, or checkpoint-only full implementation. Same raw K65 ROM, original surrounding RTL, XC7K480T FFG1156-2, pins, 20 ns clock and unchanged physical/electrical/DRC/review gates. Synthesis-only stops before placement/routing. No bitstream, card/flash programming or RK compatibility acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, env=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=86400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0, text[-6000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save(); script = out / 'build.tcl'
    try:
        parents = validate_evidence(out) if args.action in ('synth', 'run') else None
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        script.write_text(render(spec, out, before['sha256'], synthesis_only=args.action == 'synth'))
        for path in tracked:
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
        if args.action == 'prepare':
            report.update(status='PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY',
                prerequisites='No HDL or Vivado executed. synth/run require completed current prefix area/native/mapped binary and all nine prefix Icarus board modes, full Vivado and explicit board confirmation. Known strict source lint warnings are not relabeled PASS.')
        else:
            report['variant_evidence'] = parents
            assert os.environ.get('RK_CONFIRM_BOARD') == 'YPCB_00338_1P1'
            executable = shutil.which(args.vivado)
            assert executable and Path(executable).name == 'vivado', 'UNAVAILABLE: full Vivado, not Lab'
            report['tool_version'] = run([executable, '-version'], 'version')
            validate_full_vivado_version(report['tool_version'])
            env = dict(os.environ, RK_ARRAY_SOURCE_SHA=before['sha256'])
            run([executable, '-mode', 'batch', '-source', script, '-log', out / 'vivado.log',
                '-journal', out / 'vivado.jou'], 'synthesis' if args.action == 'synth' else 'implementation', env)
            assert (out / 'post_synth.dcp').is_file()
            report['synthesis_completed'] = True
            if args.action == 'synth':
                assert (out / 'utilization_synth.rpt').is_file()
                assert not (out / 'routed.dcp').exists() and not list(out.glob('*.bit'))
                assert validate_evidence(out) == parents
                report.update(status=SYNTHESIZED, routed_checkpoint_produced=False,
                    timing_signoff=False, drc_signoff=False, physical_fit_verified=False,
                    prerequisites='Actual full C32/K16 Vivado synthesis only. Placement, routing, timing/DRC review, bitstream emission and hardware programming remain separate gates.')
            else:
                assert (out / 'routed.dcp').is_file() and not list(out.glob('*.bit'))
                assert validate_evidence(out) == parents
                report.update(status=ROUTED, routed_checkpoint_produced=True)
        assert fingerprint(tracked) == before, 'Changed DSP build inputs'
        report['artifacts'] = fingerprint([p for p in out.rglob('*') if p.is_file() and p.name != 'report.json'])
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally: report['finished_utc'] = timestamp(); save(); print(out / 'report.json', flush=True)
    print(report['status'], flush=True)


if __name__ == '__main__': main()
