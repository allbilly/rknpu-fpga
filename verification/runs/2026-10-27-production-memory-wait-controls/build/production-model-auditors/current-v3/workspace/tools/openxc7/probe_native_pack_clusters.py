#!/usr/bin/env python3
"""Isolated read-only native pack-cluster export, not placement acceptance.

Use the actual qualified parent's linked arch source/object, reproduce its ELF
byte-identically, change one object only, and compare three actual small packed
graphs. Export exact cluster/XYZ/absolute-Z/child fields after packing, with a
checksum before/after check. Preserve live workers, RTL, all original guards,
old logs, tool defaults and the complete C32/K16 target. No FPGA/card access or
standalone SHA256SUMS. This diagnostic is not a new mandatory acceptance gate.
"""
import difflib
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

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import qualify_recursive_mux_feedthrough as qualified
from place_recursive_mux_prefix_shared_board import admit_qualification
from build_dsp_constant_candidate import CMAKE, dependencies, link_argv
from evidence import ROOT, source_revision, timestamp
from pack_prefix_board import digest
from place_prefix_board import verify_bindings

PARENT = ROOT / 'build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json'
QUALIFICATION = ROOT / 'build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json'
ARCH_SOURCE = Path('/home/fedora/soDLA/build/ypcb/lut-pair-engine-1791377260734986151/himbaechel/arch.cc')
ARCH_OBJECT = ARCH_SOURCE.parents[1] / 'arch.cc.o'
CONTROL = ROOT / 'tests/cmac/test_native_pack_cluster_probe_control.py'
OPTION = 'rknpu-cluster-diagnostic-file'
STATUS = 'QUALIFIED_SMALL_NATIVE_CLUSTER_METADATA_EXPORT_SAME_PACK_GRAPH_NOT_FULL_PLACEMENT_OR_SIGNOFF'
FLAGS = ('full_native_placement_executed', 'native_routing_executed', 'physical_fit_verified',
         'full_numerical_acceptance', 'timing_signoff', 'electrical_verified', 'drc_signoff',
         'bitstream_emitted', 'hardware_programmed', 'default_engine_pointer_changed',
         'native_legality_guards_changed', 'warning_checks_suppressed', 'hardware_input_modified')

DUMP_SOURCE = r'''
// Private diagnostic only: no cell/net/constraint writes or placer execution.
static void rknpu_dump_pack_clusters(Context *ctx, const std::string &filename)
{
    using Json = json11::Json;
    const uint32_t before = ctx->checksum();
    if (ctx->cells.size() > 600000)
        log_error("RKNPU cluster diagnostic cell bound exceeded\n");
    const int fd = ::open(filename.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0)
        log_error("RKNPU cluster diagnostic cannot create new output\n");
    FILE *file = ::fdopen(fd, "wb");
    if (!file) {
        ::close(fd);
        log_error("RKNPU cluster diagnostic fdopen failed\n");
    }
    auto emit = [&](const Json &value) {
        const std::string text = value.dump();
        if (std::fprintf(file, "%s\n", text.c_str()) < 0)
            log_error("RKNPU cluster diagnostic write failed\n");
    };
    auto string_of = [&](IdString id) {
        const std::string value = id.str(ctx);
        if (value.size() > 4096)
            log_error("RKNPU cluster diagnostic string bound exceeded\n");
        return value;
    };
    emit(Json::object{{"kind", "header"}, {"schema", 1},
                      {"cells", int(ctx->cells.size())}, {"pack_checksum", stringf("%08x", before)}});
    size_t count = 0;
    for (const auto &item : ctx->cells) {
        const CellInfo *cell = item.second.get();
        if (cell->constr_children.size() > 600000)
            log_error("RKNPU cluster diagnostic child bound exceeded\n");
        Json::array children;
        for (const CellInfo *child : cell->constr_children) {
            NPNR_ASSERT(child != nullptr);
            children.emplace_back(string_of(child->name));
        }
        emit(Json::object{{"kind", "cell"}, {"name", string_of(cell->name)},
                          {"type", string_of(cell->type)}, {"cluster", string_of(cell->cluster)},
                          {"x", cell->constr_x}, {"y", cell->constr_y}, {"z", cell->constr_z},
                          {"abs_z", cell->constr_abs_z}, {"children", children}});
        ++count;
    }
    const uint32_t after = ctx->checksum();
    NPNR_ASSERT(before == after && count == ctx->cells.size());
    emit(Json::object{{"kind", "footer"}, {"cells", int(count)},
                      {"pack_checksum", stringf("%08x", after)}});
    if (std::fclose(file) != 0)
        log_error("RKNPU cluster diagnostic close failed\n");
    log_info("RKNPU read-only pack cluster metadata: %zu cells, unchanged checksum %08x\n", count, after);
}

'''

