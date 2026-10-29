#!/usr/bin/env python3
"""Prove smaller simulation-only LUT bodies against the actual AMD models.

Only LUT4/5/6 behavioral bodies change in a derived simulation file. All gate
instances, INITs, clocks, DSP/RAM/FF models and FPGA sources remain byte-identical.
Every configured binary INIT is tested with every 0/1/X/Z input combination,
including initialization before the first input event. No hardware is invoked.
"""
from pathlib import Path
import argparse
from collections import Counter
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.evidence import timestamp

NET_SHA = '91d13f62ee3f9260d8c99f831ca1ccb239fc60f9c6dabd9c918f4728c7d6768b'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def select_expression(n, offset=0):
    if n == 0:
        return f'INIT_REG[{offset}]'
    return (f'(I{n-1} ? {select_expression(n-1, offset+(1 << (n-1)))} : '
            f'{select_expression(n-1, offset)})')


def derive(text):
    require('`define XIL_TIMING' not in text and '`define XIL_DR' not in text,
            'This proof admits the default functional, static-INIT profile only')
    inventory = {}
    originals, smaller = {}, {}
    transformed = text
    for n in (4, 5, 6):
        matches = list(re.finditer(r'(?ms)^module LUT'+str(n)+r' #\(.*?^endmodule', text))
        require(len(matches) == 1, 'Expected one original AMD LUT model')
        original = matches[0].group()
        before, body = original.split('// begin behavioral model', 1)
        _, after = body.split('// end behavioral model', 1)
        require('reg O_out;' in body and 'assign O = O_out;' in body and
                ('always @('+' or '.join(f'I{i}' for i in range(n))+')') in body,
                'Changed AMD LUT event/output structure')
        replacement = ('// begin behavioral model\n  reg O_out;\n  assign O = O_out;\n'
            '  always @('+' or '.join(f'I{i}' for i in range(n))+') begin\n'
            '    O_out = '+select_expression(n)+';\n  end\n// end behavioral model')
        fast = before+replacement+after
        require(transformed.count(original) == 1, 'Ambiguous primitive body replacement')
        transformed = transformed.replace(original, fast)
        originals[n], smaller[n] = original, fast
        # All used LUT parameters must be static binary hexadecimal INITs.
        prefixes = re.findall(r'(?m)^\s+LUT'+str(n)+r' #\(', text)
        cases = re.findall(r'(?m)^\s+LUT'+str(n)+r' #\(\s*\.INIT\((\d+)\x27h([0-9a-fA-F_]+)\)\)\s+', text)
        require(len(cases) == len(prefixes) and cases, 'Unmodeled/nonbinary LUT parameter form')
        require(all(int(width) == 1 << n and int(value.replace('_', ''), 16) < (1 << (1 << n))
                    for width, value in cases), 'LUT INIT width/value changed')
        inventory[n] = sorted({int(value.replace('_', ''), 16) for _, value in cases})
    return transformed, originals, smaller, inventory


