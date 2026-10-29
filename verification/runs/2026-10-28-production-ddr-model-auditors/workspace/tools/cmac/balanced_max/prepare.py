#!/usr/bin/env python3
"""Freeze the balanced-selector full512 checkpoint candidate; never run Vivado.

Fresh native candidate reports and its extracted-selector proof are required.
Old raw-board/mapped reports remain evidence for their original sources; they
are not relabeled as verification of this candidate. Actual mapped functional
and board-startup review remain required before any later image admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.cmac.balanced_max import run as native
from tools.evidence import fingerprint, timestamp


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def copy(source, target):
    require(source.is_file() and not source.is_symlink(), 'Missing/symlink input: '+str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    require(digest(source) == digest(target), 'Copy changed')


def native_report(path, simulator):
    report = read(path)
    require(report['status'] == 'PASS_FULL512_BALANCED_MAX_NATIVE_ONLY' and
            report['simulator'] == simulator and report['finished_utc'] and
            (report['channels'], report['kernels'], report['candidate_parallel_products'],
             report['frames'], report['compared_candidate_outputs']) == (32, 16, 512, 208, 3328),
            'Incomplete candidate native report')
    for name, sha in report['source']['files'].items():
        require(digest(ROOT/name) == sha, 'Native input changed: '+name)
    for name, sha in report['artifacts']['files'].items():
        require(digest(ROOT/name) == sha, 'Native artifact changed: '+name)
    require(digest(report['compiled_image']['path']) == report['compiled_image']['sha256'],
            'Native compiled image changed')
    commands = report['commands']
    names = ['simulator_version']+(['runtime_version'] if simulator == 'iverilog' else [])
    names += ['compile', 'negative', 'actual']
    require([c['name'] for c in commands] == names and all(c['status'] == 'PASS' for c in commands),
            'Incomplete native command sequence')
    for command in commands:
        log = Path(path).parent/(command['name']+'.log')
        require(digest(log) == command['log_sha256'], 'Native log changed')
    require(commands[-2]['returncode'] != 0 and commands[-1]['returncode'] == 0,
            'Missing corrupted-oracle rejection or actual completion')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-package', type=Path, required=True)
    parser.add_argument('--iverilog-report', type=Path, required=True)
    parser.add_argument('--verilator-report', type=Path, required=True)
    parser.add_argument('--selector-proof', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    native.validate_candidate_sources()
    parent = args.parent_package.resolve()
    original = read(parent/'report.json')
    require((original['channels'], original['kernels'], original['parallel_products'],
             original['clock_period_ns']) == (32, 16, 512, 20), 'Wrong full target')
    # The original verifier must run in its own ordinary import context.
    verify = subprocess.run([sys.executable, str(ROOT/'tools/cmac/startup/prepare.py'),
        'verify', str(parent)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    require(verify.returncode == 0, 'Original source/parent verification failed: '+verify.stderr[-2000:])
    admission = json.loads(verify.stdout)
    require(admission['external_parent_current'] is True and
            admission['blockers'] == ['Missing board reviewer'], 'Other original package blocker')
    reports = {s: native_report(p, s) for s, p in
               [('iverilog', args.iverilog_report), ('verilator', args.verilator_report)]}
    proof = read(args.selector_proof)
    require(proof['status'] == 'PASS_EXTRACTED_C32_SELECTOR_BINARY_EQUIVALENCE' and
            (proof['channels'], proof['free_binary_input_bits'], proof['output_bits']) == (32, 128, 4),
            'Missing actual selector proof')
    for name, sha in proof['source'].items():
        require(digest(ROOT/name) == sha, 'Selector proof source changed')
    for name, sha in proof['artifacts'].items():
        require(digest(args.selector_proof.parent/name) == sha, 'Selector proof artifact changed')
    require([c['returncode'] for c in proof['commands']] == [0, 1], 'Missing failed-selector proof control')
    out = args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh in-workspace package required')
    out.mkdir(parents=True)
    snapshot = out/'source'
    for name, sha in original['source']['files'].items():
        path = parent/'source'/name
        require(digest(path) == sha and digest(ROOT/name) == sha, 'Original source changed: '+name)
        copy(path, snapshot/name)
    for name in [native.CELL, native.ARRAY, 'tools/cmac/balanced_max/run.py',
                 'tools/cmac/balanced_max/prepare.py']:
        copy(ROOT/name, snapshot/name)
    parent_wrapper = next(name for name in original['synthesis_sources']
                          if name.endswith('/rk_cmac_cacc_fp16_array.sv'))
    wrapper = (snapshot/parent_wrapper).read_text()
    old = 'rk_cmac_fp16_array_dsp_prefix #'
    require(wrapper.count(old) == 1, 'Changed original component substitution')
    wrapper = wrapper.replace(old, 'rk_cmac_fp16_array_dsp_prefix_balanced_max #')
    generated = 'generated/rk_cmac_cacc_fp16_array.sv'
    (snapshot/'generated').mkdir()
    (snapshot/generated).write_text(wrapper)
    # Rebase the manifest to the source snapshot, without hashing rendered Tcl
    # containing its own source hash.
    files = {str(p.relative_to(snapshot)): digest(p) for p in snapshot.rglob('*') if p.is_file()}
    manifest_text = ''.join(h+'  '+n+'\n' for n, h in sorted(files.items()))
    source = dict(files=dict(sorted(files.items())), sha256=hashlib.sha256(manifest_text.encode()).hexdigest())
    text = (parent/'build.tcl').read_text()
    require(digest(parent/'build.tcl') == original['build_tcl_sha256'], 'Original Tcl changed')
    text = text.replace(str(parent/'source'), str(snapshot))
    text = text.replace(str(parent/'implementation'), str(out/'implementation'))
    text = text.replace(original['source']['sha256'], source['sha256'])
    old_read = 'read_verilog -sv {'+str(snapshot/parent_wrapper)+'}'
    require(text.count(old_read) == 1, 'Changed original wrapper read')
    text = text.replace(old_read, 'read_verilog -sv {'+str(snapshot/generated)+'}')
    insertion = 'read_xdc {'
    require(text.count(insertion) == 1, 'Changed original constraint read')
    lines = ''.join('read_verilog -sv {'+str(snapshot/name)+'}\n' for name in [native.CELL, native.ARRAY])
    text = text.replace(insertion, lines+insertion)
    old_filter = ('ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix || '
                  'REF_NAME == rk_cmac_fp16_cell_dsp_prefix')
    new_filter = old_filter.replace('rk_cmac_fp16_cell_dsp_prefix',
                                   'rk_cmac_fp16_cell_dsp_prefix_balanced_max')
    require(text.count(old_filter) == 1 and text.count('require_full_dsp_cmac\n') == 2,
            'Changed full512 retention gates')
    text = text.replace(old_filter, new_filter)
    require('if {$emit_bitstream} { error "Bitstream emission is disabled' in text and
            '20.0' in text and 'Negative $delay_type slack' in text, 'Missing original physical gates')
    (out/'build.tcl').write_text(text)
    qualification = out/'qualification'
    for name, path in [('iverilog', args.iverilog_report), ('verilator', args.verilator_report),
                       ('selector-proof', args.selector_proof), ('original-preparation', parent/'report.json')]:
        copy(path, qualification/(name+'.json'))
    selected = [generated if n == parent_wrapper else n for n in original['synthesis_sources']]
    selected += [native.CELL, native.ARRAY]
    selected += ['fpga/cmac/startup/ypcb_cmac_array_startup.xdc']
    report = dict(status='PREPARED_BALANCED_MAX_FULL512_CHECKPOINT_ONLY', created_utc=timestamp(),
        scope='Fresh balanced-selector array native/proof evidence; checkpoint-only implementation candidate, not mapped/physical/RK acceptance',
        channels=32, kernels=16, parallel_products=512, clock_period_ns=20,
        top='ypcb_cmac_array_startup_top', part='xc7k480tffg1156-2', source=source,
        synthesis_sources=selected, hardware_inputs={n: files[n] for n in selected},
        build_tcl_sha256=digest(out/'build.tcl'), original_parent_package=str(parent),
        original_parent_report_sha256=digest(parent/'report.json'), original_verification=admission,
        qualification_reports={p.name: digest(p) for p in qualification.iterdir()},
        external_native_reports={s: str(p.resolve()) for s, p in
            [('iverilog', args.iverilog_report), ('verilator', args.verilator_report)]},
        external_selector_proof=str(args.selector_proof.resolve()),
        external_qualification_must_be_rechecked_before_build=True,
        original_raw_board_reports_reused_as_new_candidate_pass=False,
        fresh_mapped_and_startup_review_required_before_bitstream=True,
        electrical_review_required=True, vivado_executed=False, bitstream_emitted=False,
        hardware_programmed=False)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(out/'report.json')


if __name__ == '__main__':
    main()
