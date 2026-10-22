#!/usr/bin/env python3
"""Build only the upstream DSP constant correction on the precision engine.

The parent's executable must relink byte-identically. Only fasm.cc.o and
pack_dsp_xc7.cc.o change, with source changes confined to the DSP writer and
dedicated-tie predicate. This is a build, not native qualification, physical
signoff or permission to reuse the old full placement. Donors/live jobs and
their qualification records are never edited. No SHA256SUMS file is written.
"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, digest, timestamp
from qualify_static_exp_candidate import verify_precision_qualification
from evidence import source_revision

QUALIFICATION = Path('/home/fedora/soDLA/build/ypcb/static-exp-qualification-1791402583316994514/qualification.json')
BUILD = Path('/home/fedora/soDLA/build/ypcb/static-exp-engine-1791401936054675202/report.json')
GAP = ROOT / 'build/openxc7/upstream-dsp-constant-gap-audit-1791413435055802734/report.json'
UPSTREAM = 'a662c08d25d7d2524ab341a387f120521c8a5d08'
NATIVE_SRC = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/himbaechel/uarch/xilinx')
CMAKE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-cli-build/himbaechel/CMakeFiles/nextpnr-himbaechel.dir')
UPSTREAM_DIGESTS = {
    'fasm.cc': '79b3164f3c8c833d6963e8e396ae9e46c7b8fc5667cc443b74c2bab6e811b002',
    'pack_dsp_xc7.cc': '314fdcefef3b4ba6966e24490366db7dd59acbfd86a37aa8187b6fa398a26a7a',
}
BUILT = 'BUILT_ISOLATED_DSP_TILE_CONSTANT_CORRECTION_NOT_NATIVE_QUALIFIED_OR_PNR'


def checked_source(filename, old, new):
    """Accept pinned upstream bytes only, and prove the narrow change boundary."""
    assert hashlib.sha256(new.encode()).hexdigest() == UPSTREAM_DIGESTS[filename], 'Unpinned upstream source'
    if filename == 'fasm.cc':
        first, last = '    void write_dsp_cell(CellInfo *ci)\n', '\n    // A placed BUFR'
    else:
        first = '                // prjxray has extra bits for these ports'
        last = '                    add_const_pin(port.second, gnd_pins, n, "$PACKER_GND_NET");'
    assert old.count(first) == new.count(first) == old.count(last) == new.count(last) == 1
    old_start, old_end = old.index(first), old.index(last)
    new_start, new_end = new.index(first), new.index(last)
    assert old_start < old_end and new_start < new_end
    assert old[:old_start] == new[:new_start] and old[old_end:] == new[new_end:], 'Unrelated source change'
    assert old != new and old.count('NPNR_ASSERT') == new.count('NPNR_ASSERT'), 'Lost assertion or absent correction'
    return new


def compile_argv(filename, source, obj, flags, recipe):
    variables = {}
    for key in ('DEFINES', 'INCLUDES', 'FLAGS'):
        matches = re.findall(r'^CXX_' + key + r' = (.*)$', flags, re.M)
        assert len(matches) == 1, 'Ambiguous compile flags'
        variables[key] = shlex.split(matches[0])
    relative = 'CMakeFiles/nextpnr-himbaechel.dir/uarch/xilinx/' + filename + '.o'
    expected = ('/usr/bin/c++ $(CXX_DEFINES) $(CXX_INCLUDES) $(CXX_FLAGS) -MD -MT himbaechel/' +
                relative + ' -MF ' + relative + '.d -o ' + relative + ' -c ' + str(NATIVE_SRC / filename))
    assert recipe.count(expected) == 1, 'Unexpected original CMake invocation'
    return ['/usr/bin/c++', *variables['DEFINES'], *variables['INCLUDES'], *variables['FLAGS'],
            '-iquote', str(NATIVE_SRC), '-MD', '-MT', str(obj), '-MF', str(obj) + '.d',
            '-o', str(obj), '-c', str(source)]


def dependencies(path):
    text = path.read_text().replace('\\\n', ' ')
    _, sep, body = text.partition(':')
    assert sep and body.strip(), 'Missing compilation dependencies'
    return {Path(name).resolve(strict=True) for name in shlex.split(body)}


def link_argv(old, output, replacements):
    for path in replacements:
        assert old.count(str(path)) == 1, 'Missing/duplicate DSP link object'
    result = [str(replacements.get(Path(item), item)) for item in old]
    assert result.count('-o') == 1
    result[result.index('-o') + 1] = str(output)
    assert sum(item.startswith('-Wl,--dependency-file=') for item in result) == 1
    return ['-Wl,--dependency-file=' + str(output) + '.d' if item.startswith('-Wl,--dependency-file=') else item
            for item in result]


def main():
    out = ROOT / f'build/openxc7/dsp-constant-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, commands=[], inputs={}, base_source_revision='c68c13582e972292c86a5025140d52e713384cbc',
        upstream_DSP_revision=UPSTREAM, part='xc7k480tffg1156-2', full_parallel_products=512,
        parent_precision_qualification=str(QUALIFICATION), parent_build_report=str(BUILD), gap_audit=str(GAP),
        native_requalification_executed=False, native_placement_executed=False, native_routing_executed=False,
        old_full_placement_reuse_admitted=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, cwd=ROOT, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), timeout_seconds=timeout,
                    log=str(out / (label + '.log')), status='RUNNING')
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with Path(step['log']).open('w') as log, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal):', text), text[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text.strip()
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    print(out / 'report.json', flush=True)
    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        report['parent_timing_inventory'] = verify_precision_qualification(QUALIFICATION)
        qualification = json.loads(QUALIFICATION.read_text())
        parent = json.loads(BUILD.read_text())
        assert parent['executable'] == qualification['executable']
        gap = json.loads(GAP.read_text())
        assert gap['status'] == 'CONFIRMED_FULL_PACKED_AND_SAVED_SMALL_NATIVE_DSP_CONSTANT_ENCODING_GAP_NOT_FIXED_NOT_SILICON_TEST'
        assert (gap['affected_full_dsps'], gap['missing_full_declared_tile_ties'],
                gap['absent_or_different_small_native_features']) == (515, 4120, 64)
        before = dict(qualification['inputs'])
        paths = [QUALIFICATION, BUILD, GAP, Path(__file__).resolve(), Path(sys.executable).resolve(strict=True),
                 ROOT / 'tests/cmac/test_dsp_constant_build_control.py', CMAKE / 'flags.make', CMAKE / 'build.make']
        copied_sources, old_objects = {}, {}
        for filename in UPSTREAM_DIGESTS:
            original, obj = NATIVE_SRC / filename, CMAKE / 'uarch/xilinx' / (filename + '.o')
            url = f'https://raw.githubusercontent.com/openXC7/nextpnr/{UPSTREAM}/himbaechel/uarch/xilinx/{filename}'
            entry = gap['upstream_sources'][url]
            upstream = ROOT / entry['path']
            assert digest(upstream) == entry['sha256'] == UPSTREAM_DIGESTS[filename]
            paths.extend([original, upstream, obj, Path(str(obj) + '.d')])
            paths.extend(dependencies(Path(str(obj) + '.d')))
            modified = checked_source(filename, original.read_text(), upstream.read_text())
            copied = out / 'himbaechel/uarch/xilinx' / filename
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_text(modified)
            shutil.copyfile(original, out / ('original-' + filename))
            (out / (filename + '.patch')).write_text(''.join(difflib.unified_diff(
                original.read_text().splitlines(True), modified.splitlines(True),
                fromfile='a/himbaechel/uarch/xilinx/' + filename, tofile='b/himbaechel/uarch/xilinx/' + filename)))
            copied_sources[filename], old_objects[filename] = copied, obj
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                paths.append(Path(filename).resolve())
        for path in paths:
            path = path.resolve(strict=True)
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed inherited input'
            before[str(path)] = sha
        for path, sha in before.items(): assert digest(path) == sha, 'Changed candidate input: ' + path
        report.update(inputs=before, changed_source_files=list(UPSTREAM_DIGESTS), changed_link_objects=2,
                      non_DSP_source_byte_identical=True, assertion_removal=False, stage='build')
        save()
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                                 '-p', 'test_dsp_constant_build_control.py', '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        parent_link = next(step for step in parent['commands'] if step['label'] == 'link_precision_candidate')
        old_link = parent_link['argv']
        assert old_link[old_link.index('-o') + 1] == parent['executable']['path']
        relinked = out / 'parent-relinked'
        run('relink_parent_identity', link_argv(old_link, relinked, {}), cwd=Path(parent_link['cwd']))
        assert digest(relinked) == parent['executable']['sha256'], 'Parent relink differs'
        report['parent_relink_byte_identical'] = True
        replacements = {}
        flags, recipe = (CMAKE / 'flags.make').read_text(), (CMAKE / 'build.make').read_text()
        for filename, copied in copied_sources.items():
            obj = out / (filename + '.o')
            run('compile_' + filename, compile_argv(filename, copied, obj, flags, recipe), cwd=CMAKE.parent.parent)
            for dependency in dependencies(Path(str(obj) + '.d')):
                if dependency == copied:
                    assert digest(dependency) == UPSTREAM_DIGESTS[filename]
                else:
                    assert str(dependency) in before and digest(dependency) == before[str(dependency)], 'Unbound new compile dependency'
            replacements[old_objects[filename]] = obj
        executable = out / 'nextpnr-himbaechel'
        run('link_DSP_constant_candidate', link_argv(old_link, executable, replacements), cwd=Path(parent_link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == parent['native_version']
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed native build input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=BUILT, stage='complete')
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
