#!/usr/bin/env python3
"""Offline callback fixtures for the root-owned SYS whole-reset client contract."""
import threading
import unittest

import tools.ddr.whole_reset as client
perform_whole_reset = client.perform_whole_reset
DeviceBusy = client.DeviceBusy
ProtocolError = client.ProtocolError
_D = client._Deadline

START = 0x53545254
ACK = 0x41434B21
ACTIVE, RESULT, ERROR, QUIESCE = 2, 4, 8, 16
SENT, ASSERTED, COMPLETE, FAULT, READY = 32, 64, 512, 1024, 2048
SUCCESS = RESULT | QUIESCE | SENT | ASSERTED | COMPLETE | READY


class FakeClock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value
    def advance(self, amount): self.value += amount


class CallbackFixture:
    """Small register-level state machine fixture; never models RTL timing/CDC."""
    def __init__(self, *, before=None, during=None, held=None, after_ack=None,
                 attempts_before=8, epoch_before=5, attempts_after=None, epoch_after=None,
                 changes=None, read_override=None, write_behavior=None, clock=None):
        self.clock=clock or FakeClock()
        self.before=dict(before or {})
        self.during=list(during if during is not None else [SUCCESS])
        self.held=SUCCESS if held is None else held
        self.after_ack=list(after_ack if after_ack is not None else [SENT|ASSERTED|COMPLETE|READY, 1|SENT|ASSERTED|COMPLETE|READY])
        self.attempts_before=attempts_before;self.epoch_before=epoch_before
        self.attempts_after=attempts_before+1 if attempts_after is None else attempts_after
        self.epoch_after=epoch_before+1 if epoch_after is None else epoch_after
        self.changes=dict(changes or {});self.read_override=read_override or {};self.write_behavior=write_behavior or {}
        self.phase='pre';self.status_pre_count=0;self.attempt_reads=0;self.epoch_reads=0
        self.during_i=0;self.after_i=0;self.actions=[];self.reads=[];self.deadline_ids=[];self.events=[]
    def read(self,address,*,deadline):
        self.deadline_ids.append(id(deadline));deadline.remaining();self.reads.append(address)
        if address in self.read_override:
            value=self.read_override[address]
            if isinstance(value,list):value=value.pop(0)
            self.events.append(('read',address,value));deadline.remaining();return value
        if address==0x00:value=0x524B5052
        elif address==0x04:value=0x00010000
        elif address==0x1C:value=0x00010001
        elif address==0x28:value=0x55667788
        elif address==0x2C:value=0x11223344
        elif address==0x10:
            self.attempt_reads+=1
            value=self.attempts_before if self.phase=='pre' else self.attempts_after
            if self.attempt_reads in self.changes:value=self.changes[self.attempt_reads]
        elif address==0x14:
            self.epoch_reads+=1
            value=self.epoch_before if self.phase=='pre' else self.epoch_after
        elif address==0x08:
            if self.phase=='pre':
                self.status_pre_count+=1;value=self.before.get('status',1)
                if self.status_pre_count in self.changes:value=self.changes[self.status_pre_count]
            elif self.phase=='after_start':
                if self.during_i<len(self.during):value=self.during[self.during_i];self.during_i+=1
                else:value=self.during[-1]
            else:
                if self.after_i<len(self.after_ack):value=self.after_ack[self.after_i];self.after_i+=1
                else:value=self.after_ack[-1]
        elif address==0x18:value=self.before.get('local_error',0)
        elif address==0x20:value=self.before.get('phase',4)
        elif address==0x24:value=self.before.get('coordinator_error',0)
        else:raise AssertionError(f'unexpected SYS read {address:#x}')
        self.events.append(('read',address,value));deadline.remaining();return value
    def write(self,address,value,*,deadline):
        self.deadline_ids.append(id(deadline));deadline.remaining();self.actions.append((address,value));self.events.append(('write',address,value))
        action=self.write_behavior.get(value)
        if action=='raise':
            self.clock.advance(0.0)
            raise TimeoutError('synthetic ambiguous write completion')
        if action=='nonnull':return 0
        if address!=0x0C:raise AssertionError(f'unexpected write address {address:#x}')
        if value==START:self.phase='after_start'
        elif value==ACK:self.phase='after_ack'
        else:raise AssertionError(f'client wrote unsupported action {value:#x}')
        deadline.remaining();return None
    def sleep(self,amount):
        self.clock.advance(amount)


def run_client(fixture,timeout=5.0):
    return perform_whole_reset(fixture.read,fixture.write,timeout=timeout,clock=fixture.clock,sleep=fixture.sleep)


