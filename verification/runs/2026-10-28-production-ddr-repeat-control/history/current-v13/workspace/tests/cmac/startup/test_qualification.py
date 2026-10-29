"""Startup source-closure and admission controls; no simulator/build is launched."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.cmac.startup import qualification as q
from tools.cmac.startup import run as startup_run

ROOT = Path(__file__).resolve().parents[3]


class StartupQualificationTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'build').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='startup-qualification-control-',dir=ROOT/'build')
        self.addCleanup(self.temporary.cleanup);self.directory = Path(self.temporary.name)
        parent_dir = self.directory/'parent';parent_dir.mkdir()
        self.parent = parent_dir/'report.json';self.parent_name = str(self.parent.relative_to(ROOT))
        (parent_dir/'rk_cmac_cacc_fp16_array.sv').write_text('// MOCK SOURCE-CLOSURE TEST; NEVER COMPILE\n')
        self.parent.write_text(json.dumps(dict(status=q.PARENT_STATUS,source_profile='dsp-prefix-c32k16',
            source=q.fingerprint([q.SPEC])))+'\n')

    def test_every_selected_compile_source_is_hashed_including_assertion_helpers(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('No tools for source closure')):
            source = q.source_revision(self.parent_name)
        selected = q.source_names(self.parent_name)
        self.assertTrue(set(selected) <= set(source['files']))
        for name in ('rtl/vendor/nvdla/compat/nv_assert_never.v','rtl/vendor/nvdla/compat/nv_assert_no_x.v'):
            self.assertIn(name,selected)
            self.assertEqual(source['files'][name],q.digest(ROOT/name))

    def test_copied_source_root_is_complete_and_helper_edits_change_identity(self):
        source = q.source_revision(self.parent_name);snapshot = self.directory/'snapshot'
        for name in source['files']:
            destination = snapshot/name;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,destination)
        self.assertEqual(q.source_revision(self.parent_name,snapshot),source)
        name = 'rtl/vendor/nvdla/compat/nv_assert_never.v'
        with (snapshot/name).open('a') as stream:stream.write('// COPY-ONLY NEGATIVE CONTROL\n')
        changed = q.source_revision(self.parent_name,snapshot)
        self.assertNotEqual(changed['sha256'],source['sha256'])
        self.assertNotEqual(changed['files'][name],source['files'][name])
        self.assertEqual(q.digest(ROOT/name),source['files'][name])

    def test_old_r28_or_compile_only_reports_cannot_qualify_startup(self):
        path = self.directory/'old-report.json'
        for status in ('PASS_FULL_C32K16_DSP_PREFIX_RAW_BOARD_FOUR_STATE_FIXTURES_ONLY',
                       'PREPARED_COMPILED_FULL_C32K16_DSP_PREFIX_RAW_BOARD_ONLY','RUNNING'):
            path.write_text(json.dumps(dict(status=status,execution_schema=1,profile=q.PROFILE)))
            with self.subTest(status=status),patch.object(subprocess,'Popen',side_effect=AssertionError('No tools')), \
                 self.assertRaisesRegex(ValueError,'completed fresh startup-native'):
                q.verify_report(path)

    def test_reduced_geometry_cannot_reach_source_or_execution_admission(self):
        path = self.directory/'reduced.json'
        for dimensions in ((8,16,128),(32,8,256),(32,16,511)):
            path.write_text(json.dumps(dict(status=q.STATUS,execution_schema=1,profile=q.PROFILE,
                channels=dimensions[0],kernels=dimensions[1],parallel_products=dimensions[2])))
            with self.subTest(dimensions=dimensions),self.assertRaisesRegex(ValueError,'reduced geometry'):
                q.verify_report(path)

    def test_full_workload_counts_and_startup_timing_remain_exact(self):
        line = ('PASS full512_startup mode=0 polarity=0 outcome=success error=00 hold=64 release=65 '
                'init=4096 checks=4096 cmd_reads=196 operand_reads=6528 writes=64 acks=64 frames=12 cycles=44915; configuration model only')
        spec = dict(mode=0,polarity=0)
        self.assertEqual(q.validate_result(line,spec),line)
        for before,after in (('init=4096','init=4095'),('checks=4096','checks=4095'),
                             ('cmd_reads=196','cmd_reads=195'),('operand_reads=6528','operand_reads=6527'),
                             ('writes=64','writes=63'),('acks=64','acks=63'),('frames=12','frames=11'),
                             ('hold=64','hold=3'),('release=65','release=3')):
            with self.subTest(field=before),self.assertRaises(ValueError):q.validate_result(line.replace(before,after),spec)

    def test_warning_inventory_rejects_new_vendor_reset_and_count_changes(self):
        def line(item):
            kind,name,row,column=item
            return f'%Warning-{kind}: {ROOT/name}:{row}:{column}: MOCK DIAGNOSTIC LOCATION CONTROL\n'
        baseline=''.join(line(item) for item in q.REVIEWED_WARNING_LOCATIONS)
        self.assertEqual(len(q.reviewed_warnings(baseline)),54)
        added=[('UNOPTFLAT','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',1,1),
               ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',107,29),
               ('SYNCASYNCNET',q.TOP,14,10),('SYNCASYNCNET',q.RESET,12,5)]
        for item in added:
            with self.subTest(item=item),self.assertRaisesRegex(ValueError,'Unreviewed'):
                q.reviewed_warnings(baseline+line(item))
        for changed in (baseline+line(q.REVIEWED_WARNING_LOCATIONS[0]),
                        baseline.replace(line(q.REVIEWED_WARNING_LOCATIONS[0]),'',1),
                        baseline.replace(line(q.REVIEWED_WARNING_LOCATIONS[21]),'',1)):
            with self.assertRaisesRegex(ValueError,'inventory'):
                q.reviewed_warnings(changed)

    def test_fault_results_require_the_original_reached_phase_and_watchdog_bound(self):
        def result(mode,error,counts,cycles=44915):
            init,checks,commands,reads,writes,acks,frames=counts
            return (f'PASS full512_startup mode={mode} polarity=0 outcome=fault error={error} hold=64 release=65 '
                    f'init={init} checks={checks} cmd_reads={commands} operand_reads={reads} '
                    f'writes={writes} acks={acks} frames={frames} cycles={cycles}; configuration model only')
        profiles={1:('05',[4096,0,1,0,0,0,0]),2:('fd',[4096,1,196,6528,64,64,12]),
                  3:('fe',[4096,0,196,20,0,0,0]),4:('fd',[4096,1,196,6528,64,64,12])}
        for mode,(error,counts) in profiles.items():
            spec=dict(mode=mode,polarity=0)
            self.assertEqual(q.validate_result(result(mode,error,counts),spec),result(mode,error,counts))
            bad_counts=[[0]*7,[4096,0,0,0,0,0,0]]
            for index in range(7):
                bad=counts.copy();bad[index]=bad[index]-1 if bad[index] else 1;bad_counts.append(bad)
            for bad in bad_counts:
                with self.subTest(mode=mode,counts=bad),self.assertRaises(ValueError):
                    q.validate_result(result(mode,error,bad),spec)
            for cycles in (0,1048576):
                with self.subTest(mode=mode,cycles=cycles),self.assertRaises(ValueError):
                    q.validate_result(result(mode,error,counts,cycles),spec)
        counts=profiles[3][1].copy();counts[3]=21
        q.validate_result(result(3,'fe',counts),dict(mode=3,polarity=0))
        counts[3]=22
        with self.assertRaises(ValueError):q.validate_result(result(3,'fe',counts),dict(mode=3,polarity=0))

    def test_parallel_entry_completion_cannot_mutate_during_serialization(self):
        def exercise(update):
            lock=threading.RLock()
            iterating=threading.Event();release=threading.Event();attempting=threading.Event();updated=threading.Event()
            snapshots=[];errors=[]
            class PausedEntry(dict):
                def items(self):
                    values=iter(super().items())
                    yield next(values)
                    iterating.set()
                    if not release.wait(2):raise RuntimeError('serialization control timeout')
                    yield from values
            entry=PausedEntry(name='led0_mode0',status='RUNNING')
            report={'commands':[entry]}
            def serialize():
                try:
                    with lock:snapshots.append(json.dumps(report,indent=2))
                except BaseException as error:errors.append(error)
            def complete():
                if not iterating.wait(2):return
                attempting.set()
                update(lock,entry,status='PASS',returncode=0,seconds=1.0,log_sha256='a'*64)
                updated.set()
            reader=threading.Thread(target=serialize);writer=threading.Thread(target=complete)
            reader.start();writer.start()
            try:
                self.assertTrue(iterating.wait(2));self.assertTrue(attempting.wait(2))
                completed_while_serializing=updated.wait(0.05)
            finally:
                release.set();reader.join(2);writer.join(2)
            self.assertFalse(reader.is_alive() or writer.is_alive())
            self.assertTrue(updated.is_set())
            return entry,snapshots,errors,completed_while_serializing
        entry,snapshots,errors,early=exercise(startup_run.update_fields)
        self.assertFalse(early)
        self.assertEqual(errors,[])
        self.assertEqual(json.loads(snapshots[0])['commands'],[{'name':'led0_mode0','status':'RUNNING'}])
        self.assertEqual(entry['status'],'PASS');self.assertEqual(entry['returncode'],0)
        # Sensitivity control: the former unlocked mutation must be detected,
        # rather than allowing a test that merely exercises uncontended updates.
        _,_,errors,early=exercise(lambda lock,entry,**fields:entry.update(fields))
        self.assertTrue(early)
        self.assertTrue(any(isinstance(error,RuntimeError) and 'dictionary changed size' in str(error) for error in errors))


if __name__ == '__main__':unittest.main()
