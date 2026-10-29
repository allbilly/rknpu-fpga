#!/usr/bin/env python3
"""Prepared full C32/K16 v2 literal-checkpoint scan/route, not signoff.

Derive the frozen corrected full-route procedure with exact reversible changes:
new output directory/profile, completed corrected-fixture v2 qualification,
read-only declaration/pair/carry audits and an exact native import census.
Keep all full 538118-cell/515-DSP/six-BRAM/16-kernel, actual routed identity,
FASM, router connectivity, 50 MHz and later physical/numerical gates. Never
execute a comparison view or repair actual connected inputs. No SHA256SUMS
file or FPGA/flash access. A prepared runner is not a completed full route.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_strict_search_board as original
from audit_empty_output_pairs import audit_pairs, local_carry_roles, source_shaped
from empty_output_candidate import literal_outputs
from verify_empty_output_evidence import QUALIFIED, verify_qualification

CONTROL = original.ROOT / 'tests/cmac/test_empty_output_full_route.py'
ROUTED = 'ROUTED_FULL_C32K16_V2_LITERAL_EMPTY_OUTPUT_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
OLD_PROFILE = 'rknpu-check-imported-placement=fixed-lut-v1'
NEW_PROFILE = 'rknpu-check-imported-placement=fixed-lut-v2'
OLD_DIRECTORY = 'full-prefix-corrected-scan-route-'
NEW_DIRECTORY = 'full-prefix-literal-empty-v2-scan-route-'
OLD_SAVE = "    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\\n')\n"
NEW_SAVE = """    (out / 'executed_prepared_main.py').write_text(MAIN_SOURCE)
    report['prepared_main_source_sha256'] = digest(out / 'executed_prepared_main.py')
    report['native_v2_literal_LUT_output_declarations_imported'] = False
""" + OLD_SAVE
OLD_PAIRS = '        del pairs, roles\n'
NEW_PAIRS = """        report['literal_disconnected_LUT_outputs'] = sum(len(literal_outputs(cell))
            for cell in module['cells'].values() if cell['type'] == 'SLICE_LUTX')
""" + OLD_PAIRS
OLD_SCAN = "        check_full_scan(log, report['full_bound_cells'], report['fixed_logic_pairs'], report['expected_local_carry_DI_roles'])\n"
NEW_SCAN = OLD_SCAN + """        check_import_count(log, report['literal_disconnected_LUT_outputs'])
        report['native_v2_literal_LUT_output_declarations_imported'] = True
"""
REPLACEMENTS = ((OLD_DIRECTORY, NEW_DIRECTORY), (OLD_PROFILE, NEW_PROFILE),
                (OLD_SAVE, NEW_SAVE), (OLD_PAIRS, NEW_PAIRS), (OLD_SCAN, NEW_SCAN))


def check_import_count(text, count):
    assert type(count) is int and count >= 0
    marker = f'RKNPU empty-output import: preserved {count} literal disconnected LUT outputs; connected graph unchanged.'
    assert text.count(marker) == 1, 'Missing exact full literal-output native import census'
    assert text.index(marker) < text.index('RKNPU imported placement scan: begin before clock/general routing.')


def prepared_main_source(source):
    assert source == inspect.getsource(original.main), 'Changed frozen full-route procedure'
    result = source_shaped(source, REPLACEMENTS)
    for gate in ('verify_placed_metadata(placed)', 'verify_placed_module(', 'verify_full_features(',
                 'assert_circuit_identity(', 'verify_routed_footprint(', 'verify_bindings(before)',
                 'checker.checkpoint.resume_argv(', "run('native_scan_and_route', argv, 43200)"):
        assert result.count(gate) == source.count(gate) and result.count(gate) > 0
    return result


MAIN_SOURCE = prepared_main_source(inspect.getsource(original.main))


def main():
    # Independent namespace; do not mutate the frozen module or a live process.
    namespace = dict(original.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
        SMALL=QUALIFIED, ROUTED=ROUTED, MAIN_SOURCE=MAIN_SOURCE, audit_pairs=audit_pairs,
        local_carry_roles=local_carry_roles, literal_outputs=literal_outputs,
        verify_small_evidence=verify_qualification, check_import_count=check_import_count)
    exec(compile(MAIN_SOURCE, __file__ + ':prepared-main', 'exec'), namespace)
    namespace['main']()


if __name__ == '__main__': main()
