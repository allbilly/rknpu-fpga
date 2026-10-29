#!/usr/bin/env python3
"""Capture the full unchanged prefix board before/after final RAM normalization.

Diagnostic evidence only. The original mapper's warning gate is not changed or
admitted. No numerical, physical, timing, DRC or bitstream acceptance follows.
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import map_dsp_prefix_board as mapper

PARENT = 'build/rknpu-dsp-prefix-board-area/1791291727991236024/report.json'
FLAGS = '-family xc7 -top ypcb_cmac_array_top -flatten -noiopad -noclkbuf'


def capture_script(text, flags, old_directory, new_directory):
    """Add one export at the exclusive check boundary; retain every real stage."""
    marker = f'synth_xilinx {flags} -run map_memory:'
    assert text.count(marker + ';\n') == 1, 'Expected one exact final synthesis stage'
    # Whitebox functional models can still have processes before final check.
    # Export only a temporary blackboxed view, then restore the actual design.
    inserted = (marker + 'check;\ndesign -save rk_normalization_capture;\nblackbox =A:whitebox;\nwrite_json ' +
                json.dumps(str(new_directory / 'before.json')) +
                f';\ndesign -load rk_normalization_capture;\nsynth_xilinx {flags} -run check:')
    result = text.replace(marker, inserted)
    outputs = []
    for name in ('mapped_hierarchy.json', 'mapped.v'):
        old, new = json.dumps(str(old_directory / name)), json.dumps(str(new_directory / name))
        assert result.count(old) == 1, 'Unexpected original export'
        result = result.replace(old, new)
        outputs.append((old, new))
    restored = result
    for old, new in outputs:
        restored = restored.replace(new, old)
    restored = restored.replace(inserted, marker)
    assert restored == text, 'Capture changed synthesis/input commands'
    return result


def resize_notices(text, top):
    found = {}
    pattern = r'Warning: Resizing cell port (\S+) from (\d+) bits to (\d+) bits\.'
    for line in text.splitlines():
        if not line.startswith('Warning: Resizing cell port '):
            continue
        match = re.fullmatch(pattern, line)
        assert match and match[1].startswith(top + '.'), line
        cell, pin = match[1][len(top) + 1:].rsplit('.', 1)
        assert (cell, pin) not in found, 'Repeated resize'
        found[cell, pin] = tuple(map(int, match.groups()[1:]))
    return found


def audit_normalization(before, after, top, notices):
    """All changes must be exact RAM port resizes, with safe lost/added bits."""
    pre, post = before['modules'][top], after['modules'][top]
    assert pre['ports'].keys() == post['ports'].keys() and pre['cells'].keys() == post['cells'].keys()
    # JSON numbers are export-local, not stable RTLIL signal identities. Pin
    # identity is anchored by every unchanged named-wire/bit position instead.
    assert pre['netnames'].keys() == post['netnames'].keys()
    wires = {}
    for name, value in pre['netnames'].items():
        final = post['netnames'][name]['bits']
        assert len(value['bits']) == len(final), 'Named wire shape changed'
        for bit, target in zip(value['bits'], final):
            if type(bit) is int:
                assert bit not in wires or wires[bit] == target, 'Wire aliases disagree'
                wires[bit] = target
            else:
                assert bit == target, 'Named constant changed'
    live_targets = [bit for bit in wires.values() if type(bit) is int]
    assert len(live_targets) == len(set(live_targets)), 'Separate wires merged'
    for name, value in pre['ports'].items():
        assert value['direction'] == post['ports'][name]['direction']
        assert [wires[bit] if type(bit) is int else bit for bit in value['bits']] == post['ports'][name]['bits']
    consumers = set()
    for value in pre['ports'].values():
        if value['direction'] in ('output', 'inout'):
            consumers.update(bit for bit in value['bits'] if type(bit) is int)
    for cell in pre['cells'].values():
        for pin, bits in cell['connections'].items():
            if cell['port_directions'][pin] in ('input', 'inout'):
                consumers.update(bit for bit in bits if type(bit) is int)
    changed, audit, dead_outputs = {}, [], set()
    for name, old in pre['cells'].items():
        new = post['cells'][name]
        assert old['type'] == new['type'] and old['parameters'] == new['parameters']
        assert old['port_directions'] == new['port_directions']
        assert old['connections'].keys() == new['connections'].keys()
        for pin, bits in old['connections'].items():
            final = new['connections'][pin]
            translated = [wires[bit] if type(bit) is int else bit for bit in bits]
            if translated == final:
                continue
            assert old['type'] == 'RAMB36E1', ('Changed non-RAM cell', name, pin)
            widths = len(bits), len(final)
            direction = old['port_directions'][pin]
            assert len(bits) != len(final), 'Same-width rewiring'
            logged = (name, pin) in notices
            if logged:
                assert widths == notices[name, pin], 'Notice width does not match graph'
            else:
                # hierarchy does not warn on fully constant input connections.
                # They still require the same padding/discard proof below.
                assert direction == 'input' and all(bit in ('0', 'x') for bit in bits), ('Unreported live connection change', name, pin)
            assert len(final) == len(after['modules']['RAMB36E1']['ports'][pin]['bits'])
            detail = dict(cell=name, pin=pin, direction=direction, old_width=len(bits), final_width=len(final), resize_notice_present=logged)
            if len(final) > len(bits):
                assert pin == 'WEBWE' and direction == 'input' and widths == (4, 8)
                assert final[:len(bits)] == translated and final[len(bits):] == ['0'] * 4
                detail['proof'] = 'ALL_OLD_ENABLE_BITS_RETAINED_AND_ADDED_BITS_ZERO'
            else:
                assert final == translated[:len(final)], 'Retained bits changed'
                discarded = bits[len(final):]
                if direction == 'output':
                    assert pin in ('DOADO', 'DOBDO', 'DOPADOP', 'DOPBDOP')
                    assert all(type(bit) is int and bit not in consumers for bit in discarded), 'Discarded output has consumer'
                    assert not set(discarded) & set(bits[:len(final)]), 'Discarded output aliases retained output'
                    dead_outputs.update(discarded)
                    detail['proof'] = 'EVERY_DISCARDED_OUTPUT_BIT_HAS_NO_CELL_OR_TOP_PORT_CONSUMER'
                else:
                    assert direction == 'input' and pin in ('DIADI', 'DIBDI', 'DIPADIP', 'DIPBDIP')
                    write_width = int(old['parameters']['WRITE_WIDTH_' + ('A' if pin in ('DIADI', 'DIPADIP') else 'B')], 2)
                    assert all(bit == '0' for bit in discarded) or (write_width == 0 and all(bit in ('0', 'x') for bit in discarded)), 'Discarded live or nonzero RAM input'
                    detail.update(proof='DISCARDED_INPUTS_ZERO_OR_UNKNOWN_CONSTANTS_ON_WRITE_DISABLED_PORT', write_width=write_width,
                                  discarded_constants=dict(Counter(discarded)))
            if logged:
                changed[name, pin] = widths
            audit.append(detail)
    assert changed == notices, 'Notices and actual connection changes differ'
    assert all(type(target) is int or (bit in dead_outputs and target == '0') for bit, target in wires.items()), 'Live named wire replaced by constant'
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-report', type=Path, default=Path(PARENT))
    args = parser.parse_args()
    parent_path = mapper.replay.workspace_path(args.parent_report)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'FAIL' and 'Unknown whole-board source diagnostics' in parent['error']
    assert parent['commands'][-1]['returncode'] == 0 and parent['finished_utc']
    for group in ('source', 'compile_inputs', 'artifacts'):
        assert fingerprint([ROOT / name for name in parent[group]['files']]) == parent[group], ('Changed original', group)
    original = parent_path.parent
    spec, _ = mapper.inputs()
    assert spec['top'] == 'ypcb_cmac_array_top' and spec['part'] == 'xc7k480tffg1156-2' and spec['clock_period_ns'] == 20
    area, raw, _ = mapper.verify_area(ROOT / parent['parent_reports']['area'])
    _, paths, _ = mapper.verify_board(ROOT / parent['parent_reports']['board'], spec)
    mapper.validate_shared_prerequisites(area, paths)
    frozen, kernel, kernel_counts = mapper.partition(raw)
    assert kernel == parent['preserved_kernel'] and kernel_counts['DSP48E1'] == 32
    out = ROOT / f'build/rknpu-dsp-prefix-board-normalization/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'capture.ys'
    script.write_text(capture_script((original / 'mapping.ys').read_text(), FLAGS, original, out))
    imported = [Path(module.__file__).resolve() for module in list(sys.modules.values())
                if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = {parent_path, script, *imported, *(ROOT / name for name in parent['source']['files']),
               *(ROOT / name for name in parent['compile_inputs']['files'])}
    source = fingerprint(tracked)
    report = dict(status='RUNNING', stage='full_mapping_capture', started_utc=timestamp(), source=source,
                  original_report=str(parent_path.relative_to(ROOT)), original_source_sha256=parent['source']['sha256'],
                  channels=32, kernels=16, parallel_products=512, part=spec['part'], clock_period_ns=20,
                  commands=[], supervisor_pid=os.getpid(), mapping_diagnostics_accepted=False,
                  numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, label, timeout=14400):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                    step['pid'] = process.pid
                    save()
                    try:
                        code = process.wait(timeout=timeout)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        raise
            step['returncode'] = code
            assert code == 0, ('Tool failed', label, code)
            text = (ROOT / step['log']).read_text()
            assert not re.search(r'(?im)ERROR:|FATAL:|sorry:', text), 'Fatal mapping diagnostic'
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128 + signum)))
    save()
    print(out / 'report.json', flush=True)
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == parent['tool_version']
        help_text = run(['yosys', '-Q', '-T', '-p', 'help synth_xilinx'], 'help')
        assert 'check:\n        hierarchy -check' in help_text, 'Changed synthesis endpoint'
        log = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        pre = json.loads((out / 'before.json').read_text())
        post = json.loads((out / 'mapped_hierarchy.json').read_text())
        original_post = json.loads((original / 'mapped_hierarchy.json').read_text())
        assert mapper.circuit_signature(post) == mapper.circuit_signature(original_post), 'Final board circuit changed'
        counts, shell, _ = mapper.validate_mapped(post, spec['top'], kernel, frozen['modules'][kernel], kernel_counts)
        old_notices = resize_notices((original / 'mapping.log').read_text(), spec['top'])
        assert len(old_notices) == 32 and resize_notices(log, spec['top']) == old_notices
        report['normalization_audit'] = audit_normalization(pre, post, spec['top'], old_notices)
        assert fingerprint(tracked) == source, 'Source changed during full mapping'
        report.update(status='CAPTURED_FULL_C32K16_BOARD_RAM_NORMALIZATION_DIAGNOSTIC_ONLY', stage='complete',
                      final_original_circuit_identity=True, logged_ram_port_resizes=32,
                      actual_ram_port_resizes=len(report['normalization_audit']), cells=dict(counts), shell_cells=dict(shell),
                      retained_cmac_dsps=512, mapped_kernel_instances=16,
                      original_warning_gate_unchanged=True, early_temporary_driver_diagnostics_admitted=False)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.iterdir() if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
