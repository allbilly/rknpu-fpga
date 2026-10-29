"""Prepare one supported post-route optimization attempt, preserving V2."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import shutil
import subprocess

BASE = Path(__file__).resolve().parent
OLD = BASE.with_name('postroute-repair-v2')
ROOT = BASE.parents[2]

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def need(ok, msg):
    if not ok:
        raise ValueError(msg)

def save(p, d):
    p.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')

def relocated(d):
    if isinstance(d, str):
        return d.replace(str(OLD), str(BASE))
    if isinstance(d, list):
        return [relocated(x) for x in d]
    if isinstance(d, dict):
        return {relocated(k): relocated(v) for k, v in d.items()}
    return d

need(not (BASE / 'preparation.json').exists(), 'Fresh preparation required')
failed = json.loads((OLD / 'report.json').read_text())
need(failed['status'] == 'FAIL' and failed['returncode'] == 1 and
     failed['all_inputs_unchanged'] and failed['owned_process_group_stopped'],
     'V2 is not an immutable completed failed attempt')
error = (OLD / 'output/stderr.log').read_text()
need('not supported yet for post-route physical synthesis' in error,
     'Unexpected V2 failure')
for name in ('run_repair.py', 'repair.tcl', 'expected-anchor-names.txt',
             'repair-selection.json'):
    shutil.copyfile(OLD / name, BASE / name)
shutil.copytree(OLD / 'helpers', BASE / 'helpers')
tcl = (BASE / 'repair.tcl').read_text()
unsupported = 'phys_opt_design -force_replication_on_nets $repair_net_objects\n'
need(tcl.count(unsupported) == 1, 'Unexpected implementation sequence')
tcl = tcl.replace(unsupported,
    '# V2 proved forced replication unsupported in post-route mode.\n'
    '# Keep the CE-driver inventory as evidence; use supported optimization.\n')
old_comment = ('# The parent is already routed. Repair may replicate only root-selected mapped\n'
               '# CE-driver nets; no place, clock, constraint, severity or exception edits occur.')
need(old_comment in tcl, 'Missing original scope comment')
tcl = tcl.replace(old_comment,
    '# The parent is already routed. Root-selected CE drivers are revalidated\n'
    '# before supported post-route optimization; no constraints are changed.')
# The source already has a tested fail-closed parser; use the exact procedure,
# adapting only its local helper names to this preparation script.
template = ROOT / 'fpga/ddr/emit_full512_ch1.tcl.in'
text = template.read_text()
start = text.index('# BEGIN ALL-ROW PULSE WIDTH AUDIT')
end = text.index('# END ALL-ROW PULSE WIDTH AUDIT') + len('# END ALL-ROW PULSE WIDTH AUDIT')
pulse = text[start:end].replace('require [expr', 'route_require [expr').replace('[finite ', '[route_finite ')
tcl = tcl.replace('puts "SHARED_DATA_ROUTE_TOOL', pulse + '\nputs "SHARED_DATA_ROUTE_TOOL', 1)
old_start = tcl.index('foreach kind {"Min Period" "Low Pulse Width" "High Pulse Width"} {',
                      tcl.index('set pulse [report_pulse_width -return_string]'))
old_end = tcl.index('\nputs PASS_FULL512_DDR_ROUTED', old_start)
tcl = tcl[:old_start] + 'set pulse_counts [audit_pulse_width_report $pulse]\n' + tcl[old_end:]
need('phys_opt_design -force_' not in tcl, 'Unsupported operation remains')
need(tcl.count('phys_opt_design -directive AggressiveExplore') == 1 and
     tcl.count('route_design -directive MoreGlobalIterations -tns_cleanup') == 1,
     'Unexpected implementation sequence')
(BASE / 'repair.tcl').write_text(tcl)
ast.parse((BASE / 'run_repair.py').read_text())
check = subprocess.run(['tclsh'], input='set f [open {' + str(BASE / 'repair.tcl') +
    '}]; set s [read $f]; close $f; if {![info complete $s]} {exit 1}\n',
    text=True, capture_output=True)
need(check.returncode == 0, 'Tcl is incomplete: ' + check.stderr)
prep = relocated(json.loads((OLD / 'preparation.json').read_text()))
controls = prep['repair_control_hashes']
for p in controls:
    controls[p] = sha(p)
for p in (template, OLD / 'report.json', OLD / 'output/stderr.log',
          OLD / 'repair.tcl', BASE / 'prepare_v3.py'):
    controls[str(p)] = sha(p)
prep.update(
    allowed_implementation_sequence=[
        'phys_opt_design -directive AggressiveExplore',
        'route_design -directive MoreGlobalIterations -tns_cleanup'],
    repair_tcl_sha256=sha(BASE / 'repair.tcl'),
    runner_sha256=sha(BASE / 'run_repair.py'),
    repair_selection_sha256=sha(BASE / 'repair-selection.json'),
    prior_attempt_report_path=str(OLD / 'report.json'),
    prior_attempt_report_sha256=sha(OLD / 'report.json'),
    prior_attempt_status='FAIL_UNSUPPORTED_POSTROUTE_FORCE_REPLICATION_OPTION',
    pulse_gate='All recognized Min/Max Period and Low/High Pulse Width rows',
    scope='Fresh supported post-route optimization of the immutable failed V6 checkpoint; no RTL/XDC/helper/electrical/clock/exception changes, no image or hardware.',
    future_report_status=prep['marker'])
save(BASE / 'preparation.json', prep)
admission = relocated(json.loads((OLD / 'repair-admission.json').read_text()))
admission.update(preparation_sha256=sha(BASE / 'preparation.json'),
                 runner_sha256=sha(BASE / 'run_repair.py'),
                 repair_tcl_sha256=sha(BASE / 'repair.tcl'),
                 repair_selection_sha256=sha(BASE / 'repair-selection.json'))
save(BASE / 'repair-admission.json', admission)
review = dict(status='ROOT_APPROVED_SUPPORTED_POST_ROUTE_AGGRESSIVE_EXPLORE_ONLY',
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    parent_failure_preserved=True,
    prior_unsupported_option_failure_preserved=True,
    parent_routed_dcp_sha256=prep['parent_routed_dcp_sha256'],
    source_post_opt_dcp_sha256=prep['source_post_opt_dcp_sha256'],
    repair_tcl_sha256=sha(BASE / 'repair.tcl'),
    runner_sha256=sha(BASE / 'run_repair.py'),
    admission_sha256=sha(BASE / 'repair-admission.json'),
    allowed_implementation_sequence=prep['allowed_implementation_sequence'],
    constraints_changed=False, bitstream_emission_authorized=False,
    hardware_accessed=False)
save(BASE / 'root-launch-review.json', review)
print(json.dumps(review, indent=2))
