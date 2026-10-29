#!/usr/bin/env python3
"""Hash-bound, process-owned full512 route launcher; root binding is mandatory."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

BASE = Path(__file__).resolve().parent
ROOT = Path('/home/fedora/rknpu-fpga')
SOURCE_PREP_DIR = ROOT / 'build/full512-ddr-preparation/shared-data-constrained-prep-v4'
ROUTE_PREP = BASE / 'preparation.json'
BINDING_PATH = BASE / 'route-binding.json'
REPORT_PATH = BASE / 'report.json'
OUTPUT = BASE / 'output'
VIVADO = Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
CH1_ROUTE = ROOT / 'build/ypcb-ddr-shell/ch1-route-v1'
child = None
received_signal = None
record = None

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def save():
    REPORT_PATH.write_text(json.dumps(record, indent=2) + '\n')

def cgroup_dir():
    rel = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines()
               if line.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup') / rel

def owned_group_members(pgid):
    members = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in {'Z', 'X'}:
                members.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
            continue
    return sorted(members)

def kill_owned(sig):
    global child
    if child is None:
        return
    pgid = child.pid
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    if owned_group_members(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if child.poll() is None:
            child.wait()

def handle_signal(sig, frame):
    global received_signal
    received_signal = sig
    raise InterruptedError('route runner received signal ' + str(sig))

def restore_child_signal_mask(mask):
    signal.pthread_sigmask(signal.SIG_SETMASK, mask)

def hash_files(paths):
    return {str(Path(path)): sha(path) for path in paths}

def expected_inputs(prep, binding, dcp, review, facts):
    items = {}
    for row in prep['source_copy_rows']:
        path = SOURCE_PREP_DIR / 'source' / row['relative_path']
        items[str(path)] = row['copy_sha256']
    fixed = {
        SOURCE_PREP_DIR / 'preparation.json': prep['source_preparation_sha256'],
        SOURCE_PREP_DIR / 'synth.tcl': prep['source_synth_tcl_sha256'],
        SOURCE_PREP_DIR / 'run_synth.py': prep['source_runner_sha256'],
        Path(prep['mapped_inventory_facts_path']): prep['mapped_inventory_facts_sha256'],
        Path(prep['mapped_inventory_report_path']): prep['mapped_inventory_report_sha256'],
        ROUTE_PREP: binding['route_preparation_sha256'],
        BASE / 'route.tcl': prep['route_tcl_sha256'],
        BASE / 'run.py': prep['runner_sha256'],
        VIVADO: prep['vivado_sha256'],
        dcp: binding['post_opt_dcp_sha256'],
        review: binding['source_review_json_sha256'],
        facts: binding['synthesis_facts_sha256'],
    }
    for helper in prep['helpers']:
        fixed[BASE / 'helpers' / helper['name']] = helper['sha256']
    for row in prep['reference_route_files']:
        fixed[Path(row['path'])] = row['sha256']
    for path, digest in fixed.items():
        items[str(path)] = digest
    # The route binding is supplied by root and frozen across this one run.
    items[str(BINDING_PATH)] = sha(BINDING_PATH)
    return items

def verify_input_hashes(expected):
    actual = hash_files(expected)
    require(actual == expected, 'One or more route inputs differ from their frozen expected hashes')
    return actual

def launch_after_preflight(expected, launcher):
    verify_input_hashes(expected)
    return launcher()

def extract_anchor_set(facts_path):
    rows = []; proof_rows = 0; proof_nets = 0
    for line in Path(facts_path).read_text().splitlines():
        fields = line.split('\t')
        if fields[0] == 'ANCHOR_SET':
            require(len(fields) == 6 and fields[2] == 'GROUND' and fields[3] == '1' and
                    fields[4].upper() in {'1', 'TRUE'} and fields[5].upper() in {'1', 'TRUE'},
                    'Source audit contains a malformed or unretained constant anchor')
            rows.append(fields[1])
        elif fields[0] == 'ZERO_ROW' and len(fields) > 1 and fields[1] == 'post_opt':
            proof_rows += 1
        elif fields[0] == 'ZERO_NET' and len(fields) > 1 and fields[1] == 'post_opt':
            require(len(fields) >= 11 and fields[7] == 'GROUND' and fields[8] == '1' and
                    fields[9].upper() in {'1', 'TRUE'} and fields[10].upper() in {'1', 'TRUE'},
                    'Post-opt source audit contains an invalid ground observation')
            proof_nets += 1
    anchors = sorted(set(rows))
    require(proof_rows == 35 and proof_nets == 101 and anchors,
            'Source audit must prove exactly35 rows and101 retained ground observations')
    return anchors

def main():
    global child, record
    started = time.monotonic()
    record = {'status': 'PREFLIGHT', 'scope': 'full512 routed checkpoint only; no image/hardware',
              'hardware_accessed': False, 'bitstream_emitted': False, 'flash_written': False,
              'route_design_started': False, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    require(not REPORT_PATH.exists(), 'Fresh route attempt required')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handle_signal)
    try:
        prep = json.loads(ROUTE_PREP.read_text())
        binding = json.loads(BINDING_PATH.read_text())
        source_prep = json.loads((SOURCE_PREP_DIR / 'preparation.json').read_text())
        require(prep['status'] in {'UNLAUNCHABLE_PENDING_POST_OPT_DCP_AND_ROOT_SOURCE_AUDIT',
                                  'BOUND_AND_ROOT_REVIEWED'},
                'Changed route package status')
        require(binding.get('launch_approved') is True and
                binding.get('root_route_approval') is True and
                binding.get('status') == 'BOUND_AND_ROOT_REVIEWED',
                'UNLAUNCHABLE: root has not bound DCP, source review, and route approval')
        require(binding.get('route_preparation_sha256') == sha(ROUTE_PREP), 'Route preparation hash is not root-bound')
        require(binding.get('route_tcl_sha256') == prep['route_tcl_sha256'] == sha(BASE / 'route.tcl'),
                'Route Tcl hash changed from frozen preparation')
        require(binding.get('runner_sha256') == prep['runner_sha256'] == sha(BASE / 'run.py'),
                'Route runner hash changed from frozen preparation')
        require(binding.get('source_preparation_sha256') == prep['source_preparation_sha256'] ==
                sha(SOURCE_PREP_DIR / 'preparation.json'), 'Source preparation changed')
        require(prep.get('vivado_path') == str(VIVADO) and VIVADO.is_file(), 'Vivado executable path changed')
        require(binding.get('source_review_status') == 'PASS_FULL512_POST_OPT_SOURCE_AUDIT',
                'Root source review is not accepted')
        dcp = Path(binding.get('post_opt_dcp_path') or '')
        review = Path(binding.get('source_review_json_path') or '')
        facts = Path(binding.get('synthesis_facts_path') or '')
        require(dcp.is_absolute() and dcp.is_file(), 'Missing bound post-opt DCP')
        require(review.is_absolute() and review.is_file(), 'Missing bound root source review')
        require(facts.is_absolute() and facts.is_file(), 'Missing bound constrained synthesis facts TSV')
        dcp_hash = sha(dcp)
        require(dcp_hash == binding.get('post_opt_dcp_sha256') == binding.get('source_review_dcp_sha256'),
                'DCP/source-review hash binding mismatch')
        review_data = json.loads(review.read_text())
        require(review_data.get('status') == 'PASS_FULL512_POST_OPT_SOURCE_AUDIT',
                'Root source review JSON has not passed')
        require(review_data.get('post_opt_dcp_sha256') == dcp_hash and
                review_data.get('synthesis_facts_sha256') == binding.get('synthesis_facts_sha256'),
                'Root source review JSON must explicitly bind this DCP and facts TSV')
        anchors = extract_anchor_set(facts)
        anchor_text = '\n'.join(anchors) + '\n'
        anchor_hash = hashlib.sha256(anchor_text.encode()).hexdigest()
        require(len(anchors) == binding.get('anchor_set_count') == prep['anchor_set_count'],
                'Anchor count differs from root binding/preparation')
        require(anchor_hash == binding.get('anchor_set_sha256') == prep['anchor_set_sha256'],
                'Anchor set hash differs from root binding/preparation')
        inputs = expected_inputs(prep, binding, dcp, review, facts)
        before = hash_files(inputs)
        record['input_hashes_expected'] = inputs
        record['input_hashes_before'] = before
        require(before == inputs, 'One or more route inputs differ from their frozen expected hashes')
        group = cgroup_dir()
        limits = {name: (group / name).read_text().strip() for name in
                  ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max')}
        expected_limits = {'memory.max': str(binding['memory_max_bytes']),
                           'memory.swap.max': str(binding['memory_swap_max_bytes']),
                           'cpu.max': binding['cpu_quota'], 'pids.max': str(binding['tasks_max'])}
        require(limits == expected_limits, 'Wrong route resource caps: ' + repr(limits))
        available = int(re.search(r'^MemAvailable:\s+(\d+) kB',
                                  Path('/proc/meminfo').read_text(), re.M)[1])
        mempsi = Path('/proc/pressure/memory').read_text()
        cpupsi = Path('/proc/pressure/cpu').read_text()
        memfull = float(re.search(r'^full avg10=([0-9.]+)', mempsi, re.M)[1])
        cpusome = float(re.search(r'^some avg10=([0-9.]+)', cpupsi, re.M)[1])
        require(available >= binding['host_mem_available_min_kib'], 'Insufficient route host memory headroom')
        require(memfull < binding['memory_psi_full_avg10_max'] and cpusome < binding['cpu_psi_some_avg10_max'],
                'Route host pressure admission failed')
        require(not OUTPUT.exists(), 'Fresh route output directory required')
        version = subprocess.run([str(VIVADO), '-version'], text=True, capture_output=True,
                                 timeout=30, check=True)
        record.update(status='READY_TO_LAUNCH', argv=[str(VIVADO), '-mode', 'batch', '-source', str(BASE / 'route.tcl'),
                      '-log', str(OUTPUT / 'vivado.log'), '-journal', str(OUTPUT / 'vivado.jou')],
                      vivado_path=str(VIVADO), vivado_sha256=sha(VIVADO), vivado_version_stdout=version.stdout,
                      vivado_version_stderr=version.stderr, kernel_limits=limits, initial_available_kib=available,
                      initial_memory_psi=mempsi, initial_cpu_psi=cpupsi, input_hashes_before=before,
                      post_opt_dcp_path=str(dcp), post_opt_dcp_sha256=dcp_hash,
                      source_review_json_path=str(review), source_review_json_sha256=sha(review),
                      synthesis_facts_path=str(facts), synthesis_facts_sha256=sha(facts),
                      anchor_set_count=len(anchors), anchor_set_sha256=anchor_hash,
                      placement_and_route_seed=binding['route_seed'], timeout_seconds=binding['deadline_seconds'])
        OUTPUT.mkdir()
        anchor_file = OUTPUT / 'expected-anchor-names.txt'
        anchor_file.write_text(anchor_text)
        env = dict(os.environ, RK_SHARED_ROUTE_POST_OPT_DCP=str(dcp),
                   RK_SHARED_ROUTE_EXPECTED_ANCHOR_FILE=str(anchor_file),
                   RK_SHARED_ROUTE_ROOT_APPROVED='APPROVED')
        record.update(status='RUNNING', pid=None, pgid=None, route_design_started=True)
        save()
        with (OUTPUT / 'stdout.log').open('x') as stdout_log, (OUTPUT / 'stderr.log').open('x') as stderr_log:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                child = launch_after_preflight(inputs, lambda: subprocess.Popen(
                    record['argv'], cwd=OUTPUT, env=env, stdout=stdout_log,
                    stderr=stderr_log, start_new_session=True,
                    preexec_fn=lambda: restore_child_signal_mask(previous_mask)))
                record.update(pid=child.pid, pgid=child.pid, launched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                save()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            try:
                record['returncode'] = child.wait(timeout=binding['deadline_seconds'])
            except subprocess.TimeoutExpired:
                record['status'] = 'TIMEOUT'
                kill_owned(signal.SIGTERM)
                record['returncode'] = child.returncode
                raise TimeoutError('Owned full512 route exceeded the bound deadline')
        stdout_text = (OUTPUT / 'stdout.log').read_text(errors='replace')
        marker = 'PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW'
        require(record['returncode'] == 0, 'Native full512 route/strict gates failed')
        require(stdout_text.splitlines().count(marker) == 1, 'Missing exact native route marker')
        after = hash_files(inputs)
        require(after == before, 'A frozen route input changed during implementation')
        record.update(status=marker, input_hashes_after=after, all_inputs_unchanged=True)
    except BaseException as error:
        if child is not None and child.poll() is None:
            kill_owned(signal.SIGTERM)
        record.update(status=(record.get('status') if record.get('status') == 'TIMEOUT' else
                             ('CANCELLED' if received_signal else 'FAIL')), error=repr(error),
                      received_signal=received_signal,
                      returncode=(child.returncode if child is not None else None))
    finally:
        record['elapsed_seconds'] = time.monotonic() - started
        record['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            group = cgroup_dir()
            record['memory_peak_bytes'] = (group / 'memory.peak').read_text().strip()
            record['memory_events'] = (group / 'memory.events').read_text().strip()
        except BaseException as error:
            record['cgroup_telemetry_error'] = repr(error)
        if child is not None:
            live_group = owned_group_members(child.pid)
            if live_group:
                record['lingering_owned_group_pids_before_cleanup'] = live_group
                kill_owned(signal.SIGTERM)
                live_group = owned_group_members(child.pid)
                if live_group:
                    record['lingering_owned_group_pids_after_cleanup'] = live_group
                    if record.get('status', '').startswith('PASS_'):
                        record['status'] = 'FAIL_OWNED_PROCESS_GROUP_LINGERED'
                else:
                    record['owned_process_group_stopped'] = True
            else:
                record['owned_process_group_stopped'] = True
        if 'input_hashes_before' in record or 'input_hashes_expected' in record:
            try:
                expected = record.get('input_hashes_before', record['input_hashes_expected'])
                paths = list(expected)
                record['input_hashes_after'] = hash_files(paths)
                frozen_expected = record.get('input_hashes_expected', expected)
                record['all_inputs_unchanged'] = (record['input_hashes_before'] == frozen_expected and
                                                  record['input_hashes_after'] == frozen_expected)
                if not record['all_inputs_unchanged'] and record.get('status', '').startswith('PASS_'):
                    record['status'] = 'FAIL_INPUT_MUTATION_AFTER_ROUTE'
            except BaseException as error:
                record['input_rehash_error'] = repr(error)
                if record.get('status', '').startswith('PASS_'):
                    record['status'] = 'FAIL_INPUT_REHASH_AFTER_ROUTE'
        if OUTPUT.exists():
            record['output_hashes'] = {str(path.relative_to(OUTPUT)): sha(path)
                                       for path in OUTPUT.rglob('*') if path.is_file()}
        record['hardware_accessed'] = False
        record['bitstream_emitted'] = False
        record['flash_written'] = False
        save()
    return 0 if record['status'].startswith('PASS_FULL512_DDR_ROUTED') else 1

if __name__ == '__main__':
    raise SystemExit(main())
