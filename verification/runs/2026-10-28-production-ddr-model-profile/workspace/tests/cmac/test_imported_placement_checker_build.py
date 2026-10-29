"""Isolated source/compile/link-recipe controls, not native qualification."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from build_imported_placement_checker import (TAG_SOURCE, TEMPLATE, OLD_OBJECT, CMAKE, NATIVE_SRC,
    OPTION, START, END, OLD_LOOP, NEW_LOOP, checked_source, compile_recipe, link_argv, verify_original_binding)


class ImportedPlacementCheckerBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = TAG_SOURCE.read_text()
        cls.block = TEMPLATE.read_text()

    def test_actual_source_changes_are_fully_reversible_and_assertions_preserved(self):
        modified = checked_source(self.old, self.block)
        self.assertIn(self.block + END, modified)
        self.assertEqual(modified.count('NPNR_ASSERT'), self.old.count('NPNR_ASSERT'))
        reverted = modified.replace(OPTION, '', 1).replace(START + '    const bool rknpu_imported_placement = !cell_tags_set;\n', START, 1).replace(self.block + END, END, 1).replace(NEW_LOOP, OLD_LOOP, 1)
        self.assertEqual(reverted, self.old)

    def test_only_loop_index_changes_and_matches_actual_context_API(self):
        header = NATIVE_SRC.parents[2] / 'common/kernel/context.h'
        text = header.read_text()
        self.assertIn('size_t getNetinfoSinkWireCount(const NetInfo *net_info, const PortRef &sink) const;', text)
        self.assertIn('WireId getNetinfoSinkWire(const NetInfo *net_info, const PortRef &sink, size_t phys_idx) const;', text)
        self.assertEqual(NEW_LOOP.replace('size_t i', 'int i'), OLD_LOOP)
        modified = checked_source(self.old, self.block)
        self.assertEqual(modified.count(NEW_LOOP), 1)
        self.assertNotIn(OLD_LOOP, modified)
        with self.assertRaises(AssertionError): checked_source(self.old.replace(OLD_LOOP, ''), self.block)

    def test_missing_ambiguous_and_already_modified_hooks_fail(self):
        for bad in (self.old.replace(START, ''), self.old + START, self.old.replace(END, ''), self.old + END,
                    self.old + 'rknpu-check-imported-placement', self.old.replace('    specific.add_options()("fasm",', '')):
            with self.subTest(length=len(bad)), self.assertRaises(AssertionError): checked_source(bad, self.block)

    def test_forbidden_circuit_mutation_or_assertion_operations_fail(self):
        for operation in ('disconnectPort', 'connectPort', 'renamePort', 'setParam', 'bindBel', 'unbindBel',
                          'ctx->nets[', 'ctx->cells[', 'attrs[', 'params[', 'NPNR_ASSERT'):
            block = self.block.replace('    // Isolated verification-only addition.', '    // Isolated verification-only addition. ' + operation)
            with self.subTest(operation=operation), self.assertRaises(AssertionError): checked_source(self.old, block)

    def test_verification_restore_and_native_check_contracts_cannot_be_omitted(self):
        for token in ('VerificationTags', 'cell_tags.swap(saved)', 'e.dirty = true', 'h.dirty = true',
                      'isBelLocationValid(ci->bel, true)', 'ctx->check();',
                      'different nets on a shared physical pin', 'wrong paired output/A6 mode contract'):
            with self.subTest(token=token), self.assertRaises(AssertionError):
                checked_source(self.old, self.block.replace(token, 'omitted'))

    def test_wrong_template_boundary_fails(self):
        for bad in (self.block[1:], self.block.rstrip(), self.block + 'arbitrary extra code\n'):
            with self.subTest(length=len(bad)), self.assertRaises(AssertionError): checked_source(self.old, bad)

    def recipe(self):
        return ['/usr/bin/c++', '-Wall', '-O3', '-g', '-std=gnu++17', '-iquote', '/unchanged/header/path',
                '-MD', '-MF', str(OLD_OBJECT) + '.d', '-c', str(TAG_SOURCE), '-o', str(OLD_OBJECT)]

    def test_compile_recipe_preserves_flags_and_changes_only_source_object_dependency(self):
        source, obj = Path('/isolated/xilinx.cc'), Path('/isolated/xilinx.cc.o')
        old = self.recipe()
        new = compile_recipe(old, source, obj)
        self.assertEqual(new[:9], old[:9])
        self.assertEqual(new[new.index('-c') + 1], str(source))
        self.assertEqual(new[new.index('-o') + 1], str(obj))
        self.assertEqual(new[new.index('-MF') + 1], str(obj) + '.d')
        self.assertEqual(len(new), len(old))
        self.assertEqual(OLD_OBJECT, CMAKE / 'uarch/xilinx/xilinx.cc.o')
        self.assertEqual(TAG_SOURCE, NATIVE_SRC / 'xilinx.cc')

    def test_changed_compile_recipe_target_or_compiler_fails(self):
        for flag in ('-c', '-o', '-MF'):
            bad = self.recipe(); bad[bad.index(flag) + 1] = '/wrong/path'
            with self.subTest(flag=flag), self.assertRaises(AssertionError): compile_recipe(bad, Path('/s'), Path('/o'))
        bad = self.recipe(); bad[0] = '/unqualified/c++'
        with self.assertRaises(AssertionError): compile_recipe(bad, Path('/s'), Path('/o'))

    def test_link_changes_exactly_one_actual_object_and_own_output(self):
        old = ['/usr/bin/c++', '/fixed/a.o', str(OLD_OBJECT), '/fixed/lib.a', '-o', '/parent/exe', '-Wl,--dependency-file=/parent/exe.d']
        replacement = Path('/isolated/xilinx.cc.o')
        new = link_argv(old, Path('/isolated/exe'), {OLD_OBJECT: replacement})
        self.assertEqual(new, ['/usr/bin/c++', '/fixed/a.o', str(replacement), '/fixed/lib.a', '-o', '/isolated/exe', '-Wl,--dependency-file=/isolated/exe.d'])
        for bad in (old + [str(OLD_OBJECT)], [x for x in old if x != str(OLD_OBJECT)]):
            with self.assertRaises(AssertionError): link_argv(bad, Path('/isolated/exe'), {OLD_OBJECT: replacement})

    def test_actual_linked_source_object_and_dependency_path_are_separately_bound(self):
        source, obj = str(TAG_SOURCE), str(OLD_OBJECT)
        inputs = {source: 'source-hash', obj: 'object-hash'}
        verify_original_binding(inputs, inputs, {TAG_SOURCE})
        for key in (source, obj):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                verify_original_binding(inputs, {**inputs, key: 'changed'}, {TAG_SOURCE})
        with self.assertRaises(AssertionError):
            verify_original_binding(inputs, inputs, {Path('/sibling-probe/xilinx.cc')})


if __name__ == '__main__':
    unittest.main()
