#!/usr/bin/env python3
"""Qualify exact unchanged library definitions needed by the actual address cone.

Preserve the eighth actual FAIL: full library parsing warned on unused
tri-state I/O models, and the unchanged strict native SAT gate refused them.
Select only the complete byte-identical definitions of the nine actual
combinational primitive types, retaining attached attributes, internal pin
attributes, parameters, expressions and specify blocks. Retain the original
license/source header and bind both full source and selected definitions.
Fresh full 557-instance binary vendor/selected-library comparisons and the
wrong-golden corpus must pass before the unchanged actual miter and strict
SAT-positive/real-negative gate run. No warning is suppressed/admitted, no
function is rewritten, no physical source/input changes, no SHA256SUMS file.
Binary address only: no sequential/startup/numeric/physical/hardware signoff.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import resume_binary_result_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

raw=previous.raw
ROOT=raw.ROOT
FAILED=ROOT/'build/openxc7/prefix-bram-address-binary-result-resume-1791438937254216944/report.json'
CONTROL=ROOT/'tests/cmac/test_selected_binary_prefix_bram_address_control.py'


def selected_definitions(data,kinds):
    assert set(kinds)==set(raw.COUNTS),'Changed actual primitive class inventory'
    first=data.index(b'\nmodule VCC(')
    header=data[:first+1]
    assert header.startswith(b'/*') and b'copyright notice' in header and b'module ' not in header
    records={}
    pattern=rb'(?m)^(?:\(\*[^\n]*\*\)\n)*module ([A-Za-z][A-Za-z0-9_]*)\b[^\n]*(?:\n(?!endmodule\b)[^\n]*)*\nendmodule\n'
    for match in re.finditer(pattern,data):
        kind=match[1].decode('ascii')
        if kind not in kinds:continue
        assert kind not in records,'Duplicate selected definition'
        block=match[0]
        assert b'`' not in block,'Unbound selected definition preprocessor context'
        records[kind]=dict(offset=match.start(),length=len(block),sha256=hashlib.sha256(block).hexdigest())
    assert set(records)==set(kinds),'Incomplete selected primitive definitions'
    selected=header+b'\n'+b'\n'.join(data[r['offset']:r['offset']+r['length']]
                                  for r in sorted(records.values(),key=lambda r:r['offset']))
    assert set(re.findall(rb'(?m)^module (\w+)',selected))=={kind.encode('ascii') for kind in kinds}
    assert len(re.findall(rb'(?m)^endmodule$',selected))==len(kinds)
    for record in records.values():
        block=data[record['offset']:record['offset']+record['length']]
        assert selected.count(block)==1 and hashlib.sha256(block).hexdigest()==record['sha256']
    return selected,records


def verify_failed(before):
    witness,cone,cuts,miter=previous.verify_failed(before)
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='qualified_library_actual_binary_SAT' and report['finished_utc']
    assert report['error']=='AssertionError()'
    expected=['software_controls','generated_check','yosys_version','iverilog_version','vvp_version',
              'vendor_compile','vendor_binary_test','synthesis_compile','synthesis_binary_test',
              'synthesis_wrong_golden_test','negative']
    assert [step['label'] for step in report['commands']]==expected
    assert all(step['returncode']==0 and step['status']=='PASS_TOOL_EXECUTION_ONLY' for step in report['commands'][:-1])
    step=report['commands'][-1]
    assert step['returncode']==1 and step['status']=='FAIL'
    log=Path(step['log']).read_text()
    assert raw.base.FAILURE in log and raw.base.SUCCESS not in log
    assert re.findall(r'(?m)^ERROR: (.*)$',log)==['Called with -verify and proof did fail!']
    assert re.findall(r'(?m)^.*Warning:.*$',log)==[
        str(FAILED.parent/'unchanged_xilinx_cells_sim.v')+':84: Warning: Yosys has only limited support for tri-state logic at the moment.',
        str(FAILED.parent/'unchanged_xilinx_cells_sim.v')+':102: Warning: Yosys has only limited support for tri-state logic at the moment.']
    assert report['binary_library_qualification']['per_instance_binary_comparisons']==570368
    assert report['binary_library_real_wrong_golden_negative']=='REJECTED_EXACT_FIRST_VECTOR_ONE_BIT_MUTATION'
    assert 'address_decoder_binary_cut_proved' not in report
    bind_report(FAILED,report,before);verify_bindings(before)
    assert (FAILED.parent/'unchanged_xilinx_cells_sim.v').read_bytes()==raw.LIBRARY.read_bytes()
    return dict(**witness,preserved_unused_tri_state_library_warning_failure_report=str(FAILED),
                original_strict_warning_gate_unchanged=True),cone,cuts,miter


OLD_LIBRARY="        frozen_library=out/'unchanged_xilinx_cells_sim.v'; shutil.copyfile(LIBRARY,frozen_library)\n"
NEW_LIBRARY="""        full_library=out/'unchanged_xilinx_cells_sim.v'; shutil.copyfile(LIBRARY,full_library)
        selected,definitions=selected_definitions(full_library.read_bytes(),set(COUNTS))
        frozen_library=out/'unchanged_selected_combinational_cells.v'; frozen_library.write_bytes(selected)
        report['selected_unchanged_library_definitions']=definitions
        report['complete_original_library_retained']=str(full_library)
"""
NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
               verify_failed=verify_failed,selected_definitions=selected_definitions)
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,(
    ('prefix-bram-address-binary-result-resume-','prefix-bram-address-selected-binary-resume-'),
    (OLD_LIBRARY,NEW_LIBRARY),
    ('[bench,frozen_library,*vendor_files]','[bench,full_library,frozen_library,*vendor_files]')))
exec(compile(MAIN_SOURCE,__file__+':unchanged-selected-definitions-proof-main','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
