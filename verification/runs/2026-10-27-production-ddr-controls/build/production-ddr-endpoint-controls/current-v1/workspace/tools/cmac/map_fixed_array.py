#!/usr/bin/env python3
"""Measure the full experimental C32/K16 fixed-mode array's XC7 primitives.

This is an area experiment, not numerical acceptance or physical fit. The
original raw-command array remains unchanged. All 512 partial-row helpers and
sixteen parallel kernels must survive elaboration and hierarchical mapping.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from xc7_primitive_counts import primitive_counts


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows-area-report', type=Path, required=True)
    args = parser.parse_args()
    parent = json.loads(args.rows_area_report.read_text())
    assert parent['status'] == 'PASS_FIXED_FP16_ROW_AREA_ONLY'
    verify(parent['source'])
    verify(parent['artifacts'])
    donor = ROOT / 'rtl/vendor/nvdla'
    experimental = ROOT / 'rtl/cmac/experimental'
    top = 'rk_cmac_fp16_array_fixed'
    cell_name = 'rk_cmac_fp16_cell_fixed'
    sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
               experimental / 'rk_cmac_fp16_rows.sv',
               experimental / (cell_name + '.sv'), experimental / (top + '.sv')]
    for path in sources[:3]:
        assert str(path.relative_to(ROOT)) in parent['source']['files']
    out = ROOT / f'build/rknpu-cmac-array/c32k16/fixed-area-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / 'rows_area_report_snapshot.json'
    snapshot.write_text(json.dumps(parent, indent=2) + '\n')
    tracked = sources + [Path(__file__).resolve(), ROOT / 'tools/cmac/xc7_primitive_counts.py', snapshot]
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
                  channels=32, kernels=16, intended_part='xc7k480tffg1156-2',
                  numerical_acceptance=False, physical_fit_verified=False,
                  scope='Experimental full-width fixed-mode area only. No numerical netlist, raw integration, packed utilization, physical timing/DRC, FPGA or RK acceptance.')
    for path in tracked:
        dest = out / 'snapshot' / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as log:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                      start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        raise
            text = (ROOT / step['log']).read_text()
            step['returncode'] = code
            assert code == 0 and 'ERROR:' not in text, text[-6000:]
            step['status'] = 'PASS'
            return text
        except Exception:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        help_text = run(['yosys', '-Q', '-T', '-p', 'help flatten; help synth_xilinx'], 'help')
        assert "'keep_hierarchy' attribute set will not be" in help_text
        coarse = re.search(r'\n    coarse:\n(.*?)\n    map_memory:', help_text, re.S)
        assert coarse, 'Unknown synth_xilinx stages'
        commands = [line.strip() for line in coarse.group(1).splitlines() if line.strip()]
        assert commands == ['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
                            'alumacc', 'share', 'opt', 'memory -nomap', 'opt_clean'], commands
        unshared = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in commands if line != 'share']
        report.update(original_coarse_stage=commands, executed_coarse_stage=unshared)
        hierarchy, partitioned, design, netlist = [out / name for name in
                                                  ('hierarchy.json', 'mapped_hierarchy.json', 'mapped.json', 'mapped.v')]
        text = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' + ' '.join(json.dumps(str(s)) for s in sources)
        text += f'; chparam -set ATOMIC_C 32 -set ATOMIC_K 16 {top}; hierarchy -check -top {top}'
        text += f'; select -assert-mod-count 1 A:hdlname={cell_name}'
        text += f'; setattr -mod -set keep_hierarchy 1 A:hdlname={cell_name}'
        text += '; select -assert-mod-count 1 A:keep_hierarchy=1'
        text += f'; select -assert-count 16 */t:*{cell_name}*'
        text += f'; proc; opt_clean; check -assert; write_json {json.dumps(str(hierarchy))}'
        flags = f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
        text += f'; synth_xilinx {flags} -run begin:map_dsp; ' + '; '.join(unshared)
        text += f'; synth_xilinx {flags} -run map_memory:; check -assert; write_json {json.dumps(str(partitioned))}'
        text += '; setattr -mod -unset keep_hierarchy; setattr -unset keep_hierarchy; flatten; check -assert'
        text += f'; write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}'
        script = out / 'mapping.ys'
        script.write_text(text.replace('; ', ';\n') + '\n')
        log = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert 'Executing SHARE pass' not in log
        modules = json.loads(hierarchy.read_text())['modules']

        def helpers(name):
            if name == 'rk_cmac_fp16_rows':
                return 1
            return sum(helpers(c['type']) for c in modules[name].get('cells', {}).values() if c['type'] in modules)

        assert helpers(top) == 512, 'Full RKNPU-sized product count changed'
        parts = json.loads(partitioned.read_text())['modules']
        kernel_types = [c['type'] for c in parts[top]['cells'].values() if cell_name in c['type']]
        assert len(kernel_types) == 16 and len(set(kernel_types)) == 1, kernel_types
        assert int(parts[kernel_types[0]]['attributes']['keep_hierarchy'], 2) == 1
        # The shared counter deliberately permits only the original cell's
        # hierarchy name. Count this explicitly checked experimental partition
        # and each top-shell primitive separately without broadening that gate.
        shell = dict(parts)
        shell[top] = dict(parts[top], cells={name: cell for name, cell in parts[top]['cells'].items()
                                          if cell['type'] not in set(kernel_types)})
        expected = primitive_counts(shell, top)
        for kind in kernel_types:
            expected.update(primitive_counts(parts, kind))
        mapped_modules = json.loads(design.read_text())['modules']
        mapped = mapped_modules[top]
        cells = Counter(c['type'] for c in mapped['cells'].values() if c['type'] != '$scopeinfo')
        assert cells == expected == primitive_counts(mapped_modules, top), 'Flattening changed mapped primitives'
        assert sum(n for t, n in cells.items() if t.startswith('FD')) >= 16 * 32 + 35
        assert sum(n for t, n in cells.items() if t.startswith('LUT')) > 0
        for name, width in [('in_ready', 1), ('out_valid', 1), ('out_groups', 16 * 44), ('out_tag', 35)]:
            bits = mapped['ports'][name]['bits']
            assert len(bits) == width and all(isinstance(bit, int) for bit in bits), (name, bits)
        assert fingerprint(tracked) == report['source'], 'Source changed during mapping'
        verify(parent['source'])
        verify(parent['artifacts'])
        report.update(status='PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY', instantiated_helpers=512,
                      mapped_kernel_instances=16, cells=dict(cells),
                      lut_count=sum(n for t, n in cells.items() if t.startswith('LUT')),
                      ff_count=sum(n for t, n in cells.items() if t.startswith('FD')),
                      dsp_count=cells['DSP48E1'],
                      artifacts=fingerprint([hierarchy, partitioned, design, netlist, script] +
                                            [ROOT / c['log'] for c in report['commands']]))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()
        print(out / 'report.json')
    print(report['status'], report['cells'])


if __name__ == '__main__':
    main()
