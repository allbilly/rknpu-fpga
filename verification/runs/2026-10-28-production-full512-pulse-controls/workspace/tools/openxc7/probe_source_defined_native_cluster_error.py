#!/usr/bin/env python3
"""Fresh separate probe with the actually linked native fatal-error contract.

Preserve the original expected1/actual125 FAIL unchanged. Bind the original
command/log objects and their actual dependency sources; prove log_error
throws the caught native exception and CommandHandler::exec returns125.
Repeat all original relink, compiler, three native pack/graph/metadata checks
and the real overwrite negative, requiring its exact error and zero warnings.
No native source correction, target reduction, hardware/protocol expectation
change, old native-result inheritance or physical acceptance is introduced.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_native_pack_clusters as previous
from audit_empty_output_pairs import source_shaped

CONTROL = previous.ROOT / 'tests/cmac/test_source_defined_native_cluster_error_control.py'
FAILED = previous.ROOT / 'build/openxc7/native-pack-cluster-export-1791518825958732551/report.json'
HANDLER = Path('/home/fedora/soDLA/build/ypcb/static-refine-engine-1791373341950321183/common/kernel/command.cc')
HANDLER_OBJECT = HANDLER.parents[2] / 'command.cc.o'
HANDLER_BUILD = HANDLER.parents[2] / 'report.json'
LOG = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/common/kernel/log.cc')
LOG_OBJECT = previous.CMAKE / '__/common/kernel/log.cc.o'
STATUS = 'QUALIFIED_SMALL_NATIVE_CLUSTER_EXPORT_SOURCE_DEFINED_125_NEGATIVE_NOT_FULL_PLACEMENT_OR_SIGNOFF'


def error_source_contract(handler, logging):
    first, last = 'int CommandHandler::exec()\n', '\nvoid CommandHandler::load_json('
    assert handler.count(first) == handler.count(last) == 1
    body = handler.split(first, 1)[1].split(last, 1)[0]
    catch = ('    } catch (log_execution_error_exception) {\n'
             '        printFooter();\n        return 125;\n    }\n')
    assert body.count(catch) == 1, 'Wrong actual native fatal-exception return contract'
    first, last = 'void logv_error(const char *format, va_list ap)\n', '\nvoid log_always('
    assert logging.count(first) == logging.count(last) == 1
    body = logging.split(first, 1)[1].split(last, 1)[0]
    assert body.count('throw log_execution_error_exception();') == 1
    assert body.count('logv_prefixed("ERROR: ", format, ap, LogLevel::ERROR_MSG);') == 1
    body = logging.split('void log_error(const char *format, ...)\n', 1)[1].split('\nstd::ifstream ', 1)[0]
    assert body.count('logv_error(format, ap);') == 1
    return dict(exception='log_execution_error_exception', fatal_returncode=125,
                fatal_error_remains_rejection=True, does_not_change_hardware_error_expectations=True)


def validate_error_contract():
    contract = error_source_contract(HANDLER.read_text(), LOG.read_text())
    parent = json.loads(previous.PARENT.read_text())
    link = next(c for c in parent['commands'] if c['label'] == 'link_recursive_mux_feedthrough')
    assert link['argv'].count(str(HANDLER_OBJECT)) == link['argv'].count(str(LOG_OBJECT)) == 1
    assert HANDLER in previous.dependencies(Path(str(HANDLER_OBJECT) + '.d'))
    assert LOG in previous.dependencies(Path(str(LOG_OBJECT) + '.d'))
    failed = json.loads(FAILED.read_text())
    assert failed['status'] == 'FAIL_NATIVE_PACK_CLUSTER_EXPORT_PROBE'
    assert failed['commands'][-1]['label'] == 'existing_output_real_negative'
    assert failed['commands'][-1]['expected_returncode'] == 1 and failed['commands'][-1]['returncode'] == 125
    historically_bound = (HANDLER, HANDLER_OBJECT, HANDLER_BUILD, LOG, LOG_OBJECT,
                          Path(previous.__file__).resolve())
    for path in historically_bound:
        assert failed['source'][str(path)] == previous.digest(path), 'Unbound/changed actual source or object'
    build = json.loads(HANDLER_BUILD.read_text())
    compiles = [c for c in build['commands'] if '-c' in c['argv'] and
                c['argv'][c['argv'].index('-c') + 1] == str(HANDLER)]
    assert len(compiles) == 1
    compile_step = compiles[0]
    assert compile_step['returncode'] == 0 and compile_step['status'] == 'PASS'
    assert compile_step['argv'][compile_step['argv'].index('-o') + 1] == str(HANDLER_OBJECT)
    # These dependency sidecars were not in the earlier input census. Bind
    # them freshly and label that fact; source/object/build identity above is
    # the historical evidence, not an invented historical sidecar hash.
    sidecars = (Path(str(HANDLER_OBJECT) + '.d'), Path(str(LOG_OBJECT) + '.d'))
    contract['freshly_bound_dependency_sidecars_not_prior_evidence'] = list(map(str, sidecars))
    contract['source'] = {str(path): previous.digest(path) for path in (*historically_bound, *sidecars, FAILED)}
    contract['original_failure_preserved'] = str(FAILED)
    return contract


OLD_ADMISSION = '    q, before = admit_qualification(QUALIFICATION)  # No output/tool on incomplete qualification.\n'
NEW_ADMISSION = '''    contract = validate_error_contract()
    q, before = admit_qualification(QUALIFICATION)  # No output/tool on incomplete qualification.
    for path, sha in contract['source'].items():
        assert path not in before or before[path] == sha, 'Changed actual native error-contract source'
        before[path] = sha
'''
REPLACEMENTS = (
    (OLD_ADMISSION, NEW_ADMISSION),
    ('build/openxc7/native-pack-cluster-export-', 'build/openxc7/source-defined-native-cluster-export-'),
    ("report = dict(status='RUNNING', stage='admitted',", "report = dict(native_error_contract=contract, status='RUNNING', stage='admitted',"),
    ('timeout=120, expected=1,', 'timeout=120, expected=125,'),
    ("required='RKNPU cluster diagnostic cannot create new output')",
     "required='RKNPU cluster diagnostic cannot create new output\\n0 warnings, 1 error')"),
    ('FAIL_NATIVE_PACK_CLUSTER_EXPORT_PROBE', 'FAIL_SOURCE_DEFINED_NATIVE_CLUSTER_EXPORT_PROBE'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 STATUS=STATUS, validate_error_contract=validate_error_contract)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-native-procedure-source-defined-error-contract', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
