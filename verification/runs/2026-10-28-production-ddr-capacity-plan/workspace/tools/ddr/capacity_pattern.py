"""Deterministic full-span DDR test data and an ordered streaming verifier.

No hardware API is imported. Patterns are memory-test expectations, never
runtime arithmetic/layout repair or an accelerator execution fallback. A
physical controller/transport witness is a separate acceptance requirement.
"""
from dataclasses import dataclass
import struct

LINE_BYTES = 64
PHYSICAL_BYTES = 1 << 31
DEFAULT_SEED = 0x3588C350


def require(ok, message):
    if not ok:
        raise ValueError(message)


@dataclass(frozen=True)
class CapacityPlan:
    base: int = 0
    size: int = PHYSICAL_BYTES
    seed: int = DEFAULT_SEED

    def __post_init__(self):
        require(type(self.base) is int and type(self.size) is int and
                self.base >= 0 and self.size > 0 and
                self.base % LINE_BYTES == self.size % LINE_BYTES == 0 and
                self.base + self.size <= PHYSICAL_BYTES,
                'Capacity window must be nonempty/aligned within the 31-bit DDR window')
        require(type(self.seed) is int and 0 <= self.seed <= 0xffffffff,
                'Capacity seed must be uint32')

    @property
    def lines(self):
        return self.size // LINE_BYTES

    @property
    def covers_full_window(self):
        return self.base == 0 and self.size == PHYSICAL_BYTES

    def pattern(self, address, trial):
        require(type(address) is int and self.base <= address < self.base+self.size
                and address % LINE_BYTES == 0, 'Pattern address is outside the planned window')
        require(type(trial) is int and trial in (0, 1), 'Only the two planned pattern trials exist')
        # Word0 directly distinguishes every 64-byte line. The remaining
        # lane constants exercise different byte/word positions. Trial1 is
        # the exact bitwise complement at every address and lane.
        index = address // LINE_BYTES
        complement = 0xffffffff if trial else 0
        words = [(index ^ self.seed ^ ((lane * 0x9e3779b9) & 0xffffffff)
                  ^ complement) for lane in range(LINE_BYTES // 4)]
        return struct.pack('<16I', *words)

    def operation(self, ordinal):
        require(type(ordinal) is int and 0 <= ordinal < 4*self.lines,
                'Capacity operation ordinal is outside the complete two-trial schedule')
        trial, offset = divmod(ordinal, 2*self.lines)
        writing = offset < self.lines
        position = offset if writing else offset-self.lines
        # Every trial writes the ENTIRE range before reading ANY of it.
        # The second trial reverses writes to expose address aliasing.
        line = self.lines-1-position if writing and trial else position
        address = self.base + line*LINE_BYTES
        return trial, 'WRITE64' if writing else 'READ64', address

    def manifest(self):
        return dict(schema='ddr-full-span-pattern-v1', base=self.base, size=self.size,
                    seed=self.seed, line_bytes=LINE_BYTES, lines=self.lines,
                    trials=2, operations=4*self.lines,
                    verified_read_bytes=2*self.size,
                    first_write_order='ascending', second_write_order='descending',
                    read_order='ascending', all_write_responses_required_before_reads=True,
                    controller_retirement_and_ecc_witness_required_separately=True,
                    pattern='LE uint32: line_index XOR seed XOR (lane*0x9e3779b9 mod2^32); trial1 complements all bits',
                    planned_full_window=self.covers_full_window,
                    hardware_executed=False, physical_capacity_qualified=False)


class CapacityVerifier:
    """Consume completed, externally decoded operations without buffering the span."""
    def __init__(self, plan):
        require(isinstance(plan, CapacityPlan), 'Explicit capacity plan required')
        self.plan = plan
        self.completed = 0
        self.failed = False
        self.finished = False

    def observe(self, *, trial, kind, address, data, response_status=0):
        require(not self.failed, 'A failed capacity stream cannot resume')
        require(not self.finished, 'A completed capacity stream cannot accept extra operations')
        try:
            expected = self.plan.operation(self.completed)
            require(type(trial) is int and type(address) is int and
                    (trial, kind, address) == expected,
                    'Capacity operation missing, duplicated, interleaved or reordered')
            require(type(response_status) is int and response_status == 0,
                    'Capacity transaction failed')
            require(type(data) is bytes and len(data) == LINE_BYTES and
                    data == self.plan.pattern(address, trial),
                    'Complete capacity line differs from its address/lane pattern')
            self.completed += 1
        except Exception:
            self.failed = True
            raise

    def finish(self):
        if self.failed or self.completed != 4*self.plan.lines:
            self.failed = True
            raise ValueError('Incomplete or failed full-span test cannot be accepted')
        self.finished = True
        return dict(status='PASS_ORDERED_DDR_SPAN_PATTERN_BYTES_ONLY',
                    completed_operations=self.completed, read_bytes=2*self.plan.size,
                    full_window_bytes_checked=self.plan.covers_full_window,
                    physical_capacity_qualified=False,
                    scope='Decoded ordered memory bytes only; source/image/target/transport/ECC/recovery require separate evidence')
