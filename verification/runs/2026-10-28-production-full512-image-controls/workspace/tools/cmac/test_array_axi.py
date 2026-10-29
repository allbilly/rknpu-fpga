#!/usr/bin/env python3
"""Test the separate C32/K16 endpoint through public AXI-Lite and AXI ports.

Only test RAM images are assembled here. No command or operand repacking,
numerical calculation, or CPU fallback occurs in the hardware execution path.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--suite', choices=('smoke', 'protocol', 'full'), default='smoke')
p.add_argument('--prepare-only', action='store_true')
a = p.parse_args()
base = ROOT / 'build/rknpu-array-core-vectors'
vr = json.loads((base / 'vectors_report.json').read_text())

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

verify(vr['source']); verify(vr['artifacts'])
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / name for name in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'compat/NV_DW_lsd.v',
                                    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v', 'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v')]
sources += [ROOT / 'rtl/cmac' / name for name in ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv', 'rk_nvdla_cacc.sv',
             'rk_cacc_fp16_array.sv', 'rk_cmac_cacc_fp16_array.sv', 'rk_nvdla_fp32_to_fp16.sv', 'rk_cmac_writer.sv',
             'rk_cmac_output_nvdla.sv', 'rk_cmac_frame_output.sv', 'rk_cmac_array_datapath.sv',
             'rk_cmac_array_front.sv', 'rk_cmac_rw_arbiter.sv', 'rk_cmac_array_core.sv', 'rk_cmac_array_dma.sv',
             'rk_cmac_job_control.sv', 'rk_cmac_axi_mem.sv', 'rk_cmac_array_axi.sv')]
sources.append(ROOT / 'rtl/rk_cmac_profile.sv')
bench = ROOT / 'tests/cmac/tb_cmac_array_axi.sv'
tracked = sources + [bench, ROOT / 'tests/axil_host.svh', ROOT / 'tests/memory_check.svh', Path(__file__).resolve(), base / 'vectors_report.json']
tracked += [donor / name for name in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
out = ROOT / f'build/rknpu-array-axi/{a.suite}-iverilog-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), suite=a.suite, source=fingerprint(tracked), vectors=vr,
              commands=[], tests=[], seed='0x3588ae16',
              scope='C32/K16 raw-command DMA and arithmetic through AXI-Lite host control and behavioral 512-bit AXI RAM. Synthetic donor-policy goldens, not RK captures, upstream UTB, PCIe/DDR, physical timing or FPGA validation.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')

def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save()
    started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            with subprocess.Popen(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                try:
                    result = proc.wait(timeout=14400)
                except BaseException:
                    if proc.poll() is None:
                        os_kill_group(proc.pid)
                    proc.wait()
                    raise
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result
        assert result == 0 and 'ERROR :' not in text, text[-6000:]
        assert not re.search(r'warning:|sorry:', text, re.I), text[-6000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()

def os_kill_group(pid):
    import os
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

def image(case):
    """Place existing physical BOs at their encoded addresses; retain all gaps."""
    directory = out / 'vectors' / case['name']
    directory.mkdir(parents=True, exist_ok=False)
    original = base / case['name']
    words = [int(line, 16) for line in (original / 'commands.hex').read_text().splitlines()]
    assert len(words) == 49
    assert hashlib.sha256(struct.pack('<49Q', *words)).hexdigest() == case['commands_sha256']
    memory, checked = {}, set()
    buffers = [(0x100e0000, struct.unpack('<196H', struct.pack('<49Q', *words)))]
    for address, name in ((0x10010000, 'input.hex'), (0x10020000, 'weight.hex')):
        buffers.append((address, [int(line, 16) for line in (original / name).read_text().splitlines()]))
    assert len(buffers[1][1]) == case['rows']*case['ai']
    assert len(buffers[2][1]) == case['ai']*case['ao']
    for address, values in buffers:
        for i, value in enumerate(values):
            addr = address+2*i
            assert addr not in memory and 0 <= value <= 65535
            memory[addr] = value
        checked.update(range(address-64, address+2*len(values)+64, 2))
    output_begin, output_end = 0x10040000, 0x10040000+case['rows']*case['ao']*4
    checked.update(range(output_begin-64, output_end+64, 2))
    assert not any(output_begin-64 <= address < output_end+64 for address in memory)
    expected = {address: memory.get(address, 0xa55a) for address in checked}
    written = set()
    for line in (original / 'writes.hex').read_text().splitlines():
        value = int(line, 16); address = value >> 16
        assert address % 2 == 0 and output_begin <= address < output_end and address not in written
        expected[address] = value & 65535
        written.add(address)
    assert len(written) == case['writes']
    assert len(expected) == 196 + case['rows']*case['ai'] + case['ai']*case['ao'] + 2*case['rows']*case['ao'] + 256
    # Each read oracle must resolve to the unchanged physical input/weight image.
    reads = [int(line, 16) for line in (original / 'reads.hex').read_text().splitlines()]
    assert len(reads) == case['reads']
    assert all(memory[value >> 16] == value & 65535 for value in reads)
    (directory / 'input.hex').write_text(''.join(f'@{(address-0x10000000)//2:08x} {value:04x}\n' for address, value in sorted(memory.items())))
    (directory / 'check.txt').write_text(''.join(f'{address:08x} {value:04x}\n' for address, value in sorted(expected.items())))
    return directory

save()
try:
    directories = {case['name']: image(case) for case in vr['cases']}
    image_files = sorted(path for directory in directories.values() for path in directory.iterdir())
    report['memory_images'] = fingerprint(image_files)
    if a.prepare_only:
        report['status'] = 'PREPARED_TEST_IMAGES_ONLY'
    else:
        report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        binary = out / 'sim.vvp'
        run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-I.',
             '-s', bench.stem, '-o', binary, *sources, bench], 'compile')
        common = vr['cases'][3]
        if a.suite == 'smoke':
            tests = [(common, mode, 1) for mode in (7, 8, 0)]
        elif a.suite == 'protocol':
            tests = [(common, mode, 1) for mode in (1, 2, 3, 7, 8, 10)]
        else:
            tests = [(case, 0, 1) for case in vr['cases']]
            tests += [(common, mode, 1) for mode in range(1, 11)] + [(common, 0, 2)]
        outputs = []
        for case, mode, repeats in tests:
            name = f'{case["name"]}-fault{mode}-repeat{repeats}'
            output = out / (name+'.memory.txt')
            text = run(['vvp', binary, f'+CASE={directories[case["name"]]}', '+START=100e0000', '+AMOUNT=45',
                        '+NTASKS=1', f'+NTRANS={196+case["reads"]+case["writes"]}', f'+WRITES={case["writes"]}',
                        f'+NCHECKS={196+case["rows"]*case["ai"]+case["ai"]*case["ao"]+2*case["rows"]*case["ao"]+256}',
                        f'+FAULT={mode}', f'+REPEATS={repeats}', f'+OUTPUT={output}'], name)
            lines = [line for line in text.splitlines() if line.startswith('PASS ')]
            error = {0:0, 1:5, 2:8, 3:8, 4:5, 5:8, 6:5, 7:7, 8:1, 9:0, 10:5}[mode]
            assert len(lines) == 1 and lines[0].startswith('PASS C32 K16 host_axi '), text
            assert f'repeats={repeats} fault_mode={mode} error={error} ' in lines[0], text
            assert lines[0].endswith('seed=3588ae16'), text
            if not error:
                assert output.read_bytes() == (directories[case['name']] / 'check.txt').read_bytes()
                outputs.append(output)
            else:
                assert not output.exists()
            report['tests'].append(dict(name=name, status='PASS', result=lines[0])); save()
        report.update(status='PASS_RAW_ARRAY_AXI_'+a.suite.upper()+'_ONLY',
                      artifacts=fingerprint([binary]+outputs+[ROOT / c['log'] for c in report['commands']]))
    assert fingerprint(tracked) == report['source']
    verify(vr['source']); verify(vr['artifacts']); verify(report['memory_images'])
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
