"""Narrow strict-legalizer search candidate, not a legality or fit waiver.

The actual init_grid computes dimensions as max(BEL coordinate + 1), and
FastBels stores entries at those coordinates. Clamp only the random-search
upper limits to that physical rectangle. Keep region checks, provisional
bindings, native validity predicates, rip-up limits and normal refinement.
Progress counters do not call the RNG or select candidates.
"""
from pathlib import Path

PRECISION_SOURCE = Path('/home/fedora/soDLA/build/ypcb/static-exp-engine-1791401936054675202/common/place/placer_static.cc')
PRECISION_OBJECT = PRECISION_SOURCE.parents[2] / 'placer_static.cc.o'


def replace_once(text, old, new):
    assert text.count(old) == 1, 'Changed strict-search source anchor'
    return text.replace(old, new)


def candidate_source(original):
    start = original.index('    void legalise_placement_strict(bool require_validity = true)\n')
    end = original.index('\n  public:\n', start)
    body = original[start:end]
    body = replace_once(body, '        int ripup_radius = 2;\n', '''        int ripup_radius = 2;
        unsigned long long search_samples = 0, queue_pops = 0, committed_cells = 0;
        unsigned long long outside_grid = 0, empty_tiles = 0, plain_checks = 0, plain_rejects = 0;
        unsigned long long cluster_checks = 0, cluster_rejects = 0;
        const auto search_started = std::chrono::steady_clock::now();
        auto last_progress = search_started;
        auto progress = [&](const char *phase, CellInfo *current, int radius) {
            const auto now = std::chrono::steady_clock::now();
            const double seconds = std::chrono::duration<double>(now - search_started).count();
            log_info("RKNPU strict search: %s seconds=%.3f queue=%zu pops=%llu committed=%llu "
                     "samples=%llu outside=%llu empty=%llu plain_checks=%llu plain_rejects=%llu "
                     "cluster_checks=%llu cluster_rejects=%llu cell=%s radius=%d ripup_radius=%d validity=%d\\n",
                     phase, seconds, to_legalise.size(), queue_pops, committed_cells, search_samples,
                     outside_grid, empty_tiles, plain_checks, plain_rejects, cluster_checks, cluster_rejects,
                     current ? current->name.c_str(ctx) : "-", radius, ripup_radius, int(require_validity));
            last_progress = now;
        };
        progress("begin", nullptr, 0);
''')
    body = replace_once(body, '            to_legalise.pop();\n', '            to_legalise.pop();\n            ++queue_pops;\n')
    body = replace_once(body, '            while (!placed) {\n', '''            while (!placed) {
                ++search_samples;
                // Clock sampling and counters do not consume randomness or change bindings.
                if ((search_samples & 4095ULL) == 0 &&
                    std::chrono::steady_clock::now() - last_progress >= std::chrono::seconds(30))
                    progress("searching", ci, radius);
''')
    body = replace_once(body, '                int x1 = cx + rx;\n                int y1 = cy + ry;\n',
        '                int x1 = std::min(cx + rx, bel_width - 1);\n                int y1 = std::min(cy + ry, bel_height - 1);\n')
    for guard in ('nx < 0 || nx > bel_width + 1', 'ny < 0 || ny > bel_height + 1'):
        old = f'                if ({guard})\n                    continue;\n'
        new = f'                if ({guard}) {{\n                    ++outside_grid;\n                    continue;\n                }}\n'
        body = replace_once(body, old, new)
    for guard in ('nx >= int(fb->size())', 'ny >= int(fb->at(nx).size())', 'fb->at(nx).at(ny).empty()'):
        old = f'                if ({guard})\n                    continue;\n'
        new = f'                if ({guard}) {{\n                    ++empty_tiles;\n                    continue;\n                }}\n'
        body = replace_once(body, old, new)
    body = replace_once(body, '                            if (require_validity && !ctx->isBelLocationValid(sz)) {\n',
        '''                            if (require_validity)
                                ++plain_checks;
                            if (require_validity && !ctx->isBelLocationValid(sz)) {
                                ++plain_rejects;
''')
    body = replace_once(body, '                            if (!ctx->isBelLocationValid(sm.first))\n                                goto fail;\n',
        '''                            ++cluster_checks;
                            if (!ctx->isBelLocationValid(sm.first)) {
                                ++cluster_rejects;
                                goto fail;
                            }
''')
    old = '            }\n        }\n    }\n'
    new = '            }\n            ++committed_cells;\n        }\n        progress("complete", nullptr, 0);\n    }\n'
    assert body.endswith(old), 'Changed strict-search closing structure'
    body = body[:-len(old)] + new
    result = original[:start] + body + original[end:]
    assert result.count('NPNR_ASSERT') == original.count('NPNR_ASSERT')
    for guard in ('require_validity && !ctx->isBelLocationValid(sz)', '!ctx->isBelLocationValid(sm.first)',
                  'total_iters_noreset > std::max(5000, 8 * int(ctx->cells.size()))',
                  '!ci->testRegion(sz)', '!target.first->testRegion(target.second)',
                  'bound->cluster != ClusterId() || bound->belStrength > STRENGTH_WEAK'):
        assert result.count(guard) == original.count(guard)
    assert result.count('ctx->rng(') == original.count('ctx->rng(')
    return result


def verify_source_transition(original, candidate):
    assert candidate == candidate_source(original), 'Unadmitted strict-search change'


def compile_argv(old, source, obj):
    assert old.count(str(PRECISION_SOURCE)) == old.count(str(PRECISION_OBJECT)) == 1
    assert old.count(str(PRECISION_OBJECT) + '.d') == 1
    return [str(source) if item == str(PRECISION_SOURCE) else str(obj) if item == str(PRECISION_OBJECT)
            else str(obj) + '.d' if item == str(PRECISION_OBJECT) + '.d' else item for item in old]
