#!/usr/bin/env python3
"""Use reversible nonempty comments for diagnostic-only instance removal.

Keep the failed preparation attempt frozen. Replace removed, independent
test-only view declarations with distinct comments so the exact-source guard
can uniquely reverse each edit. Do not change HDL/model behavior, control
transactions, original cold-state gates, tools, limits, or any acceptance flag.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import diagnose_isolated_working_bram_views as previous
from audit_empty_output_pairs import source_shaped

CONTROL=previous.base.ROOT/'tests/cmac/test_resumed_isolated_working_bram_views_control.py'
OLD="remove.append((fragment,''))"
NEW="remove.append((fragment,'    // DIAGNOSTIC_ONLY unselected_'+kind+'_view_not_instantiated\\n'))"
ISOLATION_SOURCE=source_shaped(inspect.getsource(previous.isolated_bench),((OLD,NEW),))
FUNCTIONS=dict(vars(previous))
exec(compile(ISOLATION_SOURCE,__file__+':reversible-isolation-edit','exec'),FUNCTIONS)
isolated_bench=FUNCTIONS['isolated_bench']
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,(
    ('isolated-working-bram-views-diagnostic-','isolated-working-bram-views-resume-'),
    ("        (out/'executed_main.py').write_text(MAIN_SOURCE)",
     "        (out/'executed_main.py').write_text(MAIN_SOURCE)\n        (out/'executed_isolation_source.py').write_text(ISOLATION_SOURCE)")))
NAMESPACE=dict(previous.NAMESPACE,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
    isolated_bench=isolated_bench,MAIN_SOURCE=MAIN_SOURCE,ISOLATION_SOURCE=ISOLATION_SOURCE)
exec(compile(MAIN_SOURCE,__file__+':unchanged-diagnostic-main','exec'),NAMESPACE)


if __name__=='__main__':NAMESPACE['main']()
