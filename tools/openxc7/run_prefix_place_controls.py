#!/usr/bin/env python3
"""Source-bound placement controls, not full-board placement acceptance."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import place_prefix_board
from evidence import ROOT, fingerprint, source_revision, timestamp


def main():
    out = ROOT / f'build/openxc7/prefix-place-controls-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    paths = {Path(__file__), ROOT / 'tests/cmac/test_prefix_native_place_control.py',
             ROOT / 'tests/cmac/test_prefix_pack_input_control.py',
             ROOT / 'tests/cmac/test_static_exp_place_transition_control.py'}
    paths.update(Path(module.__file__).resolve() for module in list(sys.modules.values())
                 if getattr(module, '__file__', None)
                 and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools'))
    production = source_revision()
    before = fingerprint(paths)
    for path in paths:
        frozen = out / 'sources' / path.relative_to(ROOT)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, frozen)
    report = dict(status='RUNNING', started_utc=timestamp(), source=before,
        production_source_before=production, commands=[], full_board_native_placement_executed=False,
        small_native_placement_control_executed=False, physical_fit_verified=False,
        timing_signoff=False, bitstream_emitted=False, hardware_programmed=False)
    small_reports = []
    try:
        for label, argv in [('python_version', [sys.executable, '--version']),
                            ('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                                          '-p', 'test_prefix_native_place_control.py', '-v']),
                            ('precision_transition_controls', [sys.executable, '-m', 'unittest', 'discover',
                                '-s', 'tests/cmac', '-p', 'test_static_exp_place_transition_control.py', '-v']),
                            ('generated_check', ['make', 'generated-check'])]:
            log = out / (label + '.log')
            start = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=300, check=False)
            report['commands'].append(dict(label=label, argv=argv, cwd=str(ROOT),
                log=str(log.relative_to(ROOT)), returncode=result.returncode, seconds=round(time.monotonic() - start, 3)))
        report['source_after'] = fingerprint(paths)
        report['production_source_after'] = source_revision()
        assert report['source_after'] == before and report['production_source_after'] == production
        assert all(step['returncode'] == 0 for step in report['commands'])
        names = re.findall(r'Actual small native placement control: ([^\n]+)', (out / 'controls.log').read_text())
        assert len(names) == 1, 'Missing/ambiguous actual small native placement'
        path = Path(names[0].strip()).resolve(strict=True) / 'report.json'
        assert path.is_relative_to(ROOT / 'build/openxc7')
        assert path.parent.name.startswith('prefix-native-place-small-control-')
        small = json.loads(path.read_text())
        assert small['status'] == 'PASS_SMALL_REAL_NATIVE_PLACEMENT_BINDING_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF'
        assert small['small_native_placement_executed'] is True
        assert small['full_board_native_placement_executed'] is False
        assert all(step['returncode'] == 0 for step in small['commands'])
        assert sum(step['label'] == 'native_place' for step in small['commands']) == 1
        for name, sha in small['artifacts'].items():
            artifact = Path(name).resolve(strict=True)
            assert artifact.is_relative_to(path.parent) and place_prefix_board.digest(artifact) == sha
        small_reports.append(path)
        report.update(status='PASS_PLACEMENT_SOFTWARE_AND_SMALL_REAL_NATIVE_CONTROLS_NOT_FULL_BOARD_ACCEPTANCE',
            small_native_placement_control_executed=True, actual_small_native_report=str(path.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([p for p in out.rglob('*') if p.is_file()] + small_reports)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
