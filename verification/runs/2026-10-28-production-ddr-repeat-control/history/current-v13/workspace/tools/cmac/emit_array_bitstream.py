#!/usr/bin/env python3
"""Emit a C32/K16 bitstream only from a source-bound, explicitly reviewed DCP.

The review records human report/electrical inspection; it is not manufactured
from a successful tool exit. This tool cannot program the FPGA or flash.
"""
import argparse
import hashlib
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
from vivado_array import inputs, tcl_path, verify_full_board

TEMPLATE = ROOT / 'fpga/cmac/emit_array.tcl.in'
CHECKS = ('board_part_pins_clock_reset', 'configuration_bank_supply_and_strap',
          'clocking_and_reset_routes', 'block_ram_inference', 'utilization_and_routing_complete',
          'setup_and_hold_timing', 'unconstrained_paths_and_exceptions', 'pulse_width',
          'drc_and_all_implementation_warnings')
REPORTS = ('utilization_synth.rpt', 'utilization.rpt', 'timing.rpt',
           'check_timing.rpt', 'pulse_width.rpt', 'drc.rpt')
DSP_PROFILE = 'dsp-compensated-c32k16'
PROFILES = ('baseline-c32k16', 'fixed-fp16-c32k16', DSP_PROFILE)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(manifest):
    assert manifest['files'], 'Empty evidence manifest'
    for name, sha in manifest['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and path.is_file() and digest(path) == sha, f'Stale evidence: {name}'


def implementation_inputs(parent, report_path):
    profile = parent.get('source_profile', 'baseline-c32k16')
    assert profile in PROFILES, 'Unknown implementation source profile'
    if profile == 'baseline-c32k16':
        assert parent['status'] == 'ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED', 'Completed routed implementation required'
        spec, build_inputs = inputs()
        # Reuse the strict original full-board validator, outside its evidence
        # directory. Fixed-board statuses must never satisfy this branch.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='rk-bitstream-board-gate-') as directory:
            embedded = Path(directory) / 'board.json'
            embedded.write_text(json.dumps(parent['board_report']))
            verify_full_board(embedded, spec)
    elif profile == 'fixed-fp16-c32k16':
        from vivado_fixed_array import ROUTED, inputs as fixed_inputs, validate_evidence
        assert parent['status'] == ROUTED, 'Completed routed fixed implementation required'
        spec, build_inputs = fixed_inputs(report_path.parent)
        native, board = validate_evidence(report_path.parent)
        assert native == parent['fixed_native_report'] and board == parent['board_report'], 'Fixed implementation evidence differs'
    else:
        import vivado_dsp_array as dsp
        assert profile == dsp.PROFILE and parent['status'] == dsp.ROUTED, 'Completed routed DSP implementation required'
        spec, build_inputs = dsp.inputs(report_path.parent)
        assert dsp.validate_evidence(report_path.parent) == parent['variant_evidence'], 'DSP implementation evidence differs'
    return spec, build_inputs


def implementation_board(parent):
    if parent.get('source_profile') == DSP_PROFILE:
        return parent['variant_evidence']['board']
    return parent['board_report']


def validate_review(review, report_path, parent):
    assert type(review['schema']) is int and review['schema'] == 1
    assert review['implementation_report_sha256'] == digest(report_path), 'Wrong implementation review'
    assert review['board'] == 'YPCB_00338_1P1' and review['part'] == 'xc7k480tffg1156-2'
    assert isinstance(review['reviewer'], str) and review['reviewer'].strip(), 'Named reviewer required'
    assert isinstance(review['physical_board_evidence'], str) and review['physical_board_evidence'].strip(), 'Physical board evidence required'
    assert set(review['checks']) == set(CHECKS) and all(review['checks'][key] is True for key in CHECKS), 'Incomplete explicit signoff review'
    assert (review['configuration_voltage'], review['cfgbvs']) in (
        ('1.5', 'GND'), ('1.8', 'GND'), ('2.5', 'VCCO'), ('3.3', 'VCCO')), 'Invalid electrical pair'
    assert type(review['led_active_low']) is int and review['led_active_low'] in (0, 1)
    settings = parent['implementation_settings']
    assert settings['RK_CONFIRM_BOARD'] == review['board']
    assert settings['RK_CONFIG_VOLTAGE'] == review['configuration_voltage']
    assert settings['RK_CFGBVS'] == review['cfgbvs']
    assert str(review['led_active_low']) == (settings['RK_LED_ACTIVE_LOW'] or '0'), 'LED setting mismatch'
    directory = report_path.parent
    required = [directory / name for name in REPORTS] + [directory / 'routed.dcp', directory / 'build.tcl']
    expected = {str(path.relative_to(ROOT)): digest(path) for path in required}
    assert review['reviewed_artifacts'] == expected, 'Review must bind every required report and checkpoint'
    assert all(parent['artifacts']['files'].get(name) == sha for name, sha in expected.items()), 'Unbound reviewed artifact'


def render(checkpoint, out, review, review_sha, source_profile='baseline-c32k16'):
    assert source_profile in PROFILES, 'Unknown emission source profile'
    assert re.fullmatch('[0-9a-f]{64}', review_sha)
    assert (review['configuration_voltage'], review['cfgbvs']) in (
        ('1.5', 'GND'), ('1.8', 'GND'), ('2.5', 'VCCO'), ('3.3', 'VCCO'))
    text = TEMPLATE.read_text()
    values = {'@CHECKPOINT@': tcl_path(checkpoint), '@BITSTREAM@': tcl_path(out / 'rk_cmac_c32k16.bit'),
              '@REVIEW_SHA@': review_sha, '@CFGBVS@': review['cfgbvs'], '@VOLTAGE@': review['configuration_voltage'],
              '@DRC_REPORT@': tcl_path(out / 'emission_drc.rpt')}
    for token, value in values.items():
        assert text.count(token) == 1, token
        text = text.replace(token, value)
    if source_profile == DSP_PROFILE:
        from vivado_dsp_array import GUARD
        marker = 'write_bitstream $bitstream'
        assert text.count(marker) == 1
        text = text.replace(marker, GUARD + '\n' + marker)
    assert not re.search(r'@[A-Z_]+@', text)
    assert not re.search(r'^\s*(open_hw|program_hw|set_false_path|set_clock_groups|set_property)\b', text, re.M)
    assert len(re.findall(r'^write_bitstream ', text, re.M)) == 1
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review-template', 'run'))
    parser.add_argument('--implementation-report', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--vivado', default='vivado')
    args = parser.parse_args()
    report_path = args.implementation_report.resolve()
    assert report_path.is_relative_to(ROOT)
    parent = json.loads(report_path.read_text())
    # Reject prepared/failed/running reports before any emission directory or
    # tool is created. Each profile has its own numerical and board gates.
    spec, build_inputs = implementation_inputs(parent, report_path)
    assert parent['action'] == 'run' and parent['bitstream_emitted'] is False and parent['hardware_programmed'] is False
    assert fingerprint(build_inputs) == parent['source'], 'Implementation source differs from current build inputs'
    assert parent['commands'] and all(c['status'] == 'PASS' and c['returncode'] == 0 for c in parent['commands'])
    verify(parent['source'])
    verify(parent['artifacts'])
    out = ROOT / f'build/rknpu-array-bitstream/{args.action}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    if args.action == 'review-template':
        settings = parent['implementation_settings']
        review = dict(schema=1, implementation_report_sha256=digest(report_path), board='YPCB_00338_1P1',
                      part=spec['part'], reviewer='', physical_board_evidence='',
                      configuration_voltage=settings['RK_CONFIG_VOLTAGE'], cfgbvs=settings['RK_CFGBVS'],
                      led_active_low=int(settings['RK_LED_ACTIVE_LOW'] or '0'),
                      checks={key: False for key in CHECKS}, reviewed_artifacts={
                          str((report_path.parent / name).relative_to(ROOT)): digest(report_path.parent / name)
                          for name in REPORTS + ('routed.dcp', 'build.tcl')})
        path = out / 'review.json'
        path.write_text(json.dumps(review, indent=2) + '\n')
        print(path)
        print('UNREVIEWED_TEMPLATE_ONLY; every acceptance is false. No bitstream or programming.')
        return
    assert args.review is not None
    review_path = args.review.resolve()
    assert review_path.is_relative_to(ROOT), 'Keep the source-bound review inside this project'
    review = json.loads(review_path.read_text())
    validate_review(review, report_path, parent)
    assert os.environ.get('RK_CONFIRM_BOARD') == review['board'] and os.environ.get('RK_EMIT_BITSTREAM') == '1'
    tracked = build_inputs + [TEMPLATE, Path(__file__).resolve(), report_path, review_path,
                              ROOT / 'tools/evidence.py', report_path.parent / 'routed.dcp']
    if parent.get('source_profile') == 'fixed-fp16-c32k16':
        tracked += [ROOT / 'tools/cmac/vivado_fixed_array.py', ROOT / 'tools/cmac/test_fixed_array_board.py']
    elif parent.get('source_profile') == DSP_PROFILE:
        tracked += [ROOT / 'tools/cmac/vivado_dsp_array.py', ROOT / 'tools/cmac/map_dsp_board.py',
                    ROOT / 'tools/cmac/replay_dsp_board.py', ROOT / 'tools/cmac/test_dsp_mapped_array.py']
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
                  source_profile=parent.get('source_profile', 'baseline-c32k16'),
                  review=review, bitstream_emitted=False, hardware_programmed=False,
                  scope='Source-bound reviewed C32/K16 board self-test bitstream only. Human physical/report assertions recorded, not measured here. No FPGA/flash programming or RK validation.')
    # The original implementation retains the large checkpoint. Preserve the
    # smaller emitter/source/review files too, rather than recording hashes
    # alone for code that could later change.
    for path in tracked:
        if path.name == 'routed.dcp':
            continue
        dest = out / 'snapshot' / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            env = dict(os.environ, RK_ARRAY_REVIEW_SHA=digest(review_path))
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, env=env, stdout=stream,
                                      stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=3600)
                    except BaseException:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        raise
            step['returncode'] = code
            assert code == 0, (ROOT / step['log']).read_text()[-6000:]
            step['status'] = 'PASS'
            return (ROOT / step['log']).read_text()
        except Exception:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    save()
    try:
        executable = shutil.which(args.vivado)
        assert executable and Path(executable).name == 'vivado', 'UNAVAILABLE: full Vivado required'
        version = run([executable, '-version'], 'version')
        assert version == parent['tool_version'] and 'Vivado Lab' not in version, 'Implementation tool version changed'
        report['tool_version'] = version
        script = out / 'emit.tcl'
        script.write_text(render(report_path.parent / 'routed.dcp', out, review, digest(review_path),
                                 parent.get('source_profile', 'baseline-c32k16')))
        run([executable, '-mode', 'batch', '-source', script, '-log', out / 'vivado.log', '-journal', out / 'vivado.jou'], 'emit')
        bitstream = out / 'rk_cmac_c32k16.bit'
        assert bitstream.is_file() and bitstream.stat().st_size > 1024, 'No usable bitstream artifact'
        assert fingerprint(tracked) == report['source'], 'Source/checkpoint/review changed during emission'
        board = implementation_board(parent)
        verify(board['source'])
        verify(board['artifacts'])
        verify(parent['artifacts'])
        current_spec, current_inputs = implementation_inputs(parent, report_path)
        assert current_spec == spec and fingerprint(current_inputs) == parent['source'], 'Implementation profile changed during emission'
        validate_review(review, report_path, parent)
        report.update(status='PASS_REVIEWED_ARRAY_BITSTREAM_NOT_PROGRAMMED', bitstream_emitted=True,
                      artifacts=fingerprint([path for path in out.iterdir() if path.is_file() and path.name != 'report.json']))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()
        print(out / 'report.json')
    print(report['status'])


if __name__ == '__main__':
    main()
