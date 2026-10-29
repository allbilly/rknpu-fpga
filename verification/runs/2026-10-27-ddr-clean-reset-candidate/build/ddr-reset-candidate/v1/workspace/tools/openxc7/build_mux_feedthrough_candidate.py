#!/usr/bin/env python3
"""Build and pack-only probe one isolated mux feed-through legalization fix.

Recursively legalize a newly inserted MUXF7 before constraining its tree.
This prevents a shared original MUXF7 being absorbed as an illegal extra level
under that wrapper. Only pack.cc.o changes relative to the qualified counter-
safe parent. Reproduce that parent byte-identically; reproduce the missing
LUT buffer with the parent native packer; test four-state equivalence with
unchanged vendor models, including a real wrong-output negative; pack the
same fixture with the new engine. Existing fixtures and guards are untouched.

This is NOT native placement/routing qualification, full numerical acceptance,
fit, timing/electrical/DRC signoff, bitstream emission, or FPGA/RK testing.
No production RTL, native donor source/object, default pointer or SHA256SUMS
is written. Typed primitive fixtures are tool tests, not an NPU execution API.
"""
from collections import Counter
import difflib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
from prepare_prefix_shared_pack_input import digest
import build_heap_attempt_limit_candidate as heap
from qualify_counter_safe_heap import verify_qualification
from build_dsp_constant_candidate import NATIVE_SRC, CMAKE, compile_argv, dependencies, link_argv
from place_prefix_board import verify_bindings
from pack_prefix_board import DATABASE

PARENT = ROOT / 'build/openxc7/counter-safe-heap-engine-1791481639500508440/report.json'
QUALIFICATION = ROOT / 'build/openxc7/counter-safe-heap-qualification-1791486974423403401/report.json'
SOURCE = NATIVE_SRC / 'pack.cc'
OBJECT = CMAKE / 'uarch/xilinx/pack.cc.o'
CONTROL = ROOT / 'tests/cmac/test_mux_feedthrough_candidate_control.py'
BENCH = ROOT / 'tests/cmac/tb_mux_feedthrough_equivalence.sv'
VENDOR = ROOT / 'tests/vendor/xilinx-unisim/verilog/src/unisims'
MODELS = [VENDOR / (name + '.v') for name in ('LUT1', 'MUXF7', 'MUXF8')]
OLD = '                feed_through_muxf(pn, next_type, {pr});\n                continue;\n'
NEW = ('                CellInfo *feed = feed_through_muxf(pn, next_type, {pr});\n'
       '                legalise_muxf_tree(feed, mux_roots, seen_leaves);\n'
       '                continue;\n')
BUILT = 'BUILT_ISOLATED_RECURSIVE_MUX_FEEDTHROUGH_PACK_PROBED_NOT_PNR_QUALIFIED_OR_FULL_FIT'
FLAGS = ('full_native_placement_executed', 'native_routing_executed', 'physical_fit_verified',
         'full_numerical_acceptance', 'timing_signoff', 'electrical_verified', 'drc_signoff',
         'bitstream_emitted', 'hardware_programmed', 'default_engine_pointer_changed',
         'native_legality_guards_changed', 'warning_checks_suppressed',
         'FPGA_clock_or_geometry_changed', 'runtime_CPU_arithmetic_or_layout_fixup')
COMMANDS = ['software_controls', 'generated_check', 'compiler_version', 'iverilog_version', 'vvp_version',
            'compile_mux_equivalence', 'wrong_output_negative', 'four_state_equivalence',
            'relink_qualified_parent_identity', 'native_parent_pack_probe', 'compile_recursive_mux_feedthrough',
            'link_recursive_mux_feedthrough', 'native_version', 'native_candidate_pack_probe']


def candidate_source(original):
    assert original.count(OLD) == 1 and NEW not in original, 'Unexpected feed-through insertion site'
    changed = original.replace(OLD, NEW)
    verify_source_transition(original, changed)
    return changed


def verify_source_transition(original, changed):
    assert original.count(OLD) == 1 and changed.count(NEW) == 1
    assert changed.replace(NEW, OLD) == original, 'Unrelated packer change'
    assert original.count('NPNR_ASSERT') == changed.count('NPNR_ASSERT'), 'Assertion removal'


