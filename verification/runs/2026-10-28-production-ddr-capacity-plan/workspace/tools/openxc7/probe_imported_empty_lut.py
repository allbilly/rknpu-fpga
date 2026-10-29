#!/usr/bin/env python3
"""Native diagnostic of a declared disconnected paired LUT output.

Construct a test-only 50-cell checkpoint from the qualified 49-cell placement:
retain all original cells/BELs, add an unused plain LUT2 on a free lower slot,
and select its paired upper's source-defined A6/VCC mode. Its INIT and original
XORCY annotations come from the actual full packed empty-output LUT. Two
logical inputs alias the existing upper's input, so no new live wire/output is
introduced. This is not the full input, an execution fixup, a positive checker
qualification, numerical acceptance, a bitstream or FPGA access.
The unchanged checker is expected to reject its unsupported output contract.
No SHA256SUMS file or old source/report is modified.
"""
from copy import deepcopy
import json
import mmap
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_strict_search_board as support
from audit_corrected_full_pack_identity import cell_value
from correct_placed_dsp_constants import constant_drivers
from place_prefix_board import verify_bindings
from route_prefix_board import logical_lut

ROOT = support.ROOT
FULL = support.checker.NATIVE.parent / 'full-packed.json'
BASE = support.checker.NATIVE.parent / 'valid-forced-placed.json'
CONTROL = ROOT / 'tests/cmac/test_imported_empty_lut.py'
NAME = 'test_only_declared_empty_XORCY_LUT2'


def actual_empty_lut():
    marker = b'        "rk_mapped_cell_85079$split$xorcy0": {'
    with FULL.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        start = data.find(marker); assert start >= 0
        close = data.find(b'\n        }', start); assert close > start
        cell = cell_value(data[start:close + len(b'\n        }')])
    assert cell['type'] == 'SLICE_LUTX' and cell['attributes']['X_ORIG_TYPE'] == 'LUT2'
    assert cell['connections']['O6'] == [] and cell['port_directions']['O6'] == 'output'
    assert cell['attributes']['X_ORIG_PORT_O6'] == 'O' and cell['parameters']['INIT'] == format(6, '032b')
    return cell


def fixture(original, leaf):
    design = deepcopy(original); module = next(iter(design['modules'].values())); cells = module['cells']
    assert len(cells) == 49 and NAME not in cells
    by_bel = {c['attributes']['NEXTPNR_BEL']: n for n, c in cells.items()}
    assert len(by_bel) == 49
    upper_name = next(n for n in sorted(cells) if cells[n]['type'] == 'SLICE_LUTX' and
        cells[n]['attributes']['NEXTPNR_BEL'].endswith('6LUT') and
        cells[n]['attributes']['NEXTPNR_BEL'][:-4] + '5LUT' not in by_bel and
        cells[n]['attributes']['X_ORIG_TYPE'] == 'LUT1')
    upper = cells[upper_name]; lower_bel = upper['attributes']['NEXTPNR_BEL'][:-4] + '5LUT'
    assert not upper['connections'].get('A6') and 'X_ORIG_PORT_A6' not in upper['attributes']
    source = upper['connections']['A1']; assert len(source) == 1 and type(source[0]) is int
    lower = deepcopy(leaf)
    lower['connections'] = {'A1': list(source), 'O5': []}
    lower['port_directions'] = {'A1': 'input', 'O5': 'output'}
    lower['attributes'] = {k: v for k, v in leaf['attributes'].items() if not k.startswith('X_ORIG_PORT_A') and k != 'X_ORIG_PORT_O6'}
    lower['attributes'].update(NEXTPNR_BEL=lower_bel, X_ORIG_PORT_A1='I0 I1', X_ORIG_PORT_O5='O')
    vcc = constant_drivers(module)['VCC']
    upper['connections']['A6'] = [vcc]; upper['port_directions']['A6'] = 'input'
    cells[NAME] = lower
    assert len(cells) == len({c['attributes']['NEXTPNR_BEL'] for c in cells.values()}) == 50
    # Original logical circuit is untouched; the extra output is declared but
    # disconnected. This is host fixture validation, not native placement.
    for name, old in next(iter(original['modules'].values()))['cells'].items():
        if name != upper_name: assert cells[name] == old
        else: assert logical_lut(cells[name]) == logical_lut(old)
    proof = logical_lut(lower)
    assert proof['connections']['O'] == [] and proof['connections']['I0'] == proof['connections']['I1'] == source
    return design, dict(upper_cell=upper_name, test_lower_cell=NAME, test_lower_bel=lower_bel,
        original_cells_retained=49, new_connected_output=False, original_logical_cells_changed=False,
        native_placement_executed=False, fixture_used_as_full_execution_input=False)


def check_rejection(code, text):
    assert code == 125 and text.count('RKNPU imported placement scan: begin before clock/general routing.') == 1
    assert 'RKNPU imported placement scan: changed logical output mapping.' in text
    assert not re.search(r'(?im)\bWARNING:|Assertion failure|Segmentation fault|sorry:', text)
    for marker in ('RKNPU imported placement scan: passed', 'Running router2', 'Routing complete.', 'Program finished normally.'):
        assert marker not in text, 'Unsupported input continued beyond native rejection'


def main():
    out = ROOT / f'build/openxc7/imported-empty-lut-diagnostic-{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=support.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], full_target_parallel_products=512,
        full_input_modified=False, full_native_placement_executed=False, full_native_route_executed=False,
        positive_checker_qualification=False, numerical_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, expected, timeout):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
            expected_returncode=expected, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            if expected: check_rejection(code, text)
            else: assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-3000:]
            step['status'] = 'PASS_EXPECTED_UNSUPPORTED_REJECTION_ONLY' if expected else 'PASS_SOFTWARE_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        before = {}; small, _ = support.verify_small_evidence(before)
        paths = {Path(__file__).resolve(), CONTROL, BASE, FULL, Path(sys.executable).resolve()}
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in paths:
            sha = support.digest(path); assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        verify_bindings(before); report.update(source=before, executable=small['executable'], stage='software_controls')
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 0, 120)
        run('generated_check', ['make', 'generated-check'], 0, 120)
        assert run('version', [small['executable']['path'], '--version'], 0, 60).strip() == small['native_version']
        original = json.loads(BASE.read_text()); design, details = fixture(original, actual_empty_lut())
        input_path = out / 'test-only-empty-output-50.json'; input_path.write_text(json.dumps(design, indent=2) + '\n')
        output = out / 'unsupported-output.json'
        q = json.loads(support.checker.NATIVE.read_text()); old = next(c for c in q['commands'] if c['label'] == 'valid-forced')
        xdc = Path(next(v[4:] for v in old['argv'] if v.startswith('xdc=')))
        argv = support.checker.checkpoint.resume_argv(small['executable']['path'], input_path, next(iter(design['modules'])), xdc, output, route=True)
        argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1']
        report.update(stage='native_unsupported_output_diagnostic', test_only_fixture=details, execution_input=str(input_path))
        run('native_empty_output_diagnostic', argv, 125, 600); assert not output.exists()
        verify_bindings(before)
        report.update(status='REPRODUCED_NATIVE_CHECKER_UNSUPPORTED_DISCONNECTED_PAIRED_LUT_OUTPUT_NOT_QUALIFIED_OR_FULL_ROUTE', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = support.timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): support.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
