#!/usr/bin/env python3
"""Diagnose actual synthesized C32 kernels with the unchanged full corpus.

The board DCP specializes masks and merges equal output bits across boundaries.
Its current subcell exports do not preserve the standalone interface, so this
diagnostic fails on those exports and supplies no component qualification.
Do not mask the mismatch or alter golden values to admit it. Use a closed
integrated netlist or independently preserved interface for qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.evidence import timestamp


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


BENCH = r'''`timescale 1ns/1ps
module tb_mapped_kernel;
    localparam integer BITS=512+8192+32+512+704;
    reg clk=0,capture=0;
    always #5 clk=~clk;
    // Drive the first binary payload after GSR, ensuring vendor procedural
    // combinational models see an input event, even for an all-zero frame.
    reg [511:0] data='x,weight='x;
    reg [31:0] data_mask='x,weight_mask='x;
    wire [43:0] result;
    wire invalid;
    reg [BITS-1:0] vectors[0:207];
    reg [8191:0] all_weights;
    reg [511:0] all_weight_masks;
    reg [703:0] all_expected;
    reg [43:0] expected;
    integer kernel,checked=0,held=0,burst=0;
    string path;
    mapped_kernel dut(.*);
    task automatic tick; @(posedge clk); #1; endtask
    task automatic present(input integer frame);
        {data,all_weights,data_mask,all_weight_masks,all_expected}=vectors[frame];
        weight=all_weights[kernel*512+:512];
        weight_mask=all_weight_masks[kernel*32+:32];
        expected=all_expected[kernel*44+:44];
    endtask
    initial begin
        if(!$value$plusargs("KERNEL=%d",kernel)||kernel<0||kernel>=16||
           !$value$plusargs("VECTORS=%s",path)) $fatal(1,"missing component input");
        $readmemh(path,vectors,0,207);
        wait(glbl.GSR===1'b0); tick();
        if(result!==44'd0||invalid!==1'b0) $fatal(1,"mapped payload INIT");
        for(integer i=0;i<208;i=i+1) begin
            @(negedge clk);present(i);capture=1;tick();
            if((^result)===1'bx||invalid===1'bx)
                $fatal(1,"mapped kernel unknown result frame=%0d kernel=%0d",i,kernel);
            if(result!==expected||invalid!==1'b0)
                $fatal(1,"mapped kernel mismatch frame=%0d kernel=%0d got=%h expected=%h invalid=%b",i,kernel,result,expected,invalid);
            checked=checked+1;
            @(negedge clk);capture=0;data='1;weight='1;data_mask='1;weight_mask='1;
            repeat(i%4+1) begin
                tick();held=held+1;
                if(result!==expected||invalid!==1'b0) $fatal(1,"uncaptured inputs changed mapped payload");
            end
        end
        // Two consecutive accepted payloads exercise capture with no bubble.
        @(negedge clk);present(2);capture=1;tick();
        if(result!==expected||invalid!==1'b0) $fatal(1,"first burst payload");
        burst=burst+1;
        @(negedge clk);present(5);tick();
        if(result!==expected||invalid!==1'b0) $fatal(1,"second burst payload");
        burst=burst+1;
        @(negedge clk);capture=0;
        if(checked!=208||held!=520||burst!=2) $fatal(1,"incomplete component corpus");
        $display("PASS actual_mapped_kernel kernel=%0d channels=32 products=32 frames=208 checked=208 held=520 burst=2",kernel);
        $finish;
    end
    initial begin #1000000;$fatal(1,"mapped component timeout");end
endmodule
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--export', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    export, out = args.export.resolve(), args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh build output required')
    census = (export/'census.tsv').read_text().splitlines()
    entries = [line.split('\t') for line in census]
    require(len(entries) == 16 and {int(e[0]) for e in entries} == set(range(16)) and
            all(len(e) == 3 and e[2] == '32' for e in entries), 'Incomplete physical kernel census')
    context = json.loads((export/'context.json').read_text())
    require(sha(context['dcp']) == context['dcp_sha256'] ==
            'c3d735a6d18ef8b7ccd062542c2d68fecc09638d8d6352ab3966ba26cf498ad8',
            'Wrong original synthesized checkpoint')
    vectors = ROOT/'build/rknpu-cmac-array/c32k16/vectors.hex'
    oracle = json.loads(vectors.with_name('vectors_report.json').read_text())
    require(oracle['seed'] == '0x35883216' and oracle['frames'] == 208 and
            oracle['outputs'] == 3328 and
            oracle['artifacts']['files'][str(vectors.relative_to(ROOT))] == sha(vectors),
            'Changed original full512 oracle')
    out.mkdir(parents=True)
    bench = out/'tb_mapped_kernel.sv'
    bench.write_text(BENCH)
    fixed = [Path(__file__), bench, vectors, vectors.with_name('vectors_report.json'),
             export/'context.json', export/'census.tsv', export/'export.tcl']
    report = dict(status='RUNNING_ACTUAL_MAPPED_KERNEL_COMPONENTS', started_utc=timestamp(),
        scope='All16 actual mapped C32 kernel components; not monolithic array/board, SDF, reset protocol or FPGA proof',
        channels=32, kernels=16, parallel_products=512, source_dcp_sha256=context['dcp_sha256'],
        inputs={str(p): sha(p) for p in fixed}, commands=[], results=[], hardware_accessed=False)

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def execute(name, argv, inputs, limit):
        require(all(sha(p) == h for p, h in inputs.items()), 'Component input changed')
        entry = dict(name=name, argv=list(map(str, argv)), started_utc=timestamp(), status='RUNNING')
        report['commands'].append(entry)
        child = None
        begin = time.monotonic()
        save()
        try:
            with (out/(name+'.log')).open('w') as log:
                old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
                try:
                    child = subprocess.Popen(entry['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True, preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, old))
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old)
                entry['pid'] = child.pid
                save()
                code = child.wait(timeout=limit)
            require(all(sha(p) == h for p, h in inputs.items()), 'Component input changed during command')
            entry.update(returncode=code, status='FINISHED')
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
        raise InterruptedError('Mapped component replay interrupted '+str(sig))

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupt)
    resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    nets = {str(export/f'kernel_{k}.v'): sha(export/f'kernel_{k}.v') for k in range(16)}
    report['netlists'] = nets
    try:
        for tool in ('iverilog', 'vvp'):
            code, text = execute(tool+'_version', [tool, '-V'], report['inputs'], 30)
            require(code == 0, 'Missing mapped component tool')
            report[tool+'_version'] = text.splitlines()[0]
            report['commands'][-1]['status'] = 'PASS'
        rows = vectors.read_text().splitlines()
        require(len(rows) == 208, 'Wrong corpus size')
        for k in range(16):
            net = export/f'kernel_{k}.v'
            image = out/f'kernel_{k}.vvp'
            negative = out/f'negative_{k}.hex'
            changed = list(rows)
            changed[0] = format(int(rows[0], 16) ^ (1 << (44*k)), '0'+str(len(rows[0]))+'x')
            negative.write_text('\n'.join(changed)+'\n')
            inputs = {**report['inputs'], str(net): nets[str(net)], str(negative): sha(negative)}
            code, text = execute(f'compile_{k}', ['iverilog', '-g2012', '-Ttyp', '-s', 'tb_mapped_kernel',
                '-s', 'glbl', '-o', image, net, bench], inputs, 600)
            require(code == 0 and not re.search(r'(?mi)warning:|error:|sorry:', text), 'Mapped component compile failed')
            report['commands'][-1]['status'] = 'PASS'
            inputs[str(image)] = sha(image)
            for label, selected in [('negative', negative), ('actual', vectors)]:
                code, text = execute(f'{label}_{k}', ['vvp', image, '+KERNEL='+str(k),
                    '+VECTORS='+str(selected)], inputs, 1800)
                if label == 'negative':
                    require(code != 0 and f'mapped kernel mismatch frame=0 kernel={k} ' in text and
                            not re.search(r'(?m)^PASS ', text), 'Corrupted component oracle did not reject')
                else:
                    expected = f'PASS actual_mapped_kernel kernel={k} channels=32 products=32 frames=208 checked=208 held=520 burst=2'
                    require(code == 0 and [line for line in text.splitlines() if line.startswith('PASS ')] == [expected]
                            and not re.search(r'(?mi)FATAL:|ERROR:', text), 'Mapped component result differs')
                    report['results'].append(dict(kernel=k, status='PASS', result=expected, inputs=inputs))
                report['commands'][-1]['status'] = 'PASS'
                save()
        require(all(sha(p) == h for p, h in {**report['inputs'], **nets}.items()), 'Component sources changed')
        report.update(status='PASS_ALL16_DIAGNOSTIC_COMPARISONS_ONLY', finished_utc=timestamp(),
                      checked_corpus_outputs=3328, held_checks=8320, additional_burst_outputs=32)
    except BaseException as error:
        report.update(status='FAIL', error=str(error), finished_utc=timestamp())
        raise
    finally:
        save()
    print(out/'report.json')


if __name__ == '__main__':
    main()