def primitive_fixture():
    cells = {}
    def cell(name, kind, connections, params=None):
        cells[name] = dict(hide_name=0, type=kind, parameters=params or {}, attributes={},
            port_directions={p: 'output' if p == 'O' else 'input' for p in connections},
            connections={p: [b] for p, b in connections.items()})
    cell('clock_pad', 'IBUF', {'I': 2, 'O': 6})
    for i in range(4):
        cell('leaf' + str(i), 'LUT1', {'I0': 6, 'O': 10 + i}, {'INIT': '10'})
    cell('left', 'MUXF7', {'I0': 10, 'I1': 11, 'S': 6, 'O': 20})
    cell('right', 'MUXF7', {'I0': 12, 'I1': 13, 'S': 6, 'O': 21})
    cell('root', 'MUXF8', {'I0': 20, 'I1': 21, 'S': 6, 'O': 22})
    for i, bit in enumerate((20, 21, 22)):
        cell('output_pad' + str(i), 'OBUF', {'I': bit, 'O': 3 + i})
    ports = dict(SYS_CLK=dict(direction='input', bits=[2]),
                 led_3bits_tri_o=dict(direction='output', bits=[3, 4, 5]))
    nets = {name: dict(hide_name=0, bits=port['bits'], attributes={}) for name, port in ports.items()}
    for bit in (6, 10, 11, 12, 13, 20, 21, 22):
        nets['wire_' + str(bit)] = dict(hide_name=0, bits=[bit], attributes={})
    return dict(creator='rknpu isolated native mux packer qualification fixture',
                modules=dict(mux_probe=dict(attributes={'top': '1'}, ports=ports, cells=cells, netnames=nets)))


def fixture_xdc():
    lines = ['set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]',
             'set_property IOSTANDARD LVCMOS18 [get_ports SYS_CLK]']
    for i, pin in enumerate(('P30', 'M30', 'N30')):
        port = '{led_3bits_tri_o[' + str(i) + ']}'
        lines.extend(['set_property PACKAGE_PIN ' + pin + ' [get_ports ' + port + ']',
                      'set_property IOSTANDARD LVCMOS18 [get_ports ' + port + ']'])
    return '\n'.join(lines + ['create_clock -period 20.000 [get_ports SYS_CLK]']) + '\n'


def pack_argv(executable, fixture, xdc, output):
    return list(map(str, [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
        '--top', 'mux_probe', '--json', fixture, '-o', 'xdc=' + str(xdc), '--pack-only',
        '--freq', '50', '--seed', '3588', '--Werror', '--debug', '--write', output]))


def packed_probe(document, corrected):
    assert len(document['modules']) == 1
    module = next(iter(document['modules'].values()))
    cells = module['cells']
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in bits:
                    assert bit not in drivers, 'Nonunique fixture driver'
                    drivers[bit] = (name, port)
    def driver(cell, port):
        bits = cell['connections'][port]
        assert len(bits) == 1 and bits[0] in drivers, 'Missing fixture driver'
        name, output = drivers[bits[0]]
        return name, output, cells[name]
    root = cells['root']
    assert root['type'] == 'SELMUX2_1' and root['attributes']['X_ORIG_TYPE'] == 'MUXF8'
    paths = []
    for port, foreign in (('0', 'left'), ('1', 'right')):
        name, output, wrapper = driver(root, port)
        assert wrapper['type'] == 'SELMUX2_1' and wrapper['attributes']['X_ORIG_TYPE'] == 'MUXF7'
        leaf_name, leaf_output, leaf = driver(wrapper, '0')
        if corrected:
            assert leaf['type'] == 'SLICE_LUTX' and leaf['attributes']['X_ORIG_TYPE'] == 'LUT1'
            assert int(leaf['parameters']['INIT'], 2) == 2, 'Nonidentity feed-through LUT'
            assert leaf_output == 'O6'
            foreign_name, foreign_output, foreign_cell = driver(leaf, 'A1')
        else:
            assert leaf['type'] == 'SELMUX2_1' and leaf['attributes']['X_ORIG_TYPE'] == 'MUXF7'
            foreign_name, foreign_output, foreign_cell = leaf_name, leaf_output, leaf
        assert foreign_name == foreign and foreign_output == 'OUT'
        assert foreign_cell['attributes']['X_ORIG_TYPE'] == 'MUXF7'
        paths.append(dict(root_port=port, wrapper=name, immediate_driver=leaf_name,
                          immediate_driver_type=leaf['type'], original_shared_mux=foreign))
    for i, foreign in enumerate(('left', 'right', 'root')):
        net = cells[foreign]['connections']['OUT']
        pad = cells['output_pad' + str(i)]
        assert net == pad['connections']['IN'] and pad['attributes']['X_ORIG_TYPE'] == 'OBUF'
    assert int(module['settings']['pack'], 2) == 1
    assert not int(module['settings'].get('place', '0'), 2) and not int(module['settings'].get('route', '0'), 2)
    return dict(paths=paths, corrected=corrected, cell_counts=dict(Counter(c['type'] for c in cells.values())),
                original_shared_mux_exports_preserved=True, native_placement_executed=False)


