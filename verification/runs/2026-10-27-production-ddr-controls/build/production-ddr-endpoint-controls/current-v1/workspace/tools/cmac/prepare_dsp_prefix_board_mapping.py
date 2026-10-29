#!/usr/bin/env python3
"""Real full-board mapped-CMAC/native-shell frontend preparation only.

Keep the original raw-QWORD/DMA/CACC/output/BRAM/clock/reset interface and all
512 products. This cannot stand in for whole-board mapping, netlist numerical
replay, Vivado implementation, physical signoff or a test-ready bitstream.
"""
import argparse
from collections import Counter
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
import map_dsp_prefix_board as mapping

UNPROVEN = ('full_board_mapping_acceptance', 'numerical_netlist_acceptance',
    'raw_board_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')


def frontend_script(spec, sources, partition, out):
    """Deliberately stop before synthesis: only load/elaborate native shells."""
    assert (spec['top'], spec['part'], spec['clock_period_ns'], spec['constraints']) == (
        'ypcb_cmac_array_top', 'xc7k480tffg1156-2', 20, 'fpga/ypcb.xdc')
    commands = ['read_verilog -lib +/xilinx/cells_sim.v', 'read_json ' + json.dumps(str(partition)),
        'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
        ' '.join('-I' + json.dumps(str(ROOT / n)) for n in spec['include_dirs']) + ' ' +
        ' '.join(json.dumps(str(p)) for p in sources),
        'hierarchy -check -top ' + spec['top'],
        'select -assert-mod-count 1 A:hdlname=' + mapping.KERNEL,
        'select -assert-mod-count 1 A:keep_hierarchy=1',
        'select -assert-count 16 */t:*' + mapping.KERNEL + '*',
        'proc', 'opt_clean', 'check -assert',
        # Default selection retains every concrete design module, excluding
        # only pre-existing library blackboxes with non-RTLIL model processes.
        # Do not convert design modules to blackboxes or change their cells.
        'write_json -selected ' + json.dumps(str(out / 'frontend_hierarchy.json'))]
    return ';\n'.join(commands) + '\n'


def validate_frontend(design, top, kernel, partition):
    """Count actual reachable instances and compare both imported circuits."""
    modules = design['modules']; original = partition['modules']
    assert set(original) == {mapping.MAPPED_CMAC, kernel}
    for name in original:
        assert mapping.kernel_identity(modules[name], name) == mapping.kernel_identity(original[name], name), (
            'Frontend changed imported mapped circuit', name)
    assert int(modules[kernel]['attributes']['keep_hierarchy'], 2) == 1
    assert modules[kernel]['attributes']['hdlname'] == mapping.KERNEL
    counts = Counter()
    def walk(name, stack=()):
        assert name not in stack, 'Recursive board hierarchy'
        counts[name] += 1
        if name == kernel: return
        for cell in modules[name].get('cells', {}).values():
            kind = cell['type']
            if kind in modules and not int(modules[kind].get('attributes', {}).get('blackbox', '0'), 2):
                walk(kind, stack + (name,))
    walk(top)
    assert counts[kernel] == 16 and counts[mapping.MAPPED_CMAC] == 1, 'All sixteen mapped kernels required'
    # The data-identical imported implementation retains its original hdlname
    # even though its module key is aliased. It is not the parameter shim.
    wrappers = [n for n in counts if n != mapping.MAPPED_CMAC and
        modules[n].get('attributes', {}).get('hdlname') == mapping.CMAC]
    assert len(wrappers) == 1 and counts[wrappers[0]] == 1, 'One checked C32/K16 parameter wrapper required'
    wrapper = modules[wrappers[0]]
    mapping.array.validate_ports(wrapper)
    assert len(wrapper['cells']) == 1
    delegate = next(iter(wrapper['cells'].values()))
    assert delegate['type'] == mapping.MAPPED_CMAC and delegate.get('parameters', {}) == {}
    for port, value in wrapper['ports'].items():
        assert delegate['connections'][port] == value['bits'], ('Nonliteral mapped partition delegate', port)
    forbidden = {mapping.replay.preparation.ORIGINAL_CELL, mapping.replay.preparation.ORIGINAL_ARRAY}
    forbidden_names = {Path(n).stem for n in forbidden} | {
        'rk_cmac_fp16_cell_fixed', 'rk_cmac_fp16_array_fixed',
        'rk_cmac_fp16_cell_dsp', 'rk_cmac_fp16_array_dsp', 'rk_cmac_fp16_lane_dsp',
        mapping.KERNEL, 'rk_cmac_fp16_lane_dsp_prefix', 'rk_cmac_fp16_discarded_carry'}
    for name in counts:
        if name != kernel:
            assert name not in forbidden_names
            assert modules[name].get('attributes', {}).get('hdlname') not in forbidden_names, 'Native arithmetic fallback'
    ports = modules[top]['ports']
    assert {n: (p['direction'], len(p['bits'])) for n, p in ports.items()} == {
        'SYS_CLK': ('input', 1), 'SYS_RSTN': ('input', 1), 'led_3bits_tri_o': ('output', 3)}
    assert all(type(b) is int for p in ports.values() for b in p['bits']), 'Constant board boundary'
    return dict(reachable_instances=dict(sorted(counts.items())), mapped_kernel_instances=16,
        retained_cmac_dsps=512, imported_kernel_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
        imported_array_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        checked_parameter_wrapper=wrappers[0], native_shell_unmapped=True)


