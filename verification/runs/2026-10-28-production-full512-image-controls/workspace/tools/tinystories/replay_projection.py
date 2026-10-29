#!/usr/bin/env python3
"""Replay a trained TinyStories tile on the frozen full512 pipeline in Icarus.

Uses the original raw-core bench, including memory stalls/ack/sentinel checks.
No RTL, warning policy, expected data, timing constraint or FPGA image changes.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--package', type=Path, default=ROOT/'build/full512-regmem-preparation/1793013000')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    fixture, package, out = args.fixture.resolve(), args.package.resolve(), args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Use a fresh build directory')
    parent = json.loads((package/'report.json').read_text())
    vector = json.loads((fixture/'report.json').read_text())
    require(parent['status'] == 'PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY' and
            parent['parallel_products'] == 512, 'Require the complete qualified full512 source')
    require(vector['status'] == 'PREPARED_FIRST_TINYSTORIES_RAW_PROJECTION_AND_COMPACTION_COMMANDS', 'Wrong fixture')
    require(vector['fixture'] | {'commands_sha256': None} ==
            dict(rows=1, ai=64, ao=32, frames=4, reads=2176, writes=32, commands_sha256=None), 'Unexpected first tile')
    inputs = {str(package/'source'/name): value for name, value in parent['source']['files'].items()}
    inputs.update({str(fixture/name): value['sha256'] for name, value in vector['files'].items()})
    bench = ROOT/'tests/cmac/tb_cmac_array_core.sv'
    for path in (bench, package/'report.json', fixture/'report.json', Path(__file__).resolve()):
        inputs[str(path)] = digest(path)
    def check_inputs():
        require(all(digest(path) == value for path, value in inputs.items()), 'Source/fixture changed')
    check_inputs()
    names = [n for n in parent['synthesis_sources'] if n.endswith(('.sv', '.v'))]
    names += ['rtl/vendor/nvdla/compat/nv_assert_never.v', 'rtl/vendor/nvdla/compat/nv_assert_no_x.v']
    require(len(names) == len(set(names)), 'Duplicate source modules')
    out.mkdir(parents=True)
    report = dict(status='RUNNING', inputs=inputs, channels=32, kernels=16, products=512,
                  seed='0x3588ac16', commands=[], tests=[],
                  scope='Trained BOS Wq0 tile on frozen full512 RTL with modeled physical memory; not FPGA execution, whole projection/model, host compaction or RK equivalence',
                  hardware_accessed=False)
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def execute(name, argv, timeout=1200):
        check_inputs()
        log = out/(name+'.log')
        start = time.monotonic()
        with log.open('w') as stream:
            process = subprocess.run(argv, cwd=package/'source', stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=timeout, check=False)
        text = log.read_text()
        report['commands'].append(dict(name=name, argv=argv, returncode=process.returncode,
            seconds=time.monotonic()-start, log_sha256=digest(log)))
        save()
        require(process.returncode == 0, name+' failed')
        require(not re.search(r'(?mi)\b(?:warning|error):|sorry:|ERROR :', text), 'Unadmitted simulator diagnostic')
        check_inputs()
        return text
    save()
    try:
        compiler, runtime = shutil.which('iverilog'), shutil.which('vvp')
        require(compiler and runtime, 'Icarus/vvp unavailable')
        report['tool_version'] = execute('version', [compiler, '-V']).splitlines()[0]
        report['runtime_version'] = execute('runtime_version', [runtime, '-V']).splitlines()[0]
        binary = out/'sim.vvp'
        sources = [str(package/'source'/n) for n in names]+[str(bench)]
        execute('compile', [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
            '-I'+str(package/'source/rtl/vendor/nvdla'), '-s', 'tb_cmac_array_core', '-o', str(binary), *sources])
        hierarchy = {name: len(re.findall(r'\.scope module, "[^"]*" "'+name+r'"', binary.read_text()))
            for name in ('rk_cmac_fp16_array_dsp_prefix_pipe', 'rk_cmac_fp16_cell_dsp_prefix_pipe',
                         'rk_cmac_fp16_lane_dsp_prefix', 'rk_cmac_fp16_discarded_carry')}
        require(list(hierarchy.values()) == [1,16,512,512], 'Reduced full512 hierarchy')
        report['hierarchy'] = hierarchy
        image_sha = digest(binary)
        report['binary'] = dict(path=str(binary), sha256=image_sha)
        for mode in (0, 6, 7):
            text = execute('mode'+str(mode), [runtime, str(binary), '+DIRECTORY='+str(fixture/'fixture'),
                '+MODE='+str(mode), '+ROWS=1', '+AI=64', '+AO=32', '+READS=2176', '+WRITES=32'])
            marker = f'PASS raw C32 K16 core mode={mode} reads={2176 if mode in (0,6) else 0} writes={32 if mode in (0,6) else 0} acknowledgments={32 if mode in (0,6) else 0} jobs={1 if mode in (0,6) else 0} seed=3588ac16'
            require([line for line in text.splitlines() if line.startswith('PASS ')] == [marker], 'Changed result/coverage')
            require(digest(binary) == image_sha, 'Executed binary changed')
            report['tests'].append(dict(mode=mode, status='PASS', result=marker))
            save()
        report['status'] = 'PASS_FIRST_TRAINED_TINYSTORIES_TILE_FULL512_ICARUS_ONLY'
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    print(json.dumps(dict(status=report['status'], report=str(out/'report.json'))))


if __name__ == '__main__':
    main()
