"""One-expression finite, counter-safe HeAP search-limit correction.

No device/circuit/placer validity, objective, RNG, refinement or outer-runtime
guard changes. Clamp the cell count before squaring, then saturate the result
one below INT_MAX so the existing signed attempt counter can reach limit+1
and reject without overflow. Nonpositive divisors keep the original behavior.
"""
from pathlib import Path
import re
import shlex

import audit_shared_heap_attempt_limit as audit
from build_dsp_constant_candidate import CMAKE

SOURCE = audit.SOURCE
OBJECT = CMAKE / '__/common/place/placer_heap.cc.o'
MAXIMUM = 2**31 - 2
EXPRESSION = ('int(std::clamp(std::min<uint64_t>(ctx->cells.size(), std::numeric_limits<int>::max()) * '
              'std::min<uint64_t>(ctx->cells.size(), std::numeric_limits<int>::max()) / uint64_t(timeout_divisor), '
              'uint64_t(10000), uint64_t(std::numeric_limits<int>::max() - 1)))')


def candidate_source(original):
    audit.expression(original)
    assert original.count(audit.EXPRESSION) == 1 and EXPRESSION not in original
    modified = original.replace(audit.EXPRESSION, EXPRESSION)
    assert modified.replace(EXPRESSION, audit.EXPRESSION) == original
    return modified


def verify_source_transition(original, modified):
    assert modified == candidate_source(original), 'Unrelated HeAP source change'


def limit(count, divisor):
    assert type(count) is int and 0 <= count <= 2**64 - 1
    assert type(divisor) is int and -(2**31) <= divisor <= 2**31 - 1
    if divisor <= 0:
        return 0
    return min(MAXIMUM, max(10000, count * count // divisor))


def compile_argv(source, obj, flags, recipe):
    variables = {}
    for key in ('DEFINES', 'INCLUDES', 'FLAGS'):
        matches = re.findall(r'^CXX_' + key + r' = (.*)$', flags, re.M)
        assert len(matches) == 1, 'Ambiguous original HeAP compilation flags'
        variables[key] = shlex.split(matches[0])
    relative = 'CMakeFiles/nextpnr-himbaechel.dir/__/common/place/placer_heap.cc.o'
    expected = ('/usr/bin/c++ $(CXX_DEFINES) $(CXX_INCLUDES) $(CXX_FLAGS) -MD -MT himbaechel/' + relative +
                ' -MF ' + relative + '.d -o ' + relative + ' -c ' + str(SOURCE))
    assert recipe.count(expected) == 1, 'Changed original linked HeAP recipe'
    return ['/usr/bin/c++', *variables['DEFINES'], *variables['INCLUDES'], *variables['FLAGS'],
            '-iquote', str(SOURCE.parent), '-MD', '-MT', str(obj), '-MF', str(obj) + '.d',
            '-o', str(obj), '-c', str(source)]


def fixture():
    return '''#include <algorithm>
#include <cstdint>
#include <cstddef>
#include <iostream>
#include <limits>
#include <string>
struct Cells { std::size_t count; std::size_t size() const { return count; } };
struct Context { Cells cells; };
int main(int argc, char **argv) {
    static_assert(std::numeric_limits<int>::digits == 31);
    static_assert(std::numeric_limits<std::size_t>::digits == 64);
    if (argc != 3) return 2;
    Context context{{std::stoull(argv[1])}};
    auto ctx = &context;
    int timeout_divisor = std::stoi(argv[2]);
    int actual = timeout_divisor > 0 ? ''' + EXPRESSION + ''' : 0;
    int attempts = actual;
    ++attempts;
    const bool rejected = actual > 0 && attempts > actual;
    std::cout << "count=" << ctx->cells.size() << " divisor=" << timeout_divisor
              << " timeout=" << actual << " next=" << attempts << " rejected=" << rejected << '\\n';
}
'''


def validate_result(text, code, count, divisor):
    expected = limit(count, divisor)
    assert code == 0 and text == (f'count={count} divisor={divisor} timeout={expected} '
                                 f'next={expected+1} rejected={int(expected > 0)}\n'), text
    return 'PASS_FINITE_LIMIT_AND_COUNTER_BOUNDARY_HOST_ONLY'