INCLUDE_OLD = '#include <filesystem>\n'
INCLUDE_NEW = INCLUDE_OLD + '#include <cstdio>\n#include <fcntl.h>\n#include <unistd.h>\n#include "json11.hpp"\n'
OPTION_OLD = '    vopt_desc.add_options()("help,h", "show help");\n'
OPTION_NEW = OPTION_OLD + ('    vopt_desc.add_options()("' + OPTION + '", po::value<std::string>(),\n'
                          '                            "Write read-only post-pack cluster metadata");\n')
PACK_ANCHOR = 'bool Arch::pack()\n'
CALL_OLD = '    log_info("Checksum: 0x%08x\\n", getCtx()->checksum());\n    return true;\n'
CALL_NEW = CALL_OLD.replace('    return true;\n',
    '    if (args.options.count("' + OPTION + '"))\n'
    '        rknpu_dump_pack_clusters(getCtx(), args.options["' + OPTION + '"].as<std::string>());\n'
    '    return true;\n')


def candidate_source(original):
    result = original
    for old, new in ((INCLUDE_OLD, INCLUDE_NEW), (OPTION_OLD, OPTION_NEW),
                     (PACK_ANCHOR, DUMP_SOURCE + PACK_ANCHOR), (CALL_OLD, CALL_NEW)):
        assert result.count(old) == 1 and new not in result, 'Unexpected qualified arch source'
        result = result.replace(old, new)
    verify_source_transition(original, result)
    return result


def verify_source_transition(original, changed):
    result = changed
    for old, new in reversed(((INCLUDE_OLD, INCLUDE_NEW), (OPTION_OLD, OPTION_NEW),
                              (PACK_ANCHOR, DUMP_SOURCE + PACK_ANCHOR), (CALL_OLD, CALL_NEW))):
        assert result.count(new) == 1
        result = result.replace(new, old)
    assert result == original, 'Unrelated native source change'
    assert all(original.count(text) == changed.count(text) for text in ('uarch->pack();', 'assignArchInfo();'))
    assert changed.count('NPNR_ASSERT') == original.count('NPNR_ASSERT') + 2


def compile_argv(source, obj, flags, recipe):
    values = {}
    for key in ('DEFINES', 'INCLUDES', 'FLAGS'):
        matches = re.findall(r'^CXX_' + key + r' = (.*)$', flags, re.M)
        assert len(matches) == 1, 'Ambiguous compiler flags'
        values[key] = shlex.split(matches[0])
    relative = 'CMakeFiles/nextpnr-himbaechel.dir/arch.cc.o'
    upstream = '/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/himbaechel/arch.cc'
    expected = ('/usr/bin/c++ $(CXX_DEFINES) $(CXX_INCLUDES) $(CXX_FLAGS) -MD -MT himbaechel/' + relative +
                ' -MF ' + relative + '.d -o ' + relative + ' -c ' + upstream)
    assert recipe.count(expected) == 1, 'Unexpected arch CMake command'
    return ['/usr/bin/c++', *values['DEFINES'], *values['INCLUDES'], *values['FLAGS'],
            '-iquote', str(ARCH_SOURCE.parent), '-MD', '-MT', str(obj), '-MF', str(obj) + '.d',
            '-o', str(obj), '-c', str(source)]


