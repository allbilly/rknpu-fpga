#!/usr/bin/env python3
"""Root reconciles actual native FI-leaf facts without relabeling wrappers."""
import datetime
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/home/fedora/rknpu-fpga')
MARKER = 'PASS fi_xor_leaf seed=00003588 scenarios=38 byte_lanes=9 low72_only=1 write_clear=1'
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
cases = []
for version, simulator in ((7, 'verilator'), (10, 'icarus')):
    base = ROOT / f'build/ddr-ecc-fi-leaf-validation-v{version}'
    report_path = base / 'report.json'
    report = json.loads(report_path.read_text())
    for path, expected in report['source_inputs'].items():
        assert sha(path) == expected, path
    if simulator == 'verilator':
        assert report['source_inputs'] == report['source_inputs_after']
        assert report['status'] == 'PASS_FI_XOR_LEAF_VERILATOR_ONLY'
    else:
        assert report['status'] == 'FAIL'
        assert 'vvp_run native output differs' in report['error']
    commands = {row['name']:row for row in report['commands']}
    assert len(commands) == 2
    for row in commands.values():
        assert row['returncode'] == 0 and row['timeout_seconds'] == 300
        assert row['owned_process_group_absent']
        for stream in ('stdout','stderr'):
            assert sha(row[stream + '_log']) == row[stream + '_sha256']
    bench = base / 'tests/tb_mig_fi_xor.sv'
    assert sha(bench) == 'fac070c2af73db164edf1bdbbe1833d9502973967d2226b06eab6806513d0a15'
    leaf = base / 'source/mig_7series_v4_2_fi_xor.v'
    assert sha(leaf) == 'ba05d31545d807b8e485a6d2c4e6bd51824aefe31981c9fe4e3d98bbd4e06fb1'
    compile_name, run_name = ('verilator_compile','verilator_run') if simulator=='verilator' else ('iverilog_compile','vvp_run')
    compile_row, run_row = commands[compile_name], commands[run_name]
    assert '-Wall' in compile_row['argv']
    assert not any(arg.startswith('-Wno') for arg in compile_row['argv'])
    output = Path(run_row['stdout_log']).read_text().splitlines()
    assert output.count(MARKER) == 1 and output[0] == MARKER
    assert Path(run_row['stderr_log']).read_text() == ''
    warning = None
    if simulator=='icarus':
        warning = str(leaf) + ':106: warning: Anachronistic use of begin/end to surround generate schemes.\n'
        assert Path(compile_row['stderr_log']).read_text() == warning
        assert Path(compile_row['stdout_log']).read_text() == ''
        assert len(output) == 2
        finish_line = next(n for n,line in enumerate(bench.read_text().splitlines(),1) if line.strip()=='$finish;')
        assert re.fullmatch(re.escape(str(bench)) + ':' + str(finish_line) + r': \$finish called at 457 \(1ps\)', output[1])
    else:
        assert Path(compile_row['stderr_log']).read_text() == ''
        assert not re.search(r'%Warning|%Error',Path(compile_row['stdout_log']).read_text())
        assert all(line.startswith(('- ' + str(bench) + ':', '- S i m u l a t i o n', '- Verilator:')) for line in output[1:])
    cases.append({'simulator':simulator,'report_path':str(report_path),'report_sha256':sha(report_path),
        'producer_status_preserved':report['status'],'native_compile_rc':0,'native_run_rc':0,
        'exact_marker':MARKER,'compile_warning':warning,'native_logs_rehashed':4})
history=[]
for base in sorted((ROOT / 'build').glob('ddr-ecc-fi-leaf-validation-v*')):
    path=base/'report.json'
    if path.exists():
        history.append({'path':str(path),'sha256':sha(path),'status':json.loads(path.read_text())['status']})
result={
    'status':'PASS_ROOT_FI_LEAF_NATIVE_BEHAVIOR_ONLY_WITH_RECORDED_ICARUS_VENDOR_WARNING',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'reviewer_sha256':sha(__file__),'cases':cases,'history':history,
    'bench_source_review':['Nine byte lanes, mask hold, low72 XOR, upper504 passthrough',
        'Explicit zero disarm, write-clear priority, clean following writes',
        'Mock reset intentionally unconnected; no reset-clearing claim'],
    'same_vendor_and_bench_bytes_both_simulators':True,
    'failed_v10_receipt_relabelled':False,'native_execution_repeated':False,
    'hardware_accessed':False,'physical_ecc_injection_qualified':False,
    'memory_controller_decoder_or_phy_simulated':False,
}
with (ROOT/'build/ddr-ecc-fi-leaf-root-review-v1.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True)
    stream.write('\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('cases','history','bench_source_review')},sort_keys=True))
