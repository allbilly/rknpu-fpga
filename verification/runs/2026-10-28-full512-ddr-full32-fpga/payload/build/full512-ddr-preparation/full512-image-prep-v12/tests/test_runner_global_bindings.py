import builtins
from pathlib import Path
import symtable
import unittest

PACKAGE=Path(__file__).resolve().parents[1]
RUNNERS=('prepare_image.py','run_image.py','run_io_query.py','io_snapshot.py')

def walk(table):
    yield table
    for child in table.get_children():
        yield from walk(child)

def unresolved_globals(path):
    root=symtable.symtable(path.read_text(),str(path),'exec')
    tables=list(walk(root))
    bound=set(dir(builtins))|{'__name__','__file__','__package__','__doc__','__cached__','__loader__','__spec__'}
    referenced=set()
    for table in tables:
        for symbol in table.get_symbols():
            if symbol.is_global():
                if symbol.is_assigned() or symbol.is_imported():bound.add(symbol.get_name())
                if symbol.is_referenced():referenced.add(symbol.get_name())
    return sorted(referenced-bound)

class RunnerGlobalBindingTests(unittest.TestCase):
    def test_private_runner_modules_have_no_unbound_global_references(self):
        for name in RUNNERS:
            with self.subTest(module=name):
                self.assertEqual(unresolved_globals(PACKAGE/name),[])

    def test_scanner_detects_a_referenced_but_unassigned_module_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'broken.py';source.write_text('def main():\n    return MISSING_RUNNER\n')
            self.assertEqual(unresolved_globals(source),['MISSING_RUNNER'])

if __name__=='__main__':unittest.main()
