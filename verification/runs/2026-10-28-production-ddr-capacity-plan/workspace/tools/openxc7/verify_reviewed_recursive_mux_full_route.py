"""Read-only reviewed full-route revalidation, not a status-label acceptance.

Require the independently reviewed complete original placement and the actual
new full v2 scan/route. Preserve every qualified full-target source, command,
checkpoint, logical/physical identity, DSP/BRAM and clock-feature guard. Keep
original failed execution history separate and immutable. No native tool,
frame conversion, bitstream, physical signoff or FPGA/flash access follows.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_recursive_mux_shared_route as previous
import route_reviewed_recursive_mux_full_board as route
from audit_empty_output_pairs import source_shaped

ROOT = route.ROOT
PROFILE = previous.PROFILE
assert PROFILE in route.MAIN_SOURCE


def route_cell_count(report):
    path = (ROOT / report['placed_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-recursive-mux-valid-pack-completed-placement-review-')
    placed = json.loads(path.read_text())
    route.verify_placed_metadata(placed)
    return route.own_pack(placed)['native_census']['cells']


# The complete prior native metadata body already derives all three whole-
# circuit censuses from actual packing. Change only its reviewed producer.
METADATA_SOURCE = previous.METADATA_SOURCE
METADATA_NAMESPACE = dict(previous.METADATA_NAMESPACE, route=route, route_cell_count=route_cell_count)
exec(compile(METADATA_SOURCE, __file__ + ':same-all-full-native-metadata-reviewed-producer', 'exec'), METADATA_NAMESPACE)
WRAPPER_SOURCE = inspect.getsource(previous.verify_metadata)
WRAPPER_NAMESPACE = dict(previous.__dict__, route=route, METADATA_NAMESPACE=METADATA_NAMESPACE)
exec(compile(WRAPPER_SOURCE, __file__ + ':unchanged-recursive-mux-route-parent-chain-guards', 'exec'), WRAPPER_NAMESPACE)


def verify_metadata(report):
    WRAPPER_NAMESPACE['verify_metadata'](report)
    assert report['independent_full_placement_review_report'] == report['placed_report']
    assert all(report[k] is False for k in ('original_failed_native_report_relabelled',
        'original_native_output_modified', 'analytic_subset_marker_used_as_full_census'))
    path = Path(report['original_failed_native_execution_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-place-')


def verify_route_snapshots(path, report, before, placed_path, placed):
    """Require the actual new route producer and original native owner."""
    assert report['independent_full_placement_review_report'] == str(placed_path)
    owner, native = route.original_execution(placed)
    assert report['original_failed_native_execution_report'] == str(owner)
    assert report['hardware_execution_input'] == str(owner.parent / 'placed.json')
    assert not Path(f'/proc/{report["commands"][-1]["pid"]}').exists(), 'Native routing worker still live'
    assert not Path(f'/proc/{report["supervisor_pid"]}').exists(), 'Route producer still live'
    expected = {'executed_source.py': Path(route.__file__).read_text(),
        'executed_control_source.py': route.CONTROL.read_text(), 'executed_prepared_main.py': route.MAIN_SOURCE}
    for name, text in expected.items():
        item = path.parent / name
        assert str(item) in before and before[str(item)] == route.original.digest(item)
        assert item.read_text() == text, 'Changed actual full-route producer/guard snapshot'
    assert report['prepared_main_source_sha256'] == before[str(path.parent / 'executed_prepared_main.py')]
    for source in (Path(route.__file__).resolve(), route.CONTROL):
        assert before[str(source)] == route.original.digest(source)


REPLACEMENTS = (
    ("    path=Path(path).resolve(strict=True);assert path.is_relative_to(ROOT/'build/openxc7')\n",
     """    path=Path(path).resolve(strict=True);assert path.is_relative_to(ROOT/'build/openxc7')
    assert path.name == 'report.json' and path.parent.name.startswith('full-reviewed-recursive-mux-literal-empty-v2-scan-route-')
"""),
    ("    candidate,before=route.placement.qualification.verify_qualification(Path(placed['qualification']))\n",
     "    candidate,before=route.NAMESPACE['verify_placement_engine'](route.qualification_path(placed))\n"),
    ('    placing_build=route.placement_build(candidate,before)\n',
     "    placing_build=route.NAMESPACE['placement_build'](candidate,before)\n"),
    ('    bind_report(path,r,before);verify_bindings(before)\n',
     '    bind_report(path,r,before);verify_bindings(before)\n    verify_route_snapshots(path,r,before,placed_path,placed)\n'),
)
VERIFY_SOURCE = source_shaped(previous.VERIFY_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, route=route, PROFILE=PROFILE, bind_report=route.bind_report,
    verify_metadata=verify_metadata, verify_route_snapshots=verify_route_snapshots)
exec(compile(VERIFY_SOURCE, __file__ + ':same-entire-native-route-evidence-reviewed-placement-owner', 'exec'), NAMESPACE)
verify_route = NAMESPACE['verify_route']