class WholeResetClientOfflineTests(unittest.TestCase):
    def test_import_and_construction_do_no_callback_io(self):
        fixture=CallbackFixture()
        self.assertEqual(fixture.reads,[]);self.assertEqual(fixture.actions,[])
        # Function call needs explicit callbacks; there is no implicit link.
        with self.assertRaises(TypeError):perform_whole_reset(None,fixture.write,timeout=1)
        self.assertEqual(fixture.reads,[]);self.assertEqual(fixture.actions,[])

    def test_immediate_result_before_first_poll_success_ack(self):
        f=CallbackFixture(during=[SUCCESS],after_ack=[SENT|ASSERTED|COMPLETE|READY,1|SENT|ASSERTED|COMPLETE|READY])
        receipt=run_client(f)
        self.assertEqual(receipt.action_writes,((0x0C,START),(0x0C,ACK)))
        self.assertEqual((receipt.attempts_before,receipt.attempts_after,receipt.epoch_before,receipt.epoch_after),(8,9,5,6))
        self.assertEqual(receipt.configured_deadline_edges,0x1122334455667788)
        self.assertEqual(f.during_i,1)
        self.assertTrue(f.after_i>=2)
        self.assertEqual(len(set(f.deadline_ids)),1)

    def test_active_status_can_retain_old_live_complete_ready_and_fault(self):
        old_live=ACTIVE|QUIESCE|SENT|COMPLETE|READY|FAULT
        f=CallbackFixture(during=[old_live,ACTIVE|QUIESCE|SENT,SUCCESS])
        receipt=run_client(f)
        self.assertEqual(receipt.status_reads[1:4],(old_live,ACTIVE|QUIESCE|SENT,SUCCESS))
        self.assertEqual(receipt.action_writes,((0x0C,START),(0x0C,ACK)))

    def test_held_success_requires_each_freshness_witness(self):
        for missing in (RESULT,QUIESCE,SENT,ASSERTED,COMPLETE,READY):
            with self.subTest(missing=missing):
                held=SUCCESS & ~missing
                f=CallbackFixture(during=[held],held=held)
                with self.assertRaises(ProtocolError):run_client(f)
                self.assertEqual(f.actions,[(0x0C,START)])

    def test_held_success_rejects_each_forbidden_status_bit(self):
        for forbidden in (ACTIVE,ERROR,FAULT,1):
            with self.subTest(forbidden=forbidden):
                held=SUCCESS|forbidden
                f=CallbackFixture(during=[held],held=held)
                with self.assertRaises(ProtocolError):run_client(f)
                self.assertEqual(f.actions,[(0x0C,START)])

    def test_held_failure_never_acknowledged_even_with_success_flags(self):
        failure=SUCCESS|ERROR
        f=CallbackFixture(during=[failure])
        # Fixture error/phase values are provided for the diagnostic reads.
        f.before.update(local_error=3,phase=5,coordinator_error=7)
        with self.assertRaises(ProtocolError) as caught:run_client(f)
        self.assertEqual(f.actions,[(0x0C,START)])
        self.assertTrue(any('Do not retry or auto-ACK' in n for n in getattr(caught.exception,'__notes__',[])))

    def test_success_requires_exact_counter_epoch_phase_error_and_coordinator(self):
        cases=[{'attempts_after':10},{'epoch_after':7},{'read_override':{0x18:1}},{'read_override':{0x20:3}},{'read_override':{0x24:1}}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                f=CallbackFixture(during=[SUCCESS],**kwargs)
                with self.assertRaises(ProtocolError):run_client(f)
                self.assertEqual(f.actions,[(0x0C,START)])

    def test_post_ack_barrier_may_delay_start_and_retain_sent_asserted(self):
        retained=SENT|ASSERTED|COMPLETE|READY
        f=CallbackFixture(during=[SUCCESS],after_ack=[retained,retained|1])
        receipt=run_client(f)
        self.assertEqual(receipt.action_writes,((0x0C,START),(0x0C,ACK)))
        self.assertEqual(receipt.attempts_after,9);self.assertEqual(receipt.epoch_after,6)
        self.assertIn(retained,receipt.status_reads)

    def test_post_ack_start_eligible_waits_for_complete_and_ready(self):
        ready_without_start=COMPLETE|READY|SENT|ASSERTED
        states=[SENT|ASSERTED|1, COMPLETE|SENT|ASSERTED|1, ready_without_start|1]
        f=CallbackFixture(during=[SUCCESS],after_ack=states)
        receipt=run_client(f)
        post=receipt.status_reads[-len(states):]
        self.assertEqual(post,tuple(states))
        self.assertEqual(receipt.action_writes,((0x0C,START),(0x0C,ACK)))

    def test_post_ack_false_start_eligible_times_out_without_retry_or_false_clean(self):
        false_ready=1|SENT|ASSERTED
        f=CallbackFixture(during=[SUCCESS],after_ack=[false_ready])
        with self.assertRaises(TimeoutError):run_client(f,timeout=0.003)
        self.assertEqual(f.actions,[(0x0C,START),(0x0C,ACK)])
        self.assertFalse(any(address==0x0c and value==START for address,value in f.actions[1:]))

    def test_prestart_identity_abi_capability_and_deadline_reject_before_write(self):
        cases=[{0x00:0x12345678},{0x04:0x10001},{0x1C:0x10000},{0x28:0,0x2C:0}]
        for override in cases:
            with self.subTest(override=override):
                f=CallbackFixture(read_override=override)
                with self.assertRaises(ProtocolError):run_client(f)
                self.assertEqual(f.actions,[])

    def test_prestart_active_result_or_not_eligible_is_busy_without_write(self):
        for status in (ACTIVE|QUIESCE,RESULT|QUIESCE|SENT,0):
            with self.subTest(status=status):
                f=CallbackFixture(before={'status':status})
                with self.assertRaises(DeviceBusy):run_client(f)
                self.assertEqual(f.actions,[])

    def test_preexisting_fault_is_allowed_only_when_start_eligible(self):
        f=CallbackFixture(before={'status':1|FAULT},during=[SUCCESS])
        receipt=run_client(f)
        self.assertEqual(receipt.action_writes,((0x0C,START),(0x0C,ACK)))

    def test_counters_must_remain_stable_before_start(self):
        # read 1/2 are snapshots; read 3/4 are pre-START stability checks.
        f=CallbackFixture(read_override={0x10:[8,9]})
        with self.assertRaises(ProtocolError):run_client(f)
        self.assertEqual(f.actions,[])

    def test_unknown_reserved_and_contradictory_status_reject_before_or_after_start(self):
        for status in (1<<12,ACTIVE|RESULT,1|ACTIVE,ASSERTED):
            with self.subTest(status=status):
                f=CallbackFixture(before={'status':status})
                with self.assertRaises(ProtocolError):run_client(f)
                self.assertEqual(f.actions,[])

    def test_malformed_register_uint32_and_deadline_fail_before_start(self):
        f=CallbackFixture(read_override={0x00:0x1_0000_0000})
        with self.assertRaises(ProtocolError):run_client(f)
        self.assertEqual(f.actions,[])
        # One absolute budget is shared; a slow pre-START callback cannot be restarted.
        clock=FakeClock();g=CallbackFixture(clock=clock,read_override={0x00:0x524B5052})
        original=g.read
        def slow_read(address,*,deadline):
            value=original(address,deadline=deadline);clock.advance(2.0);return value
        with self.assertRaises(TimeoutError):perform_whole_reset(slow_read,g.write,timeout=1.0,clock=clock,sleep=g.sleep)
        self.assertEqual(g.actions,[])

    def test_deadline_expiring_after_start_status_callback_poison_no_retry(self):
        clock=FakeClock();f=CallbackFixture(clock=clock,during=[ACTIVE|QUIESCE])
        original=f.read
        def slow_status(address,*,deadline):
            value=original(address,deadline=deadline)
            if address==0x08 and f.phase=='after_start':clock.advance(2.0)
            return value
        with self.assertRaises(TimeoutError):perform_whole_reset(slow_status,f.write,timeout=1.0,clock=clock,sleep=f.sleep)
        self.assertEqual(f.actions,[(0x0C,START)])
        self.assertTrue(all(x==f.deadline_ids[0] for x in f.deadline_ids))

    def test_start_ambiguous_callback_is_never_retried(self):
        f=CallbackFixture(write_behavior={START:'raise'})
        with self.assertRaises(TimeoutError) as caught:run_client(f)
        self.assertEqual(f.actions,[(0x0C,START)])
        self.assertTrue(any('Do not retry or auto-ACK' in n for n in getattr(caught.exception,'__notes__',[])))

    def test_ack_ambiguous_callback_is_never_retried(self):
        f=CallbackFixture(during=[SUCCESS],held=SUCCESS,write_behavior={ACK:'raise'})
        with self.assertRaises(TimeoutError) as caught:run_client(f)
        self.assertEqual(f.actions,[(0x0C,START),(0x0C,ACK)])
        self.assertTrue(any('Do not retry or auto-ACK' in n for n in getattr(caught.exception,'__notes__',[])))

    def test_write_callback_non_none_is_protocol_failure_without_retry(self):
        f=CallbackFixture(write_behavior={START:'nonnull'})
        with self.assertRaises(ProtocolError):run_client(f)
        self.assertEqual(f.actions,[(0x0C,START)])

    def test_single_absolute_deadline_is_passed_to_every_callback(self):
        f=CallbackFixture(during=[SUCCESS])
        run_client(f)
        self.assertTrue(f.deadline_ids)
        self.assertEqual(len(set(f.deadline_ids)),1)
        self.assertTrue(all(event[1] in ({0,4,8,0x10,0x14,0x18,0x1c,0x20,0x24,0x28,0x2c,0x0c}) for event in f.events))
        self.assertTrue(all(event[0]=='read' or (event[0]=='write' and event[1]==0x0c and event[2] in (START,ACK)) for event in f.events))

    def test_no_bo_reset_or_backend_callbacks_exist_or_are_used(self):
        f=CallbackFixture(during=[SUCCESS])
        receipt=run_client(f)
        self.assertTrue(receipt.action_writes)
        self.assertTrue(all(address==0x0c and value in (START,ACK) for address,value in receipt.action_writes))
        self.assertNotIn(0x0c,[address for address in f.reads])
        self.assertEqual(set(f.reads).issubset({0x00,0x04,0x08,0x10,0x14,0x18,0x1c,0x20,0x24,0x28,0x2c}),True)


if __name__ == '__main__':
    unittest.main()
