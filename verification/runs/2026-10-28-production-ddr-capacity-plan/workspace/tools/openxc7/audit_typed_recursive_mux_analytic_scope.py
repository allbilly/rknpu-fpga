#!/usr/bin/env python3
"""Same read-only analytic-scope audit with source-defined typed linker metadata.

The actual mux builder uses PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY for every
command, but its link must have both expected and actual return codes zero.
Recognize only that evidenced link record, not a negative or failed command.
Preserve the first rejected audit/helper and every worker/source/object/log,
full-target, checksum and no-acceptance guard. No placement counter expectation
or hardware input is changed; no full fit, numerical or physical pass follows.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_recursive_mux_analytic_scope as previous
import audit_empty_output_pairs as shaping

CONTROL = previous.ROOT / 'tests/cmac/test_typed_recursive_mux_analytic_scope_control.py'
STATUS = 'CONFIRMED_NATIVE_ANALYTIC_LOG_SUBSET_SCOPE_TYPED_LINK_NOT_FULL_PLACEMENT_ACCEPTANCE'


def verify_typed_link(links):
    assert len(links) == 1
    step = links[0]
    assert step['label'] == 'link_recursive_mux_feedthrough'
    assert step['status'] == 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'
    assert step.get('expected_returncode', 0) == step['returncode'] == 0, 'Link must be genuine zero-code success'


OLD_LINK = "    verify_native_link_command(built['commands'], obj, native['executable']['path'])\n"
NEW_LINK = "    verify_typed_link([verify_native_link_command(built['commands'], obj, native['executable']['path'])])\n"
OLD_BIND = '    for item in (Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()):\n'
NEW_BIND = '''    for item in (Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve(),
                 Path(previous.__file__).resolve(), previous.CONTROL, Path(shaping.__file__).resolve()):
'''
OLD_OUT = '    out.mkdir(parents=True, exist_ok=False)\n'
NEW_OUT = OLD_OUT + "    (out / 'executed_prepared_main.py').write_text(MAIN_SOURCE)\n"
REPLACEMENTS = (
    (OLD_LINK, NEW_LINK),
    (OLD_BIND, NEW_BIND),
    ('recursive-mux-analytic-scope-', 'recursive-mux-analytic-scope-typed-'),
    (OLD_OUT, NEW_OUT),
)
MAIN_SOURCE = shaping.source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL, STATUS=STATUS,
                 previous=previous, shaping=shaping, verify_typed_link=verify_typed_link, MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE, __file__ + ':same-diagnostic-only-gates-typed-zero-code-link', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
