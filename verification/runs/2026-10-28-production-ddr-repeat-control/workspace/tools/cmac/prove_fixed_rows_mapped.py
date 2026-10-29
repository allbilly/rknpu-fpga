#!/usr/bin/env python3
"""Prove the actual mapped FP16 rows against their source for all binary inputs.

The original donor configuration lemma remains a required parent. Functional
LUT/MUX definitions are frozen from the installed Yosys, without blackboxes,
input assumptions or replacing either partial row with a compensated product.
This complements, never substitutes for, vendor-model four-state simulation.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from test_fixed_rows_mapped import validate_parents
from xc7_primitive_counts import primitive_counts

TOP = 'cmac_fixed_rows_mapped_miter'
MITER = ROOT / 'tests/cmac/cmac_fixed_rows_mapped_miter.sv'
BOOLEAN = {'$_AND_', '$_NOT_', '$_OR_', '$_NAND_', '$_NOR_', '$_XOR_',
           '$_XNOR_', '$_MUX_', '$_NMUX_', '$_BUF_', '$_AOI3_', '$_OAI3_',
           '$_AOI4_', '$_OAI4_'}


def check_boolean_design(design):
    assert set(design['modules']) == {TOP}, 'Unflattened or blackboxed implementation'
    module = design['modules'][TOP]
    ports = module['ports']
    expected = {'clk': 1, 'rst_n': 1, 'pair_nz': 1, 'op_a': 16, 'op_b': 16, 'exp_sft': 4}
    assert {name: len(port['bits']) for name, port in ports.items()
            if port['direction'] == 'input'} == expected
    input_bits = [bit for name in expected for bit in ports[name]['bits']]
    assert all(isinstance(bit, int) for bit in input_bits)
    assert len(input_bits) == len(set(input_bits)), 'Coupled input variables reduce the proof domain'
    outputs = {'reference_a': 32, 'reference_b': 32, 'mapped_a': 32, 'mapped_b': 32,
               'reference_tag': 8, 'mapped_tag': 8, 'difference': 72, 'mismatch': 1}
    assert {name: len(port['bits']) for name, port in ports.items()
            if port['direction'] == 'output'} == outputs
    counts = Counter(cell['type'] for cell in module['cells'].values())
    assert set(counts) <= BOOLEAN, ('State, assumptions, blackboxes or unsupported logic', counts)
    return dict(counts)


def sanity_miter(text):
    old = 'reference_tag ^ mapped_tag};'
    assert text.count(old) == 1, 'Unexpected comparison declaration'
    return text.replace(old, "reference_tag ^ mapped_tag ^ 8'h01};")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    parser.add_argument('--rows-report', type=Path, required=True)
    args = parser.parse_args()
    ap, rp = args.area_report.resolve(), args.rows_report.resolve()
    assert ap.is_relative_to(ROOT) and rp.is_relative_to(ROOT)
    area, rows = json.loads(ap.read_text()), json.loads(rp.read_text())
    validate_parents(area, rows)
    mapped = ap.parent / 'fixed_mapped.v'
    mapped_json = ap.parent / 'fixed_mapped.json'
    for path in (mapped, mapped_json):
        assert str(path.relative_to(ROOT)) in area['artifacts']['files']
    cells = dict(primitive_counts(json.loads(mapped_json.read_text())['modules'], 'fp16_rows_area_top'))
    assert cells == area['results']['fixed']['cells']
    assert set(cells) <= {'LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6', 'MUXF7', 'MUXF8'}
    donor = ROOT / 'rtl/vendor/nvdla'
    sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
               ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_rows.sv']
    assert all(str(path.relative_to(ROOT)) in rows['source']['files'] for path in sources)
    assert 'assume' not in MITER.read_text() and 'initial' not in MITER.read_text()
    out = ROOT / f'build/rknpu-fixed-fp16-rows/mapped-formal-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    snapshots = []
    for label, parent in (('area', area), ('rows', rows)):
        path = out / (label+'_report_snapshot.json')
        path.write_text(json.dumps(parent, indent=2) + '\n'); snapshots.append(path)
    negative = out / 'negative_miter.sv'
    negative.write_text(sanity_miter(MITER.read_text()))
    tracked = sources + [MITER, negative, ap, rp, mapped, mapped_json, *snapshots,
        donor / 'LICENSE', Path(__file__).resolve(), ROOT / 'tools/evidence.py',
        ROOT / 'tools/cmac/test_fixed_rows_mapped.py', ROOT / 'tools/cmac/xc7_primitive_counts.py']
    report = dict(status='RUNNING', started_utc=timestamp(), commands=[], mapped_cells=cells,
                  parent_formal_result=rows['formal_result'], seed='none; symbolic binary inputs',
                  relevant_free_input_bits=37, compared_output_bits=72,
                  numerical_netlist_binary_acceptance=False, physical_fit_verified=False,
                  scope='Actual mapped single fixed-FP16 partial-row helper against its unchanged '
                        'RTL for every binary operand, pair-nz and shift. Required parent proof '
                        'links that RTL to NVIDIA after configuration. Not four-state/startup, '
                        'full C32/K16 mapping, routed timing/DRC, a bitstream, FPGA or RK evidence.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name, expected_failure=False):
        step = dict(argv=list(map(str, argv)), status='RUNNING',
                    log=str((out / (name+'.log')).relative_to(ROOT)),
                    expected='SAT countermodel/proof failure' if expected_failure else 'exit zero')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                                      stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            text = (ROOT / step['log']).read_text(); step['returncode'] = code
            if expected_failure:
                assert code != 0 and 'SAT proof finished - model found: FAIL!' in text
                assert 'Called with -verify and proof did fail!' in text, text[-4000:]
                step['observed'] = 'Expected single-bit comparison mutation rejected with SAT countermodel'
            else:
                assert code == 0 and 'ERROR:' not in text, text[-4000:]
            step['status'] = 'PASS'; return text
        except Exception:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic()-started, 3); save()

    save()
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == area['tool_version']
        data = Path(run(['yosys-config', '--datdir'], 'datadir').strip()).resolve()
        original_model = data / 'xilinx/cells_sim.v'
        model_bytes = original_model.read_bytes()
        model = out / 'xilinx_functional_models.v'
        model.write_bytes(model_bytes)
        report['primitive_model_original'] = dict(path=str(original_model),
            sha256=hashlib.sha256(model_bytes).hexdigest(), frozen=str(model.relative_to(ROOT)),
            scope='Unmodified installed Yosys functional LUT/MUX truth tables; specify timing not enabled')
        tracked.append(model)
        report['source'] = fingerprint(tracked)
        for path in tracked:
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
        help_text = run(['yosys', '-Q', '-T', '-p', 'help flatten; help sat; help design; help simplemap'], 'help')
        assert '-wb' in help_text and '-noscopeinfo' in help_text and '-timeout' in help_text
        assert 'design -copy-from' in help_text and '$mux' in help_text
        artifacts = []
        for label, bench in (('negative_sanity', negative), ('actual_proof', MITER)):
            graph, script = out / (label+'.json'), out / (label+'.ys')
            prefix = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST -I'+json.dumps(str(donor))+' '
            prefix += ' '.join(json.dumps(str(path)) for path in [*sources, model, mapped, bench])
            prefix += '; hierarchy -check -top '+TOP+'; proc; flatten -wb -noscopeinfo'
            prefix += '; opt -full; check -assert; techmap; opt -full; abc -g AND; opt -full'
            # opt_share may create word-level $mux after ABC. Lower those
            # specifically; don't expand the accepted graph cell whitelist.
            # Yosys retains unused library/ABC placeholder definitions. Copy
            # the exact comparison module only; any instantiated blackbox or
            # unknown cell still fails the strict graph check below.
            prefix += '; simplemap t:$mux; opt_clean; design -stash lowered_comparison'
            prefix += '; design -copy-from lowered_comparison '+TOP
            prefix += '; check -assert; stat; write_json '+json.dumps(str(graph))
            script.write_text(prefix.replace('; ', ';\n')+'\n')
            run(['yosys', '-Q', '-T', '-s', script], label+'_lowering')
            report[label+'_boolean_cells'] = check_boolean_design(json.loads(graph.read_text()))
            proof_script = out / (label+'_sat.ys')
            proof_script.write_text('read_json '+json.dumps(str(graph))+';\n'
                'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            proof = run(['yosys', '-Q', '-T', '-s', proof_script], label+'_sat',
                        expected_failure=label == 'negative_sanity')
            if label == 'actual_proof':
                assert 'SAT proof finished - no model found: SUCCESS!' in proof, proof[-4000:]
            artifacts += [graph, script, proof_script]
        assert fingerprint(tracked) == report['source']
        assert original_model.read_bytes() == model_bytes
        validate_parents(area, rows)
        report.update(status='PASS_MAPPED_FIXED_FP16_ROWS_BINARY_FORMAL_ONLY',
                      numerical_netlist_binary_acceptance=True,
                      artifacts=fingerprint(artifacts+[ROOT / step['log'] for step in report['commands']]))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'])


if __name__ == '__main__':
    main()
