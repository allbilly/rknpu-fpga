#!/usr/bin/env python3
"""Build an isolated, opt-in native imported-placement verification probe.

Reproduce the qualified corrected encoder byte-for-byte, then replace only
its actual compiled xilinx.cc object. Preserve donor/live files and all old
assertions and placement/routing/FASM code. This build is not qualification,
full placement-transfer admission or physical signoff. No SHA256SUMS file.
"""
import difflib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_corrected_native_evidence import verify_corrected_evidence
from build_dsp_constant_candidate import dependencies, link_argv, compile_argv, CMAKE, NATIVE_SRC
from pack_prefix_board import ROOT, digest, timestamp
from place_prefix_board import verify_bindings
from evidence import source_revision

TEMPLATE = ROOT / 'tools/openxc7/native/check_imported_placement.inc'
CONTROL = ROOT / 'tests/cmac/test_imported_placement_checker_build.py'
TAG_SOURCE = NATIVE_SRC / 'xilinx.cc'
OLD_OBJECT = CMAKE / 'uarch/xilinx/xilinx.cc.o'
OPTION = ('    specific.add_options()("rknpu-check-imported-placement", po::value<std::string>(),\n'
          '                           "opt-in fixed-lut-v1 imported placement verification before routing");\n')
START = 'void XilinxImpl::preRoute()\n{\n'
END = '    find_source_sink_locs();\n    route_clocks();\n    apply_prerouted();\n}\n'
OLD_LOOP = '            for (int i = 0; i < ctx->getNetinfoSinkWireCount(ni, usr); i++) {\n'
NEW_LOOP = OLD_LOOP.replace('for (int i', 'for (size_t i')


def checked_source(old, block):
    assert old.count(START) == old.count(END) == 1, 'Ambiguous native hook boundary'
    assert old.count('    specific.add_options()("fasm",') == 1
    assert old.count(OLD_LOOP) == 1 and NEW_LOOP not in old, 'Unpinned pre-routed loop correction'
    assert 'rknpu-check-imported-placement' not in old
    assert block.startswith('    // Isolated verification-only addition.') and block.endswith('    }\n')
    for forbidden in ('disconnectPort', 'connectPort', 'renamePort', 'setParam', 'bindBel', 'unbindBel',
                      'ctx->nets[', 'ctx->cells[', 'attrs[', 'params[', 'NPNR_ASSERT'):
        assert forbidden not in block, 'Forbidden circuit/assertion operation in probe'
    for required in ('rknpu_imported_placement', 'VerificationTags', 'cell_tags.swap(saved)',
                     'e.dirty = true', 'h.dirty = true', 'isBelLocationValid(ci->bel, true)',
                     'ctx->check();', 'different nets on a shared physical pin', 'wrong paired output/A6 mode contract'):
        assert required in block, 'Missing probe contract'
    modified = old.replace('    specific.add_options()("fasm",', OPTION + '    specific.add_options()("fasm",', 1)
    modified = modified.replace(START, START + '    const bool rknpu_imported_placement = !cell_tags_set;\n', 1)
    modified = modified.replace(END, block + END, 1)
    # Both Context::getNetinfoSinkWireCount's return and
    # Context::getNetinfoSinkWire's index are size_t. Preserve the loop's
    # body/bounds and fix its pre-existing signedness diagnostic, not flags.
    modified = modified.replace(OLD_LOOP, NEW_LOOP, 1)
    restored = modified.replace(OPTION, '', 1).replace(START + '    const bool rknpu_imported_placement = !cell_tags_set;\n', START, 1).replace(block + END, END, 1).replace(NEW_LOOP, OLD_LOOP, 1)
    assert restored == old, 'Unrelated native change'
    assert modified.count('NPNR_ASSERT') == old.count('NPNR_ASSERT'), 'Changed existing assertions'
    return modified


def compile_recipe(argv, source, obj):
    result = list(argv)
    for flag, old, new in (('-c', TAG_SOURCE, source), ('-o', OLD_OBJECT, obj),
                           ('-MF', Path(str(OLD_OBJECT) + '.d'), Path(str(obj) + '.d'))):
        assert result.count(flag) == 1 and result[result.index(flag) + 1] == str(old), 'Changed actual compile recipe'
        result[result.index(flag) + 1] = str(new)
    assert result[0] == '/usr/bin/c++'
    return result


