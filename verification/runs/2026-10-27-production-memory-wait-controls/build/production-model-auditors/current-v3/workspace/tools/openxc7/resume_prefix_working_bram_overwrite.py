#!/usr/bin/env python3
"""Continue the same primitive corpus with the actual integer-width admission key.

The preserved first run fails KeyError('9') before recording input bindings or
executing a native command. Record that provenance limitation honestly; freeze
the still-unchanged original helper now as a post-failure observation, not as
an executed snapshot from that old run. Reproduce its read-only failure in
controls. Replace only the string lookup with the checker-created integer 9;
keep the full target, parameter/alias contracts, complete native corpus,
default GSR, warning and real-negative gates and resource/time limits.
Snapshot the new source and derived main before admission. No old helper,
RTL/input/model/live job, error expectation or SHA256SUMS file is modified.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_prefix_working_bram_overwrite as previous
from audit_empty_output_pairs import source_shaped

FAILED=previous.ROOT/'build/openxc7/prefix-working-bram-overwrite-1791440422211967208/report.json'
CONTROL=previous.ROOT/'tests/cmac/test_resumed_working_bram_overwrite_control.py'
OLD_KEY="checks['working_RAM_by_consumed_width']['9']"
NEW_KEY="checks['working_RAM_by_consumed_width'][9]"
ADMISSION_SOURCE=source_shaped(inspect.getsource(previous.admitted_inputs),((OLD_KEY,NEW_KEY),))
FUNCTION_NAMESPACE=dict(vars(previous))
exec(compile(ADMISSION_SOURCE,__file__+':integer-key-admission','exec'),FUNCTION_NAMESPACE)
fixed_admitted_inputs=FUNCTION_NAMESPACE['admitted_inputs']


def observe_failure():
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='admission' and report['finished_utc']
    assert report['error']=="KeyError('9')" and report['commands']==[]
    assert report['source']=={} and report['artifacts']=={}
    assert report['working_BRAM_model_overwrite_fixture_acceptance'] is False
    assert report['hardware_input_modified'] is False and report['bitstream_emitted'] is False
    return dict(terminal_failed_report=str(FAILED),original_input_bindings_recorded=False,
        original_executed_source_snapshot_recorded=False,native_commands_executed=0,
        observed_original_helper_after_failure=str(Path(previous.__file__).resolve()),
        observed_original_helper_after_failure_sha256=previous.digest(previous.__file__),
        original_source_not_relabelled_as_old_executed_snapshot=True)


def admitted_inputs(before):
    observe_failure()
    before[str(FAILED)]=previous.digest(FAILED)
    before[str(Path(previous.__file__).resolve())]=previous.digest(previous.__file__)
    return fixed_admitted_inputs(before)


OLD_SAVE="    save();print(out/'report.json',flush=True)\n    signal.signal"
NEW_SAVE="""    report['preserved_admission_failure']=observe_failure()
    shutil.copyfile(__file__,out/'executed_source.py')
    shutil.copyfile(CONTROL,out/'executed_control_source.py')
    shutil.copyfile(previous.__file__,out/'observed_previous_source_after_failure.py')
    (out/'executed_main.py').write_text(MAIN_SOURCE)
"""+OLD_SAVE
MAIN_SOURCE=source_shaped(inspect.getsource(previous.main),(
    ('prefix-working-bram-overwrite-','prefix-working-bram-overwrite-resume-'),(OLD_SAVE,NEW_SAVE)))
NAMESPACE=dict(vars(previous),__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
               admitted_inputs=admitted_inputs,observe_failure=observe_failure,previous=previous,
               MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE,__file__+':unchanged-corpus-main','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
