#!/usr/bin/env python3
"""Separate HeAP continuation for source-bound early constraint rejection.

Preserve the first failed procedure and its original marker expectation.
The native illegal fixture is rejected by HeAP::place_constraints before the
analytic-placement banner. The frozen binary has a literal beta=0.5 setter,
but not the newer source snapshot's beta logger. Bind/read its complete
compiled getter and unchanged ABI header rather than invent a log message.
Require the exact sole illegal-pair rejection and all original positive
placement/refinement, LUT and DSP/BRAM feature gates. No old source/input,
native executable, live job, constraint, warning/time limit or SHA256SUMS changes.
"""
import inspect
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import qualify_native_heap_placement as first
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest

FAILED=ROOT/'build/openxc7/native-heap-qualification-1791457692353795739/report.json'
CONTROL=ROOT/'tests/cmac/test_native_heap_early_constraints_control.py'
QUALIFIED='QUALIFIED_SMALL_NATIVE_HEAP_COMPILED_BETA_AND_EARLY_ILLEGAL_CONSTRAINT_REJECTION_DSP_BRAM_PNR_NOT_FULL_FIT_OR_SIGNOFF'
HEAD=Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/common/place/placer_heap.h')
HEAP_SOURCE=HEAD.with_suffix('.cc')
EARLY="ERROR: Bel 'X160Y206/SLICE_X0Y0.A6LUT' of type 'SLICE_LUTX' is not valid for cell 'captured_pair_lut1' of type 'SLICE_LUTX'"
COMMANDS=['nm_version','objdump_version','compiled_heap_symbol_census','compiled_heap_getter',*first.COMMANDS]


def check_heap_log(code,text,negative=False):
    assert code==(125 if negative else 0),text[-4000:]
    assert not re.search(r'(?im)\bWARNING:|sorry:|target is ignored|matched nothing|Assertion failure|terminate called|bad_alloc',text)
    assert 'Running Static placer...' not in text and 'RKNPU strict search:' not in text
    beta=[line for line in text.splitlines() if 'Xilinx HeAP effective beta:' in line]
    assert not beta or beta==['Info: Xilinx HeAP effective beta: 0.500000 (architecture default)']
    if negative:
        assert [line for line in text.splitlines() if line.startswith('ERROR:')]==[EARLY]
        assert text.endswith('0 warnings, 1 error\n')
        for marker in ('Creating initial analytic placement for ','HeAP Placer Time:',
                       'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...','Routing complete.','Program finished normally.'):
            assert marker not in text,'Invalid constrained pair continued into later stage: '+marker
    else:
        assert not re.search(r'(?im)\b(?:ERROR|FATAL):',text)
        for marker in ('Creating initial analytic placement for ','HeAP Placer Time:',
                       'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...','Program finished normally.'):
            assert marker in text,'Missing normal HeAP completion: '+marker


def admit():
    q,before=first.admit();r=json.loads(FAILED.read_text())
    assert r['status']=='FAIL' and r['stage']=='small_heap_native_legality_controls' and r['finished_utc']
    assert r['error']=='AssertionError()' and r['executable']==q['executable'] and r['native_source_or_executable_changed'] is False
    assert [c['label'] for c in r['commands']]==first.COMMANDS[:4]
    assert all(c['status']=='PASS_TOOL_EXECUTION_ONLY' and c['returncode']==0 for c in r['commands'][:3])
    c=r['commands'][-1];assert c['status']=='FAIL' and c['returncode']==125 and c['expected_returncode']==125
    assert c['argv']==first.expected_argv(q,'invalid-forced',FAILED.parent)
    text=Path(c['log']).read_text();check_heap_log(125,text,True)
    try:first.check_heap_log(125,text,True)
    except AssertionError:pass
    else:raise AssertionError('Original failed procedure no longer rejects its original log')
    assert not (FAILED.parent/'invalid-forced-placed.json').exists()
    assert all(r[k] is False for k in first.FLAGS)
    bind_report(FAILED,r,before)
    for name in ('nm','objdump'):
        p=Path(shutil.which(name)).resolve(strict=True);before[str(p)]=digest(p)
    assert str(HEAD) in before and str(HEAP_SOURCE) in before
    source=HEAP_SOURCE.read_text()
    assert 'const bool bel_is_not_valid_where_it_is = !ctx->isBelLocationValid(bel, /* explain_invalid */ true);' in source
    assert r'''log_error("Bel \'%s\' of type \'%s\' is not valid for cell "''' in source
    verify_bindings(before);return q,before


