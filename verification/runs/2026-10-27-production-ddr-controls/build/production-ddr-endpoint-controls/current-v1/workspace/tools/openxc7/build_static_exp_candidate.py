#!/usr/bin/env python3
"""Build an isolated double-exp static placer; not native qualification or P&R.

Revalidate the old qualified binary/objects, reproduce its byte-identical
relink, change only the two exponential overloads in a copied source, then
replace only its static-placer object. All old sources/artifacts stay intact;
no global engine pointer, qualification, bitstream or board is updated.
"""
import difflib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, QUALIFICATION, DATABASE, CONSTIDS, digest, timestamp, audit
from evidence import source_revision

PROBE = ROOT / 'build/openxc7/static-exp-precision-probe-1791401782822101529/report.json'


def main():
    out = Path('/home/fedora/soDLA/build/ypcb') / f'static-exp-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        commands=[], source_revision='c68c13582e972292c86a5025140d52e713384cbc', part='xc7k480tffg1156-2',
        scope=__doc__, native_requalification_executed=False, native_placement_executed=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, cwd=ROOT, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), status='RUNNING',
            log=str(out / (label + '.log')), timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
                step['pid'] = proc.pid
                save()
                try: code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not __import__('re').search(r'(?im)warning:|error:', text), text[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text.strip()
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    before = {}
    try:
        report['timing_inventory'] = audit(QUALIFICATION, DATABASE, CONSTIDS)
        q = json.loads(QUALIFICATION.read_text())
        before.update(q['inputs'])
        probe = json.loads(PROBE.read_text())
        assert probe['status'] == 'PASS_HOST_STATIC_EXP_OVERFLOW_REPRODUCER_AND_WIDENED_NUMERIC_CONTROLS_NOT_NATIVE_PLACEMENT'
        assert probe['actual_old_overload_overflow_reproduced'] is True and probe['widened_numeric_control_passed'] is True
        for name, sha in probe['source'].items():
            assert digest(name) == sha
        for name, sha in probe['artifacts'].items():
            assert not Path(name).is_absolute() and (ROOT / name).resolve().is_relative_to(PROBE.parent)
            assert digest(ROOT / name) == sha
        parent_path = Path(q['build_report']).resolve(strict=True)
        parent = json.loads(parent_path.read_text())
        assert parent['status'] == q['status'] and parent['executable'] == q['executable']
        commands = {Path(c['log']).stem: c for c in parent['commands']}
        original = QUALIFICATION.parent / 'common/place/placer_static.cc'
        original_obj = QUALIFICATION.parent / 'placer_static.cc.o'
        assert str(original) in before and str(original_obj) in before
        builder_snapshot = out / 'build-method-at-launch.py'
        shutil.copyfile(Path(__file__), builder_snapshot)
        for path in (QUALIFICATION, PROBE, parent_path, Path(__file__)):
            before[str(path.resolve())] = digest(path)
        report.update(inputs=before, parent_qualification=str(QUALIFICATION), parent_build_report=str(parent_path),
                      numeric_probe_report=str(PROBE))
        save()
        original_text = original.read_text()
        modified = original_text
        for name in ('emin', 'emax'):
            old = f'std::exp({name})'
            assert modified.count(old) == 1, 'Unexpected static-placer source contract'
            modified = modified.replace(old, f'std::exp(static_cast<double>({name}))')
        assert original_text.count('NPNR_ASSERT') == modified.count('NPNR_ASSERT')
        copied = out / 'common/place/placer_static.cc'
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_text(modified)
        shutil.copyfile(original, out / 'original-placer_static.cc')
        patch = out / 'widen-static-exponentials.patch'
        patch.write_text(''.join(difflib.unified_diff(original_text.splitlines(True), modified.splitlines(True),
            fromfile='a/common/place/placer_static.cc', tofile='b/common/place/placer_static.cc')))
        report.update(stage='build', exact_changed_calls=2, assertion_removal=False,
            objective_or_coefficient_changed=False, FPGA_clock_or_geometry_changed=False)
        save()
        version = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        report['compiler_version'] = version
        # All unmodified objects and link flags come from the actual parent
        # invocation; do not reconstruct a different ABI or silently rebuild.
        old_link = commands['link-candidate']['argv']
        assert old_link.count(str(original_obj)) == 1
        assert old_link[old_link.index('-o') + 1] == q['executable']['path']
        def link_argv(output, obj):
            argv = [str(obj) if item == str(original_obj) else item for item in old_link]
            argv[argv.index('-o') + 1] = str(output)
            return ['-Wl,--dependency-file=' + str(output) + '.d' if item.startswith('-Wl,--dependency-file=') else item for item in argv]
        old_relinked = out / 'parent-relinked'
        run('relink_parent_identity', link_argv(old_relinked, original_obj), cwd=Path(commands['link-candidate'].get('cwd', ROOT)))
        assert digest(old_relinked) == q['executable']['sha256'], 'Parent relink differs: refuse untracked toolchain change'
        report['parent_relink_byte_identical'] = True
        obj = out / 'placer_static.cc.o'
        old_compile = commands['compile-static']['argv']
        assert old_compile.count(str(original)) == old_compile.count(str(original_obj)) == 1
        compile_argv = [str(copied) if item == str(original) else str(obj) if item == str(original_obj)
                        else str(obj) + '.d' if item == str(original_obj) + '.d' else item for item in old_compile]
        run('compile_static_precision', compile_argv, cwd=Path(commands['compile-static'].get('cwd', ROOT)))
        executable = out / 'nextpnr-himbaechel'
        run('link_precision_candidate', link_argv(executable, obj), cwd=Path(commands['link-candidate'].get('cwd', ROOT)))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == Path(commands['version']['log']).read_text().strip()
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed native build input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='BUILT_ISOLATED_STATIC_DOUBLE_EXP_CANDIDATE_NOT_NATIVE_REQUALIFIED_OR_PNR', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path): digest(path) for path in out.rglob('*') if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
