#!/usr/bin/env python3
"""Audit the live native analytic-log scope; NEVER accept a full placement.

The pinned HeAP log reports place_cells.size(), not ctx->cells.size(). Bind
the actual compiled source/object inherited by the live corrected-mux engine
and snapshot its actual log/report. Keep the full packed census separate.
This diagnostic does not reconstruct the exact active set, approve a changed
count expectation, edit the live runner, reuse a result, launch P&R, or access
an FPGA. Complete cell/BEL/DSP/tie/numerical/physical gates remain mandatory.
No standalone SHA256SUMS manifest is produced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
import place_recursive_mux_prefix_shared_board as placement

CONTROL = ROOT / 'tests/cmac/test_recursive_mux_analytic_scope_control.py'
STATUS = 'CONFIRMED_NATIVE_ANALYTIC_LOG_SUBSET_SCOPE_NOT_FULL_PLACEMENT_ACCEPTANCE'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def source_contract(text):
    """Source facts about the marker and final all-cell checks, not a census."""
    marker = 'log_info("Creating initial analytic placement for %d cells, random placement wirelen = %d.\\n",'
    assert text.count(marker) == 1
    assert marker + '\n                 int(place_cells.size()), int(hpwl));' in text
    start = text.index('    void seed_placement()\n')
    end = text.index('    // Setup the cells to be solved', start)
    seed = text[start:end]
    required = (
        'if (ci->isPseudo()) {',
        'if (ci->bel != BelId()) {',
        'else if (ci->cluster == ClusterId() || ctx->getClusterRootCell(ci->cluster) == ci) {',
        'if (has_connectivity(cell.second.get()) && !cfg.ioBufTypes.count(ci->type)) {\n'
        '                        bels_used.insert(bel);\n'
        '                        place_cells.push_back(ci);',
    )
    assert all(seed.count(fragment) == 1 for fragment in required), 'Changed active-root selection'
    assert text.count('place_cells.push_back(ci);') == 1, 'Changed analytic population construction'
    assert ('port.second.net != nullptr && port.second.net->driver.cell != nullptr &&\n'
            '                !port.second.net->users.empty()') in text, 'Changed meaningful-connectivity rule'
    final = text[text.index('        unsigned num_errors = 0;'):text.index('        bool any_bad_placements = false;')]
    for fragment in ('for (auto &cell : ctx->cells)', 'cell.second->isPseudo()',
                     'cell.second->bel == BelId()', 'Found unbound cell', 'Found mismatched binding',
                     'if (num_errors > 0)', 'Stopping the program after %u errors found'):
        assert fragment in final, 'Missing native all-cell final binding guard'
    return dict(marker_expression='place_cells.size()', full_population_expression='ctx->cells.size()',
                pseudo_bound_cluster_child_and_nonmeaningful_root_exclusions_present=True,
                native_final_all_nonpseudo_cell_binding_guard_present=True,
                exact_active_population_independently_reconstructed=False)


def log_observation(text, full_cells, expected_checksum):
    assert type(full_cells) is int and full_cells > 0
    assert re.fullmatch(r'0x[0-9a-f]{8}', expected_checksum)
    assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text), 'Native diagnostic present'
    marker = 'Creating initial analytic placement for '
    assert text.count(marker) == 1, 'Missing or duplicate analytic marker'
    counts = re.findall(r'(?m)^Info: Creating initial analytic placement for (\d+) cells, random placement wirelen = (-?\d+)\.$', text)
    assert len(counts) == 1, 'Unsupported analytic marker'
    active = int(counts[0][0])
    assert 0 < active <= full_cells, 'Impossible analytic subset count'
    checksums = re.findall(r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$', text.split(marker, 1)[0])
    assert checksums == [expected_checksum], 'Changed or ambiguous fresh packed checksum'
    return dict(actual_native_packed_checksum=checksums[0],
                actual_logged_analytic_active_roots=active,
                independently_characterized_full_packed_cells=full_cells,
                arithmetic_count_difference_not_an_omission_census=full_cells - active,
                analytic_marker_is_full_packed_cell_census=False,
                exact_active_population_independently_reconstructed=False,
                full_unique_BEL_and_cell_membership_still_required=True)


def live_metadata(report):
    assert report['status'] == 'RUNNING' and report['stage'] == 'native_place'
    assert (report['channels'], report['kernels'], report['parallel_products'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed']) == (32, 16, 512, 'xc7k480tffg1156-2', 20, 3588)
    command = report['commands'][-1]
    assert command['label'] == 'native_place' and command['status'] == 'RUNNING'
    assert type(command['pid']) is int and command['pid'] > 0
    assert command.get('returncode') is None and command['timeout_seconds'] == 43200
    placement.NAMESPACE['verify_full_argv'](command['argv'])
    assert command['argv'][0] == report['executable']['path']
    assert report['native_packing_executed'] is True and report['native_placement_executed'] is True
    assert report['original_prepared_input_repacked'] is True
    for flag in ('native_routing_executed', 'old_placement_reused', 'input_group_assignment_used',
                 'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False, 'Unmodeled native profile: ' + flag
    return command


def verify_native_link_command(commands, object_path, executable_path):
    """Prove the final feedthrough link consumes the audited HeAP object."""
    links = [step for step in commands if step.get('label') == 'link_recursive_mux_feedthrough']
    assert len(links) == 1, 'Missing or ambiguous final native-engine link evidence'
    link = links[0]
    assert link['returncode'] == 0
    assert link['status'] in ('PASS_TOOL_EXECUTION_ONLY', 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY')
    argv = link['argv']
    assert argv.count(str(Path(object_path).resolve())) == 1, 'Linked engine omits or duplicates the audited HeAP object'
    assert argv.count('-o') == 1, 'Unsupported native-engine link output syntax'
    output = Path(argv[argv.index('-o') + 1]).resolve()
    assert output == Path(executable_path).resolve(), 'Native-engine link produced a different executable'
    return link


def verify_worker(command):
    pid = command['pid']
    assert Path(os.readlink(f'/proc/{pid}/exe')).resolve() == Path(command['argv'][0]).resolve()
    assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:-1] == [a.encode() for a in command['argv']]
    # A start-time identity, not the changing CPU/counter fields.
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    args = parser.parse_args()
    path = args.native_report.resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-place-')
    observed_at = timestamp()
    native_bytes = path.read_bytes()
    native = json.loads(native_bytes)
    command = live_metadata(native)  # Fail closed before output or any tool execution.
    worker_start = verify_worker(command)
    production = source_revision()
    assert production == native['production_source_before']
    before = {}

    def bound(name):
        name = Path(name).resolve(strict=True)
        sha = digest(name)
        assert native['source'][str(name)] == sha, 'Changed admitted source/artifact: ' + str(name)
        before[str(name)] = sha
        return name

    packed_path = bound(native['packed_report'])
    assert packed_path.is_relative_to(ROOT / 'build/openxc7')
    packed = json.loads(packed_path.read_bytes())
    placement.packer.validate_pack(packed)
    assert native['executable'] == packed['executable']
    assert native['execution_input'] == packed['execution_input']
    assert native['qualification'] == packed['encoder_qualification']
    bound(native['executable']['path'])
    qualified = json.loads(bound(native['qualification']).read_bytes())
    placement.qualification.verify_metadata(qualified)
    built_path = bound(qualified['build_report'])
    built = json.loads(built_path.read_bytes())
    placement.qualification.candidate.verify_metadata(built)
    assert built['executable'] == native['executable']
    counter_path = bound(Path(built['parent_executable']['path']).parent / 'report.json')
    counter = json.loads(counter_path.read_bytes())
    assert counter['executable'] == built['parent_executable']
    source = bound(counter_path.parent / 'common/place/placer_heap.cc')
    assert digest(source) == counter['generated_source_sha256']
    compiles = [c for c in counter['commands'] if '-c' in c['argv'] and str(source) in c['argv']]
    assert len(compiles) == 1 and compiles[0]['returncode'] == 0 and compiles[0]['status'] == 'PASS_TOOL_EXECUTION_ONLY'
    argv = compiles[0]['argv']
    assert argv.count('-o') == 1
    obj = bound(argv[argv.index('-o') + 1])
    verify_native_link_command(built['commands'], obj, native['executable']['path'])
    contract = source_contract(source.read_text())
    pack_log = bound(packed['commands'][-1]['log'])
    checksums = re.findall(r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$', pack_log.read_text())
    assert len(checksums) == 1
    log = Path(command['log']).resolve(strict=True)
    assert log.is_relative_to(path.parent)
    observation = log.read_text()  # Snapshot the live prefix, not a frozen-file binding.
    checks = log_observation(observation, packed['native_census']['cells'], checksums[0])
    for item in (Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()):
        before[str(item)] = digest(item)
    assert verify_worker(command) == worker_start
    assert all(digest(p) == sha for p, sha in before.items())
    assert source_revision() == production
    out = ROOT / f'build/openxc7/recursive-mux-analytic-scope-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'native-report-at-observation.json').write_bytes(native_bytes)
    (out / 'native-log-at-observation.log').write_text(observation)
    (out / 'executed_source.py').write_bytes(Path(__file__).read_bytes())
    report = dict(status=STATUS, observed_utc=observed_at, finished_utc=timestamp(),
                  scope=__doc__, native_report=str(path), current_native_pid=command['pid'],
                  native_worker_start_ticks=worker_start, native_version=native['native_version'],
                  packed_report=str(packed_path), source=before, production_source=production,
                  compiled_HeAP_source=str(source), compiled_HeAP_object=str(obj),
                  native_source_scope_contract=contract, actual_log_observation=checks,
                  frozen_runner_or_error_expectation_changed=False,
                  replacement_placement_acceptance_prepared=False,
                  full_cell_membership_verified=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
                  drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
                  processes_signalled=False,
                  artifacts={str(p): digest(p) for p in out.iterdir() if p.is_file()})
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)
    print(STATUS, flush=True)


if __name__ == '__main__':
    main()