def proof_bench(inventory):
    cases = [(n, value) for n, values in sorted(inventory.items()) for value in values]
    count = len(cases)
    lines = ['`timescale 1ns/1ps', 'module tb_lut;', 'reg [5:0] inputs;',
             f'wire [{count-1}:0] original, smaller;', f'integer widths[0:{count-1}];',
             'integer pattern, comparisons=0, corrupt=0;', 'reg observed;']
    for index, (n, value) in enumerate(cases):
        pins = ','.join(f'.I{i}(inputs[{i}])' for i in range(n))
        for model, bus in [('LUT', 'original'), ('FAST_LUT', 'smaller')]:
            lines.append(f'{model}{n} #(.INIT({1<<n}\'h{value:x})) {bus}_{index}(.O({bus}[{index}]),{pins});')
    lines += ['initial begin', 'inputs=6\'bxxxxxx;',
              'if($value$plusargs("CORRUPT=%d",corrupt))begin end',
              'if(corrupt!=0&&corrupt!=1)$fatal(1,"invalid proof control");']
    lines += [f'widths[{index}]={n};' for index, (n, _) in enumerate(cases)]
    lines += ['#1;', 'if(original!==smaller)$fatal(1,"initial event behavior differs");',
        'for(pattern=0;pattern<4096;pattern=pattern+1)begin',
        'for(integer bit_index=0;bit_index<6;bit_index=bit_index+1)begin',
        'case((pattern>>(bit_index*2))&3)',
        '0:inputs[bit_index]=0;1:inputs[bit_index]=1;2:inputs[bit_index]=1\'bx;3:inputs[bit_index]=1\'bz;',
        'endcase end', '#1;', f'for(integer index=0;index<{count};index=index+1)begin',
        'if(pattern<(1<<(2*widths[index])))begin',
        'observed=smaller[index];', 'if(corrupt&&index==0)observed=~observed;',
        'if(original[index]!==observed)$fatal(1,"fast LUT mismatch case=%0d pattern=%0d original=%b smaller=%b",index,pattern,original[index],observed);',
        'comparisons=comparisons+1;', 'end end end']
    total = sum(len(values)*4**n for n, values in inventory.items())
    lines += [f'if(comparisons!={total})$fatal(1,"incomplete four-state coverage");',
        f'$display("PASS exact_configured_LUT_4state configs={count} comparisons={total} initial_event=1");',
        '$finish;end', 'initial begin #10000;$fatal(1,"LUT proof timeout");end', 'endmodule']
    return '\n'.join(lines)+'\n', total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--netlist', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    net, out = args.netlist.resolve(), args.out.resolve()
    require(sha(net) == NET_SHA, 'Wrong exact closed full512 netlist')
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh proof directory required')
    text = net.read_text()
    transformed, originals, smaller, inventory = derive(text)
    out.mkdir(parents=True)
    (out/'closed_fast_lut.v').write_text(transformed)
    (out/'original_lut_models.v').write_text('`timescale 1ps/1ps\n'+'\n'.join(originals.values())+'\n')
    (out/'fast_lut_models.v').write_text('`timescale 1ps/1ps\n'+'\n'.join(
        model.replace('module LUT'+str(n)+' #(', 'module FAST_LUT'+str(n)+' #(')
        for n, model in smaller.items())+'\n')
    bench, total = proof_bench(inventory)
    (out/'tb_lut.sv').write_text(bench)
    (out/'inventory.json').write_text(json.dumps({str(n): [f'{v:x}' for v in vs] for n, vs in inventory.items()}, indent=2)+'\n')
    inputs = {str(path): sha(path) for path in [net, Path(__file__), out/'original_lut_models.v',
        out/'fast_lut_models.v', out/'tb_lut.sv', out/'inventory.json', out/'closed_fast_lut.v']}
    report = dict(status='RUNNING_CONFIGURED_LUT_4STATE_PROOF', started_utc=timestamp(),
        scope=__doc__, original_netlist=str(net), original_netlist_sha256=NET_SHA,
        derived_netlist=str(out/'closed_fast_lut.v'), derived_netlist_sha256=sha(out/'closed_fast_lut.v'),
        inputs=inputs, configurations={str(n): len(vs) for n, vs in inventory.items()},
        comparisons=total, commands=[], hardware_accessed=False, image_admission=False)

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def execute(name, argv, limit):
        require(all(sha(p) == expected for p, expected in inputs.items()), 'LUT proof input changed')
        entry = dict(name=name, argv=list(map(str, argv)), status='RUNNING', started_utc=timestamp())
        report['commands'].append(entry)
        child = None
        begin = time.monotonic()
        save()
        try:
            with (out/(name+'.log')).open('w') as log:
                old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
                try:
                    child = subprocess.Popen(entry['argv'], cwd=out, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True, preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, old))
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old)
                entry['pid'] = child.pid
                save()
                code = child.wait(timeout=limit)
            entry.update(returncode=code, status='FINISHED')
            require(all(sha(p) == expected for p, expected in inputs.items()), 'Proof input changed during execution')
            return code, (out/(name+'.log')).read_text()
        except BaseException as error:
            entry.update(status='FAIL', error=str(error))
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise
        finally:
            entry.update(seconds=time.monotonic()-begin, finished_utc=timestamp())
            entry['log_sha256'] = sha(out/(name+'.log'))
            save()

    def interrupt(sig, frame):
        raise InterruptedError('LUT proof interrupted '+str(sig))

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupt)
    resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        for tool in ('iverilog', 'vvp'):
            code, output = execute(tool+'_version', [tool, '-V'], 30)
            require(code == 0, 'LUT proof tool unavailable')
            report[tool+'_version'] = output.splitlines()[0]
            report['commands'][-1]['status'] = 'PASS'
        image = out/'proof.vvp'
        code, output = execute('compile', ['iverilog', '-g2012', '-Ttyp', '-s', 'tb_lut', '-o', image,
            out/'original_lut_models.v', out/'fast_lut_models.v', out/'tb_lut.sv'], 300)
        require(code == 0 and not re.search(r'(?mi)warning:|error:|sorry:', output), 'LUT proof compilation failed')
        report['commands'][-1]['status'] = 'PASS'
        inputs[str(image)] = sha(image)
        report['compiled_image'] = dict(path=str(image), sha256=sha(image))
        for label, corrupt in [('wrong_output_control', 1), ('actual', 0)]:
            code, output = execute(label, ['vvp', image, '+CORRUPT='+str(corrupt)], 900)
            if corrupt:
                require(code != 0 and 'fast LUT mismatch case=0 pattern=0' in output and
                        not re.search(r'(?m)^PASS ', output), 'Wrong LUT output control did not reject')
            else:
                expected = f'PASS exact_configured_LUT_4state configs={sum(len(vs) for vs in inventory.values())} comparisons={total} initial_event=1'
                require(code == 0 and [line for line in output.splitlines() if line.startswith('PASS ')] == [expected]
                        and not re.search(r'(?mi)FATAL:|ERROR:', output), 'Configured LUT four-state proof failed')
                report['result'] = expected
            report['commands'][-1]['status'] = 'PASS'
            save()
        require(derive(net.read_text())[0] == (out/'closed_fast_lut.v').read_text(), 'Derived netlist changed beyond LUT bodies')
        report.update(status='PASS_ALL_CONFIGURED_LUTS_EXHAUSTIVE_4STATE', finished_utc=timestamp())
    except BaseException as error:
        report.update(status='FAIL', error=str(error), finished_utc=timestamp())
        if report['commands'] and report['commands'][-1]['status'] == 'FINISHED':
            report['commands'][-1].update(status='FAIL', error=str(error))
        raise
    finally:
        report['artifacts'] = {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name != 'report.json'}
        save()
    print(out/'report.json')


if __name__ == '__main__':
    main()