def verify_metadata(report):
    assert report['status'] == BUILT and report['stage'] == 'complete' and report['finished_utc']
    assert report['part'] == 'xc7k480tffg1156-2' and report['clock_period_ns'] == 20 and report['seed'] == 3588
    assert report['full_parallel_products'] == 512 and report['changed_link_objects'] == 1
    assert report['actual_original_source'] == str(SOURCE) and report['actual_original_object'] == str(OBJECT)
    assert report['source_change'] == 'RECURSE_ONLY_INTO_NEW_FEEDTHROUGH_MUX_BEFORE_CONSTRAINING'
    assert report['qualified_parent_relinked_byte_identical'] is True
    assert report['production_source_before'] == report['production_source_after']
    assert all(report[flag] is False for flag in FLAGS)
    assert [step['label'] for step in report['commands']] == COMMANDS
    for step in report['commands']:
        expected = 1 if step['label'] == 'wrong_output_negative' else 0
        assert step['returncode'] == expected and step['status'] == 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'
    assert report['four_state_vectors'] == 16384 and report['four_state_comparisons'] == 32768
    assert report['parent_probe']['corrected'] is False and report['candidate_probe']['corrected'] is True
    assert report['candidate_probe']['cell_counts']['SLICE_LUTX'] - report['parent_probe']['cell_counts']['SLICE_LUTX'] == 2


