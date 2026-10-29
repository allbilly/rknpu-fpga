#!/usr/bin/env python3
"""Continue the unchanged temporal proof after its WaveJSON parser failure.

Preserve the actual first failure: the intended native wrong-golden base case
completed, but the parser incorrectly expected only explicitly shown signals
and an extra trailing frame. Native Yosys also emits the literal initial actual
storage state, with three frames (initial, steps 1 and 2) and sparse vector data.
Revalidate that frozen failure. Decode every native WaveJSON field strictly and
cross-check it against unchanged finite table-row/real-negative requirements.
No hardware, clocked model, native SAT script, assumptions, limit or original
acceptance gate is changed. Run fresh native negative and positive proofs.
Scope remains binary sampled-reset ownership/prefix safety, not four-state
startup, reset pulses, liveness, full numerical or physical acceptance.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import prove_prefix_binary_temporal_ownership as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report,verify_bindings

ROOT=previous.ROOT
FAILED=ROOT/'build/openxc7/prefix-binary-temporal-ownership-1791449841446876666/report.json'
CONTROL=ROOT/'tests/cmac/test_wavejson_prefix_binary_temporal_ownership_control.py'
WIDTHS={**dict.fromkeys(previous.SHOW,1),'index':12,'probe':12,'writes_seen':13,'demo_state':4,'dma_state':3,'storage_state':50}


def decode_signal(signal):
    assert set(signal)<= {'name','wave','data'} and {'name','wave'}<=set(signal)
    name=signal['name'];assert name in WIDTHS
    width=WIDTHS[name];wave=signal['wave'];data=signal.get('data',[])
    assert isinstance(wave,str) and len(wave)==3 and isinstance(data,list)
    vector=width>1;assert ('data' in signal)==vector
    values=[];cursor=0
    for symbol in wave:
        if symbol=='.':
            assert values and values[-1] is not None,'Unbound native WaveJSON repeat'
            value=values[-1]
        elif symbol=='4':
            value=None
            if vector:
                assert cursor<len(data) and data[cursor]=='','Changed native blank vector frame'
                cursor+=1
        elif symbol=='=':
            assert vector and cursor<len(data),'Unbound native vector frame'
            bits=data[cursor];cursor+=1
            assert isinstance(bits,str) and len(bits)==width and re.fullmatch('[01]+',bits),'Non-finite or wrong-width native vector'
            value=int(bits,2)
        elif symbol in ('0','1'):
            assert not vector,'Scalar symbol for native vector'
            value=int(symbol)
        else:raise AssertionError('Unknown native WaveJSON symbol')
        values.append(value)
    assert cursor==len(data),'Unused native WaveJSON data'
    return values


def crosscheck_wave(text,wave,records):
    assert set(wave)=={'signal','config'} and wave['config']=={'hscale':12.5}
    signals=wave['signal'];names=[s['name'] for s in signals]
    assert len(names)==len(set(names)) and set(names)==set(previous.SHOW)|{'storage_state'},'Changed native WaveJSON trace signals'
    decoded={s['name']:decode_signal(s) for s in signals}
    for t,frame in records.items():
        for name,value in frame.items():assert decoded[name][t]==value,'Native WaveJSON/table mismatch'
    init={}
    for line in text.splitlines():
        match=re.fullmatch(r'\s*init\s+\\(probe|probe_written|seen_reset|storage_state|writes_seen)\s+(-?\d+|--)\s+([0-9a-f]+|--)\s+([01]+)\s*',line)
        if not match:continue
        name=match[1];bits=match[4]
        assert name not in init and len(bits)==WIDTHS[name],'Duplicate/wrong-width native initial state'
        value=int(bits,2)
        if name=='storage_state':assert match[2]==match[3]=='--'
        else:assert int(match[2])==value and int(match[3],16)==value
        init[name]=value
    assert set(init)=={'probe','probe_written','seen_reset','storage_state','writes_seen'}
    assert init['seen_reset']==0 and decoded['storage_state'][1:]==[None,None]
    for name,value in init.items():assert decoded[name][0]==value,'Changed native initial-state WaveJSON/table value'
    assert re.findall(r'(?m)^Import set-constraint from init attribute: (.*)$',text)==["\\seen_reset = 1'0"]
    return init


NAMESPACE=dict(previous.__dict__,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,FAILED=FAILED,
               crosscheck_wave=crosscheck_wave)
TRACE_SOURCE=source_shaped(inspect.getsource(previous.negative_trace),(
    ("    signals=wave['signal'];names=[x['name'] for x in signals]\n"
     "    assert len(names)==len(set(names)) and set(names)==set(SHOW),'Changed native WaveJSON trace signals'\n"
     "    assert all(isinstance(x['wave'],str) and len(x['wave'])==4 for x in signals)\n",
     '    initial_values=crosscheck_wave(text,wave,records)\n'),
    ('return dict(actual_frames=records,base_case_steps=2,',
     'return dict(actual_frames=records,actual_initial_values=initial_values,native_wavejson_table_crosschecked=True,base_case_steps=2,'),))
exec(compile(TRACE_SOURCE,__file__+':unchanged-real-negative-with-strict-native-wavejson','exec'),NAMESPACE)
negative_trace=NAMESPACE['negative_trace']


def admit(before):
    cone,model,library,certificate=previous.admit(before)
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='native_binary_temporal_induction_negative' and report['finished_utc']
    assert report['error']=="AssertionError('Changed native WaveJSON trace signals')"
    assert [c['label'] for c in report['commands']]==['software_controls','generated_check','yosys_version','negative']
    assert all(c['returncode']==0 and c['status']=='PASS_TOOL_EXECUTION_ONLY' for c in report['commands'][:-1])
    command=report['commands'][-1]
    assert command['returncode']==1 and command['status']=='PASS_EXPECTED_REAL_TEMPORAL_BASE_CASE_NEGATIVE'
    assert 'positive' not in [c['label'] for c in report['commands']]
    assert report['binary_model_temporal_port_ownership_proved'] is False and report['binary_prefix_write_before_core_request_proved'] is False
    bind_report(FAILED,report,before);verify_bindings(before)
    root=FAILED.parent
    assert model==(root/'actual-binary-temporal-controller.v').read_text()
    assert library==(root/'unchanged_selected_controller_cells.v').read_bytes()
    assert certificate==json.loads((root/'actual-async-clear-fixed-point.json').read_text())
    witness=root/'negative-counterexample.json';text=Path(command['log']).read_text();wave=json.loads(witness.read_text())
    previous.validate(text,1,True)
    assert (root/'negative.ys').read_text()==previous.script(root/'unchanged_selected_controller_cells.v',root/'actual-binary-temporal-controller.v',True,witness)
    try:previous.negative_trace(text,wave)
    except AssertionError as error:assert str(error)=='Changed native WaveJSON trace signals'
    else:raise AssertionError('Frozen original WaveJSON parser failure not reproduced')
    negative_trace(text,wave);verify_bindings(before)
    return cone,model,library,certificate


MAIN_SOURCE=source_shaped(inspect.getsource(previous.main),(
    ('prefix-binary-temporal-ownership-','prefix-binary-temporal-ownership-wavejson-'),
    ('        before={};cone,model_text,library_data,certificate=admit(before)\n',
     '        before={};cone,model_text,library_data,certificate=admit(before)\n'
     '        report.update(preserved_initial_wavejson_parser_failure_report=str(FAILED),actual_model_and_native_script_unchanged=True)\n'),))
NAMESPACE.update(admit=admit)
exec(compile(MAIN_SOURCE,__file__+':unchanged-native-temporal-proof-main','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