def verify_original_binding(bindings, observed, dependency_paths):
    """Bind the actual linked object and its source, not a sibling probe."""
    assert TAG_SOURCE in dependency_paths, 'Wrong actual compilation source'
    for path in (TAG_SOURCE, OLD_OBJECT):
        key = str(path)
        assert key in observed and key in bindings
        assert observed[key] == bindings[key], 'Changed bound compile source/object'


def main():
    out = ROOT / f'build/openxc7/imported-placement-checker-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
                  scope=__doc__, commands=[], inputs={}, changed_objects_relative_to_corrected_encoder=1,
                  native_requalification_executed=False, full_placement_transfer_admitted=False,
                  physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
                  drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
                  production_source_before=source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, cwd=ROOT, timeout=1800):
        log = out / (label + '.log')
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), log=str(log), status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with log.open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal):', text), text[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text.strip()
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        base_path = Path(q['candidate_build_report'])
        base = json.loads(base_path.read_text())
        assert base['executable'] == q['executable']
        dependency_paths = dependencies(Path(str(OLD_OBJECT) + '.d'))
        observed = {str(p): digest(p) for p in (TAG_SOURCE, OLD_OBJECT)}
        verify_original_binding(before, observed, dependency_paths)
        links = [c for c in base['commands'] if c['label'] == 'link_DSP_constant_candidate']
        assert len(links) == 1 and links[0]['status'] == 'PASS_TOOL_EXECUTION_ONLY'
        link = links[0]
        assert link['argv'].count(str(OLD_OBJECT)) == 1
        files = {base_path, OLD_OBJECT, Path(str(OLD_OBJECT) + '.d'), TAG_SOURCE, CMAKE / 'flags.make', CMAKE / 'build.make',
                 TEMPLATE, CONTROL, Path(__file__).resolve(), Path(sys.executable).resolve()}
        files.update(dependency_paths)
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for p in files:
            sha = digest(p)
            assert str(p) not in before or before[str(p)] == sha, 'Changed inherited native input'
            before[str(p)] = sha
        report.update(inputs=before, parent_build_report=str(base_path), parent_executable=base['executable'],
                      parent_native_qualification_report=str(ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'),
                      actual_original_source=str(TAG_SOURCE), actual_original_object=str(OLD_OBJECT))
        verify_bindings(before)
        old, block = TAG_SOURCE.read_text(), TEMPLATE.read_text()
        source = out / 'himbaechel/uarch/xilinx/xilinx.cc'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(checked_source(old, block))
        shutil.copyfile(TAG_SOURCE, out / 'original-xilinx.cc')
        shutil.copyfile(TEMPLATE, out / TEMPLATE.name)
        (out / 'xilinx.cc.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True), source.read_text().splitlines(True),
            fromfile='a/himbaechel/uarch/xilinx/xilinx.cc', tofile='b/himbaechel/uarch/xilinx/xilinx.cc')))
        report.update(stage='build', generated_source_sha256=digest(source), original_source_and_old_assertions_preserved=True,
                      preexisting_prerouted_loop_index_corrected_to_API_size_t=True, warning_checks_suppressed=False,
                      software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        relinked = out / 'corrected-parent-relinked'
        run('relink_corrected_parent_identity', link_argv(link['argv'], relinked, {}), cwd=Path(link['cwd']))
        assert digest(relinked) == base['executable']['sha256'], 'Corrected parent relink differs'
        report['corrected_parent_relink_byte_identical'] = True
        obj = out / 'xilinx.cc.o'
        argv = compile_argv('xilinx.cc', source, obj, (CMAKE / 'flags.make').read_text(), (CMAKE / 'build.make').read_text())
        run('compile_imported_placement_probe', argv, cwd=CMAKE.parent.parent)
        for dependency in dependencies(Path(str(obj) + '.d')):
            if dependency == source:
                assert digest(dependency) == report['generated_source_sha256']
            else:
                assert str(dependency) in before and digest(dependency) == before[str(dependency)], 'Unbound new compile dependency'
        executable = out / 'nextpnr-himbaechel'
        run('link_imported_placement_probe', link_argv(link['argv'], executable, {OLD_OBJECT: obj}), cwd=Path(link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == q['native_version']
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='BUILT_OPT_IN_NATIVE_IMPORTED_PLACEMENT_CHECKER_NOT_QUALIFIED_OR_FULL_TRANSFER_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
