#!/usr/bin/env python3
"""Retry the unchanged full address proof after a source-bound namespace error.

Preserve the actual NameError and all old sources/gates. Supply only the frozen
base-module binding to an independent derived-function namespace; validate
that exact function in host controls, then execute the complete full census,
unchanged-model SAT and real negative. No RTL/input/limit/model/SHA256SUMS edit.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import prove_full_budget_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

FAILED = previous.base.ROOT / 'build/openxc7/prefix-bram-address-full-budget-proof-1791437421979606743/report.json'
CONTROL = previous.base.ROOT / 'tests/cmac/test_resumed_prefix_bram_address_control.py'
PASS = 'PROVED_ACTUAL_FULL_PREFIX_COHERENT_BINARY_BRAM_ADDRESS_WITH_FROZEN_NAMESPACE_BINDING_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'


def verify_failed(before):
    witness=previous.verify_failed(before)
    report=json.loads(FAILED.read_text())
    assert report['status']=='FAIL' and report['stage']=='actual_full_driver_census_and_address_cone' and report['finished_utc']
    assert report['error']==repr(NameError("name 'base' is not defined"))
    assert [c['label'] for c in report['commands']]==['software_controls','generated_check','yosys_version']
    assert all(c['returncode']==0 and c['status']=='PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])
    assert report['symbolic_binary_input_bits'] is None and 'address_decoder_binary_cut_proved' not in report
    bind_report(FAILED,report,before);verify_bindings(before)
    return dict(**witness,preserved_namespace_failure_report=str(FAILED),only_missing_base_namespace_binding_added=True)


NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,PASS=PASS,
               verify_failed=verify_failed,base=previous.base)
exec(compile(previous.TRACE_SOURCE,__file__ + ':unchanged-full-census-trace','exec'),NAMESPACE)
trace_coherent=NAMESPACE['trace_coherent']
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,
    (('prefix-bram-address-full-budget-proof-','prefix-bram-address-full-budget-resume-'),))
NAMESPACE['MAIN_SOURCE']=MAIN_SOURCE


def main():
    exec(compile(MAIN_SOURCE,__file__ + ':unchanged-full-census-main','exec'),NAMESPACE)
    NAMESPACE['main']()


if __name__=='__main__':main()
