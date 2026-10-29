"""Full native HeAP clock/FASM comparison adapter, not route/signoff admission.

Execute the unchanged corrected full-target comparison body in an independent
namespace. Only its read-only parser receives the actual routed PIP contracts;
all 515-DSP/six-BRAM, C32/K16, BEL, wiring and 39-tie checks remain unchanged.
The route caller must bind the clock-model sources before native execution and
derive contracts from its actual routed module, not a comparison/execution view.
No native artifact, old parser, input, executable or acceptance gate is rewritten.
"""
import inspect
from pathlib import Path

import check_full_corrected_native_features as original
import clock_bound_native_features as clock

COMPARISON_SOURCE=inspect.getsource(original.verify_full_features)


def comparison_namespace(contracts):
    namespace=dict(original.__dict__,parse_native_features=lambda text:
                   clock.parse_clock_bound_features(text,contracts)[:2])
    exec(compile(COMPARISON_SOURCE,__file__+':unchanged-full-DSP-BRAM-census-and-comparison','exec'),namespace)
    return namespace


def verify_full_features(fasm_path,placement_path,routed_path,selected,expected_groups,contracts):
    features,io,repeated=clock.parse_clock_bound_features(Path(fasm_path).read_text(),contracts)
    compared=comparison_namespace(contracts)['verify_full_features'](
        fasm_path,placement_path,routed_path,selected,expected_groups)
    assert compared['native_FASM_features']==len(features)
    assert compared['repeated_idempotent_STEPDOWN_lines']==io
    return dict(**compared,clock_source_contract=clock.source_contract(),
                repeated_source_bound_clock_enable_lines=repeated,
                clock_contracts_from_actual_routed_module=contracts,
                clock_feature_model_modified_original_parser=False,
                consumer_merge_contract=clock.consumer_merge_check())
