"""Read-only fresh full corrected-mux route admission, not PASS-label/signoff.

Keep every original source/placement/v2-scan/router/circuit/feature check.
Require the new graph's completed full placement and own full-pack census,
never the retired fixed count. No native execution, conversion or FPGA access.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_counter_safe_shared_route as previous
import route_recursive_mux_prefix_shared_board as route
from audit_empty_output_pairs import source_shaped

ROOT = route.ROOT
PROFILE = previous.PROFILE
assert PROFILE in route.MAIN_SOURCE


def route_cell_count(report):
    path = (ROOT / report['placed_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-place-')
    placed = json.loads(path.read_text())
    route.verify_placed_metadata(placed)
    return route.own_pack(placed)['native_census']['cells']


METADATA_REPLACEMENTS = (
    ("r['full_bound_cells']==523410", "r['full_bound_cells']==route_cell_count(r)"),
    ("resource['unchanged_physical_bel_assignments']==523410",
     "resource['unchanged_physical_bel_assignments']==route_cell_count(r)"),
    ("r['original_logical_circuit_identity']['logical_board']['cells']==523410",
     "r['original_logical_circuit_identity']['logical_board']['cells']==route_cell_count(r)"),
)
METADATA_SOURCE = source_shaped(previous.METADATA_SOURCE, METADATA_REPLACEMENTS)
METADATA_NAMESPACE = dict(previous.METADATA_NAMESPACE, route=route, route_cell_count=route_cell_count)
exec(compile(METADATA_SOURCE, __file__ + ':same-full-native-metadata-own-bound-census', 'exec'), METADATA_NAMESPACE)


def verify_metadata(report):
    METADATA_NAMESPACE['verify_metadata'](report)
    assert report['recursive_mux_and_counter_safe_placement_parent_chain_revalidated'] is True
    assert report['corrected_DSP_route_base_parent_chain_revalidated'] is True
    path = Path(report['recursive_mux_placement_engine_build_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-native-io-engine-')


REPLACEMENTS = (("route.NAMESPACE['check_full_scan'](text,523410,",
                 "route.NAMESPACE['check_full_scan'](text,r['full_bound_cells'],"),)
VERIFY_SOURCE = source_shaped(previous.VERIFY_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, route=route, PROFILE=PROFILE,
                 bind_report=route.bind_report, verify_metadata=verify_metadata)
exec(compile(VERIFY_SOURCE, __file__ + ':all-original-route-artifact-and-feature-revalidation', 'exec'), NAMESPACE)
verify_route = NAMESPACE['verify_route']
