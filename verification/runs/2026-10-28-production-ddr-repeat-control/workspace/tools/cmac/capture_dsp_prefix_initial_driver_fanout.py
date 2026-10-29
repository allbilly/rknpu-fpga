#!/usr/bin/env python3
"""Capture initial full-board temporary-driver fanout; no warning admission.

Reuse the original complete board inputs and all sixteen actual mapped kernels.
Stop after process lowering and opt_clean, before arithmetic/resource mapping.
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
import capture_dsp_prefix_board_normalization as normalization
import prepare_dsp_prefix_board_mapping as frontend

mapper = normalization.mapper


def frontend_capture_script(original, out):
    marker = f'synth_xilinx {normalization.FLAGS} -run begin:coarse;\n'
    assert original.count(marker) == 1, 'Changed original initial synthesis stage'
    prefix = original.split(marker)[0]
    commands = [f'synth_xilinx {normalization.FLAGS} -run begin:prepare', 'proc']
    for name, next_commands in (('after_proc', ['check', 'opt_clean']), ('after_clean', ['check -assert'])):
        commands += ['design -save rk_initial_driver_capture', 'blackbox =A:whitebox',
                     'write_json ' + json.dumps(str(out / (name + '.json'))),
                     'design -load rk_initial_driver_capture', *next_commands]
    assert not any('map_memory' in command or 'share' in command for command in commands)
    return prefix + ';\n'.join(commands) + '\n'


def driver_notices(text):
    return Counter(line for line in text.splitlines()
                   if line.startswith('Warning: Wire ') and line.endswith(' is used but has no driver.'))


def notice_bit(design, line):
    match = re.fullmatch(r'Warning: Wire (.+?)(?: \[(\d+)\])? is used but has no driver\.', line)
    assert match, 'Unknown driver diagnostic'
    qualified, printed_index = match.groups()
    candidates = [name for name in design['modules'] if qualified.startswith(name + '.')]
    assert candidates, ('Unknown warning module', qualified)
    module = max(candidates, key=len)
    name = qualified[len(module) + 1:]
    nets = design['modules'][module]['netnames']
    keys = {name, name[1:] if name.startswith('\\') else '\\' + name} & nets.keys()
    assert len(keys) == 1, ('Unknown or ambiguous warning wire', module, name)
    key = keys.pop()
    wire = nets[key]
    width = len(wire['bits'])
    if printed_index is None:
        assert width == 1, 'Missing vector bit index'
        index = 0
    else:
        offset = int(wire.get('offset', 0))
        index = int(printed_index) - offset
        if wire.get('upto', 0):
            index = width - 1 - index
        assert 0 <= index < width, 'Warning bit outside captured wire'
    bit = wire['bits'][index]
    assert type(bit) is int, 'Driver diagnostic unexpectedly refers to a constant'
    return module, key, index, bit


def fanout_inventory(design, notices):
    """Count every real cell-input/inout and module-output/inout consumer."""
    sinks = {}
    for module, body in design['modules'].items():
        uses = {}
        for name, port in body['ports'].items():
            if port['direction'] in ('output', 'inout'):
                for index, bit in enumerate(port['bits']):
                    if type(bit) is int:
                        uses.setdefault(bit, []).append(('module_port', name, index))
        for name, cell in body.get('cells', {}).items():
            for pin, bits in cell['connections'].items():
                assert pin in cell['port_directions'], ('Unknown cell pin direction', module, name, pin)
                if cell['port_directions'][pin] in ('input', 'inout'):
                    for index, bit in enumerate(bits):
                        if type(bit) is int:
                            uses.setdefault(bit, []).append(('cell_pin', name, pin, index))
        sinks[module] = uses
    result = []
    for line, count in sorted(notices.items()):
        assert count == 1, 'Repeated initial driver notice'
        module, name, index, bit = notice_bit(design, line)
        consumers = sinks[module].get(bit, [])
        result.append(dict(notice=line, module=module, wire=name, wire_bit_position=index,
                           export_bit=bit, direct_consumer_count=len(consumers), consumers=consumers))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-report', type=Path, default=Path(normalization.PARENT))
    args = parser.parse_args()
    parent_path = mapper.replay.workspace_path(args.parent_report)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'FAIL' and parent['finished_utc'] and parent['commands'][-1]['returncode'] == 0
    assert 'Unknown whole-board source diagnostics' in parent['error']
    for field in ('source', 'compile_inputs'):
        assert fingerprint([ROOT / name for name in parent[field]['files']]) == parent[field]
    original = parent_path.parent
    out = ROOT / f'build/rknpu-dsp-prefix-initial-driver-fanout/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'frontend_capture.ys'
    script.write_text(frontend_capture_script((original / 'mapping.ys').read_text(), out))
    source_paths = {parent_path, script, Path(__file__).resolve(), Path(normalization.__file__).resolve(),
                    Path(frontend.__file__).resolve(), *(ROOT / name for name in parent['source']['files'])}
    source = fingerprint(source_paths)
    report = dict(status='RUNNING', stage='initial_frontend_capture', started_utc=timestamp(), source=source,
                  original_report=str(parent_path.relative_to(ROOT)), commands=[], supervisor_pid=os.getpid(),
                  channels=32, kernels=16, parallel_products=512, mapping_diagnostics_accepted=False,
                  numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
                  hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, label):
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
                        code = process.wait(timeout=1800)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)ERROR:|FATAL:|sorry:', text)
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
        text = run(['yosys', '-Q', '-T', '-s', script], 'frontend')
        expected = driver_notices((original / 'mapping.log').read_text())
        assert sum(expected.values()) == 288 and driver_notices(text) == expected, 'Different initial driver notices'
        before = json.loads((out / 'after_proc.json').read_text())
        after = json.loads((out / 'after_clean.json').read_text())
        partition = json.loads((original / 'cmac_partition.json').read_text())
        spec, _ = mapper.inputs()
        report['compiled_hierarchy'] = frontend.validate_frontend(after, spec['top'], parent['preserved_kernel'], partition)
        report['initial_driver_fanout'] = fanout_inventory(before, expected)
        report['all_initial_notice_bits_have_no_direct_consumers'] = all(
            item['direct_consumer_count'] == 0 for item in report['initial_driver_fanout'])
        report['initial_driver_notices'] = 288
        report['checks_problem_counts'] = [int(value) for value in re.findall(r'Found and reported (\d+) problems\.', text)]
        assert report['checks_problem_counts'] == [288, 0]
        assert fingerprint(source_paths) == source
        report.update(status='CAPTURED_FULL_BOARD_INITIAL_DRIVER_FANOUT_DIAGNOSTIC_ONLY', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([item for item in out.iterdir() if item.is_file() and item.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
