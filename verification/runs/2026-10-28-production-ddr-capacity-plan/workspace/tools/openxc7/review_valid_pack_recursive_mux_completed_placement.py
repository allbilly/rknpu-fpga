#!/usr/bin/env python3
"""Same complete-output review with corrected host-control preconditions only.

Keep the first fourteen-control failure/helper intact. Its refinement-negative
test supplied no packed metadata, so the unchanged verifier rejected pack
admission before reaching that test's intended native refinement guard. Select
a separate control fixture that supplies valid pack metadata and separately
tests invalid-pack rejection. Every real execution/admission/full-output guard
is unchanged; a prepared reviewer still accepts no live/incomplete placement.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_recursive_mux_completed_placement as previous
from audit_empty_output_pairs import source_shaped

CONTROL = previous.ROOT / 'tests/cmac/test_recursive_mux_completed_review_valid_pack_control.py'
REVIEWED = previous.REVIEWED
REPLACEMENTS = (
    ('full-recursive-mux-completed-placement-review-', 'full-recursive-mux-valid-pack-completed-placement-review-'),
    ('    out.mkdir(parents=True, exist_ok=False)\n',
     "    out.mkdir(parents=True, exist_ok=False)\n    (out / 'executed_prepared_main.py').write_text(MAIN_SOURCE)\n"),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL, MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE, __file__ + ':identical-full-review-guards-valid-control-preconditions', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
