#!/usr/bin/env python3
"""Reproduce the bound HeAP search-limit arithmetic, without rerunning placement.

The real full-size failure and source remain unchanged. Execute the exact
linked-source expression in an isolated host UBSan fixture with the actual
packed cell count and in-range positive controls. This establishes a host
arithmetic defect, not that its correction will fit the failed mux or design.
No legality, hardware, model, raw command, timing/electrical/DRC or bits change.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
from prepare_prefix_shared_pack_input import digest
from place_prefix_shared_board import validate_pack

FAILED = ROOT / 'build/openxc7/full-prefix-shared-native-heap-place-1791476631447626227/report.json'
PACKED = ROOT / 'build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json'
SOURCE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/common/place/placer_heap.cc')
COMMAND = SOURCE.parents[1] / 'kernel/command.cc'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_limit_control.py'
EXPRESSION = 'std::max(10000, (int(ctx->cells.size()) * int(ctx->cells.size()) / timeout_divisor))'


def expression(source):
    line = 'cell_placement_timeout = ' + EXPRESSION + ';'
    assert source.count(line) == 1, 'Changed linked HeAP timeout expression'
    assert source.count('int timeout_divisor = ctx->setting<int>("placerHeap/cellPlacementTimeout", 8);') == 1
    return EXPRESSION


def verify_failure(report, pack, log, pack_log):
    validate_pack(pack)
    assert report['status'] == 'FAIL_PREFIX_SHARED_NATIVE_HEAP_PLACE' and report['finished_utc']
    assert report['stage'] == 'native_place'
    assert (report['channels'], report['kernels'], report['parallel_products'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed']) == (32, 16, 512, 'xc7k480tffg1156-2', 20, 3588)
    step = report['commands'][-1]
    assert step['label'] == 'native_place' and step['status'] == 'FAIL' and step['returncode'] == 125
    assert '--placer-heap-cell-placement-timeout' not in step['argv']
    assert '--timing-allow-fail' not in step['argv'] and '--Werror' in step['argv']
    assert step['argv'][step['argv'].index('--placer') + 1] == 'heap'
    assert '0 warnings, 1 error' in log
    assert "Unable to find legal placement for cell 'rk_mapped_cell_86668.rk_mapped_cell_22977' of type 'SELMUX2_1' after 10001 attempts" in log
    assert 'Running main analytical placer, max placement attempts per cell = 10000.' in log
    pattern = r'(?m)^Info: Checksum: (0x[0-9a-f]+)$'
    assert re.findall(pattern, log) == re.findall(pattern, pack_log) == ['0x0f489b2b']
    n = pack['native_census']['cells']
    assert n == sum(pack['native_census']['primitive_counts'].values()) == 523410
    return n


def fixture(source):
    return '''#include <algorithm>
#include <cstddef>
#include <iostream>
#include <limits>
#include <string>
struct Cells { std::size_t count; std::size_t size() const { return count; } };
struct Context { Cells cells; };
int main(int argc, char **argv) {
    static_assert(std::numeric_limits<int>::digits == 31);
    if (argc != 2) return 2;
    Context context{{std::stoull(argv[1])}};
    auto ctx = &context;
    int timeout_divisor = 8;
    int actual = ''' + expression(source) + ''';
    std::cout << "count=" << ctx->cells.size() << " timeout=" << actual << '\\n';
}
'''


def validate_arithmetic(text, code, n):
    if n <= 46340:
        assert code == 0 and text == f'count={n} timeout={max(10000, n*n//8)}\n'
        return 'PASS_IN_RANGE_EXACT_SOURCE_EXPRESSION'
    assert code == 1 and 'runtime error: signed integer overflow:' in text
    assert f'{n} * {n} cannot be represented in type' in text
    assert 'timeout=' not in text
    return 'REJECTED_ACTUAL_SIGNED_INTEGER_OVERFLOW'


def main():
    failed, pack = json.loads(FAILED.read_text()), json.loads(PACKED.read_text())
    log, pack_log = (Path(r['commands'][-1]['log']) for r in (failed, pack))
    n = verify_failure(failed, pack, log.read_text(), pack_log.read_text())
    source = SOURCE.read_text()
    expression(source)
    compiler = Path(shutil.which('g++')).resolve(strict=True)
    before = {str(p): digest(p) for p in (FAILED, PACKED, SOURCE, COMMAND, log, pack_log,
                                         compiler, CONTROL, Path(__file__).resolve(), Path(sys.executable).resolve())}
    for path in (SOURCE, COMMAND, Path(failed['commands'][-1]['argv'][0])):
        assert digest(path) == failed['source'][str(path)], 'Changed actual failed native source/tool'
        before[str(path)] = digest(path)
    assert failed['production_source_before'] == source_revision()
    out = ROOT / f'build/openxc7/shared-heap-attempt-limit-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='host_arithmetic_reproduction', started_utc=timestamp(), source=before,
        production_source_before=source_revision(), failed_report=str(FAILED), packed_report=str(PACKED),
        actual_packed_cells=n, default_divisor=8, mathematical_default_attempt_limit=n*n//8,
        actual_native_logged_attempt_limit=10000, exact_source_expression=EXPRESSION, commands=[], scope=__doc__,
        native_placement_reexecuted=False, failed_placement_relabelled=False, correction_proves_fit=False,
        numerical_netlist_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, count=None):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            result = subprocess.run(step['argv'], cwd=ROOT, capture_output=True, text=True, timeout=120)
            text = result.stdout + result.stderr
            Path(step['log']).write_text(text)
            step['returncode'] = result.returncode
            if count is None:
                assert result.returncode == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:', text)
                step['status'] = 'PASS_HOST_TOOL_OR_CONTROL_ONLY'
            else:
                step['status'] = validate_arithmetic(text, result.returncode, count)
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    try:
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        report['compiler_version'] = run('compiler_version', [compiler, '--version']).splitlines()[0]
        cpp, exe = out / 'actual_expression.cc', out / 'actual_expression'
        cpp.write_text(fixture(source))
        run('compile_exact_expression', [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=signed-integer-overflow', '-fno-sanitize-recover=all', cpp, '-o', exe])
        report['actual_fixture_inputs'] = {str(p): digest(p) for p in (cpp, exe)}
        for count in (7, 46340, 46341, n):
            run('count_' + str(count), [exe, str(count)], count)
        assert all(digest(p) == sha for p, sha in report['actual_fixture_inputs'].items())
        assert all(digest(p) == sha for p, sha in before.items())
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='CONFIRMED_SOURCE_BOUND_HEAP_DEFAULT_ATTEMPT_ARITHMETIC_OVERFLOW_NOT_FIT_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL_SHARED_HEAP_ATTEMPT_LIMIT_AUDIT', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()


if __name__ == '__main__':
    main()
