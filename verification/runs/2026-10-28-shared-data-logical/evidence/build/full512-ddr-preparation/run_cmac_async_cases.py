"""Fixed-source CMAC async component simulations; no MIG/FPGA qualification."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

ROOT = Path('/home/fedora/rknpu-fpga')
BASE = ROOT / 'build/full512-ddr-preparation'
EXPECTED = {
    'iverilog': ('cmac-async-bench-compile-v2/tb_cmac_async_engine.vvp',
                '87ab2bfe71b689b0925541fe45b434c0002adae520aa098a716134414962fb00'),
    'verilator': ('cmac-async-verilator-native-v2/obj/sim',
                 '013d9fa35918f96cf782166a50f22ca78a545b4fda8fb3553bd1a5c57d4dd6ac'),
}
# admitted, consumed, raw words, operand reads, writes, responses, rearms
COUNTS = {0:(2,2,98,13056,128,13576,2), 1:(1,1,0,0,0,1,0),
          2:(1,1,0,0,0,0,0), 3:(1,1,1,0,0,4,0), 4:(1,1,0,0,0,1,0),
          5:(1,1,0,0,0,0,0), 6:(1,1,49,6528,64,6788,0),
          7:(1,1,49,6528,64,6788,1), 8:(1,1,49,6528,64,6788,1)}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--simulator', choices=EXPECTED, required=True)
parser.add_argument('--mode', type=int, choices=range(9), action='append', required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh runtime directory required')
require(len(set(args.mode)) == len(args.mode), 'Duplicate runtime selection')
review_path = BASE/'cmac-async-diagnostics-root-review-v1.json'
review = json.loads(review_path.read_text())
binary_rel, binary_sha = EXPECTED[args.simulator]
binary = BASE/binary_rel
require(sha(binary) == binary_sha, 'Changed executed binary')
inputs = dict(review['source_inputs'])
inputs.update({str(p):sha(p) for p in (ROOT/'tests/cmac/array_data').iterdir() if p.is_file()})
inputs.update({str(binary):binary_sha, str(review_path):sha(review_path),
               str(Path(__file__).resolve()):sha(__file__)})
require(all(sha(p) == value for p,value in inputs.items()), 'Changed runtime input')
out.mkdir()
record = dict(status='RUNNING', scope=__doc__, simulator=args.simulator,
    selected=args.mode, inputs=inputs, binary_sha256=binary_sha, cases=[],
    hardware_accessed=False, started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())


def save():
    (out/'report.json').write_text(json.dumps(record, indent=2)+'\n')


def interrupted(sig, frame):
    raise InterruptedError('Owned CMAC simulation interrupted '+str(sig))


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, interrupted)
child = None
save()
try:
    for mode in args.mode:
        require(all(sha(p) == value for p,value in inputs.items()), 'Changed case input')
        launch = ['vvp',str(binary)] if args.simulator == 'iverilog' else [str(binary)]
        argv = launch+['+DIRECTORY='+str(ROOT/'tests/cmac/array_data'), '+MODE='+str(mode)]
        item = dict(mode=mode, status='RUNNING', argv=argv, timeout_seconds=1200)
        record['cases'].append(item)
        save()
        started = time.monotonic()
        stdout, stderr = out/f'mode-{mode}.stdout.log', out/f'mode-{mode}.stderr.log'
        with stdout.open('x') as so, stderr.open('x') as se:
            child = subprocess.Popen(argv, cwd=ROOT, stdout=so, stderr=se, start_new_session=True)
            item['pid'] = child.pid
            save()
            item['returncode'] = child.wait(timeout=1200)
        item.update(seconds=time.monotonic()-started, stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
        require(item['returncode'] == 0, 'Native CMAC test failed')
        require(not stderr.read_text(), 'Unexpected native simulator stderr')
        text = stdout.read_text()
        a,c,w,r,wr,rsp,rearm = COUNTS[mode]
        expected = (f'PASS async_cmac_boundary mode={mode} admitted={a} consumed={c} '
            f'command_words={w} operand_reads={r} writes={wr} responses={rsp} '
            f'rearm={rearm} seed=3588ad16 raw_K65_two_clocks_only')
        require([s for s in text.splitlines() if s.startswith('PASS ')] == [expected],
                'Missing/duplicate/changed numerical or protocol result')
        require(not re.search(r'(?i)%Error|%Warning|\b(?:warning|error|fatal|sorry):|assertion failed', text),
                'Unexpected native runtime diagnostic')
        if args.simulator == 'iverilog':
            lines = text.splitlines()
            require(len(lines) == 2 and lines[0] == expected, 'Unexpected Icarus stdout')
            finish = re.fullmatch(re.escape(str(ROOT/'tests/ddr/tb_cmac_async_engine.sv'))+
                r':([0-9]+): \$finish called at ([0-9]+) \(1ps\)', lines[1])
            require(finish is not None and
                (ROOT/'tests/ddr/tb_cmac_async_engine.sv').read_text().splitlines()[int(finish[1])-1].strip() == '$finish;',
                'Unexpected Icarus completion location')
        require(all(sha(p) == value for p,value in inputs.items()), 'Changed executed source/fixture')
        item.update(status='PASS', marker=expected)
        save()
        print(expected, flush=True)
    record['status'] = 'PASS_SELECTED_CMAC_ASYNC_COMPONENT_MODES_ONLY'
except BaseException as error:
    record.update(status='FAIL', error=repr(error))
    if record['cases'] and record['cases'][-1]['status']=='RUNNING':
        record['cases'][-1]['status']='FAIL'
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    raise
finally:
    record['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record['all_inputs_unchanged'] = all(sha(p) == value for p,value in inputs.items())
    save()
print(record['status'])
