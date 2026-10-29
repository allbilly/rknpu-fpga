#!/usr/bin/env python3
"""Fresh WHOLE production regression with private generated-C++ OPT_FAST=-O0.

Preserve the failed default run, every production source/stimulus and original
whole-test/simulator/numerical/warning/deadline guard. Only this private make
invocation sets Verilator's documented generated-C++ optimization variables.
The reference C++ model retains the Makefile's -O2/-Wall/-Wextra/-Werror flags.
No RTL/model/golden/BO/layout/physical constraint or default tool is changed.
All five original numerical/native reports remain mandatory for acceptance.
This is not shared full-board numerical, physical FPGA or RK acceptance.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_source_identical_production_regression as previous
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
PARENT = ROOT / 'build/source-identical-production-regression/1791508511941204286/report.json'
CONTROL = ROOT / 'tests/cmac/test_source_identical_production_opt0_control.py'
VERILATED_MAKE = Path('/home/linuxbrew/.linuxbrew/Cellar/verilator/5.048/share/verilator/include/verilated.mk')
OPTIONS = ['OPT_FAST=-O0', 'OPT_SLOW=-O0']
PASS = 'PASS_SOURCE_IDENTICAL_COMPLETE_PRODUCTION_OPT0_REGRESSION_NOT_SHARED_BOARD_OR_FPGA'


def metadata(record):
    assert record['status'] == 'FAIL' and record['finished_utc'], 'Require completed failed default producer'
    assert record['actual_make_test_executed'] is True
    assert record['production_source_before'] == record['production_source_after']
    assert record['declared_source_files'] == 101
    assert len(record['commands']) == 1
    step = record['commands'][0]
    assert step['argv'] == ['make', '-j2', '-o', 'vectors', '-o', 'cmac-vectors', 'test']
    assert step['status'] == 'FAIL' and step['returncode'] == 2 and step['timeout_seconds'] == 7200
    assert 0 < step['seconds'] < 7200
    for flag in ('full_board_numerical_acceptance', 'physical_fit_verified', 'timing_signoff',
                 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
                 'hardware_programmed', 'hardware_input_modified'):
        assert record[flag] is False


def admission():
    record = json.loads(PARENT.read_text()); metadata(record)
    assert not Path(f'/proc/{record["supervisor_pid"]}').exists(), 'Default producer still live'
    assert not Path(f'/proc/{record["commands"][0]["pid"]}').exists(), 'Default make still live'
    assert previous.source_revision() == record['production_source_after']
    previous.verify_bindings(record['source']); previous.verify_bindings(record['execution_inputs'])
    assert (PARENT.parent / 'executed_source.py').read_text() == Path(previous.__file__).read_text()
    work = ROOT / record['source_identical_workspace']
    assert work.is_relative_to(PARENT.parent)
    for folder, target in (('rtl', 'tb_job_control'), ('cmac_verilator', 'tb_cmac_operand_front')):
        path = work / 'build' / folder / 'report.json'
        assert record['subreport_artifacts'][str(path.relative_to(ROOT))] == previous.digest(path)
        failed = json.loads(path.read_text())
        assert failed['status'] == 'FAIL' and failed['finished_utc']
        assert failed['source_revision'] == record['production_source_after']
        stopped = [c for c in failed['commands'] if c['status'] == 'TIMEOUT']
        assert len(stopped) == 1 and stopped[0]['argv'][stopped[0]['argv'].index('--top-module') + 1] == target
        assert 600 <= stopped[0]['seconds'] < 610
        log = work / stopped[0]['log']
        assert record['artifacts'][str(log.relative_to(ROOT))] == previous.digest(log)
        text = log.read_text()
        assert 'c++ -Os ' in text and re.search(r'Verilator: Walltime (?:[7-9][0-9][0-9]|[1-9][0-9]{3,})\.', text)
        assert ' -o sim\n' in text, 'Missing late default link evidence'
    template = VERILATED_MAKE.read_text()
    assert '\nOPT_FAST = -Os\n' in template and '\nOPT_SLOW =\n' in template
    assert '$(CXX) $(OPT_FAST) $(CXXFLAGS) $(CPPFLAGS)' in template
    assert '$(CXX) $(OPT_SLOW) $(CXXFLAGS) $(CPPFLAGS)' in template
    assert previous.REPORTS == {'numeric_report.json': 'PASS', 'rtl/report.json': 'PASS',
        'iverilog/report.json': 'PASS', 'cmac_verilator/report.json': 'PASS_RAW_PRODUCT_PATH_ONLY',
        'cmac_iverilog/report.json': 'PASS_RAW_PRODUCT_PATH_ONLY'}
    return record


REPLACEMENTS = (
    ("    out=ROOT/f'build/source-identical-production-regression/{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)\n",
     "    admitted=admission()\n    out=ROOT/f'build/source-identical-production-opt0/{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)\n"),
    ("        production_source_before=source_revision(),source={},execution_inputs={},actual_make_test_executed=False,\n",
     "        production_source_before=source_revision(),source={},execution_inputs={},actual_make_test_executed=False,\n"
     "        failed_default_report=str(PARENT), private_generated_CPP_make_options=OPTIONS,\n"
     "        original_per_tool_deadlines_unchanged=True, reference_CXX_flags_unchanged=True,\n"),
    ("        shutil.copyfile(__file__,out/'executed_source.py')\n",
     "        shutil.copyfile(__file__,out/'executed_source.py')\n"
     "        shutil.copyfile(CONTROL,out/'executed_control_source.py')\n"
     "        (out/'executed_prepared_main.py').write_text(MAIN_SOURCE)\n"),
    ("        before={};copied={};sources=report['production_source_before']['files']\n",
     "        before={str(PARENT):digest(PARENT), str(VERILATED_MAKE):digest(VERILATED_MAKE),\n"
     "            str(CONTROL):digest(CONTROL), str(Path(previous.__file__).resolve()):digest(previous.__file__)}\n"
     "        copied={};sources=report['production_source_before']['files']\n"),
    ("        argv=['make','-j2','-o','vectors','-o','cmac-vectors','test']\n",
     "        argv=['make','-j2','-o','vectors','-o','cmac-vectors',*OPTIONS,'test']\n"),
    ('PASS_UNCHANGED_COMPLETE_PRODUCTION_REGRESSION_ONLY_NOT_EXPERIMENTAL_BOARD_OR_FPGA', PASS),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    previous=previous, PARENT=PARENT, VERILATED_MAKE=VERILATED_MAKE, OPTIONS=OPTIONS,
    MAIN_SOURCE=MAIN_SOURCE, admission=admission)
exec(compile(MAIN_SOURCE, __file__ + ':all-original-whole-test-guards-private-generated-CXX-optimization', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
