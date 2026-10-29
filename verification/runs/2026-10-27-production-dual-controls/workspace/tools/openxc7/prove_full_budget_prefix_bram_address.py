#!/usr/bin/env python3
"""Actual coherent address proof budgeted for the full retained mapped circuit.

Preserve/recheck the third actual attempt's software cone-budget failure.
Increase only this read-only proof harness's cell/input capacity to the exact
full physical-input census: at most 503128 cells and 42239 known producer bits
(17519 register Q plus 515*48 DSP P). Keep every source/primitive/wire guard,
four-aperture contract, complete shared cone and SAT/real-negative gate. The
old limit and old failure remain untouched. Native SAT/wall/memory limits are
not increased; this is no FPGA timing/resource/DRC/electrical waiver, runtime
fixup, physical transformation or startup/numerical acceptance. No SHA256SUMS.
"""
from collections import Counter
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import prove_coherent_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

base = previous.base
FAILED = base.ROOT / 'build/openxc7/prefix-bram-address-coherent-proof-1791437025464486188/report.json'
CONTROL = base.ROOT / 'tests/cmac/test_full_budget_prefix_bram_address_control.py'
PASS = 'PROVED_ACTUAL_FULL_PREFIX_FULL_CENSUS_BUDGET_COHERENT_BINARY_BRAM_ADDRESS_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'


def census_limits(counts):
    assert sum(counts.values()) == 503128 and counts['DSP48E1'] == 515 and counts['RAMB36E1'] == 6
    registers = sum(counts[kind] for kind in previous.RESET_PIN)
    assert registers == 17519
    return dict(maximum_actual_cells=sum(counts.values()),
                maximum_known_binary_producer_bits=registers+48*counts['DSP48E1'],
                actual_register_Q_bits=registers, actual_DSP_P_bits=48*counts['DSP48E1'])


LIMITS = census_limits(json.loads(base.INVENTORY.read_text())['actual_primitive_counts'])
OLD_LIMIT = "    assert nodes and cuts and len(cuts) <= 512 and len(nodes) <= 20000, 'Missing/unbounded coherent producer cut'\n"
NEW_LIMIT = """    assert nodes and cuts and len(cuts) <= LIMITS['maximum_known_binary_producer_bits'] and len(nodes) <= LIMITS['maximum_actual_cells'], 'Missing/out-of-full-census coherent producer cut'
"""


def verify_failed(before):
    witness = previous.verify_failed(before)
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'actual_full_driver_census_and_address_cone' and report['finished_utc']
    assert report['error'] == "AssertionError('Missing/unbounded coherent producer cut')"
    assert [c['label'] for c in report['commands']] == ['software_controls','generated_check','yosys_version']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])
    assert report['symbolic_binary_input_bits'] is None and 'address_decoder_binary_cut_proved' not in report
    assert report['original_failure_relabelled'] is False
    bind_report(FAILED,report,before);verify_bindings(before)
    assert LIMITS == census_limits(json.loads(base.INVENTORY.read_text())['actual_primitive_counts'])
    return dict(**witness, preserved_software_cone_budget_failure_report=str(FAILED),
                original_probe_max_cells=20000, original_probe_max_bits=512,
                full_actual_census_proof_budget=LIMITS,
                FPGA_resources_and_SAT_timing_limits_unchanged=True)


NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 PASS=PASS, verify_failed=verify_failed, LIMITS=LIMITS,
                 RESET_PIN=previous.RESET_PIN, validate_producer=previous.validate_producer,
                 validate_cell=previous.validate_cell)
TRACE_SOURCE = source_shaped(inspect.getsource(previous.trace_coherent), ((OLD_LIMIT,NEW_LIMIT),))
exec(compile(TRACE_SOURCE,__file__ + ':full-census-coherent-trace','exec'),NAMESPACE)
trace_coherent = NAMESPACE['trace_coherent']
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE,
    (('prefix-bram-address-coherent-proof-','prefix-bram-address-full-budget-proof-'),))
NAMESPACE['MAIN_SOURCE']=MAIN_SOURCE


def main():
    exec(compile(MAIN_SOURCE,__file__ + ':full-census-coherent-main','exec'),NAMESPACE)
    NAMESPACE['main']()


if __name__=='__main__':main()
