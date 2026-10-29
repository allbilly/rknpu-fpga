"""Revalidate the own full counter-safe shared route, not a PASS label/signoff.

Keep the original route/scan/circuit/feature verification body. Select only the
completed new full shared route and fresh engine qualification, use its actual
523410-cell census and own 515-DSP/six-BRAM input, and recheck the corrected
placement limit/checksum and qualified routing-base chain. No tool, circuit,
native P&R, frame conversion, bitstream or physical acceptance occurs here.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_full_heap_route as previous
import route_counter_safe_prefix_shared_board as route
from audit_empty_output_pairs import source_shaped

ROOT = route.ROOT
PROFILE = 'rknpu-check-imported-placement=fixed-lut-v2'
assert PROFILE in route.MAIN_SOURCE
METADATA_SOURCE = inspect.getsource(previous.verify_metadata)
assert METADATA_SOURCE.count('538118') == 3
METADATA_SOURCE = METADATA_SOURCE.replace('538118', str(route.CELLS))
METADATA_NAMESPACE = dict(previous.__dict__, route=route)
exec(compile(METADATA_SOURCE, __file__ + ':same-full-route-metadata-current-census', 'exec'), METADATA_NAMESPACE)


def verify_metadata(report):
    METADATA_NAMESPACE['verify_metadata'](report)
    assert report['counter_safe_placement_only_HeAP_limit_expression_changed'] is True
    assert report['corrected_DSP_route_base_parent_chain_revalidated'] is True
    path = Path(report['counter_safe_placement_engine_build_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('counter-safe-heap-engine-')


REPLACEMENTS = (
    ("route.placement.qualified.verify_qualification(Path(placed['qualified_engine_report']))",
     "route.placement.qualification.verify_qualification(Path(placed['qualification']))"),
    ('route.previous.verify_qualification(before)', "route.NAMESPACE['verify_small_evidence'](before)"),
    ('route.previous.NEW_PROFILE', 'PROFILE'),
    ('route.check_full_scan(text,538118,', "route.NAMESPACE['check_full_scan'](text,523410,"),
    ('route.previous.check_import_count(', "route.NAMESPACE['check_import_count']("),
    ('route.clock_contracts(module)', "route.NAMESPACE['clock_contracts'](module)"),
    ('    selected=json.loads(checker.checkpoint.SELECTED.read_text())',
     "    selected=route.NAMESPACE['selected_inputs'](placed,before)"),
    ('route.verify_full_features(', "route.NAMESPACE['verify_full_features']("),
)
VERIFY_SOURCE = source_shaped(inspect.getsource(previous.verify_route), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, route=route, PROFILE=PROFILE,
                 bind_report=route.bind_report, verify_metadata=verify_metadata)
exec(compile(VERIFY_SOURCE, __file__ + ':same-native-full-route-source-revalidation', 'exec'), NAMESPACE)
verify_route = NAMESPACE['verify_route']
