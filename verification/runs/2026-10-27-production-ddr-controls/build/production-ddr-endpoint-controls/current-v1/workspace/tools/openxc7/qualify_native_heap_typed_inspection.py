#!/usr/bin/env python3
"""Separate native HeAP qualification with typed nm output, not a warning waiver.

The first early-constraint continuation is preserved FAIL: its successful nm
symbol census contains C++ error destructor names, which the generic native-log
regex mistakes for a diagnostic. Admit that exact failure, parse every symbol
line using nm's address/size/type/name grammar, and still reject diagnostics or
unmodeled lines. All native warnings, exact illegal-pair rejection, positive
placement/refinement, LUT truth, DSP/BRAM features and limits stay unchanged.
No executed old source/input/model/expectation, native binary, live job, default
tool, constraint or standalone checksum manifest is changed.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import resume_native_heap_early_constraints as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report,verify_bindings

ROOT=previous.ROOT
FAILED=ROOT/'build/openxc7/native-heap-early-constraints-1791458660562002118/report.json'
CONTROL=ROOT/'tests/cmac/test_native_heap_typed_inspection_control.py'
QUALIFIED=previous.QUALIFIED
COMMANDS=previous.COMMANDS
FLAGS=previous.first.FLAGS
check_heap_log=previous.check_heap_log
SYMBOL_LINE=r'(?:[0-9a-f]{16}(?: [0-9a-f]{16})?| {16}) [A-Za-z?] [^\r\n]+'
OLD_GENERIC="            else:assert code==expected and not re.search(r'(?im)\\b(?:WARNING|ERROR|FATAL):',text),text[-4000:]"
NEW_GENERIC="""            elif label=='compiled_heap_symbol_census':
                assert code==expected,text[-4000:]
                check_symbol_census(text)
            else:assert code==expected and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text),text[-4000:]"""
# Keep the native diagnostic regex literal, not a Python string backspace.
NEW_GENERIC=NEW_GENERIC.replace('\x08',r'\b')


def check_symbol_census(text):
    assert text and text.endswith('\n')
    lines=text.splitlines();assert lines
    assert all(re.fullmatch(SYMBOL_LINE,line) for line in lines),'Unmodeled nm output or tool diagnostic'
    previous.getter_symbol(text)


def admit():
    q,before=previous.admit();r=json.loads(FAILED.read_text())
    assert r['status']=='FAIL' and r['stage']=='compiled_beta_store_and_early_constraint_qualification' and r['finished_utc']
    assert r['executable']==q['executable'] and r['native_source_or_executable_changed'] is False
    assert [c['label'] for c in r['commands']]==COMMANDS[:3]
    assert all(c['returncode']==c['expected_returncode']==0 for c in r['commands'])
    assert all(c['status']=='PASS_TOOL_EXECUTION_ONLY' for c in r['commands'][:2])
    c=r['commands'][-1];assert c['status']=='FAIL' and c['argv']==['nm','-S','-C',q['executable']['path']]
    text=Path(c['log']).read_text();check_symbol_census(text)
    offending=[line for line in text.splitlines() if re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',line)]
    assert len(offending)==3 and all(line.endswith(' W boost::program_options::error::~error()') for line in offending)
    assert r['error'].startswith('AssertionError(') and all(r[k] is False for k in FLAGS)
    assert not any(FAILED.parent.glob('*-placed.json'))
    bind_report(FAILED,r,before);verify_bindings(before);return q,before


NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,admit=admit,
               check_symbol_census=check_symbol_census)
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,(
    ('native-heap-early-constraints-','native-heap-typed-inspection-'),(OLD_GENERIC,NEW_GENERIC)))
exec(compile(MAIN_SOURCE,__file__+':typed-symbol-data-native-gates-unchanged','exec'),NAMESPACE)
OLD_VERIFY="        else:assert not re.search(r'(?im)\\b(?:WARNING|ERROR|FATAL):',text)"
NEW_VERIFY="""        elif label=='compiled_heap_symbol_census':check_symbol_census(text)
        else:assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text)""".replace('\x08',r'\b')
VERIFY_SOURCE=source_shaped(inspect.getsource(previous.first.verify_qualification),((OLD_VERIFY,NEW_VERIFY),))
exec(compile(VERIFY_SOURCE,__file__+':typed-symbol-revalidation-native-gates-unchanged','exec'),NAMESPACE)
verify_qualification=NAMESPACE['verify_qualification']
verify_metadata=previous.verify_metadata


def main():NAMESPACE['main']()


if __name__=='__main__':main()
