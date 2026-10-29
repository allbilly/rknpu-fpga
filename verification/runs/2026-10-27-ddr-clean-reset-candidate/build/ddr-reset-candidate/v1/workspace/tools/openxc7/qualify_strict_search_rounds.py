#!/usr/bin/env python3
"""Qualify unchanged bounded-search engine with source-defined two-pass logs.

Keep the original failed qualification and its one-pass parser/control intact.
StaticPlacer::place calls legalise_step(true) once for DSP/BRAM and then
legalise_step(false) once for logic. Require both complete ordered rounds,
all native validity/counters, original illegal/positive outcomes and literal
four-DSP/six-BRAM features. Only this process's procedure configuration changes;
no native source/executable, old artifact or SHA256SUMS file changes.
"""
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_strict_search_candidate as first

ROOT = first.ROOT
FAILED = ROOT / 'build/openxc7/strict-search-qualification-1791428189705464078/report.json'
CONTROL = ROOT / 'tests/cmac/test_strict_search_rounds.py'
QUALIFIED = 'QUALIFIED_SMALL_NATIVE_BOUNDED_STRICT_SEARCH_TWO_PASSES_AND_DSP_BRAM_PNR_NOT_FULL_FIT_OR_SIGNOFF'
OLD_PARSE = first.check_strict_log
OLD_VERIFY = first.verify_corrected_evidence
COUNTERS = ('queue', 'pops', 'committed', 'samples', 'outside', 'empty',
            'plain_checks', 'plain_rejects', 'cluster_checks', 'cluster_rejects')
PATTERN = re.compile(r'^Info: RKNPU strict search: (?P<phase>begin|searching|complete) '
    r'seconds=(?P<seconds>\d+\.\d+) ' + ' '.join(rf'{key}=(?P<{key}>\d+)' for key in COUNTERS) +
    r' cell=(?P<cell>\S+) radius=(?P<radius>\d+) ripup_radius=(?P<ripup_radius>\d+) validity=(?P<validity>[01])$')


def check_strict_log(text):
    rounds = []; active = None; previous = None
    for line in text.splitlines():
        if 'RKNPU strict search:' not in line: continue
        match = PATTERN.fullmatch(line); assert match, 'Malformed native strict-search marker'
        values = match.groupdict(); phase = values.pop('phase'); cell = values.pop('cell')
        values = {key: float(value) if key == 'seconds' else int(value) for key, value in values.items()}
        assert math.isfinite(values['seconds']) and values['validity'] == 1, 'Invalid time or disabled native validity'
        assert values['outside'] == 0, 'Unexpected out-of-grid sample'
        assert values['plain_rejects'] <= values['plain_checks'] and values['cluster_rejects'] <= values['cluster_checks']
        assert values['committed'] <= values['pops'], 'Impossible queue commit count'
        if phase == 'begin':
            assert active is None and len(rounds) < 2, 'Nested or extra strict-search round'
            assert all(values[k] == 0 for k in COUNTERS if k != 'queue'), 'Counters not reset at round begin'
            assert values['seconds'] == values['radius'] == 0 and cell == '-'
            active = dict(begin=line, initial_queue=values['queue']); previous = values
            continue
        assert active is not None, 'Native progress/completion without begin'
        for key in (*COUNTERS[1:], 'seconds'):
            assert values[key] >= previous[key], 'Regressed native strict-search counter/time'
        if phase == 'searching':
            assert cell != '-', 'Missing active search cell'
            active.setdefault('heartbeats', []).append(line)
        else:
            assert values['queue'] == 0 and cell == '-', 'Incomplete native strict-search round'
            assert values['pops'] >= active['initial_queue'], 'Original queue not fully processed'
            active.update(complete=line, final_counters=values)
            rounds.append(active); active = None
        previous = values
    assert active is None and len(rounds) == 2, 'Missing source-defined DSP/BRAM or logic round'
    return dict(source_defined_rounds=2, order='DSP_BRAM_THEN_LOGIC', rounds=rounds,
                native_validity_enabled_in_every_marker=True)


def verify_failed_metadata(report):
    assert report['status'] == 'FAIL' and report['stage'] == 'native_legality_controls' and report['finished_utc']
    assert report['error'] == "AssertionError('Missing actual strict-search begin/completion')"
    assert report['part'] == 'xc7k480tffg1156-2' and report['full_parallel_products'] == 512
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'version', 'invalid-forced']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'][:3])
    last = report['commands'][-1]
    assert last['returncode'] == last['expected_returncode'] == 125 and last['status'] == 'FAIL'
    assert all(report[key] is False for key in first.FLAGS), 'Failed parent cannot grant physical/full acceptance'


def verify_failed_evidence():
    q, before = OLD_VERIFY()
    failed = json.loads(FAILED.read_text()); verify_failed_metadata(failed)
    first.bind_report(FAILED, failed, before); first.verify_bindings(before)
    step = failed['commands'][-1]; text = Path(step['log']).read_text()
    first.check_log(125, text, 125); check_strict_log(text)
    try: OLD_PARSE(text)
    except AssertionError as error:
        assert str(error) == 'Missing actual strict-search begin/completion'
    else: raise AssertionError('Original parser no longer preserves actual failure')
    old = next(c for c in q['commands'] if c['label'] == 'invalid-forced')
    xdc = Path(next(v[4:] for v in old['argv'] if v.startswith('xdc=')))
    output = FAILED.parent / 'invalid-forced-placed.json'
    assert step['argv'] == first.probe_argv(failed['executable']['path'], old['fixture'], xdc, output)
    assert not output.exists()
    return q, before


def configure():
    # Process-local extension of the frozen procedure; its old source and
    # expectations remain available/bound through the actual failed report.
    first.check_strict_log = check_strict_log
    first.verify_corrected_evidence = verify_failed_evidence
    first.CONTROL = CONTROL
    first.QUALIFIED = QUALIFIED
    first.__doc__ = __doc__


def verify_qualification(path):
    configure()
    report, before = first.verify_qualification(path)
    assert str(FAILED) in before and str(Path(__file__).resolve()) in before, 'Missing actual extension/failure binding'
    return report, before


if __name__ == '__main__':
    configure(); first.main()