def read_metadata(path, packed):
    """Exact export schema/census/cluster membership; not BEL/geometry fit."""
    rows = []
    with Path(path).open() as stream:
        for line in stream:
            assert len(line) <= 32 * 1024 * 1024, 'Oversized metadata line'
            rows.append(json.loads(line))
            assert len(rows) <= 600002, 'Oversized metadata census'
    assert len(rows) >= 2
    header, footer = rows[0], rows[-1]
    assert set(header) == {'kind', 'schema', 'cells', 'pack_checksum'}
    assert set(footer) == {'kind', 'cells', 'pack_checksum'}
    assert header['kind'] == 'header' and header['schema'] == 1 and footer['kind'] == 'footer'
    assert isinstance(header['cells'], int) and not isinstance(header['cells'], bool)
    assert header['cells'] == footer['cells'] == len(rows) - 2
    assert isinstance(header['pack_checksum'], str) and re.fullmatch('[0-9a-f]{8}', header['pack_checksum'])
    assert footer['pack_checksum'] == header['pack_checksum']
    cells = {}
    for cell in rows[1:-1]:
        assert set(cell) == {'kind', 'name', 'type', 'cluster', 'x', 'y', 'z', 'abs_z', 'children'}
        assert cell['kind'] == 'cell'
        for key in ('name', 'type', 'cluster'):
            assert isinstance(cell[key], str) and len(cell[key]) <= 4096
        assert cell['name'] and cell['type'] and cell['name'] not in cells
        for key in ('x', 'y', 'z'):
            assert type(cell[key]) is int and -(2**31) <= cell[key] < 2**31
        assert type(cell['abs_z']) is bool and isinstance(cell['children'], list)
        assert len(cell['children']) <= 600000 and all(isinstance(c, str) and c and len(c) <= 4096 for c in cell['children'])
        assert len(set(cell['children'])) == len(cell['children']) and cell['name'] not in cell['children']
        cells[cell['name']] = cell
    assert len(packed['modules']) == 1
    module = next(iter(packed['modules'].values()))
    assert set(cells) == set(module['cells']), 'Metadata omits/changes packed cells'
    assert int(module['settings']['pack'], 2) == 1
    assert int(module['settings'].get('place', '0'), 2) == int(module['settings'].get('route', '0'), 2) == 0
    for name, cell in cells.items():
        assert cell['type'] == module['cells'][name]['type']
        if cell['cluster']:
            root = cells[cell['cluster']]
            assert root['cluster'] == root['name'], 'Missing true cluster root'
            if name != root['name']:
                assert name in root['children'], 'Nonroot not listed by native root'
        else:
            assert not cell['children'], 'Unclustered cell with children'
        for child in cell['children']:
            assert child in cells and cells[child]['cluster'] == cell['cluster'] == name, 'Inconsistent child membership'
    return dict(cells=len(cells), cluster_roots=sum(c['cluster'] == c['name'] for c in cells.values()),
                cluster_children=sum(bool(c['cluster']) and c['cluster'] != c['name'] for c in cells.values()),
                absolute_z_cells=sum(c['abs_z'] for c in cells.values()),
                nonzero_xy_cells=sum(bool(c['x'] or c['y']) for c in cells.values()),
                pack_checksum=header['pack_checksum'], cluster_metadata_exported=True,
                geometry_fit_checked=False, full_placement_or_timing_acceptance=False)