def getter_symbol(text):
    pattern=r'^([0-9a-f]{16}) ([0-9a-f]{16}) T nextpnr_himbaechel::XilinxImpl::configurePlacerHeap\(nextpnr_himbaechel::PlacerHeapCfg&\)$'
    found=re.findall(pattern,text,re.MULTILINE);assert len(found)==1
    address,size=(int(n,16) for n in found[0]);assert address>0 and 0<size<=8192
    return address,size


def validate_getter(text,address,size,head):
    assert 'file format elf64-x86-64' in text
    assert f'{address:016x} <nextpnr_himbaechel::XilinxImpl::configurePlacerHeap(nextpnr_himbaechel::PlacerHeapCfg&)>:' in text
    assert head.count('float alpha, beta;')==1
    writes=re.findall(r'\bmov(?:l|q)?\s+([^,\n]+),0x4\(%r(?:si|13)\)',text)
    assert writes==['$0x3f000000'],'Changed or ambiguous compiled beta field store'
    assert 'c7 46 04 00 00 00 3f' in text
    return dict(ELF_amd64=True,complete_getter_symbol_address=hex(address),complete_getter_symbol_size=size,
                second_reference_argument_sysv_register='rsi',ABI_header_first_fields='float alpha, beta;',
                observed_direct_beta_field_store_offset=4,observed_binary32_beta_store='0x3f000000',
                observed_literal_beta_store_value=0.5,not_full_binary_semantic_or_physical_timing_proof=True)


def record_getter(q,r,out,run):
    exe=q['executable']['path']
    r['nm_version']=run('nm_version',['nm','--version'],timeout=60).splitlines()[0]
    r['objdump_version']=run('objdump_version',['objdump','--version'],timeout=60).splitlines()[0]
    symbols=run('compiled_heap_symbol_census',['nm','-S','-C',exe],timeout=60)
    address,size=getter_symbol(symbols)
    text=run('compiled_heap_getter',['objdump','-d','-C','--start-address='+hex(address),'--stop-address='+hex(address+size),exe],timeout=60)
    r['compiled_heap_beta_store_certificate']=validate_getter(text,address,size,HEAD.read_text())


VERIFY_NAMESPACE=dict(first.__dict__,QUALIFIED=QUALIFIED,COMMANDS=COMMANDS)
exec(compile(inspect.getsource(first.verify_metadata),__file__+':all-unchanged-native-feature-and-full-exclusion-metadata','exec'),VERIFY_NAMESPACE)


def verify_metadata(r):
    VERIFY_NAMESPACE['verify_metadata'](r)
    c={c['label']:c for c in r['commands']};address,size=getter_symbol(Path(c['compiled_heap_symbol_census']['log']).read_text())
    assert r['compiled_heap_beta_store_certificate']==validate_getter(Path(c['compiled_heap_getter']['log']).read_text(),address,size,HEAD.read_text())
    exe=r['executable']['path']
    assert c['compiled_heap_symbol_census']['argv']==['nm','-S','-C',exe]
    assert c['compiled_heap_getter']['argv']==['objdump','-d','-C','--start-address='+hex(address),'--stop-address='+hex(address+size),exe]


NAMESPACE=dict(first.__dict__,__file__=__file__,__doc__=__doc__,admit=admit,CONTROL=CONTROL,
               QUALIFIED=QUALIFIED,COMMANDS=COMMANDS,check_heap_log=check_heap_log,verify_metadata=verify_metadata,
               record_getter=record_getter)
MAIN_SOURCE=source_shaped(inspect.getsource(first.main),(
    ('native-heap-qualification-','native-heap-early-constraints-'),
    ("        verify_bindings(before);r.update(source=before,executable=q['executable'],native_version=q['native_version'],stage='small_heap_native_legality_controls')",
     "        verify_bindings(before);r.update(source=before,executable=q['executable'],native_version=q['native_version'],stage='compiled_beta_store_and_early_constraint_qualification')\n"
     "        record_getter(q,r,out,run)"),))
exec(compile(MAIN_SOURCE,__file__+':source-bound-native-procedure-continuation','exec'),NAMESPACE)
exec(compile(inspect.getsource(first.verify_qualification),__file__+':same-exact-native-commands-positive-checks-and-features','exec'),NAMESPACE)
verify_qualification=NAMESPACE['verify_qualification']


def main():NAMESPACE['main']()


if __name__=='__main__':main()
