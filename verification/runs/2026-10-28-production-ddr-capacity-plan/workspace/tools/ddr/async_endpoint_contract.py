"""Strict source, diagnostic and result gates for the SYS50/UI133 async DDR model.

This module has no simulator or hardware side effects. Software arithmetic
constructs test expectations only; raw final BOs remain the execution input.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re

from tools.ddr.endpoint_vectors import captured_cases, lines
from tools.ddr.interface import require
from tools.ddr.run_monitor import diagnostics

ROOT = Path(__file__).resolve().parents[2]
TOP = 'tb_jtag_ew_ddr_async'
SCOPE = ('SYS50 engine / UI133 owner async raw EW/job/AXI/UI/MC/ECC logical simulation '
         'with encoded PHY model only; no PHY training, physical DDR, PCIe, FPGA or RK proof')
SCHEMA = 2
CASE_COUNT = 21
MARKER = re.compile(r'PASS jtag_ew_ddr_async jobs=(\d+) negative=(\d+) recovered=(\d+) '
                    r'lines=(\d+) uploaded_nonzero=(\d+) rawtasks=(\d+) '
                    r'phy_user_returns=(\d+) scope=actual_AXI_UI_MC_modeled_PHY')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selection(specs, names):
    known = {s['name']: s for s in specs}
    require(len(known) == len(specs) == CASE_COUNT, 'Incomplete async DDR scenario inventory')
    if not names:
        return specs
    require(len(names) == len(set(names)) and set(names) <= set(known), 'Unknown/duplicate DDR case')
    return [known[n] for n in names]


def metrics(spec, vector_root):
    case = next(c for c in captured_cases() if c['name'] == spec['case'])
    physical_lines = sum(len(data)//64 for data in case['regions'].values())
    require(physical_lines == spec['lines'], 'BO extent differs from captured allocation')
    text = (Path(vector_root)/spec['case']/'upload.txt').read_text()
    require(text == lines(case['regions']), 'Upload differs from complete original BOs')
    nonzero = sum(int(row.split()[1], 16) != 0 for row in text.splitlines())
    command_reads = 4*sum(t['descriptor']['regcfg_amount'] for t in case['production']['tasks'])
    scalar_transactions = 3*((case['production']['logical_count']+7)//8*8)*case['tasks']
    # A host line read performs32 independent halfword AXI reads. A host line
    # write performs32 masked RMW reads and32 per-halfword retirement fences.
    # Normal startup: init fence + first/last line reads + explicit zero write.
    # Recovery: new init fence + one command-line read, then a fresh upload.
    expected_returns = None
    if spec['negative'] == 0:
        expected_returns = 129+nonzero*64+spec['jobs']*(command_reads+scalar_transactions+1+physical_lines*32)
    elif spec['reset_recovery']:
        expected_returns = 33+nonzero*64+command_reads+scalar_transactions+1+physical_lines*32
    return dict(lines=physical_lines, physical_bytes=physical_lines*64,
                uploaded_nonzero=0 if spec['negative'] == 9 else nonzero,
                successful_jobs=(spec['jobs'] if spec['negative'] == 0 else
                                 1 if spec['reset_recovery'] or spec['negative'] == 6 else 0),
                phy_user_returns=expected_returns)


def check_result(text, code, spec, data, observed, expected):
    require(type(code) is int and code == 0, 'Async DDR simulation did not exit successfully')
    require(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|\$fatal|Assertion failed|\bwarning:', text),
            'Unadmitted runtime failure/diagnostic')
    markers = [line for line in text.splitlines() if line.startswith('PASS ')]
    require(len(markers) == 1 and MARKER.fullmatch(markers[0]) is not None, 'Missing/extra/malformed DDR completion')
    values = [int(v) for v in MARKER.fullmatch(markers[0]).groups()]
    jobs = 0 if spec['negative'] == 9 else spec['jobs']+int(bool(spec['reset_recovery']))
    require(values[:6] == [jobs, spec['negative'], int(bool(spec['reset_recovery'])), data['lines'],
                           data['uploaded_nonzero'], spec['tasks']], 'Changed DDR scenario coverage')
    if spec['negative'] == 10:
        require(text.splitlines().count('CHECKED partial_task_fault completed=1 ui_code=5') == 1,
                'Missing actual partial-task/first-cause assertion')
    if data['phy_user_returns'] is not None:
        require(values[6] == data['phy_user_returns'], 'Actual logical PHY return inventory differs')
    else:
        require(values[6] >= 129, 'Missing initialized-memory traffic in fault scenario')
    observed, expected = Path(observed), Path(expected)
    if data['successful_jobs']:
        require(observed.is_file() and observed.read_bytes() == expected.read_bytes(), 'Complete DDR BO readback differs')
        require(len(observed.read_text().splitlines()) == data['lines'], 'Incomplete readback rows')
    else:
        require(not observed.exists(), 'Fault-only case produced a successful readback')
    return dict(marker=markers[0], phy_user_returns=values[6],
                readback_physical_bytes=data['physical_bytes'] if data['successful_jobs'] else 0,
                observed_text_bytes=observed.stat().st_size if observed.is_file() else 0,
                observed_sha256=sha(observed) if observed.is_file() else None,
                successful_jobs=data['successful_jobs'])


def check_warnings(text, policy, sources, version, root=ROOT):
    require(policy['schema'] == 1 and policy['status'] == 'SOURCE_BOUND_LOGICAL_SIMULATION_BASELINE_ONLY',
            'Unreviewed simulation warning policy')
    require(version.strip() == policy['verilator_version'], 'Compiler version differs from diagnostic inventory')
    source_map = {}
    for path in sources:
        path = Path(path)
        require(path.name not in source_map, 'Ambiguous compiler source basename')
        source_map[path.name] = path
    for name, digest in policy['origin_sha256'].items():
        require(name in source_map and sha(source_map[name]) == digest, 'Diagnostic source changed: '+name)
    for name, digest in policy['reset_context_sha256'].items():
        require(sha(Path(root)/name) == digest, 'Reset-notice context changed: '+name)
    actual = diagnostics(text, 'verilator')
    encode = lambda item: json.dumps(item, sort_keys=True, separators=(',', ':'))
    require(Counter(map(encode, actual)) == Counter(map(encode, policy['verilator'])),
            'Unexpected/missing/duplicate compiler diagnostic')
    require(not re.search(r'(?m)^%Error', text), 'Compiler error')
    return actual
