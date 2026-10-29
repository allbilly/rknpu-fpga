#!/usr/bin/env python3
"""Continue the unchanged binary-library/address proof after a bench-order bug.

Preserve the sixth actual failure and every old source. Move only the unchanged
testbench initial block after its output declaration, with a reversible text
check and actual Icarus compile controls against both libraries. Primitive
instances/functions, parameters, vectors, startup, real negative, actual miter
and native limits are unchanged. Not four-state, startup, numeric or physical
signoff. No hardware source/input or standalone SHA256SUMS is changed.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import resume_binary_library_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

FAILED=previous.ROOT/'build/openxc7/prefix-bram-address-binary-library-resume-1791438584044546240/report.json'
CONTROL=previous.ROOT/'tests/cmac/test_declared_binary_prefix_bram_address_control.py'


def qualify_bench(nodes):
    text,width=previous.qualify_bench(nodes)
    lines=text.splitlines(keepends=True)
    assert lines[4]=='initial begin\n' and lines[13]=='end\n'
    assert lines[14].startswith('wire [') and lines[-1]=='endmodule\n'
    assert lines[-2].startswith('wire [') and ' observed = ' in lines[-2]
    result=''.join(lines[:4]+lines[14:-1]+lines[4:14]+lines[-1:])
    # Reorder only: no expression, stimulus, function, instance or gate changes.
    rebuilt=result.splitlines(keepends=True)
    assert ''.join(rebuilt[:4]+rebuilt[-11:-1]+rebuilt[4:-11]+rebuilt[-1:])==text
    return result,width


def verify_failed(before):
    witness,cone,cuts,miter=previous.verify_failed(before)
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='unchanged_libraries_actual_binary_qualification' and report['finished_utc']
    expected=['software_controls','generated_check','yosys_version','iverilog_version','vvp_version','vendor_compile']
    assert [step['label'] for step in report['commands']]==expected
    assert all(step['returncode']==0 and step['status']=='PASS_TOOL_EXECUTION_ONLY' for step in report['commands'][:-1])
    step=report['commands'][-1]
    assert step['returncode']==1 and step['status']=='FAIL'
    log=Path(step['log']).read_text()
    assert "Unable to bind wire/reg/memory `observed'" in log and 'declaration after use' in log
    assert len(re.findall(r'error\(s\) during elaboration',log))==1
    assert 'binary_library_qualification' not in report and 'address_decoder_binary_cut_proved' not in report
    bind_report(FAILED,report,before);verify_bindings(before)
    bench,width=previous.qualify_bench(cone['cells'])
    assert bench==(FAILED.parent/'binary_library_control.sv').read_text() and width==753
    return dict(**witness,preserved_bench_declaration_order_failure_report=str(FAILED),
                only_test_initial_block_moved_after_declarations=True),cone,cuts,miter


NAMESPACE=dict(vars(previous),__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
               verify_failed=verify_failed,qualify_bench=qualify_bench)
MAIN_SOURCE=source_shaped(inspect.getsource(previous.main),
    (('prefix-bram-address-binary-library-resume-','prefix-bram-address-declared-binary-resume-'),))
exec(compile(MAIN_SOURCE,__file__+':unchanged-binary-proof-main','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
