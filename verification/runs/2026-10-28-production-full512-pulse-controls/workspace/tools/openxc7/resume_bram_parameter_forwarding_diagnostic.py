#!/usr/bin/env python3
"""Correct VVP root scope and explicit output-width extension in the diagnosis.

Preserve the previous source-bound parser FAIL and original cold-state FAIL.
The VVP root record has one source location, not the two used by child scopes.
The unchanged model forwards unsigned 36-bit INIT/SRVAL into 72-bit internal
parameters: compare the mandated zero extension, not unequal string lengths.
No HDL, compiled input, vendor model, simulation expectation or acceptance
gate is changed. The same minimal independent native forwarding bench runs.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import diagnose_bram_parameter_forwarding as previous
from audit_empty_output_pairs import source_shaped

PARSER_FAILURE=previous.previous.ROOT/'build/openxc7/bram-parameter-forwarding-diagnostic-1791441669153784348/report.json'
CONTROL=previous.previous.ROOT/'tests/cmac/test_bram_parameter_forwarding_diagnostic_control.py'
OLD_ROOT=r'[^"]+" [^,]+,[^,]+(?:, [^,]+)?;'
NEW_ROOT=r'[^"]+" [^,;]+(?:, [^,;]+)?;'
PARSER_SOURCE=source_shaped(inspect.getsource(previous.parameter_tables),((OLD_ROOT,NEW_ROOT),))
FUNCTIONS=dict(vars(previous))
exec(compile(PARSER_SOURCE,__file__+':root-scope-reader','exec'),FUNCTIONS)
OLD_COMPARE="a[key][-len(b[key]):]!=b[key]"
NEW_COMPARE="a[key].zfill(len(b[key]))[-len(b[key]):]!=b[key]"
RECORDS_SOURCE=source_shaped(inspect.getsource(previous.forwarding_records),((OLD_COMPARE,NEW_COMPARE),))
exec(compile(RECORDS_SOURCE,__file__+':explicit-unsigned-width-comparison','exec'),FUNCTIONS)
parameter_tables=FUNCTIONS['parameter_tables'];forwarding_records=FUNCTIONS['forwarding_records']


def observe_parser_failure():
    report=json.loads(PARSER_FAILURE.read_text())
    assert report['status']=='FAIL' and report['stage']=='observe' and report['finished_utc']
    assert report['error']=="KeyError('tb_prefix_working_bram_overwrite.mapped.actual_0')"
    assert [c['label'] for c in report['commands']]==['generated_check','iverilog_version','vvp_version','compile']
    assert all(c['returncode']==0 for c in report['commands'])
    assert report['observation_only'] and report['working_BRAM_model_overwrite_fixture_acceptance'] is False
    return dict(report=str(PARSER_FAILURE),native_bench_executed=False,failed_parser_not_relabelled=True)


OLD_BEFORE="        before={};bind_report(FAILED,failed,before)"
NEW_BEFORE=OLD_BEFORE+"""
        report['preserved_parser_failure']=observe_parser_failure()
        before[str(PARSER_FAILURE)]=digest(PARSER_FAILURE)
        before[str(CONTROL)]=digest(CONTROL)
        shutil.copyfile(CONTROL,out/'executed_control_source.py')
        shutil.copyfile(previous.__file__,out/'preserved_previous_source.py')
        (out/'executed_parser_source.py').write_text(PARSER_SOURCE)
        (out/'executed_record_comparison.py').write_text(RECORDS_SOURCE)
        (out/'executed_main.py').write_text(MAIN_SOURCE)
"""
OLD_GENERATED="        report['stage']='generated_check';save();run('generated_check',['make','generated-check'])"
NEW_GENERATED="""        report['stage']='software_controls';save()
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
"""+OLD_GENERATED
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,(
    ('bram-parameter-forwarding-diagnostic-','bram-parameter-forwarding-resume-'),
    (OLD_BEFORE,NEW_BEFORE),(OLD_GENERATED,NEW_GENERATED)))
NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,
    forwarding_records=forwarding_records,PARSER_FAILURE=PARSER_FAILURE,
    observe_parser_failure=observe_parser_failure,CONTROL=CONTROL,previous=previous,
    PARSER_SOURCE=PARSER_SOURCE,RECORDS_SOURCE=RECORDS_SOURCE,MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE,__file__+':unchanged-forwarding-diagnostic-main','exec'),NAMESPACE)


if __name__=='__main__':NAMESPACE['main']()
