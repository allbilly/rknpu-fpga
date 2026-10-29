#!/usr/bin/env python3
"""Emit only an explicitly reviewed full C32/K16 prefix-DSP checkpoint.

This profile has its own completed native, mapped, area and nine-mode board
parents. Preparation reports cannot authorize emission. No FPGA/flash access.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import emit_array_bitstream as common
import vivado_dsp_prefix_array as prefix

PROFILE = prefix.PROFILE
PASS = 'PASS_REVIEWED_DSP_PREFIX_ARRAY_BITSTREAM_NOT_PROGRAMMED'
CHECKS, REPORTS, TEMPLATE = common.CHECKS, common.REPORTS, common.TEMPLATE
digest, verify, validate_review = common.digest, common.verify, common.validate_review


def implementation_inputs(parent, report_path):
    assert parent.get('source_profile') == PROFILE, 'Wrong prefix implementation source profile'
    assert parent.get('status') == prefix.ROUTED, 'Completed routed prefix implementation required'
    assert parent['action'] == 'run' and parent['finished_utc'], 'Incomplete prefix implementation'
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert parent['bitstream_emitted'] is False and parent['hardware_programmed'] is False
    assert [Path(s['log']).stem for s in parent['commands']] == ['rom_check', 'version', 'implementation']
    assert all(s['status'] == 'PASS' and type(s['returncode']) is int and s['returncode'] == 0
               for s in parent['commands']), 'Incomplete implementation commands'
    prefix.validate_full_vivado_version(parent['tool_version'])
    spec, tracked = prefix.inputs(report_path.parent)
    assert prefix.validate_evidence(report_path.parent) == parent['variant_evidence'], 'Prefix implementation evidence differs'
    return spec, tracked


def implementation_board(parent):
    assert parent['source_profile'] == PROFILE
    return parent['variant_evidence']['board']


def render(checkpoint, out, review, review_sha, source_profile=PROFILE):
    assert source_profile == PROFILE, 'Unknown prefix emission source profile'
    # The unchanged physical template is shared, not the older numerical gates.
    text = common.render(checkpoint, out, review, review_sha)
    marker = 'write_bitstream $bitstream'
    assert text.count(marker) == 1
    text = text.replace(marker, prefix.GUARD + '\n' + marker)
    assert len(re.findall(r'^write_bitstream ', text, re.M)) == 1
    assert not re.search(r'^\s*(open_hw|program_hw|set_false_path|set_clock_groups|set_property)\b', text, re.M)
    return text


def emission_inputs(build_inputs, report_path, review_path):
    return sorted(set(build_inputs + [TEMPLATE, Path(__file__).resolve(),
        Path(common.__file__).resolve(), Path(prefix.__file__).resolve(),
        ROOT / 'tools/evidence.py', report_path, review_path,
        *[report_path.parent / name for name in REPORTS + ('routed.dcp', 'build.tcl')]]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review-template', 'run'))
    parser.add_argument('--implementation-report', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--vivado', default='vivado')
    args = parser.parse_args()
    report_path = args.implementation_report.resolve()
    assert report_path.is_relative_to(ROOT) and report_path.is_file()
    parent = json.loads(report_path.read_text())
    # Reject incomplete/cross-profile evidence before creating output or tools.
    spec, build_inputs = implementation_inputs(parent, report_path)
    assert fingerprint(build_inputs) == parent['source'], 'Implementation source differs from current build inputs'
    verify(parent['source']); verify(parent['artifacts'])
    if args.action == 'run':
        assert args.review is not None, 'Explicit reviewed implementation required'
        review_path = args.review.resolve()
        assert review_path.is_relative_to(ROOT) and review_path.is_file()
        review = json.loads(review_path.read_text())
        validate_review(review, report_path, parent)
        assert os.environ.get('RK_CONFIRM_BOARD') == review['board'] and os.environ.get('RK_EMIT_BITSTREAM') == '1'
    out = ROOT / f'build/rknpu-dsp-prefix-bitstream/{args.action}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    if args.action == 'review-template':
        settings = parent['implementation_settings']
        review = dict(schema=1, implementation_report_sha256=digest(report_path),
            board='YPCB_00338_1P1', part=spec['part'], reviewer='', physical_board_evidence='',
            configuration_voltage=settings['RK_CONFIG_VOLTAGE'], cfgbvs=settings['RK_CFGBVS'],
            led_active_low=int(settings['RK_LED_ACTIVE_LOW'] or '0'),
            checks={key: False for key in CHECKS}, reviewed_artifacts={
                str((report_path.parent / name).relative_to(ROOT)): digest(report_path.parent / name)
                for name in REPORTS + ('routed.dcp', 'build.tcl')})
        path = out / 'review.json'
        path.write_text(json.dumps(review, indent=2) + '\n')
        print(path)
        print('UNREVIEWED_PREFIX_TEMPLATE_ONLY; every acceptance is false. No bitstream or programming.')
        return
    tracked = emission_inputs(build_inputs, report_path, review_path)
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
        source_profile=PROFILE, channels=32, kernels=16, parallel_products=512,
        review=review, bitstream_emitted=False, hardware_programmed=False,
        scope='Source-bound reviewed full C32/K16 prefix-DSP raw-board self-test bitstream only. Own completed native, area, mapped binary and nine-mode raw-board evidence required. Human electrical/report assertions recorded, not measured here. No FPGA/flash programming or RK compatibility acceptance.')
    for path in tracked:
        if path.name == 'routed.dcp':
            continue
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            env = dict(os.environ, RK_ARRAY_REVIEW_SHA=digest(review_path))
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, env=env, stdout=stream,
                                      stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try:
                        code = proc.wait(timeout=3600)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code
            assert code == 0, (ROOT / step['log']).read_text()[-6000:]
            step['status'] = 'PASS'
            return (ROOT / step['log']).read_text()
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        executable = shutil.which(args.vivado)
        assert executable and Path(executable).name == 'vivado', 'UNAVAILABLE: full Vivado required'
        version = run([executable, '-version'], 'version')
        assert version == parent['tool_version'] and 'Vivado Lab' not in version, 'Implementation tool version changed'
        report['tool_version'] = version
        script = out / 'emit.tcl'
        script.write_text(render(report_path.parent / 'routed.dcp', out, review, digest(review_path)))
        run([executable, '-mode', 'batch', '-source', script, '-log', out / 'vivado.log',
             '-journal', out / 'vivado.jou'], 'emit')
        bitstream = out / 'rk_cmac_c32k16.bit'
        assert bitstream.is_file() and bitstream.stat().st_size > 1024, 'No usable bitstream artifact'
        assert fingerprint(tracked) == report['source'], 'Source/checkpoint/review changed during emission'
        verify(parent['source']); verify(parent['artifacts'])
        board = implementation_board(parent)
        verify(board['source']); verify(board['artifacts'])
        current_spec, current_inputs = implementation_inputs(parent, report_path)
        assert current_spec == spec and fingerprint(current_inputs) == parent['source'], 'Implementation profile changed during emission'
        validate_review(review, report_path, parent)
        report.update(status=PASS, bitstream_emitted=True,
            artifacts=fingerprint([p for p in out.iterdir() if p.is_file() and p.name != 'report.json']))
    except BaseException as error:
        report.update(status='FAIL', reason=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json', flush=True)
    print(report['status'], flush=True)


if __name__ == '__main__':
    main()
