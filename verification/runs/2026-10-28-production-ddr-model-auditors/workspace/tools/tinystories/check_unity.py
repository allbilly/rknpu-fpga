#!/usr/bin/env python3
"""Prove finite FP16 MUL-unity bit preservation in the unchanged ALU RTL.

Uses the existing backpressure/unknown-sensitive ALU bench in both simulators.
This is a prerequisite for hardware output compaction, not a gather engine,
DMA/board result, general NaN policy or RK numerical equivalence proof.
"""
from pathlib import Path
import datetime
import hashlib
import json
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT/'build/tinystories-unity'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    sources = [ROOT/'rtl/rk_fp16_alu.sv', ROOT/'tests/tb_fp16.sv', Path(__file__).resolve()]
    before = {str(p): digest(p) for p in sources}
    report = dict(status='RUNNING', source_hashes=before, seed='0x12345678',
                  scope='Finite ALU identity under RTL backpressure only; not full compaction/DMA/FPGA/RK acceptance',
                  hardware_accessed=False, commands=[])
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def execute(name, argv, expected_failure=False, timeout=180):
        log = out/(name+'.log')
        started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        text = log.read_text()
        command = dict(name=name, argv=argv, returncode=result.returncode,
                       seconds=time.monotonic()-started, log=str(log), log_sha256=digest(log),
                       expected_failure=expected_failure)
        report['commands'].append(command)
        save()
        if expected_failure:
            if result.returncode == 0 or 'ALU vector 0' not in text or 'expected 0000' not in text:
                raise RuntimeError('Signed-zero mismatch control did not fail at the intended comparison')
        elif result.returncode != 0:
            raise RuntimeError(name+' failed: '+str(log))
        return text
    save()
    try:
        compilers = {n: shutil.which(n) for n in ('iverilog', 'vvp', 'verilator')}
        if not all(compilers.values()):
            raise FileNotFoundError('Both Icarus/vvp and Verilator are required')
        report['versions'] = {n: execute(n+'_version', [p, '-V' if n in ('iverilog','vvp') else '--version'])
                              for n, p in compilers.items()}
        finite = [x for x in range(65536) if x & 0x7c00 != 0x7c00]
        if len(finite) != 63488:
            raise RuntimeError('Incomplete finite word inventory')
        vectors = []
        for side in ('right', 'left'):
            path = out/('unity_'+side+'.hex')
            rows = []
            for value in finite:
                a, b = (value, 0x3c00) if side == 'right' else (0x3c00, value)
                rows.append(f'{(2<<48)|(a<<32)|(b<<16)|value:016x}\n')
            path.write_text(''.join(rows))
            vectors.append(path)
        negative = out/'wrong_zero_sign.hex'
        negative.write_text(f'{(2<<48)|(0x8000<<32)|(0x3c00<<16):016x}\n')
        images = {}
        for simulator in ('iverilog', 'verilator'):
            if simulator == 'iverilog':
                binary = out/'alu.vvp'
                argv = [compilers['iverilog'], '-g2012', '-Wall', '-s', 'tb_fp16', '-o', str(binary)]
                execute(simulator+'_compile', argv+[str(p) for p in sources[:2]])
                runtime = [compilers['vvp'], str(binary)]
            else:
                obj = out/'obj';obj.mkdir()
                argv = [compilers['verilator'], '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                        '--top-module', 'tb_fp16', '--Mdir', str(obj), '-o', 'sim']
                execute(simulator+'_compile', argv+[str(p) for p in sources[:2]], timeout=600)
                binary = obj/'sim';runtime = [str(binary)]
            images[simulator] = dict(path=str(binary), sha256=digest(binary))
            for vector in vectors:
                text = execute(simulator+'_'+vector.stem, runtime+[f'+VECTORS={vector}', '+COUNT=63488'])
                if sum(line.startswith('PASS ALU: 63488 vectors,') for line in text.splitlines()) != 1:
                    raise RuntimeError('Missing exact finite coverage marker')
            execute(simulator+'_wrong_zero_sign', runtime+[f'+VECTORS={negative}', '+COUNT=1'], expected_failure=True)
            if digest(binary) != images[simulator]['sha256']:
                raise RuntimeError('Compiled image changed during checks')
        after = {str(p): digest(p) for p in sources}
        if before != after:
            raise RuntimeError('Source changed during identity proof')
        report.update(status='PASS_FINITE_FP16_MUL_UNITY_RTL_IDENTITY_BOTH_SIMULATORS',
                      finite_words=63488, operand_orders=2, comparisons_per_simulator=126976,
                      negative_controls=2, images=images, sources_unchanged=True,
                      vector_hashes={str(p): digest(p) for p in vectors+[negative]})
    except BaseException as error:
        report.update(status='UNAVAILABLE' if isinstance(error, FileNotFoundError) else 'FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        (ROOT/'build/current-tinystories-unity.txt').write_text(str(out)+'\n')
    print(json.dumps(dict(status=report['status'], report=str(out/'report.json'))))


if __name__ == '__main__':
    main()
