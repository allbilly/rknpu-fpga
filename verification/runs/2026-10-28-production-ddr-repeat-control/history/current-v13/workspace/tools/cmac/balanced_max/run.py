#!/usr/bin/env python3
"""Native full512 qualification of the separate balanced-exponent candidate.

Uses the unchanged 208-frame corpus and stream assertions, plus a concurrent
original-prefix reference. No mapping, implementation or hardware acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.evidence import fingerprint, timestamp

CELL = 'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix_balanced_max.sv'
ARRAY = 'rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix_balanced_max.sv'
BENCH = 'tests/cmac/tb_cmac_fp16_array.sv'
SOURCES = [
    'rtl/vendor/nvdla/compat/nv_assert_never.v',
    'rtl/vendor/nvdla/compat/nv_assert_no_x.v',
    'rtl/vendor/nvdla/NV_DW02_tree.v',
    'rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'rtl/cmac/experimental/rk_cmac_fp16_rows.sv',
    'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv',
    'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv',
    'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv',
    'rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv', CELL, ARRAY]
DONOR = ROOT/'rtl/vendor/nvdla'
VECTOR_ROOT = ROOT/'build/rknpu-cmac-array/c32k16'

LINEAR_MAX = '''    always @* begin
        maximum=0;
        for(integer i=0;i<ATOMIC_C;i=i+1) if(exponent[i]>maximum) maximum=exponent[i];
    end'''
BALANCED_MAX = '''    // The supported C values are powers of two. Unsigned maximum is exact
    // and associative; balance only this selector, preserving donor arithmetic,
    // grouping, NaN priority and the array's original one-slot stream latency.
    wire [3:0] exponent_tree[1:2*ATOMIC_C-1];
    for(genvar leaf=0;leaf<ATOMIC_C;leaf=leaf+1)begin: exponent_leaves
        assign exponent_tree[ATOMIC_C+leaf]=exponent[leaf];
    end
    for(genvar node=1;node<ATOMIC_C;node=node+1)begin: exponent_nodes
        assign exponent_tree[node]=(exponent_tree[2*node]>exponent_tree[2*node+1])
            ? exponent_tree[2*node]:exponent_tree[2*node+1];
    end
    assign maximum=exponent_tree[1];'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_candidate_sources():
    original = (ROOT/'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv').read_text()
    require(original.count(LINEAR_MAX) == 1, 'Original selector changed')
    expected = '// Separate timing candidate: balanced exponent selector; no FPGA acceptance.\n'
    expected += original.replace('rk_cmac_fp16_cell_dsp_prefix',
        'rk_cmac_fp16_cell_dsp_prefix_balanced_max').replace(LINEAR_MAX, BALANCED_MAX)
    require((ROOT/CELL).read_text() == expected, 'Extra arithmetic or priority change')
    original = (ROOT/'rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv').read_text()
    expected = '// Separate timing candidate: all512 products retained; no FPGA acceptance.\n'
    expected += original.replace('rk_cmac_fp16_array_dsp_prefix',
        'rk_cmac_fp16_array_dsp_prefix_balanced_max').replace('rk_cmac_fp16_cell_dsp_prefix',
        'rk_cmac_fp16_cell_dsp_prefix_balanced_max')
    require((ROOT/ARRAY).read_text() == expected, 'Changed stream/geometry/reset/fault contract')


def admitted_compile_messages(text, simulator):
    """Retain Wall; admit only diagnosed Icarus information messages.

    Both original and candidate cells produce the array-sensitivity messages:
    they describe correct @* sensitivity, not omitted inputs. The unmodified
    combinational donor/assertion modules intentionally inherit their wrapper
    timescale. Other warning/error classes remain failures.
    """
    admitted = []
    for line in text.splitlines():
        if not re.search(r'(?i)(?:\bwarning:|\berror:|sorry:|^%Warning|^%Error)', line):
            continue
        sensitivity = re.fullmatch(
            re.escape(str(ROOT))+r'/rtl/cmac/experimental/'
            r'rk_cmac_fp16_cell_dsp_prefix(?:_balanced_max)?\.sv:[0-9]+: warning: '
            r"@\* is sensitive to all 32 words in array '(?:a|b|row_tag|lane_total|exponent)'\.", line)
        timescale = re.fullmatch(
            re.escape(str(DONOR))+r'/(?:nv_assert_never\.vlib|nv_assert_no_x\.vlib|'
            r'NV_DW02_tree\.v|NV_NVDLA_CMAC_CORE_MAC_mul\.v):[0-9]+: warning: timescale for '
            r'(?:nv_assert_never|nv_assert_no_x|NV_DW02_tree|NV_NVDLA_CMAC_CORE_MAC_mul|'
            r'NV_NVDLA_CMAC_CORE_MAC_booth) inherited from another file\.', line)
        verilator = False
        if simulator == 'verilator':
            match = re.fullmatch(r'%Warning-([A-Z0-9_]+): ([^:]+):[0-9]+:[0-9]+: (.*)', line)
            if match:
                kind, path, message = match.groups()
                verilator = (
                    kind == 'DECLFILENAME' and path == str(DONOR/'NV_NVDLA_CMAC_CORE_MAC_mul.v') and
                    message == "Filename 'NV_NVDLA_CMAC_CORE_MAC_mul' does not match MODULE name: 'NV_NVDLA_CMAC_CORE_MAC_booth'"
                ) or (
                    kind == 'PINCONNECTEMPTY' and
                    path == str(ROOT/'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv') and
                    message in ("Instance pin connected by name with empty reference: 'res_b'",
                                "Instance pin connected by name with empty reference: 'res_tag'")
                ) or (
                    kind == 'UNUSEDSIGNAL' and
                    path == str(ROOT/'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv') and
                    message in ("Bits of signal are not used: 'first_row'[31:28]",
                                "Bits of signal are not used: 'total'[31:28]")
                )
        require((simulator == 'iverilog' and (sensitivity or timescale)) or verilator,
                'Unadmitted compile diagnostic: '+line)
        admitted.append(line)
    return admitted


def bench_text():
    text = (ROOT/BENCH).read_text()
    old = 'rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);'
    require(text.count(old) == 1, 'Changed original bench instantiation')
    extra = '''rk_cmac_fp16_array_dsp_prefix_balanced_max #(
        .ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);
    wire reference_ready,reference_valid,reference_error;
    wire [ATOMIC_K*44-1:0] reference_groups;
    wire [34:0] reference_tag;
    rk_cmac_fp16_array_dsp_prefix #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) reference_dut(
        .clk,.rst_n,.in_valid,.in_ready(reference_ready),.in_data,.in_weight,
        .in_data_mask,.in_weight_mask,.in_tag,.out_valid(reference_valid),
        .out_ready,.out_groups(reference_groups),.out_tag(reference_tag),.error(reference_error));
    always @(negedge clk)begin
        // Observe both designs after reset/ready delta cycles have settled.
        #1;
        if({in_ready,out_valid,error}!=={reference_ready,reference_valid,reference_error})
            $fatal(1,"balanced maximum changed stream control");
        if(out_valid&&({out_groups,out_tag}!=={reference_groups,reference_tag}))
            $fatal(1,"balanced maximum differs from original prefix array");
    end'''
    text = text.replace(old, extra)
    boundary = '        end\n`ifndef VERILATOR'
    require(text.count(boundary) == 1, 'Changed original corpus loop boundary')
    return text.replace(boundary, '''            if(i==0||(i+1)%16==0)begin
                $display("PROGRESS balanced_max_frames=%0d",i+1);
                $fflush();
            end
        end
`ifndef VERILATOR''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run-timeout', type=int, default=1800)
    args = parser.parse_args()
    require(1 <= args.run_timeout <= 3600, 'Native run deadline must be 1..3600 seconds')
    validate_candidate_sources()
    out = args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh build output required')
    vectors = VECTOR_ROOT/'vectors.hex'
    vector_report = VECTOR_ROOT/'vectors_report.json'
    vr = json.loads(vector_report.read_text())
    require(vr['status'] == 'PASS_SIZED_CMAC_VECTOR_GENERATION' and
            (vr['channels'], vr['kernels'], vr['frames'], vr['outputs']) == (32, 16, 208, 3328) and
            vr['seed'] == '0x35883216', 'Wrong original oracle corpus')
    require(vr['artifacts']['files'][str(vectors.relative_to(ROOT))] == digest(vectors),
            'Changed original numerical vectors')
    rows = vectors.read_text().splitlines()
    require(len(rows) == 208 and all(re.fullmatch('[0-9a-fA-F]+', row) for row in rows),
            'Malformed oracle corpus')
    out.mkdir(parents=True)
    bench = out/'tb_cmac_fp16_array.sv'
    bench.write_text(bench_text())
    # Corrupt only the expected result of frame zero, retaining every operand.
    corrupted = rows.copy()
    corrupted[0] = format(int(corrupted[0], 16)^1, '0'+str(len(corrupted[0]))+'x')
    negative = out/'negative_vectors.hex'
    negative.write_text('\n'.join(corrupted)+'\n')
    tracked = [ROOT/name for name in SOURCES+[BENCH]] + [Path(__file__),
        ROOT/'tools/evidence.py', vectors, vector_report, bench, negative]
    tracked += [DONOR/name for name in ('assertion_header.h', 'assertion_task.h',
        'nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'LICENSE')]
    before = fingerprint(tracked)
    report = dict(status='RUNNING', started_utc=timestamp(), simulator=args.simulator,
        scope='Separate full C32/K16 balanced maximum candidate; unchanged numerical/stream assertions and original-prefix reference; native only',
        source=before, channels=32, kernels=16, candidate_parallel_products=512,
        reference_parallel_products=512, frames=208, compared_candidate_outputs=3328,
        seed=vr['seed'], commands=[], mapping_verified=False, physical_fit_verified=False,
        vivado_executed=False, hardware_programmed=False)

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def run(name, argv, timeout, expected='zero'):
        require(fingerprint(tracked) == before, 'Source or stimulus changed')
        entry = dict(name=name, argv=list(map(str, argv)), started_utc=timestamp(), status='RUNNING')
        report['commands'].append(entry)
        save()
        started = time.monotonic()
        child = None
        try:
            with (out/(name+'.log')).open('w') as log:
                child = subprocess.Popen(entry['argv'], cwd=ROOT, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                entry['pid'] = child.pid
                save()
                code = child.wait(timeout=timeout)
            text = (out/(name+'.log')).read_text()
            entry['returncode'] = code
            if expected == 'negative':
                require(code != 0 and 'sized array mismatch frame=0' in text and
                        not re.search(r'(?m)^PASS ', text), 'Corrupted oracle did not reject')
            else:
                require(code == 0, 'Native command failed')
                if expected == 'actual':
                    faults = 1 if args.simulator == 'iverilog' else 0
                    marker = ('PASS sized FP16 CMAC C=32 K=16 frames=208 checked_outputs=3328 '
                              f'retired_outputs=3312 reset_canceled=16 held_cycles=520 faults={faults}')
                    require([s for s in text.splitlines() if s.startswith('PASS ')] == [marker]
                            and not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)', text),
                            'Changed numerical/stream result')
                    report['result'] = marker
            if name == 'compile':
                entry['admitted_information_messages'] = admitted_compile_messages(text, args.simulator)
            require(fingerprint(tracked) == before, 'Source changed during native command')
            entry['status'] = 'PASS'
            return text
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
            entry.update(finished_utc=timestamp(), seconds=time.monotonic()-started)
            log = out/(name+'.log')
            if log.exists():
                entry['log_sha256'] = digest(log)
            save()

    def stop(signum, frame):
        raise InterruptedError('Qualification interrupted by signal '+str(signum))

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        compiler = shutil.which(args.simulator)
        require(compiler, 'Simulator unavailable')
        report['tool_version'] = run('simulator_version', [compiler,
            '-V' if args.simulator == 'iverilog' else '--version'], 30).splitlines()[0]
        common = ['-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-I'+str(DONOR)]
        files = [str(ROOT/name) for name in SOURCES]+[str(bench)]
        if args.simulator == 'iverilog':
            image = out/'sim.vvp'
            command = [compiler, '-g2012', '-Wall', *common, '-s', 'tb_cmac_fp16_array',
                '-Ptb_cmac_fp16_array.ATOMIC_C=32', '-Ptb_cmac_fp16_array.ATOMIC_K=16',
                '-o', str(image), *files]
            runtime = shutil.which('vvp')
            require(runtime, 'vvp unavailable')
            report['runtime_version'] = run('runtime_version', [runtime, '-V'], 30).splitlines()[0]
            launch = [runtime, str(image)]
        else:
            image = out/'obj/sim'
            # Keep every diagnostic visible; admit only the reviewed source/
            # message pairs above. No blanket warning-class suppression.
            command = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal', *common,
                '--top-module', 'tb_cmac_fp16_array', '-j', '1', '--Mdir', str(out/'obj'),
                '-o', 'sim', *files]
            launch = [str(image)]
        run('compile', command, 1200)
        image_hash = digest(image)
        report['compiled_image'] = dict(path=str(image), sha256=image_hash)
        for name, stimulus in [('negative', negative), ('actual', vectors)]:
            run(name, launch+['+VECTORS='+str(stimulus), '+COUNT=208'], args.run_timeout, name)
            require(digest(image) == image_hash, 'Compiled image changed')
        report.update(status='PASS_FULL512_BALANCED_MAX_NATIVE_ONLY', finished_utc=timestamp())
        validate_candidate_sources()
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=str(error))
        raise
    finally:
        report['artifacts'] = fingerprint([p for p in out.iterdir() if p.is_file() and p.name != 'report.json'])
        save()
    print(out/'report.json')


if __name__ == '__main__':
    main()
