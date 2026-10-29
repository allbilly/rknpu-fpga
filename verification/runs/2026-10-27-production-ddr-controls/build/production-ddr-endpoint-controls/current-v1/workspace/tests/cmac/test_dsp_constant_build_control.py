"""Build/source boundary controls, not native or hardware acceptance."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import build_dsp_constant_candidate as builder


class DSPConstantBuildControl(unittest.TestCase):
    def sources(self, filename):
        upstream = builder.GAP.parent / ('upstream-' + filename)
        return (builder.NATIVE_SRC / filename).read_text(), upstream.read_text()

    def test_exact_DSP_only_sources(self):
        for filename in builder.UPSTREAM_DIGESTS:
            old, new = self.sources(filename)
            self.assertEqual(builder.checked_source(filename, old, new), new)

    def test_unpinned_in_function_change_rejected(self):
        old, new = self.sources('fasm.cc')
        with self.assertRaises(AssertionError):
            builder.checked_source('fasm.cc', old, new.replace('return bus_inverts != packer_inverts;',
                                                             'return bus_inverts || packer_inverts;'))

    def test_unrelated_old_source_change_rejected(self):
        old, new = self.sources('fasm.cc')
        with self.assertRaises(AssertionError):
            builder.checked_source('fasm.cc', old + '\n// unexpected change\n', new)

    def test_parent_link_preserves_non_DSP_objects(self):
        old = ['c++', '/old/static.o', '/old/fasm.o', '/old/pack.o', '-o', '/old/engine', '-Wl,--dependency-file=/old/engine.d']
        result = builder.link_argv(old, '/new/engine', {Path('/old/fasm.o'): '/new/fasm.o', Path('/old/pack.o'): '/new/pack.o'})
        self.assertEqual(result, ['c++', '/old/static.o', '/new/fasm.o', '/new/pack.o', '-o', '/new/engine',
                                  '-Wl,--dependency-file=/new/engine.d'])

    def test_missing_or_duplicate_link_object_rejected(self):
        for old in (['c++', '-o', 'engine'], ['c++', 'fasm.o', 'fasm.o', '-o', 'engine']):
            with self.assertRaises(AssertionError):
                builder.link_argv(old, 'new', {Path('fasm.o'): 'new-fasm.o'})

    def test_compile_recipe_change_rejected(self):
        flags = 'CXX_DEFINES = -DNO_GUI\nCXX_INCLUDES = -Iinclude\nCXX_FLAGS = -O3\n'
        with self.assertRaises(AssertionError):
            builder.compile_argv('fasm.cc', 'new.cc', 'new.o', flags, '/usr/bin/c++ -O0 -c fasm.cc')


if __name__ == '__main__':
    unittest.main()
