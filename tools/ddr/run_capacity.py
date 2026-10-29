#!/usr/bin/env python3
"""Bounded capacity BIST simulations; no Vivado, board or physical-capacity claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.capacity_pattern import CapacityPlan

SOURCES = [ROOT / 'rtl/ddr' / name for name in (
    'rk_ddr_capacity_pattern.sv', 'rk_ddr_capacity_sweep.sv',
    'rk_ddr_capacity_axi.sv', 'rk_ddr_capacity_bist.sv',
    'rk_mig_write_fence.sv', 'rk_mig_ecc_monitor.sv')]
BENCHES = [ROOT / 'tests/ddr/capacity' / name for name in (
    'tb_capacity_axi.sv', 'tb_capacity_bist_joined.sv')]
CASES = [
    ('small256', 'tb_capacity_axi', 0, 256, True),
    ('small512', 'tb_capacity_axi', 0, 512, False),
    ('offset256', 'tb_capacity_axi', 0x1000, 256, True),
    ('last512', 'tb_capacity_axi', 0x7ffffe00, 512, False),
    ('joined256', 'tb_capacity_bist_joined', 0, 256, False),
    ('joined_offset256', 'tb_capacity_bist_joined', 0x1000, 256, False),
]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run_command(output, name, argv):
    stdout, stderr = output / (name + '.stdout.log'), output / (name + '.stderr.log')
    started = time.monotonic()
    with stdout.open('xb') as out, stderr.open('xb') as err:
        process = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
        try:
            returncode = process.wait(timeout=300)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
            raise
    return {'name':name, 'argv':argv, 'returncode':returncode,
            'wall_seconds':time.monotonic()-started, 'timeout_seconds':300,
            'stdout_path':str(stdout), 'stdout_sha256':sha(stdout),
            'stderr_path':str(stderr), 'stderr_sha256':sha(stderr)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog','verilator'), required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    output = (args.out or ROOT/'build/ddr-capacity'/f'{args.simulator}-{time.time_ns()}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = SOURCES + BENCHES + [Path(__file__).resolve(), ROOT/'tools/ddr/capacity_pattern.py']
    before = {str(path.relative_to(ROOT)):sha(path) for path in paths}
    commands, versions = [], {}
    report = {'status':'FAIL', 'simulator':args.simulator, 'physical_capacity_qualified':False,
              'hardware_accessed':False, 'vivado_executed':False,
              'scope':'Bounded AXI/control models only; no real MIG, PHY, full-span or physical qualification',
              'source_hashes_before':before, 'commands':commands, 'tool_versions':versions}
    def interrupted(signum, frame):
        raise InterruptedError('Capacity simulation interrupted by signal ' + str(signum))
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        tools = {}
        for tool in (('iverilog','vvp') if args.simulator=='iverilog' else ('verilator',)):
            executable = shutil.which(tool)
            if executable is None:
                raise RuntimeError('UNAVAILABLE: required tool ' + tool)
            tools[tool] = executable
            version = run_command(output, tool+'_version', [executable, '--version' if tool=='verilator' else '-V'])
            commands.append(version)
            if version['returncode'] != 0:
                raise RuntimeError(tool+' version query failed')
            versions[tool] = {'path':executable, 'sha256':sha(executable),
                             'stdout':Path(version['stdout_path']).read_text(),
                             'stderr':Path(version['stderr_path']).read_text()}
        golden = output/'nonzero-public-goldens.txt'
        with golden.open('x') as stream:
            for seed in (0,0x3588c350,0xffffffff):
                plan = CapacityPlan(base=0x1000,size=256,seed=seed)
                for address in (0x1000,0x1040,0x10c0):
                    for trial in (0,1):
                        data = plan.pattern(address,trial)
                        stream.write(f'{address:08x} {seed:08x} {trial} {int.from_bytes(data,"little"):0128x}\n')
        report['golden_fixture'] = {'path':str(golden),'sha256':sha(golden),'rows':18,
                                    'scope':'Simulation expectations from the software oracle only'}
        for label, top, base, span, faults in CASES:
            if args.simulator=='iverilog':
                image = output / (label+'.vvp')
                compile_argv = [tools['iverilog'],'-g2012','-Wall','-s',top,
                    f"-P{top}.BASE_ADDR=31'd{base}",f"-P{top}.SPAN_BYTES=32'd{span}",
                    f'-P{top}.TIMEOUT_CYCLES=32','-o',str(image)]
                execute = [tools['vvp'],str(image)]
            else:
                objects = output / (label+'-obj')
                compile_argv = [tools['verilator'],'--binary','--timing','--assert','--Wall',
                    '--top-module',top,'-j','2','--Mdir',str(objects),
                    f"-GBASE_ADDR=31'd{base}",f"-GSPAN_BYTES=32'd{span}",'-GTIMEOUT_CYCLES=32']
                execute = [str(objects/('V'+top))]
            compile_argv += [str(path) for path in SOURCES + BENCHES]
            command = run_command(output,label+'_compile',compile_argv)
            commands.append(command)
            if command['returncode'] != 0:
                raise RuntimeError(label+' compilation failed')
            if faults:
                execute.append('+FAULTS')
            execute.append('+GOLDENS='+str(golden))
            command = run_command(output,label+'_run',execute)
            commands.append(command)
            lines = Path(command['stdout_path']).read_text().splitlines()
            prefix = 'PASS_JOINED_BIST' if top=='tb_capacity_bist_joined' else 'PASS_AXI_INTEGRATED'
            marker = f'{prefix} span={span} base={base:08x} '
            if command['returncode'] != 0 or sum(line.startswith(marker) for line in lines) != 1:
                raise RuntimeError(label+' failed or lacks its exact completion marker')
            if faults and lines.count('PASS_AXI_FAULT_DIRECTED') != 1:
                raise RuntimeError(label+' lacks directed fault completion')
            if lines.count('PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py') != 1:
                raise RuntimeError(label+' lacks independent software-pattern check')
        report['status'] = 'PASS_BOUNDED_CAPACITY_MODEL_SIMULATION_ONLY'
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        after = {str(path.relative_to(ROOT)):sha(path) for path in paths}
        report['source_hashes_after'] = after
        if before != after:
            report['status'] = 'FAIL'
            report['source_change_detected'] = True
        with (output/'report.json').open('x') as stream:
            json.dump(report,stream,indent=2,sort_keys=True)
            stream.write('\n')
    print(json.dumps({'status':report['status'],'report':str(output/'report.json'),
                      'error':report.get('error')},sort_keys=True))
    return 0 if report['status'].startswith('PASS_') else 1

if __name__ == '__main__':
    raise SystemExit(main())