def verify_parents(area_path, native_path, prepared_path, spec):
    area, raw, hierarchy = mapping.verify_area(area_path)
    native = mapping.replay.verify_native(native_path)
    prepared, binary, sources = mapping.replay.verify_prepared(prepared_path, spec)
    mapping.array_contract.validate_shared_leaf(area, native)
    assert prepared['lane_report'] == native['lane_report'], 'Different compiled/native prefix leaf'
    return area, native, prepared, raw, hierarchy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('area', 'native', 'prepared'): parser.add_argument('--' + name + '-report', type=Path, required=True)
    args = parser.parse_args()
    ap, np, pp = [mapping.replay.workspace_path(p) for p in (args.area_report, args.native_report, args.prepared_report)]
    spec, base = mapping.inputs()
    area, native, prepared, raw, hierarchy = verify_parents(ap, np, pp, spec)
    frozen, kernel, cells = mapping.partition(raw)
    frozen, shim_text = mapping.parameter_binding(frozen, mapping.array.DSP_ARRAY.read_text())
    out = ROOT / f'build/rknpu-dsp-prefix-board-mapping-preparation/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    join, shim, part = [out / n for n in (Path(mapping.replay.preparation.JOIN).name,
        'mapped_cmac_parameter_binding.sv', 'cmac_partition.json')]
    join.write_text(mapping.replay.preparation.dsp_join((ROOT / mapping.replay.preparation.JOIN).read_text()))
    shim.write_text(shim_text); part.write_text(json.dumps(frozen) + '\n')
    sources = mapping.synthesis_sources(spec, join, shim)
    imported = {Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')}
    tracked = {*base, *sources, part, ap, np, pp, hierarchy, *imported, Path(__file__).resolve()}
    for parent in (area, native, prepared): tracked.update(ROOT / n for n in parent['source']['files'])
    before = fingerprint(tracked); generated = [join, shim, part]
    report = dict(status='RUNNING', stage='frontend', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, intended_part=spec['part'], intended_clock_period_ns=spec['clock_period_ns'],
        parent_reports={'area': str(ap.relative_to(ROOT)), 'native': str(np.relative_to(ROOT)),
            'compiled_board': str(pp.relative_to(ROOT))},
        parent_source_sha256={'area': area['source']['sha256'], 'native': native['source']['sha256'],
            'compiled_board': prepared['source']['sha256']},
        synthesis_sources=[str(p.relative_to(ROOT)) for p in sources], preserved_kernel=kernel,
        source_bound_imported_kernel_cells=dict(cells), frontend_prepared=False,
        **{n: False for n in UNPROVEN}, scope=__doc__)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)),
            status='RUNNING', timeout_seconds=1800)
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0, text[-3000:]
            if label == 'frontend': report['source_bound_frontend_notices'] = mapping.frontend_diagnostics(text)
            else: assert not re.search(r'(?im)\b(?:warning|error):|sorry:|FATAL:', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        for path in sorted(tracked):
            if path.suffix in ('.json', '.vvp') and str(path.relative_to(ROOT)).startswith('build/') and path not in {ap, np, pp, part}:
                continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == area['tool_version']
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        script = out / 'frontend.ys'; script.write_text(frontend_script(spec, sources, part, out)); generated.append(script)
        report['compile_inputs'] = fingerprint([*sources, part, script]); save()
        graph = out / 'frontend_hierarchy.json'; generated.append(graph)
        run(['yosys', '-Q', '-T', '-s', script], 'frontend')
        assert fingerprint([*sources, part, script]) == report['compile_inputs']
        report['geometry'] = validate_frontend(json.loads(graph.read_text()), spec['top'], kernel, frozen)
        assert fingerprint(tracked) == before
        verify_parents(ap, np, pp, spec); mapping.array.validate_sources()
        report.update(status='PREPARED_FULL_C32K16_DSP_PREFIX_MAPPED_KERNEL_NATIVE_BOARD_SHELL_FRONTEND_ONLY',
            stage='complete', finished_utc=timestamp(), frontend_prepared=True,
            artifacts=fingerprint([*generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
