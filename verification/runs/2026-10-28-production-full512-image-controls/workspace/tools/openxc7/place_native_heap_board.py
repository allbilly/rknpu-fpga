#!/usr/bin/env python3
"""Full C32/K16 HeAP alternative, admitted only by actual native qualification.

Reuse the full-target static runner's exact prepared input, source-bound packing
parents, preserved previous failure, resource/time limits and whole primitive /
unique-BEL checks. Change only the placement algorithm and its genuine native
completion markers. Revalidate the completed early-constraint HeAP qualification
before execution; never restart or modify the existing static placement/replay.
Normal refinement, native validity, -2 part, 50 MHz and seed 3588 remain required.
Placement is not routing, numerical acceptance, fit/timing/electrical/DRC signoff,
bitstream emission or programming. No standalone checksum manifest is written.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import place_strict_search_board as parent
import place_prefix_board as placed
import qualify_native_heap_clock_features as qualified
from audit_empty_output_pairs import source_shaped

CONTROL=parent.ROOT/'tests/cmac/test_native_heap_board_control.py'
PLACED='PLACED_FULL_C32K16_CORRECTED_DSP_NATIVE_HEAP_NORMAL_REFINEMENT_LEGALITY_NOT_ROUTED_FIT_OR_SIGNOFF'
NATIVE_TIMEOUT=parent.NATIVE_TIMEOUT
FLAGS=parent.FLAGS


def placement_argv(executable,input_path,constraints,output):
    return qualified.previous.first.heap_argv(parent.placement_argv(executable,input_path,constraints,output))


def verify_full_argv(argv):
    assert argv.count('--placer')==1 and argv[argv.index('--placer')+1]=='heap'
    static=list(argv);static[static.index('--placer')+1]='static';parent.verify_full_argv(static)
    assert argv.count('--json')==argv.count('--write')==argv.count('-o')==1
    xdc=argv[argv.index('-o')+1];assert xdc.startswith('xdc=')
    assert argv==placement_argv(argv[0],argv[argv.index('--json')+1],xdc[4:],argv[argv.index('--write')+1])


PLACED_NAMESPACE=dict(placed.__dict__)
PLACED_SOURCE=source_shaped(inspect.getsource(placed.verify_placed_module),(
    ("settings['placer'] == 'static'","settings['placer'] == 'heap'"),
    ('QUALIFIED_STATIC_REFINEMENT_FINAL_BEL_VALIDITY_CHECK_NOT_COMPLETE_ARCHITECTURE_SIGNOFF',
     'QUALIFIED_HEAP_NORMAL_REFINEMENT_FINAL_BEL_VALIDITY_CHECK_NOT_COMPLETE_ARCHITECTURE_SIGNOFF'),))
exec(compile(PLACED_SOURCE,__file__+':unchanged-full-membership-and-unique-BEL-gates','exec'),PLACED_NAMESPACE)
verify_placed_module=PLACED_NAMESPACE['verify_placed_module']

OLD_NATIVE_BLOCK="""            if label == 'native_place':
                for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                               'Running post-placement legalisation...', 'Program finished normally.'):
                    assert marker in text, 'Missing normal full-placement completion: ' + marker
                assert 'Static refinement iteration limit:' not in text
                step['search_progress'] = check_strict_log(text)"""
NEW_NATIVE_BLOCK="""            if label == 'native_place':
                check_heap_log(code,text)
                step['native_heap_completion_checked']=True"""

NAMESPACE=dict(parent.__dict__,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,PLACED=PLACED,
               placement_argv=placement_argv,verify_full_argv=verify_full_argv,
               verify_placed_module=verify_placed_module,verify_qualification=qualified.verify_qualification,
               check_heap_log=qualified.check_heap_log)
MAIN_SOURCE=source_shaped(inspect.getsource(parent.main),(
    ('full-prefix-bounded-search-place-','full-prefix-native-heap-place-'),
    (OLD_NATIVE_BLOCK,NEW_NATIVE_BLOCK),
    ('changed_static_placer_object=1, corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True',
     "placement_algorithm='heap', native_source_or_executable_changed=False, "
     'corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True'),))
exec(compile(MAIN_SOURCE,__file__+':full-target-native-HeAP-alternative','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