def main():
    parent = json.loads(PARENT.read_text())
    heap.verify_metadata(parent)
    q, before = verify_qualification(QUALIFICATION)
    assert q['executable'] == parent['executable'] and q['native_version'] == parent['native_version']
    heap.merge(before, parent['source'])
    heap.merge(before, parent['artifacts'])
    link = next(step for step in parent['commands'] if step['label'] == 'link_counter_safe_heap')
    assert link['argv'].count(str(OBJECT)) == 1
    deps = dependencies(Path(str(OBJECT) + '.d'))
    assert SOURCE in deps and str(SOURCE) in before and str(OBJECT) in before
    iverilog = Path(shutil.which('iverilog')).resolve(strict=True)
    vvp = Path(shutil.which('vvp')).resolve(strict=True)
    paths = {PARENT, QUALIFICATION, SOURCE, OBJECT, Path(str(OBJECT) + '.d'), CONTROL, BENCH,
             *MODELS, DATABASE, CMAKE / 'flags.make', CMAKE / 'build.make', Path(__file__).resolve(),
             Path(sys.executable).resolve(), Path('/usr/bin/c++').resolve(), iverilog, vvp, *deps}
    paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    heap.merge(before, {str(p): digest(p) for p in paths})
    verify_bindings(before)
    assert source_revision() == parent['production_source_after']
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (5 * 1024**3, 5 * 1024**3))
    out = ROOT / f'build/openxc7/recursive-mux-feedthrough-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='small_mapping_probe_and_build', started_utc=timestamp(),
        supervisor_pid=os.getpid(), source=before, commands=[], scope=__doc__, part='xc7k480tffg1156-2',
        clock_period_ns=20, seed=3588, full_parallel_products=512, changed_link_objects=1,
        actual_original_source=str(SOURCE), actual_original_object=str(OBJECT),
        source_change='RECURSE_ONLY_INTO_NEW_FEEDTHROUGH_MUX_BEFORE_CONSTRAINING',
        parent_build_report=str(PARENT), parent_qualification=str(QUALIFICATION),
        parent_executable=parent['executable'], production_source_before=source_revision(),
        **{flag: False for flag in FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, cwd=ROOT, timeout=1800, expected=0):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), timeout_seconds=timeout,
                    log=str(out / (label + '.log')), status='RUNNING', expected_returncode=expected)
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == expected, text[-3500:]
            if expected:
                assert 'MUX_EQ_MISMATCH vector=0 inactive=0' in text
                assert 'PASS_MUX_FEEDTHROUGH' not in text
            else:
                assert not re.search(r'(?im)\b(?:warning|error|fatal):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            step['status'] = 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'
            return text.strip()
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        original = SOURCE.read_text()
        source = out / 'himbaechel/uarch/xilinx/pack.cc'
        source.parent.mkdir(parents=True, exist_ok=False)
        source.write_text(candidate_source(original))
        report['generated_source_sha256'] = digest(source)
        shutil.copyfile(SOURCE, out / 'original-pack.cc')
        shutil.copyfile(__file__, out / 'executed_source.py')
        (out / 'recursive-mux-feedthrough.patch').write_text(''.join(difflib.unified_diff(
            original.splitlines(True), source.read_text().splitlines(True),
            fromfile='a/himbaechel/uarch/xilinx/pack.cc', tofile='b/himbaechel/uarch/xilinx/pack.cc')))
        fixture, xdc = out / 'mux_probe.json', out / 'mux_probe.xdc'
        fixture.write_text(json.dumps(primitive_fixture(), indent=2) + '\n')
        xdc.write_text(fixture_xdc())
        report['fixture_inputs'] = {str(p): digest(p) for p in (fixture, xdc)}
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        report['iverilog_version'] = run('iverilog_version', [iverilog, '-V'], timeout=60)
        report['vvp_version'] = run('vvp_version', [vvp, '-V'], timeout=60)
        simulation = out / 'mux-equivalence.vvp'
        run('compile_mux_equivalence', [iverilog, '-g2012', '-s', 'tb_mux_feedthrough_equivalence',
                                      '-o', simulation, BENCH, *MODELS], timeout=120)
        run('wrong_output_negative', [vvp, simulation, '+NEGATIVE'], timeout=120, expected=1)
        text = run('four_state_equivalence', [vvp, simulation], timeout=120)
        assert text.count('PASS_MUX_FEEDTHROUGH_FOUR_STATE vectors=16384 comparisons=32768') == 1
        report.update(four_state_vectors=16384, four_state_comparisons=32768)
        relinked = out / 'qualified-parent-relinked'
        run('relink_qualified_parent_identity', link_argv(link['argv'], relinked, {}), cwd=Path(link['cwd']))
        assert digest(relinked) == parent['executable']['sha256'], 'Qualified parent relink differs'
        report['qualified_parent_relinked_byte_identical'] = True
        old_packed = out / 'parent-packed.json'
        run('native_parent_pack_probe', pack_argv(parent['executable']['path'], fixture, xdc, old_packed))
        report['parent_probe'] = packed_probe(json.loads(old_packed.read_text()), corrected=False)
        obj = out / 'pack.cc.o'
        run('compile_recursive_mux_feedthrough', compile_argv('pack.cc', source, obj,
            (CMAKE / 'flags.make').read_text(), (CMAKE / 'build.make').read_text()), cwd=CMAKE.parent.parent)
        for dependency in dependencies(Path(str(obj) + '.d')):
            expected = report['generated_source_sha256'] if dependency == source else before[str(dependency)]
            assert digest(dependency) == expected, 'Changed/unbound new compilation dependency'
        assert digest(source) == report['generated_source_sha256']
        executable = out / 'nextpnr-himbaechel'
        run('link_recursive_mux_feedthrough', link_argv(link['argv'], executable, {OBJECT: obj}), cwd=Path(link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == parent['native_version']
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        new_packed = out / 'candidate-packed.json'
        run('native_candidate_pack_probe', pack_argv(executable, fixture, xdc, new_packed))
        report['candidate_probe'] = packed_probe(json.loads(new_packed.read_text()), corrected=True)
        for path, sha in report['fixture_inputs'].items(): assert digest(path) == sha
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        report.update(status=BUILT, stage='complete', finished_utc=timestamp())
        verify_metadata(report)
    except BaseException as error:
        report.update(status='FAIL_RECURSIVE_MUX_FEEDTHROUGH_BUILD_OR_PACK_PROBE', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
