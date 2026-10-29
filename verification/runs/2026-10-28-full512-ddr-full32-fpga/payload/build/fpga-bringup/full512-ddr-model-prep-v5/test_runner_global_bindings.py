"""Stdlib symtable guard against unresolved names in the future physical runner."""
import ast
from pathlib import Path
import builtins
import symtable
import unittest

SOURCE=Path(__file__).with_name('run_full_model.py')
SPECIAL={'__file__','__name__','__package__','__spec__','__builtins__','__doc__','__annotations__'}

def unresolved_globals(path=SOURCE):
    table=symtable.symtable(Path(path).read_text(),str(path),'exec')
    defined={s.get_name() for s in table.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}
    allowed=set(dir(builtins))|SPECIAL
    issues=[]
    def walk(scope):
        for s in scope.get_symbols():
            if s.is_global() and s.is_referenced() and s.get_name() not in defined and s.get_name() not in allowed:
                issues.append((scope.get_name(),s.get_lineno(),s.get_name()))
        for child in scope.get_children():walk(child)
    walk(table)
    return issues

def duplicate_top_level_functions(source):
    tree=ast.parse(source)
    names=[node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]
    return sorted(name for name in set(names) if names.count(name)>1)

class RunnerGlobalBindingTests(unittest.TestCase):
    def test_all_referenced_globals_are_bound(self):
        self.assertEqual(unresolved_globals(),[])

    def test_no_duplicate_top_level_function_can_shadow_admission(self):
        tree=ast.parse(SOURCE.read_text())
        names=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
        duplicates=sorted(n for n in set(names) if names.count(n)>1)
        self.assertEqual(duplicates,[])
        self.assertEqual(names.count('validate_admission'),1)
        # The detector itself must catch the reviewed shadowing failure mode.
        fake=ast.parse('def validate_admission(): pass\ndef validate_admission(): pass')
        fake_names=[n.name for n in fake.body if isinstance(n,ast.FunctionDef)]
        self.assertIn('validate_admission',[n for n in set(fake_names) if fake_names.count(n)>1])

    def test_duplicate_admission_definition_cannot_shadow_receipt_validation(self):
        source=SOURCE.read_text()
        self.assertEqual(duplicate_top_level_functions(source),[])
        self.assertEqual(sum(1 for node in ast.parse(source).body
                             if isinstance(node,ast.FunctionDef) and node.name=='validate_admission'),1)
        self.assertEqual(duplicate_top_level_functions('def validate_admission(): pass\ndef validate_admission(): pass'),
                         ['validate_admission'])
        self.assertIn('validate_trained_tile_prerequisite(prep,prereq,sha(canonical_path),bit_sha,prereq_sha)',source)

if __name__=='__main__':unittest.main()
