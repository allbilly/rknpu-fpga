#!/usr/bin/env python3
"""Independently test forwarding and inspect all actual nested INIT parameters.

No compiled VVP, model, wrapper, failed bench, RTL or running job is repaired.
Check complete outer/internal parameter tables in the source-bound failing
binary, and run a minimal separate constant-forwarding diagnostic. This is
local simulator diagnosis, never acceptance of the failed cold-read property.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import diagnose_prefix_working_bram_cold as previous
from audit_empty_output_pairs import source_shaped

BENCH=previous.ROOT/'tests/cmac/tb_bram_parameter_forwarding_diagnostic.sv'


def parameter_tables(path):
    scopes={};tables={};current=None
    for line in path.read_text().splitlines():
        match=re.fullmatch(r'(S_\w+) \.scope (?:module|generate), "([^"]+)" "[^"]+" .*?, (S_\w+);',line)
        if match:
            key,name,parent=match.groups();scopes[key]=scopes.get(parent,())+(name,);current=scopes[key]
            continue
        match=re.fullmatch(r'S_\w+ \.scope (?:module|generate), "([^"]+)" "[^"]+" [^,]+,[^,]+(?:, [^,]+)?;',line)
        if match:
            current=(match.group(1),)
            key=line.split()[0];scopes[key]=current;continue
        match=re.fullmatch(r'P_\w+ \.param/l "(INITP?_[0-9A-F]{2}|INIT_[AB]|SRVAL_[AB])" [^,]+, C4<([01xz]+)>;',line)
        if match and current is not None:tables.setdefault('.'.join(current),{})[match.group(1)]=match.group(2)
    return tables


def forwarding_records(path):
    tables=parameter_tables(path);result={}
    for view in ('mapped','zero_encoded','counterfactual_one'):
        for index in (0,1):
            outer=f'tb_prefix_working_bram_overwrite.{view}.actual_{index}'
            inner=outer+'.gen_tdp.INT_RAMB_TDP'
            a=tables[outer];b=tables[inner]
            assert len(a)==148 and set(a)==set(b)
            differences={key:dict(outer=a[key],internal=b[key]) for key in a if a[key][-len(b[key]):]!=b[key]}
            result[outer]=dict(parameters=148,differences=differences)
    return result


OLD_OBSERVE="""        text=run('observe',['vvp',binary])
        assert 'OBSERVATION_ONLY unchanged actual working BRAM cold trace; no overwrite, startup or hardware acceptance' in text
        report['observed_trace']=text.splitlines()
"""
NEW_OBSERVE="""        report['actual_failed_binary_parameter_forwarding']=forwarding_records(FAILED.parent/'overwrite.vvp')
        text=run('observe',['vvp',binary])
        assert 'PASS independent constant parameter forwarding only; not vendor-model or board acceptance' in text
        report['independent_constant_forwarding_log']=text.splitlines()
"""
MAIN_SOURCE=source_shaped(inspect.getsource(previous.main),(
    ('prefix-working-bram-cold-diagnostic-','bram-parameter-forwarding-diagnostic-'),
    ('tb_prefix_working_bram_cold_diagnostic','tb_bram_parameter_forwarding_diagnostic'),
    (OLD_OBSERVE,NEW_OBSERVE)))
NAMESPACE=dict(vars(previous),__file__=__file__,__doc__=__doc__,BENCH=BENCH,
    forwarding_records=forwarding_records)
exec(compile(MAIN_SOURCE,__file__+':independent-diagnostic-main','exec'),NAMESPACE)


if __name__=='__main__':NAMESPACE['main']()
