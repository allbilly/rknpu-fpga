#!/usr/bin/env python3
"""Recognize the exact Icarus normal finish record, then qualify libraries/SAT.

Preserve the seventh native failure. Both complete binary runs ended normally,
but their additional native $finish informational records failed the literal
1024-line parser. Require the precise generated source path/line, default-GSR
completion time and unit as a separate record, then use the original strict
corpus comparator. No warning, error, X/Z, missing/reordered vector or wrong
result is admitted. Bench, primitive libraries, actual cone/miter and original
SAT limits/positive/real-negative gates stay unchanged. Binary only, not
temporal/startup, numerical, physical or hardware acceptance. No SHA256SUMS.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import resume_declared_binary_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

raw=previous.previous
ROOT=raw.ROOT
FAILED=ROOT/'build/openxc7/prefix-bram-address-declared-binary-resume-1791438732760601100/report.json'
CONTROL=ROOT/'tests/cmac/test_binary_result_prefix_bram_address_control.py'


def expected_finish(bench,text):
    lines=text.splitlines()
    assert lines.count('$finish;')==1
    return str(bench)+':'+str(lines.index('$finish;')+1)+': $finish called at 1125000 (1ps)'


def corpus(text,footer):
    lines=text.splitlines()
    assert len(lines)==1025 and lines[-1]==footer,'Missing/changed native normal finish record'
    return '\n'.join(lines[:-1])+'\n'


def vectors(text,width,footer): return raw.vectors(corpus(text,footer),width)


def compare_vectors(vendor,synthesis,width,footer):
    return raw.compare_vectors(corpus(vendor,footer),corpus(synthesis,footer),width)


def verify_failed(before):
    witness,cone,cuts,miter=previous.verify_failed(before)
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='unchanged_libraries_actual_binary_qualification' and report['finished_utc']
    assert report['error']=="AssertionError('Incomplete binary model corpus')"
    expected=['software_controls','generated_check','yosys_version','iverilog_version','vvp_version',
              'vendor_compile','vendor_binary_test','synthesis_compile','synthesis_binary_test']
    assert [step['label'] for step in report['commands']]==expected
    assert all(step['returncode']==0 and step['status']=='PASS_TOOL_EXECUTION_ONLY' for step in report['commands'])
    assert 'binary_library_qualification' not in report and 'address_decoder_binary_cut_proved' not in report
    bind_report(FAILED,report,before);verify_bindings(before)
    bench_text,width=previous.qualify_bench(cone['cells'])
    bench=FAILED.parent/'binary_library_control.sv'
    assert bench.read_text()==bench_text and width==753
    footer=expected_finish(bench,bench_text)
    for label in ('vendor_binary_test','synthesis_binary_test'):
        text=(FAILED.parent/(label+'.log')).read_text()
        vectors(text,width,footer)
        try:raw.vectors(text,width)
        except AssertionError as error:assert str(error)=='Incomplete binary model corpus'
        else:raise AssertionError('Old native parser failure not reproduced')
    return dict(**witness,preserved_native_finish_format_failure_report=str(FAILED),
                exact_native_finish_record_separate_from_1024_vectors=True),cone,cuts,miter


OLD_COMPARE="compare_vectors(outputs['vendor'],outputs['synthesis'],width)"
OLD_VECTOR="vectors(outputs['vendor'],width); wrong=vectors(negative,width)"
OLD_NEGATIVE="compare_vectors(outputs['vendor'],negative,width)"
OLD_BENCH="bench=out/'binary_library_control.sv'; bench.write_text(bench_text)\n"
NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
               verify_failed=verify_failed,vectors=vectors,compare_vectors=compare_vectors,
               expected_finish=expected_finish)
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,(
    ('prefix-bram-address-declared-binary-resume-','prefix-bram-address-binary-result-resume-'),
    (OLD_BENCH,OLD_BENCH+"        footer=expected_finish(bench,bench_text)\n"),
    (OLD_COMPARE,OLD_COMPARE[:-1]+',footer)'),
    (OLD_VECTOR,"vectors(outputs['vendor'],width,footer); wrong=vectors(negative,width,footer)"),
    (OLD_NEGATIVE,OLD_NEGATIVE[:-1]+',footer)')))
exec(compile(MAIN_SOURCE,__file__+':exact-normal-finish-proof-main','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
