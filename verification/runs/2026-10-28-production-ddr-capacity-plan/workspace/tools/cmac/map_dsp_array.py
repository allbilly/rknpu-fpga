#!/usr/bin/env python3
"""Measure all 512 compensated DSP lanes; area only, never physical signoff.

The sixteen C32 kernels remain parallel hardware. Preserve their synthesis
hierarchy so the repeated circuit is mapped once, then flatten primitives.
Numerical, raw-board, electrical, timing and DRC acceptance are separate gates.
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
from dsp_array_contract import DSP_ARRAY, DSP_CELL, FIXED_ARRAY, FIXED_CELL, validate_sources
from lane_dsp_library import timing_only_view
from test_mapped_lane_dsp import SOURCES, validate_parent_metadata
from test_fixed_array_board import verify_manifest
from xc7_primitive_counts import primitive_counts

TOP = 'rk_cmac_fp16_array_dsp'
CELL = 'rk_cmac_fp16_cell_dsp'
LANE = 'rk_cmac_fp16_lane_dsp'
INPUTS = {'clk': 1, 'rst_n': 1, 'in_valid': 1, 'in_data': 512,
    'in_weight': 8192, 'in_data_mask': 32, 'in_weight_mask': 512,
    'in_tag': 35, 'out_ready': 1}
OUTPUTS = {'in_ready': 1, 'out_valid': 1, 'out_groups': 704, 'out_tag': 35, 'error': 1}
COARSE = ['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
    'alumacc', 'share', 'opt', 'memory -nomap', 'opt_clean']


def validate_ports(module):
    assert {n: (p['direction'], len(p['bits'])) for n, p in module['ports'].items()} == {
        **{n: ('input', w) for n, w in INPUTS.items()},
        **{n: ('output', w) for n, w in OUTPUTS.items()}}, 'Changed full-array boundary'
    bits = [b for n in INPUTS for b in module['ports'][n]['bits']]
    assert all(type(b) is int for b in bits) and len(set(bits)) == sum(INPUTS.values()), 'Reduced or coupled inputs'
    for name in OUTPUTS:
        assert all(type(b) is int for b in module['ports'][name]['bits']), ('Constant output', name)


def kernel_types(modules):
    kinds = [c['type'] for c in modules[TOP]['cells'].values() if c['type'] in modules
        and modules[c['type']].get('attributes', {}).get('hdlname') == CELL]
    assert len(kinds) == 16 and len(set(kinds)) == 1, 'Changed sixteen parallel kernels'
    assert int(modules[kinds[0]]['attributes'].get('keep_hierarchy', '0'), 2) == 1
    return kinds


def validate_elaboration(design):
    modules = design['modules']; validate_ports(modules[TOP]); kernel_types(modules)
    def lanes(name, stack=()):
        assert name not in stack, 'Recursive hierarchy'
        if name == LANE: return 1
        return sum(lanes(c['type'], stack + (name,)) for c in modules[name]['cells'].values()
            if c['type'] in modules)
    assert lanes(TOP) == 512, 'Changed 512 parallel compensated lanes'


def validate_partition(design):
    modules, audit = timing_only_view(design['modules'])
    validate_ports(modules[TOP]); kinds = kernel_types(modules)
    # Do not broaden the global counter's permitted original-kernel hierarchy.
    # Count this explicitly admitted experimental kernel and shell separately.
    shell = dict(modules)
    shell[TOP] = dict(modules[TOP], cells={n: c for n, c in modules[TOP]['cells'].items()
        if c['type'] not in set(kinds)})
    counts = primitive_counts(shell, TOP)
    kernel_counts = primitive_counts(modules, kinds[0])
    assert kernel_counts['DSP48E1'] == 32, 'Each C32 kernel must retain 32 DSPs'
    for _ in kinds: counts.update(kernel_counts)
    assert counts['DSP48E1'] == 512, 'Changed full-array DSP count'
    return counts, audit, kinds


def validate_flat(design, expected):
    modules, audit = timing_only_view(design['modules']); validate_ports(modules[TOP])
    counts = Counter(c['type'] for c in modules[TOP]['cells'].values() if c['type'] != '$scopeinfo')
    assert counts == expected == primitive_counts(modules, TOP), 'Flattening changed hardware primitives'
    assert counts['DSP48E1'] == 512
    assert sum(v for k, v in counts.items() if k.startswith('FD')) >= 16 * 32 + 35
    assert sum(v for k, v in counts.items() if k.startswith('LUT')) > 0
    return counts, audit


def unshared_coarse(help_text):
    assert "'keep_hierarchy' attribute set will not be" in help_text
    match = re.search(r'\n    coarse:\n(.*?)\n    map_memory:', help_text, re.S)
    assert match and [s.strip() for s in match.group(1).splitlines() if s.strip()] == COARSE
    return [s.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for s in COARSE if s != 'share']


def mapping_script(sources, out, coarse):
    quote = lambda name: json.dumps(str(out / name))
    commands = ['read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
        ' '.join(json.dumps(str(p)) for p in sources),
        f'chparam -set ATOMIC_C 32 -set ATOMIC_K 16 {TOP}', f'hierarchy -check -top {TOP}',
        f'select -assert-mod-count 1 A:hdlname={CELL}', f'setattr -mod -set keep_hierarchy 1 A:hdlname={CELL}',
        'select -assert-mod-count 1 A:keep_hierarchy=1', f'select -assert-count 16 */t:*{CELL}*',
        'proc', 'opt_clean', 'check -assert', 'write_json ' + quote('hierarchy.json')]
    flags = f'-family xc7 -top {TOP} -flatten -noiopad -noclkbuf'
    # The ending label is exclusive. Stop at coarse, not map_dsp, so the
    # DSP stage executes before replacing only the optional SHARE pass.
    # Detect missing products before expensive LUT mapping or flat export.
    commands += [f'synth_xilinx {flags} -run begin:coarse',
        'select -assert-count 32 */t:DSP48E1', 'select -clear', *coarse,
        f'synth_xilinx {flags} -run map_memory:', 'check -assert',
        'write_json ' + quote('mapped_hierarchy.json'), 'setattr -mod -unset keep_hierarchy',
        'setattr -unset keep_hierarchy', 'flatten', 'check -assert',
        'write_json ' + quote('mapped.json'), 'write_verilog -noattr -noexpr -norename ' + quote('mapped.v')]
    return ';\n'.join(commands) + '\n'


def audit_mapping_log(text):
    assert 'ERROR:' not in text and 'Executing SHARE pass' not in text
    assert text.count('Executing XILINX_DSP pass') == 1, 'DSP synthesis stage must execute exactly once'
    donor = str(ROOT / 'rtl/vendor/nvdla/NV_DW02_tree.v')
    allowed = {
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33',
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28'}
    warnings = [s for s in text.splitlines() if s.startswith('Warning:')]
    assert set(warnings) <= allowed, ('Unknown mapping warning', warnings)
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane-area-report', type=Path, required=True)
    args = parser.parse_args(); parent_path = args.lane_area_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text()); validate_parent_metadata(parent)
    for manifest in (parent['source'], parent['artifacts']): verify_manifest(manifest)
    validate_sources(); sources = [*SOURCES[:4], DSP_CELL, DSP_ARRAY]
    assert all(str(p.relative_to(ROOT)) in parent['source']['files'] for p in SOURCES[:4])
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), parent_path, *sources, FIXED_CELL, FIXED_ARRAY,
        ROOT / 'rtl/vendor/nvdla/LICENSE', *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-array-area/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='preparation', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, intended_part='xc7k480tffg1156-2', target_family='xc7',
        parent_report=str(parent_path.relative_to(ROOT)), parent_source_sha256=parent['source']['sha256'],
        numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Full parallel C32/K16 experimental DSP-array area/structure only. Original raw-command path unchanged. Synthesis hierarchy does not serialize or share physical products. Timing-only primitive declaration qualifiers audited solely in the counter view; unchanged actual circuit stored. No native/mapped numerical, raw-board, packed utilization, physical timing/electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0 and 'ERROR:' not in text, text[-6000:]
            if label == 'mapping': report['source_bound_array_lowering_notices'] = audit_mapping_log(text)
            else: assert not re.search(r'(?im)\b(?:warning|error):', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == parent['tool_version']
        help_text = run(['yosys', '-Q', '-T', '-p', 'help flatten; help synth_xilinx'], 'help')
        coarse = unshared_coarse(help_text)
        report.update(original_coarse_stage=COARSE, executed_coarse_stage=coarse)
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        script = out / 'mapping.ys'; script.write_text(mapping_script(sources, out, coarse)); generated.append(script)
        compile_inputs = fingerprint([*sources, script]); report['compile_inputs'] = compile_inputs
        report['stage'] = 'mapping'; save(); run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert fingerprint([*sources, script]) == compile_inputs
        generated += [out / n for n in ('hierarchy.json', 'mapped_hierarchy.json', 'mapped.json', 'mapped.v')]
        report['stage'] = 'structural_checks'; save()
        validate_elaboration(json.loads((out / 'hierarchy.json').read_text()))
        expected, partition_audit, kinds = validate_partition(json.loads((out / 'mapped_hierarchy.json').read_text()))
        counts, flat_audit = validate_flat(json.loads((out / 'mapped.json').read_text()), expected)
        assert flat_audit == partition_audit, 'Changed primitive timing declaration'
        assert fingerprint(tracked) == before; validate_sources()
        for manifest in (parent['source'], parent['artifacts']): verify_manifest(manifest)
        report.update(status='PASS_FULL_C32K16_DSP_ARRAY_XC7_AREA_ONLY', stage='complete',
            finished_utc=timestamp(), instantiated_lanes=512, mapped_kernel_instances=16,
            mapped_kernel_types=sorted(set(kinds)), cells=dict(counts), timing_qualifier_counter_audit=flat_audit,
            lut_count=sum(v for k, v in counts.items() if k.startswith('LUT')),
            ff_count=sum(v for k, v in counts.items() if k.startswith('FD')), dsp_count=counts['DSP48E1'],
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
