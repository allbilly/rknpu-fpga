#!/usr/bin/env python3
"""Source-bound synthetic feature controls, not native execution or signoff."""
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_prefix_native_config import ROOT, PARENT, SELECTED, FASM_SOURCE, digest, timestamp
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_prefix_native_feature_controls.py'
COMPARATOR = ROOT / 'tools/openxc7/check_prefix_native_features.py'
ARCH = FASM_SOURCE.parent
FUZZER = Path('/home/fedora/tiny-gpu/build/ypcb/prjxray/fuzzers/100-dsp-mskpat/generate.py')
DB = Path('/home/fedora/tiny-gpu/build/ypcb/prjxray-db/kintex7')


def main():
    out = ROOT / f'build/openxc7/prefix-native-feature-controls-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', started_utc=timestamp(), scope=__doc__, commands=[],
        python_version=platform.python_version(), native_PNR_FASM_executed=False,
        full_board_native_FASM_executed=False, USE_MULT_physical_default_verified=False,
        observable_BRAM_startup_reset_independence_proved=False, numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        expected_vectors_used_for_execution=False, entire_upstream_chain_revalidated=False)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        parent = json.loads(PARENT.read_text())
        assert parent['status'] == 'AUDITED_ACTUAL_FULL_PREFIX_DSP_BRAM_CONFIGURATION_WITH_EXPLICIT_GAPS_NOT_FASM_OR_SIGNOFF'
        assert digest(SELECTED) == parent['artifacts'][str(SELECTED.relative_to(ROOT))]
        paths = {Path(__file__).resolve(), CONTROL, COMPARATOR, PARENT, SELECTED, FUZZER,
                 DB / 'segbits_dsp_l.db', DB / 'segbits_dsp_r.db'}
        paths.update(ARCH / n for n in ('fasm.cc', 'pack.cc', 'pins.cc', 'pack_dsp_xc7.cc'))
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        before = {str(p): digest(p) for p in sorted(paths)}
        report.update(source=before, production_source_before=source_revision(), selected_inventory=str(SELECTED.relative_to(ROOT)))
        for p in paths:
            if p.is_relative_to(ROOT) and p.suffix == '.py':
                frozen = out / 'sources' / p.relative_to(ROOT)
                frozen.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, frozen)
        save()
        for label, argv in (
            ('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
            ('generated_check', ['make', 'generated-check'])):
            step = dict(label=label, argv=argv, cwd=str(ROOT), log=str(out / (label + '.log')), status='RUNNING')
            report['commands'].append(step)
            save()
            start = time.monotonic()
            try:
                with Path(step['log']).open('w') as stream:
                    result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=False)
                step['returncode'] = result.returncode
                assert result.returncode == 0, Path(step['log']).read_text()[-3000:]
                step['status'] = 'PASS_SOFTWARE_ONLY'
            except BaseException:
                step['status'] = 'FAIL'
                raise
            finally:
                step['seconds'] = round(time.monotonic() - start, 3)
                save()
        report['independent_local_database_USE_MULT_records'] = {
            p.name: [line for line in p.read_text().splitlines() if 'USE_MULT' in line]
            for p in (DB / 'segbits_dsp_l.db', DB / 'segbits_dsp_r.db')}
        report['source_defined_gap'] = 'Fuzzer requests USE_MULT tags; pinned native writer and exact local DSP databases have no USE_MULT records. No physical-default proof inferred.'
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed feature-control input'
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='PASS_SYNTHETIC_DSP_BRAM_FEATURE_CORRUPTION_CONTROLS_NOT_NATIVE_OR_SIGNOFF')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
