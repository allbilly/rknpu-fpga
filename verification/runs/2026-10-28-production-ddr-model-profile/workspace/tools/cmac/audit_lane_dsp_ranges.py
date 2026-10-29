#!/usr/bin/env python3
"""Source-bound unsigned donor ranges, not a composed multiply/lane proof.

Inspect the actual elaborated FP16 row wiring. Apply already completed,
source-identical full-integer carry-save lemmas, with explicit interval
bounds for every wired word. No black-box axioms, sampling or assumptions
about recoder values beyond their actual binary output widths.
"""
import argparse
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
from test_fixed_array_board import verify_manifest
import prove_lane_dsp_tree_ranges as lemmas

TOP = 'rk_cmac_fp16_rows'
DONORS = [ROOT / 'rtl/vendor/nvdla' / name for name in
    ('NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
ROWS = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_rows.sv'


def validate_parent(report):
    assert report['status'] == 'PASS_CONDITIONAL_DONOR_TREE_INTEGER_LEMMAS_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert set(report['lemmas']) == set(lemmas.DOMAINS)
    labels = ['version']
    for top, (inputs, width, conditional) in lemmas.DOMAINS.items():
        assert report['lemmas'][top] == dict(status='PASS_COMPONENT_ONLY',
            free_input_bits=sum(inputs.values()), compared_output_bits=width,
            conditional_on_no_unsigned_row_sum_overflow=conditional)
        for mode in ('negative', 'actual'):
            stem = top + '_' + mode
            labels += [stem + '_lowering', stem + '_sat']
    assert [Path(s['log']).stem for s in report['commands']] == labels
    for step in report['commands']:
        negative = Path(step['log']).stem.endswith('_negative_sat')
        assert step['status'] == 'PASS' and step['returncode'] == (1 if negative else 0)
    for field in ('binary_lane_sum_equivalence', 'composed_lane_proof',
            'donor_range_bound_proved', 'multiply_distributivity_proved',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False


def validate_bindings(report, directory):
    for manifest in (report['source'], report['artifacts'],
            *report['lowering_inputs'].values(), *report['proof_inputs'].values()):
        verify_manifest(manifest)
    for top in lemmas.DOMAINS:
        for mode in ('negative', 'actual'):
            stem = top + '_' + mode
            graph = directory / (stem + '.json')
            lemmas.validate_graph(json.loads(graph.read_text()), top)
            script = directory / (stem + '_sat.ys')
            assert script.read_text() == ('read_json ' + json.dumps(str(graph)) + '\n' +
                'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            step = next(s for s in report['commands'] if Path(s['log']).stem == stem + '_sat')
            assert step['argv'] == ['yosys', '-Q', '-T', '-s', str(script)]
            lemmas.validate_sat((ROOT / step['log']).read_text(), step['returncode'], mode == 'negative')


def packed_words(selected, inverted, offset):
    """Little-endian bits of the five exact actual 24-bit input words."""
    s, inv = selected[offset:offset+4], inverted[offset:offset+4]
    return [s[0] + ['0']*7,
        [inv[0], '0'] + s[1] + ['0']*5,
        ['0']*2 + [inv[1], '0'] + s[2] + ['0']*3,
        ['0']*4 + [inv[2], '0'] + s[3] + ['0'],
        ['0']*6 + [inv[3]] + ['0']*17]


def word_bound(bits):
    assert all(b == '0' or type(b) is int for b in bits), 'Unknown/one-valued structural padding'
    return sum(1 << i for i, b in enumerate(bits) if type(b) is int)


def audit_lowering_log(text):
    donor=str(DONORS[0])
    allowed={
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33',
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28'}
    warnings=[line for line in text.splitlines() if line.startswith('Warning:')]
    assert 'ERROR:' not in text and set(warnings)<=allowed,('Unknown lowering warning',warnings)
    return warnings


def validate_wiring(design):
    module = design['modules'][TOP]
    ports, cells = module['ports'], module['cells']
    expected = {'op_a': ('input',16), 'op_b': ('input',16),
        'exp_sft': ('input',4), 'pair_nz': ('input',1),
        'res_a': ('output',32), 'res_b': ('output',32), 'res_tag': ('output',8)}
    assert {n:(p['direction'],len(p['bits'])) for n,p in ports.items()} == expected
    free = [b for n in ('op_a','op_b','exp_sft','pair_nz') for b in ports[n]['bits']]
    assert len(set(free)) == 37 and all(type(b) is int for b in free)
    booths = sorted((n,c) for n,c in cells.items() if c['type'] == 'NV_NVDLA_CMAC_CORE_MAC_booth')
    assert [n for n,c in booths] == [f'booth[{i}].recode' for i in range(8)]
    codes = ['0'] + ports['op_a']['bits'][:15] + ['0']
    selected, inverted = [], []
    sign = None
    for i, (_, cell) in enumerate(booths):
        assert not cell['parameters']
        assert cell['port_directions'] == {'code':'input','is_8bit':'input','sign':'input',
            'src_data':'input','out_data':'output','out_inv':'output'}
        pins = cell['connections']
        assert set(pins) == set(cell['port_directions'])
        assert pins['code'] == codes[2*i:2*i+3]
        assert pins['is_8bit'] == ['0']
        assert pins['src_data'] == ports['op_b']['bits'][:15] + ['0']
        if sign is None: sign = pins['sign']
        assert pins['sign'] == sign and len(sign) == 1 and type(sign[0]) is int
        assert len(pins['out_data']) == 17 and all(type(b) is int for b in pins['out_data'])
        assert len(pins['out_inv']) == 1 and type(pins['out_inv'][0]) is int
        selected.append(pins['out_data']); inverted.append(pins['out_inv'][0])
    sign_driver = [c for c in cells.values() if c.get('connections',{}).get('Y') == sign]
    assert len(sign_driver) == 1 and sign_driver[0]['type'] == '$xor'
    assert sign_driver[0]['connections'] == {'A':ports['op_a']['bits'][15:],
        'B':ports['op_b']['bits'][15:], 'Y':sign}
    tree_names = [n for n,c in cells.items() if c['type'] in design['modules'] and
        'NV_DW02_tree' in c['type']]
    assert set(tree_names) == {'low_tree','high_tree','final_tree'}
    outputs = {}
    group_bounds = {}
    for name, offset in [('low_tree',0),('high_tree',4),('final_tree',None)]:
        cell = cells[name]; tree = design['modules'][cell['type']]
        shape = {n:int(v,2) for n,v in tree['parameter_default_values'].items()}
        expected_shape={'num_inputs':5,'input_width':24} if offset is not None else {'num_inputs':4,'input_width':32}
        assert shape == expected_shape
        assert cell['port_directions'] == {'INPUT':'input','OUT0':'output','OUT1':'output'}
        pins = cell['connections']; assert set(pins) == {'INPUT','OUT0','OUT1'}
        width = 24 if offset is not None else 32
        assert all(len(pins[p]) == width and all(type(b) is int for b in pins[p]) for p in ('OUT0','OUT1'))
        outputs[name] = (pins['OUT0'],pins['OUT1'])
        if offset is not None:
            words = packed_words(selected,inverted,offset)
            assert all(len(word) == 24 for word in words)
            assert pins['INPUT'] == [b for word in words for b in word], ('Changed actual packed tree input',name)
            bounds = [word_bound(word) for word in words]
            total = sum(bounds); assert total < 1 << 24
            group_bounds[name] = dict(input_word_upper_bounds=bounds,
                full_integer_input_sum_upper_bound=total, width=24,
                resulting_row_sum_upper_bound=total,
                applied_lemma='cmac_tree_5x24_integer_lemma')
        else:
            low_a,low_b = outputs['low_tree']; high_a,high_b = outputs['high_tree']
            assert pins['INPUT'] == low_a + ['0']*8 + low_b + ['0']*8 + ['0']*8 + high_a + ['0']*8 + high_b
    allowed = {'$xor','$logic_not','$logic_or','$mux','$shr'}
    assert all(c['type'] in allowed or c['type'] in design['modules'] for c in cells.values())
    assert set(design['modules']) == {TOP,'NV_NVDLA_CMAC_CORE_MAC_booth',
        *(cells[n]['type'] for n in tree_names)}, 'Unexpected hierarchy, state or opaque arithmetic'
    total = group_bounds['low_tree']['resulting_row_sum_upper_bound'] + (
        group_bounds['high_tree']['resulting_row_sum_upper_bound'] << 8)
    assert total == 2863267840 and total < 1 << 32
    return dict(free_binary_input_bits=37, recoder_instances=8, tree_shapes=[(5,24),(5,24),(4,32)],
        groups=group_bounds, final_full_integer_input_sum_upper_bound=total,
        final_unsigned_row_sum_upper_bound=total, final_width=32,
        final_applied_lemma='cmac_tree_4x32_integer_lemma',
        discarded_carry_no_unsigned_overflow_condition_satisfied=True,
        scope='Binary unsigned range for exact elaborated specialization only; no multiply identity, compensation/shift composition, X/reset, mapped/full-array/raw-board or physical proof.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree-report',type=Path,required=True)
    args = parser.parse_args(); parent_path = args.tree_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text()); validate_parent(parent)
    validate_bindings(parent,parent_path.parent)
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    tracked = [*DONORS,ROWS,parent_path,Path(__file__).resolve(),*imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-donor-ranges/{time.time_ns()}'; out.mkdir(parents=True,exist_ok=False)
    report = dict(status='RUNNING',stage='lowering',started_utc=timestamp(),source=before,
        supervisor_pid=os.getpid(),python_version=sys.version,commands=[],
        parent_report=str(parent_path.relative_to(ROOT)),parent_status=parent['status'],
        parent_source_sha256=parent['source']['sha256'],donor_range_bound_proved=False,
        composed_lane_proof=False,binary_lane_sum_equivalence=False,multiply_distributivity_proved=False,
        full_array_numerical_acceptance=False,raw_board_numerical_acceptance=False,
        physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False)
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,label):
        step = dict(argv=list(map(str,argv)),log=str((out/(label+'.log')).relative_to(ROOT)),status='RUNNING')
        report['commands'].append(step); save(); start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid;save()
                    try: code=proc.wait(timeout=1000)
                    except BaseException:
                        try: os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait();raise
            step['returncode']=code; text=(ROOT/step['log']).read_text()
            assert code==0 and 'ERROR:' not in text,text[-3000:]
            if label=='lowering':report['source_bound_array_lowering_notices']=audit_lowering_log(text)
            else:assert not re.search(r'(?im)^Warning:',text),text[-3000:]
            step['status']='PASS';return text
        except BaseException: step['status']='FAIL';raise
        finally: step['seconds']=round(time.monotonic()-start,3);save()
    signal.signal(signal.SIGTERM,lambda s,f: (_ for _ in ()).throw(SystemExit(128+s)))
    save();generated=[]
    try:
        report['tool_version']=run(['yosys','-V'],'version').strip()
        for path in sorted(set(tracked)):
            target=out/'snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes());generated.append(target)
        graph,script=out/'rows.json',out/'lowering.ys';generated += [graph,script]
        script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST '+
            ' '.join(json.dumps(str(p)) for p in [*DONORS,ROWS])+'\n'+
            'hierarchy -check -top '+TOP+'\nproc\nopt -full\ncheck -assert\n'+
            'write_json '+json.dumps(str(graph))+'\n')
        report['lowering_inputs']=fingerprint([*DONORS,ROWS,script]);save()
        run(['yosys','-Q','-T','-s',script],'lowering')
        assert fingerprint([*DONORS,ROWS,script])==report['lowering_inputs']
        report['ranges']=validate_wiring(json.loads(graph.read_text()))
        validate_bindings(parent,parent_path.parent)
        assert fingerprint(tracked)==before
        report.update(status='PASS_SOURCE_BOUND_UNSIGNED_DONOR_RANGES_ONLY',stage='complete',
            finished_utc=timestamp(),donor_range_bound_proved=True,
            artifacts=fingerprint([*generated,*out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL',finished_utc=timestamp(),error=repr(error),
            artifacts=fingerprint([p for p in [*generated,*out.glob('*.log')] if p.is_file()]));raise
    finally: save()
    print(out/'report.json',flush=True)


if __name__=='__main__': main()