def main():
    q, before = admit_qualification(QUALIFICATION)  # No output/tool on incomplete qualification.
    parent = json.loads(PARENT.read_text())
    qualified.candidate.verify_metadata(parent)
    assert parent['executable'] == q['executable']
    old_link = next(c for c in parent['commands'] if c['label'] == 'link_recursive_mux_feedthrough')
    assert old_link['argv'].count(str(ARCH_OBJECT)) == 1
    assert ARCH_SOURCE in dependencies(Path(str(ARCH_OBJECT) + '.d'))
    for path in (PARENT, ARCH_SOURCE, ARCH_OBJECT, Path(str(ARCH_OBJECT) + '.d'), CMAKE / 'flags.make',
                 CMAKE / 'build.make', Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()):
        path = path.resolve(strict=True)
        sha = digest(path)
        assert str(path) not in before or before[str(path)] == sha, 'Conflicting bound input'
        before[str(path)] = sha
    verify_bindings(before)
    out = ROOT / f'build/openxc7/native-pack-cluster-export-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control.py')
    report = dict(status='RUNNING', stage='admitted', started_utc=timestamp(), supervisor_pid=os.getpid(),
                  parent_build_report=str(PARENT), parent_qualification=str(QUALIFICATION),
                  qualified_parent_executable=parent['executable'], commands=[], source=before,
                  production_source_before=source_revision(), part='xc7k480tffg1156-2',
                  target_c=32, target_k=16, full_parallel_products=512, full_target_dsp=515,
                  full_target_bram=6, diagnostic_optional_not_new_acceptance_gate=True,
                  unchanged_qualified_parent_relink=False, changed_link_objects=1,
                  **{flag: False for flag in FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=1800, expected=0, required=None, cwd=ROOT):
        step = dict(label=label, argv=list(map(str, argv)), timeout_seconds=timeout, expected_returncode=expected,
                    cwd=str(cwd), log=str(out / (label + '.log')), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], stdout=stream,
                stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
            step['pid'] = proc.pid
            save()
            try:
                code = proc.wait(timeout=timeout)
            except BaseException:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                step.update(returncode=proc.returncode, status='FAIL', seconds=round(time.monotonic() - start, 3))
                save()
                raise
        text = Path(step['log']).read_text()
        step.update(returncode=code, seconds=round(time.monotonic() - start, 3), status='FAIL')
        save()
        assert code == expected and (not required or required in text), text[-3500:]
        if expected == 0:
            assert not re.search(r'(?im)\b(?:warning|error|fatal):', text), text[-3500:]
        step['status'] = 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'
        save()
        return text

    print(out / 'report.json', flush=True)
    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                                 '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60).strip()
        parent_copy = out / 'parent-relinked'
        run('relink_qualified_parent_identity', link_argv(old_link['argv'], parent_copy, {}), cwd=Path(old_link['cwd']))
        assert digest(parent_copy) == parent['executable']['sha256'], 'Changed parent ELF'
        report['unchanged_qualified_parent_relink'] = True
        original = ARCH_SOURCE.read_text()
        changed = candidate_source(original)
        source = out / 'himbaechel/arch.cc'
        source.parent.mkdir()
        source.write_text(changed)
        (out / 'arch.cc.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
            fromfile='qualified-parent/himbaechel/arch.cc', tofile='diagnostic/himbaechel/arch.cc')))
        obj = out / 'arch.cc.o'
        argv = compile_argv(source, obj, (CMAKE / 'flags.make').read_text(), (CMAKE / 'build.make').read_text())
        # Pre-bind any newly used system/header dependencies before compilation.
        dep_argv = argv[:argv.index('-MD')] + ['-M', '-MT', str(obj), str(source)]
        run('dependency_preflight', dep_argv, timeout=120)
        for path in dependencies(out / 'dependency_preflight.log'):
            if path == source:
                continue
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed dependency before compile'
            before[str(path)] = sha
        verify_bindings(before)
        run('compile_diagnostic_arch', argv)
        for path in dependencies(Path(str(obj) + '.d')):
            assert (path == source and path.read_text() == changed) or (str(path) in before and digest(path) == before[str(path)])
        executable = out / 'nextpnr-himbaechel'
        run('link_diagnostic_candidate', link_argv(old_link['argv'], executable, {ARCH_OBJECT: obj}), cwd=Path(old_link['cwd']))
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60).strip()
        assert report['native_version'] == parent['native_version']
        fixture, xdc = out / 'mux_probe.json', out / 'mux_probe.xdc'
        shutil.copyfile(PARENT.parent / fixture.name, fixture)
        shutil.copyfile(PARENT.parent / xdc.name, xdc)
        graphs, logs = [], []
        for name, exe, enabled in (('parent', parent_copy, False), ('diagnostic_off', executable, False),
                                   ('diagnostic_on', executable, True)):
            output = out / (name + '-packed.json')
            command = qualified.candidate.pack_argv(exe, fixture, xdc, output)
            if enabled:
                command += ['-o', OPTION + '=' + str(out / 'clusters.jsonl')]
            logs.append(run(name + '_native_pack', command, timeout=120))
            graphs.append(output)
        assert all(p.read_bytes() == graphs[0].read_bytes() for p in graphs), 'Diagnostic changed packed JSON'
        checksums = [re.findall(r'(?m)^Info: Checksum: 0x([0-9a-f]{8})$', text) for text in logs]
        assert all(c == checksums[0] and len(c) == 1 for c in checksums), 'Diagnostic changed native checksum'
        packed = json.loads(graphs[-1].read_text())
        report['metadata_checks'] = read_metadata(out / 'clusters.jsonl', packed)
        assert report['metadata_checks']['pack_checksum'] == checksums[0][0]
        assert 'RKNPU read-only pack cluster metadata:' in logs[-1]
        negative = qualified.candidate.pack_argv(executable, fixture, xdc, out / 'negative-packed.json')
        negative += ['-o', OPTION + '=' + str(out / 'clusters.jsonl')]
        frozen_metadata = digest(out / 'clusters.jsonl')
        run('existing_output_real_negative', negative, timeout=120, expected=1,
            required='RKNPU cluster diagnostic cannot create new output')
        assert digest(out / 'clusters.jsonl') == frozen_metadata
        assert not (out / 'negative-packed.json').exists()
        verify_bindings(before)
        report.update(parent_off_on_packed_graphs_byte_identical=True, parent_off_on_checksums_identical=True,
                      existing_metadata_overwrite_rejected=True, exact_actual_parent_arch_source_retained=True,
                      production_source_after=source_revision())
        assert report['production_source_after'] == report['production_source_before']
        assert all(report[flag] is False for flag in FLAGS)
        report.update(status=STATUS, stage='complete')
    except BaseException as exc:
        report.update(status='FAIL_NATIVE_PACK_CLUSTER_EXPORT_PROBE', error=repr(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()


if __name__ == '__main__':
    main()
