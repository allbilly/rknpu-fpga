"""Independent frozen-input/report review; explicitly not timing acceptance."""
from pathlib import Path
from collections import Counter
import datetime
import hashlib
import json
import re

BASE=Path(__file__).resolve().parent
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
report=json.loads((BASE/'report.json').read_text())
require(report['status']=='PASS_ACTUAL_ORIGINAL_MIG_ASYNC_EW_SYNTHESIS_ONLY_REQUIRES_REVIEW'
        and report['returncode']==0,'Native synthesis did not pass')
for name,digest in report['inputs'].items():
    require(sha(name)==digest,'Changed synthesis input: '+name)
for name,digest in report['artifacts'].items():
    require(sha(BASE/name)==digest,'Changed synthesis artifact: '+name)
prep=json.loads((BASE/'preparation.json').read_text())
require(prep['rtl_files']==118,'Changed actual HDL selection')
script=(BASE/'synth.tcl').read_text()
require('synth_design -top rk_original_mig_ew_platform' in script
        and '-mode out_of_context -flatten_hierarchy none' in script,'Changed synthesis scope')
for forbidden in ('place_design','route_design','write_bitstream','set_clock_groups',
                  'set_msg_config','create_waiver','open_hw_manager','program_hw_devices'):
    require(forbidden not in script,'Unexpected action/waiver: '+forbidden)
require('IS_BLACKBOX == 1' in script and 'Unresolved black boxes' in script,
        'Missing unresolved-module gate')
require(sha(BASE/'source/mig-original.xdc')==
        '5ea42669bed59d09cfad5c25a08aec20e0824d48895071ecd2acfbff8261b6fc',
        'Changed original MIG constraints')
require(report['kernel_limits']['memory.max']=='8589934592'
        and report['kernel_limits']['memory.swap.max']=='0','Changed resource cap')
events=dict(line.split() for line in report['memory.events'].splitlines())
require(events['oom']=='0' and events['oom_kill']=='0','Native synthesis had an OOM')
log=(BASE/'vivado.log').read_text()
require('PASS_ACTUAL_ORIGINAL_MIG_AND_ASYNC_EW_SYNTHESIS_ONLY' in log,'Missing native completion')
require(not re.search(r'^(?:CRITICAL WARNING|ERROR):',log,re.M),'Critical/error diagnostics present')
require('Common 17-55' not in log and 'Vivado 12-584' not in log,'Unbound original XDC objects')
warning_codes=Counter(re.findall(r'^WARNING: \[([^]]+)\]',log,re.M))
timing=(BASE/'unplaced_timing.rpt').read_text()
header=timing.index('WNS(ns)')
rows=timing[header:].splitlines()
summary=next(line.split() for line in rows[1:] if re.match(r'^\s*-?\d+\.\d+\s',line))
require(len(summary)==12,'Unrecognized native timing summary')
require(float(summary[0])<0 and float(summary[4])<0,'Unexpected timing evidence; review again')
paths=[]
lines=timing.splitlines()
for i,line in enumerate(lines):
    if 'Slack (VIOLATED)' not in line:continue
    fields={}
    for row in lines[i+1:i+19]:
        match=re.match(r'\s*(Source|Destination|Path Group|Path Type):\s*(.*)',row)
        if match:fields[match[1]]=match[2]
    paths.append(dict(slack_ns=float(line.split(':')[1].split('ns')[0]),**fields))
out=dict(status='PASS_FROZEN_ACTUAL_SOURCE_SYNTHESIS_INTEGRITY_ONLY_TIMING_OPEN',
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    reviewer_sha256=sha(__file__),native_report_sha256=sha(BASE/'report.json'),
    input_count=len(report['inputs']),artifact_count=len(report['artifacts']),rtl_files=118,
    checkpoint_sha256=sha(BASE/'actual_sources_synth.dcp'),
    native_warning_lines=sum(warning_codes.values()),warning_codes=dict(warning_codes),
    critical_warning_count=0,error_count=0,
    timing=dict(unplaced=True,setup_wns_ns=float(summary[0]),hold_whs_ns=float(summary[4]),
                pulse_wpws_ns=float(summary[8]),signoff=False),
    reported_violating_group_representatives=sorted(paths,key=lambda p:p['slack_ns']),
    unresolved=['Source-bound first-stage/held-bus/reset CDC constraints',
                'Same-UI control setup path and vendor clock/reset paths',
                'Complete async 21-case logical qualification',
                'Physical shell, board implementation, DDR training and application readback',
                'Full512 DDR integration and PCIe'],
    hardware_accessed=False,implementation_executed=False,physical_integration_ready=False)
(BASE/'root-synthesis-review.json').write_text(json.dumps(out,indent=2)+'\n')
print(out['status'],out['input_count'],out['artifact_count'],out['timing'])
