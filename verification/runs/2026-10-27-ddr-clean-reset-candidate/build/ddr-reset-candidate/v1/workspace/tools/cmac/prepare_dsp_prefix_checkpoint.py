#!/usr/bin/env python3
"""Prepare a full own-parent-validated checkpoint package without invoking Vivado.

No routed checkpoint, bitstream, electrical/timing/DRC acceptance or programming
is inferred. The implementation and reviewed emitter remain separate gates.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import vivado_dsp_prefix_array as checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('area', 'native', 'board', 'mapped')
    for name in names:
        parser.add_argument('--' + name + '-report', type=Path, required=True)
    args = parser.parse_args()
    paths = {name: checkpoint.gates.replay.workspace_path(getattr(args, name + '_report')) for name in names}
    out = ROOT / f'build/rknpu-dsp-prefix-checkpoint-preflight/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    join = out / Path(checkpoint.gates.replay.preparation.JOIN).name
    join.write_text(checkpoint.gates.replay.preparation.dsp_join((ROOT / checkpoint.gates.replay.preparation.JOIN).read_text()))
    (out / 'profile_evidence.json').write_text(json.dumps({name: str(path.relative_to(ROOT))
        for name, path in paths.items()}, indent=2, sort_keys=True) + '\n')
    for name, path in paths.items():
        (out / (name + '_snapshot.json')).write_bytes(path.read_bytes())
    spec, tracked = checkpoint.inputs(out)
    tracked = sorted(set(tracked) | {Path(__file__).resolve()})
    before = fingerprint(tracked)
    report = dict(status='RUNNING', stage='own_parent_admission', started_utc=timestamp(), source=before,
        source_profile=checkpoint.PROFILE, parent_reports={name: str(path.relative_to(ROOT))
            for name, path in paths.items()}, channels=32, kernels=16, parallel_products=512,
        part=spec['part'], clock_period_ns=spec['clock_period_ns'], commands=[],
        own_numerical_parents_validated=False, actual_vivado_executed=False,
        routed_checkpoint_produced=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False,
        remaining_acceptance=['Full Vivado with exact XC7K480T part support and usable licensing',
            'Audited target/configuration-bank voltage and CFGBVS strap',
            'Actual synthesis/placement/routing and retained sixteen 32-DSP kernels',
            'Setup/hold, BRAM, electrical and DRC checks plus explicit report review'],
        scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save()
    try:
        parents = checkpoint.validate_evidence(out)
        report['own_numerical_parents_validated'] = True
        report['validated_parent_source_sha256'] = {name: parent['source']['sha256']
            for name, parent in parents.items()}
        report['stage'] = 'source_package'
        save()
        argv = [sys.executable, str(ROOT / 'tools/cmac/gen_array_board.py'), '--check']
        log = out / 'rom_check.log'
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        report['commands'].append(dict(argv=argv, log=str(log.relative_to(ROOT)),
            returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL'))
        assert result.returncode == 0
        script = out / 'build.tcl'
        script.write_text(checkpoint.render(spec, out, before['sha256']))
        assert 'write_bitstream' not in script.read_text()
        for path in tracked:
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        assert fingerprint(tracked) == before
        assert not list(out.glob('*.dcp')) and not list(out.glob('*.bit'))
        report.update(status='PREPARED_OWN_PARENTS_VALIDATED_FULL_C32K16_PREFIX_CHECKPOINT_ONLY',
            stage='complete', build_script=str(script.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*')
            if path.is_file() and path != out / 'report.json'])
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
