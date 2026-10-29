#!/usr/bin/env python3
"""Prepare all original nine-mode bench observations on the full prefix board.

Reuse the exact admitted native-shell/mapped-kernel import. Retain all 22
original observation/force signals before optimization, and the original
four-bit state before recoding. No arithmetic, raw commands, bench checks,
device geometry, electrical constraints or timing gates are changed. This
frontend-only package is not a new mapped/numerical or physical result.
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import admit_dsp_prefix_board_diagnostics as admission
import prepare_observed_board as observations
from bind_mapped_board_bench import TOP, BENCH, WIDTHS

PARENT = 'build/rknpu-dsp-prefix-board-diagnostic-admission/1791306879354271482/report.json'


def retention_script(original, destination, kernel):
    marker = f'synth_xilinx {admission.ram.FLAGS} -run begin:coarse;\n'
    assert original.count(marker) == 1, 'Unexpected original prefix mapping boundary'
    prefix = original.split(marker)[0]
    assert f'select -assert-count 16 */t:*{admission.mapper.KERNEL}*;' in prefix
    commands = ('proc;\nflatten;\n' + observations.keep_commands() +
                f'opt_expr -keepdc {TOP};\nopt_clean {TOP};\ncheck -assert;\n' +
                f'select {TOP} {kernel};\nselect -assert-mod-count 2 %;\n' +
                'write_json -selected ' + json.dumps(str(destination)) + ';\nselect -clear;\n')
    assert 'fsm_encoding "none"' in commands and commands.count('setattr -set keep 1 ') == len(WIDTHS)
    assert not any(word in commands for word in ('map_memory', 'abc', 'share;', 'write_bitstream'))
    return prefix + commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission-report', type=Path, default=Path(PARENT))
    args = parser.parse_args()
    pp = admission.mapper.replay.workspace_path(args.admission_report)
    parent = json.loads(pp.read_text())
    assert parent['status'] == admission.STATUS and parent['stage'] == 'complete' and parent['finished_utc']
    assert parent['structural_mapping_acceptance'] and parent['mapping_diagnostics_accepted']
    assert (parent['channels'], parent['kernels'], parent['parallel_products'], parent['mapped_kernel_instances'],
            parent['retained_cmac_dsps'], parent['intended_part'], parent['intended_clock_period_ns']) == (
                32, 16, 512, 16, 512, 'xc7k480tffg1156-2', 20)
    assert fingerprint([ROOT / name for name in parent['source']['files']]) == parent['source']
    op = ROOT / parent['parent_reports']['original']
    original = json.loads(op.read_text())
    original_script, partition = [op.parent / name for name in ('mapping.ys', 'cmac_partition.json')]
    kernel = original['preserved_kernel']
    for path in (op, original_script, partition, BENCH):
        name = str(path.relative_to(ROOT))
        assert name in parent['source']['files'] and fingerprint([path])['files'][name] == parent['source']['files'][name]
    out = ROOT / f'build/rknpu-dsp-prefix-observed-board-preparation/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    graph, script = out / 'observable_frontend.json', out / 'prepare.ys'
    script.write_text(retention_script(original_script.read_text(), graph, kernel))
    paths = {pp, op, original_script, partition, BENCH, script, Path(__file__).resolve(),
             Path(observations.__file__).resolve(), *(ROOT / name for name in parent['source']['files'])}
    source = fingerprint(paths)
    report = dict(status='RUNNING', stage='observation_retention_frontend', started_utc=timestamp(),
                  source=source, supervisor_pid=os.getpid(), commands=[], parent_report=str(pp.relative_to(ROOT)),
                  parent_source_sha256=parent['source']['sha256'], original_mapping_report=str(op.relative_to(ROOT)),
                  preserved_kernel=kernel, channels=32, kernels=16, parallel_products=512,
                  intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
                  full_board_mapping_acceptance=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
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
            assert code == 0 and not re.search(r'(?im)ERROR:|FATAL:|sorry:', text), text[-4000:]
            if label == 'frontend':
                report['source_bound_frontend_notices'] = admission.mapper.frontend_diagnostics(text)
            step['status'] = 'PASS_FRONTEND_ONLY'
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
        run(['yosys', '-Q', '-T', '-s', script], 'frontend')
        design = json.loads(graph.read_text())
        original_partition = json.loads(partition.read_text())
        observations.verify_implementation_boundary(design, original_partition, kernel)
        report['bindings'] = observations.verify_observations(design['modules'][TOP], BENCH.read_text())
        assert len(report['bindings']) == 22
        assert fingerprint(paths) == source
        report.update(status='PREPARED_FULL_C32K16_PREFIX_ORIGINAL_OBSERVATION_RETENTION_ONLY', stage='complete',
                      original_four_bit_state_preserved=True, original_bench_unchanged=True,
                      mapped_kernel_instances=16, retained_cmac_dsps=512,
                      imported_kernel_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.iterdir() if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
