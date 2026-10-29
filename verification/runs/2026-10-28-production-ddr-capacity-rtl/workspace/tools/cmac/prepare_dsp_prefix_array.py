#!/usr/bin/env python3
"""Elaborate exact full C32/K16 prefix geometry; no numerical/physical PASS."""
from collections import Counter
import hashlib
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
import dsp_prefix_array_contract as contract

TOP = 'rk_cmac_fp16_array_dsp_prefix'
LANE = 'rk_cmac_fp16_lane_dsp_prefix'
PORTS = {n: (d, w) for n, d, w in (
    ('clk', 'input', 1), ('rst_n', 'input', 1), ('in_valid', 'input', 1), ('in_ready', 'output', 1),
    ('in_data', 'input', 512), ('in_weight', 'input', 8192), ('in_data_mask', 'input', 32),
    ('in_weight_mask', 'input', 512), ('in_tag', 'input', 35), ('out_valid', 'output', 1),
    ('out_ready', 'input', 1), ('out_groups', 'output', 704), ('out_tag', 'output', 35), ('error', 'output', 1))}


def validate_geometry(design):
    modules = design['modules']; top = modules[TOP]
    assert {n: (p['direction'], len(p['bits'])) for n, p in top['ports'].items()} == PORTS
    assert {n: int(v, 2) for n, v in top['parameter_default_values'].items()} == {
        'ATOMIC_C': 32, 'ATOMIC_K': 16, 'TAG_WIDTH': 35}
    inputs = [b for n, p in top['ports'].items() if p['direction'] == 'input' for b in p['bits']]
    assert all(type(b) is int for b in inputs) and len(inputs) == len(set(inputs)), 'Coupled or constant array inputs'
    kernels = {n: c for n, c in top['cells'].items() if 'rk_cmac_fp16_cell_dsp_prefix' in c['type']}
    assert set(kernels) == {f'kernels[{k}].cell_core' for k in range(16)}, 'Reduced or renamed kernel geometry'
    assert len({c['type'] for c in kernels.values()}) == 1
    kernel = modules[next(iter(kernels.values()))['type']]
    assert int(kernel['parameter_default_values']['ATOMIC_C'], 2) == 32
    assert {n: (p['direction'], len(p['bits'])) for n, p in kernel['ports'].items()} == {
        'data': ('input', 512), 'weight': ('input', 512), 'data_mask': ('input', 32),
        'weight_mask': ('input', 32), 'result': ('output', 44), 'invalid': ('output', 1)}
    lanes = {n: c for n, c in kernel['cells'].items() if c['type'] == LANE}
    assert set(lanes) == {f'lanes[{i}].donor' for i in range(32)}, 'Reduced or serialized products'
    assert LANE in modules and 'rk_cmac_fp16_lane_dsp' not in modules, 'Retained original/native fallback lane'
    result_bits, invalid_bits = [], []
    for k in range(16):
        c = kernels[f'kernels[{k}].cell_core']['connections']
        assert c['data'] == top['ports']['in_data']['bits'] and c['data_mask'] == top['ports']['in_data_mask']['bits']
        assert c['weight'] == top['ports']['in_weight']['bits'][k*512:(k+1)*512]
        assert c['weight_mask'] == top['ports']['in_weight_mask']['bits'][k*32:(k+1)*32]
        assert len(c['result']) == 44 and len(c['invalid']) == 1
        result_bits += c['result']; invalid_bits += c['invalid']
    assert all(type(b) is int for b in result_bits + invalid_bits)
    assert len(set(result_bits)) == 704 and len(set(invalid_bits)) == 16, 'Coupled kernel outputs'
    return dict(channels=32, kernels=16, parallel_products=512, tag_width=35,
        cell_module=next(iter(kernels.values()))['type'], lane_module=LANE)


def native_diagnostics(text):
    donor = contract.leaf.lane.SOURCES[0]
    expected = Counter({
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33': 3,
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28': 3})
    found = Counter(s for s in text.splitlines() if re.search(r'(?i)\bwarning:', s))
    assert found == expected, ('Changed native hierarchy diagnostics', dict(found))
    assert not re.search(r'(?im)ERROR:|FATAL:|sorry:', text), 'Failed hierarchy diagnostics'
    return dict(found)


def main():
    contract.validate_sources()
    sources = [*contract.leaf.lane.SOURCES[:4], contract.leaf.HELPER, contract.leaf.CANDIDATE,
        contract.CELL, contract.ARRAY]
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), contract.original.DSP_CELL, contract.original.DSP_ARRAY,
        contract.original.FIXED_CELL, contract.original.FIXED_ARRAY, *sources, *imported,
        ROOT / 'rtl/vendor/nvdla/LICENSE', contract.original.BENCH, contract.leaf.MITER, contract.leaf.LEMMA]
    before = fingerprint(tracked); out = ROOT / f'build/rknpu-dsp-prefix-array-preparation/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='hierarchy', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, native_hierarchy_prepared=False, numerical_acceptance=False,
        four_state_acceptance=False, mapped_numerical_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Exact declared prefix-array derivation and real native C32/K16/TAG35 hierarchy/wiring preparation only. No array numerical/hold/reset/X, XC7 area, mapped circuit, raw-board, physical packing/timing/electrical/DRC, bitstream or FPGA/RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, mapping=False):
        step = dict(argv=list(map(str, argv)), log=str((out / (label+'.log')).relative_to(ROOT)), status='RUNNING')
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
            if mapping: report['native_diagnostics'] = native_diagnostics(text)
            else: assert not re.search(r'(?im)warning:|ERROR:|FATAL:|sorry:', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128+s)))
    generated = []; save(); print(out / 'report.json', flush=True)
    try:
        report['tool_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes()); generated.append(target)
        graph, script = out / 'native_hierarchy.json', out / 'native_hierarchy.ys'
        script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST '+
            ' '.join(json.dumps(str(p)) for p in sources)+'\nhierarchy -check -top '+TOP+
            ' -chparam ATOMIC_C 32 -chparam ATOMIC_K 16 -chparam TAG_WIDTH 35\nproc\nopt_clean\ncheck -assert\nwrite_json '+json.dumps(str(graph))+'\n')
        generated += [graph, script]; binding = fingerprint([*sources, script]); report['elaboration_inputs'] = binding; save()
        run(['yosys', '-Q', '-T', '-s', script], 'native_hierarchy', True)
        assert fingerprint([*sources, script]) == binding
        report['geometry'] = validate_geometry(json.loads(graph.read_text()))
        contract.validate_sources(); assert fingerprint(tracked) == before
        report.update(status='PREPARED_FULL_C32K16_DSP_PREFIX_NATIVE_HIERARCHY_ONLY', stage='complete',
            finished_utc=timestamp(), native_hierarchy_prepared=True, artifacts=fingerprint([*generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(report['status'], flush=True)


if __name__ == '__main__': main()
