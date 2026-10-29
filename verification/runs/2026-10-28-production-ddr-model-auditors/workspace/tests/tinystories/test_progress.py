"""Progress durability/control tests, not model or FPGA numerical evidence."""
from pathlib import Path
import json
import struct
import tempfile
import unittest

from tools.tinystories.c_engine import CModel
from tools.tinystories.progress import Progress,available_memory_kib,require_memory


class Library:
    def __init__(self):self.calls=0;self.sample_index=0
    def rknpu_encode(self,prompt,tokens,capacity):
        tokens[0]=1
        if prompt:tokens[1]=5;return 2
        return 1
    def rknpu_forward(self,token,position,logits,callback):
        self.calls+=36
        for i in range(512):logits[i]=(token*512+position*4+i)/16
        return 0
    def rknpu_sample(self,logits):
        value=(11,12,1)[self.sample_index];self.sample_index+=1;return value
    def rknpu_decode(self,previous,token):return f'<{token}>'.encode()
    def rknpu_calls(self):return self.calls


def model():
    instance=CModel.__new__(CModel)
    instance.closed=False;instance.failure=None;instance.calls=[];instance.external=False
    instance.callback=None;instance.library=Library()
    return instance


def event(position=0):
    return dict(position=position,input_token=1,next_token=11,forced_prompt=False,
                stop=False,piece_hex=b'Once'.hex(),logits=[i/16 for i in range(512)])


class ProgressTests(unittest.TestCase):
    def test_observer_preserves_model_tokens_logits_and_terminal_position(self):
        expected=model().generate('two',4);events=[]
        actual=model().generate('two',4,on_position=events.append)
        self.assertEqual(actual,expected)
        self.assertEqual(len(events),4)
        self.assertEqual(events[0]['forced_prompt'],True)
        self.assertTrue(events[-1]['stop'])
        self.assertEqual(events[-1]['piece_hex'],'')
        self.assertEqual(actual['generated_tokens'],[11,12,1])

    def test_observer_cannot_replace_logits_or_tokens(self):
        def change(e):
            e['logits'][0]=9999;e['next_token']=511
            return [123]*512
        self.assertEqual(model().generate('',2,on_position=change),model().generate('',2))

    def test_observer_failure_poison_is_not_a_restart_or_fallback(self):
        m=model()
        def fail(e):raise OSError('synthetic progress write failure')
        with self.assertRaises(OSError):m.generate('',2,on_position=fail)
        self.assertEqual(m.library.calls,36)
        with self.assertRaises(ValueError):m.generate('',2)
        self.assertEqual(m.library.calls,36)

    def test_completed_binary_row_and_receipts_survive_later_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Progress(directory)
            try:
                p.dense(dict(name='fixture',input_fp16_sha256='a'*64,output_fp16_sha256='b'*64))
                p.position(event())
                before=(Path(directory)/'logits.bin').read_bytes()
                self.assertEqual(before,struct.pack('<512f',*event()['logits']))
                bad=event(2)
                with self.assertRaises(ValueError):p.position(bad)
                self.assertEqual((Path(directory)/'logits.bin').read_bytes(),before)
                rows=[json.loads(s) for s in (Path(directory)/'positions.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['logits_offset'],0)
                self.assertEqual(p.summary()['text'],'Once')
                self.assertEqual(p.summary()['recorded_dense_calls'],1)
            finally:p.close()

    def test_nonfinite_or_unknown_position_data_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Progress(directory)
            try:
                for bad in (dict(event(),unexpected=0),dict(event(),logits=[float('nan')]*512)):
                    with self.assertRaises(ValueError):p.position(bad)
                self.assertEqual((Path(directory)/'logits.bin').stat().st_size,0)
                self.assertEqual(p.position_count,0)
            finally:p.close()

    def test_resource_gate_requires_actual_available_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'meminfo';path.write_text('MemTotal: 9999999 kB\nMemAvailable: 2048 kB\n')
            self.assertEqual(available_memory_kib(path),2048)
            self.assertEqual(require_memory(2,path=path),2048)
            with self.assertRaises(ValueError):require_memory(3,path=path)
            path.write_text('MemAvailable: 2048 MB\n')
            with self.assertRaises(ValueError):available_memory_kib(path)
            self.assertIsNone(require_memory(0,path=Path(directory)/'absent'))
            with self.assertRaises(ValueError):require_memory(True,path=path)


if __name__=='__main__':unittest.main()
