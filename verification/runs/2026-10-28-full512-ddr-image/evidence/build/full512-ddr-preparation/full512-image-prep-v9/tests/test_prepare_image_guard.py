import importlib.util
from pathlib import Path
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_prepare_image_guard',BASE/'prepare_image.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

class FreshRenderGuardTests(unittest.TestCase):
    def test_existing_emit_tcl_is_not_overwritten_and_renderer_is_not_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'emission';emit=root/'emit_full512_ch1.tcl';sentinel=b'preserve this reviewed prior output exactly\n';emit.write_bytes(sentinel)
            called=[]
            with self.assertRaisesRegex(prepare.GateError,'Fresh full512 emission Tcl path required'):
                prepare.render_to_fresh_paths(output,emit,lambda:called.append(True) or 'overwrite')
            self.assertEqual(emit.read_bytes(),sentinel);self.assertEqual(called,[]);self.assertFalse(output.exists())

    def test_existing_output_directory_blocks_tcl_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'emission';output.mkdir();emit=root/'emit_full512_ch1.tcl';called=[]
            with self.assertRaisesRegex(prepare.GateError,'Fresh full512 emission output directory required'):
                prepare.render_to_fresh_paths(output,emit,lambda:called.append(True) or 'text')
            self.assertEqual(called,[]);self.assertFalse(emit.exists())

if __name__=='__main__':unittest.main()
