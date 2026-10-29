"""Raw-byte DDR bring-up tests; callers own image/target/lease admission.

No connection or hardware action occurs on import. Expected BOs are test
targets only. A mismatch stops before ACK; no arithmetic/layout repair, retry,
reset, programming or CPU execution fallback is provided.
"""
from pathlib import Path
import hashlib
import re

LINE = re.compile(r'([0-9a-fA-F]{8}) ([0-9a-fA-F]{128})')
LIMIT = 1 << 31


def records(path):
    result = []
    previous = -1
    for line in Path(path).read_text().splitlines():
        match = LINE.fullmatch(line)
        if match is None:
            raise ValueError('Malformed raw BO line')
        address = int(match[1], 16)
        if address % 64 or address <= previous or address + 64 > LIMIT:
            raise ValueError('Raw BO lines must be unique, ordered, aligned and in31-bit RAM')
        result.append((address, int(match[2], 16).to_bytes(64, 'little')))
        previous = address
    if not result:
        raise ValueError('Empty raw BO image')
    return result


def run_case(device, upload, expected, output, *, command_address, initial_amount,
             expected_tasks, tag, initialization_timeout=30.0, job_timeout=30.0):
    """Execute an already-encoded program and compare every owned BO before ACK.

    This byte-only helper does not identify a physical card. The hardware
    runner must bind the actual scan trace, exact image/load receipt and lease.
    """
    before, after = records(upload), records(expected)
    if [address for address, _ in before] != [address for address, _ in after]:
        raise ValueError('Readback must cover the entire unchanged upload address set')
    if before == after:
        raise ValueError('Qualification fixture must require observable memory changes')
    if type(command_address) is not int or not 0 <= command_address < (1 << 32):
        raise ValueError('command address must be uint32')
    for value, name in ((initial_amount, 'amount'), (expected_tasks, 'task count'), (tag, 'tag')):
        if type(value) is not int or not 0 < value < (1 << 32):
            raise ValueError(name+' must be a nonzero uint32')
    if command_address % 16 or command_address >= LIMIT:
        raise ValueError('Command address must be16-byte aligned in31-bit RAM')
    if not any(address <= command_address < address+64 for address, _ in before):
        raise ValueError('Command pointer is absent from the raw upload')
    if expected_tasks > 4095:
        raise ValueError('Task count exceeds the bounded endpoint profile')
    output = Path(output)
    if output.exists() or not output.parent.is_dir():
        raise ValueError('Fresh complete readback path required')
    device.wait_memory_ready(timeout=initialization_timeout)
    for address, data in before:
        device.mem_write(address, data)
    device.submit(command_address, initial_amount, tag)
    result = device.poll_result(timeout=job_timeout)
    if (result.tag != tag or result.completed_tasks != expected_tasks or result.error_code or
            not result.status & 4 or result.status & (2 | 8 | 32 | 64)):
        raise ValueError('Raw hardware result differs from the fixed descriptor contract')
    checked = 0
    digest = hashlib.sha256()
    with output.open('x') as captured:
        for address, wanted in after:
            actual = device.mem_read(address, 64)
            if type(actual) is not bytes or len(actual) != 64:
                raise ValueError('Device returned an incomplete raw readback')
            # Preserve the actual bytes, including the first failing line.
            captured.write(f'{address:08x} {int.from_bytes(actual,"little"):0128x}\n')
            captured.flush()
            digest.update(actual)
            if actual != wanted:
                raise ValueError(f'Complete raw BO differs at {address:#x}; result remains unacknowledged')
            checked += 64
    device.ack_success()
    return dict(status='PASS_RAW_CASE_READBACK_AND_ACK', tag=tag, tasks=expected_tasks,
                checked_bo_bytes=checked, readback_bytes_sha256=digest.hexdigest(),
                output=str(output), source_commands_rewritten=False,
                cpu_arithmetic_or_layout_repair=False,
                scope='Caller-supplied device raw BO test; physical proof requires independent wire/image audit')


def scratch(device):
    """Two fixed write orders at address-bit and end-of-window landmarks.

    These six lines do not establish complete capacity or physical row mapping.
    The containing runner must use only disposable RAM in a fresh admitted image.
    """
    addresses = (0x40, 0x1000, 0x1800, 0x200040, 0x1000040, 0x7FFFFFC0)
    checked = 0
    for trial, order in enumerate((addresses, tuple(reversed(addresses)))):
        patterns = {address: bytes((i*37 + index*19 + trial*83) & 255 for i in range(64))
                    for index, address in enumerate(addresses)}
        for address in order:
            device.mem_write(address, patterns[address])
        for address in addresses:
            actual = device.mem_read(address, 64)
            if actual != patterns[address]:
                raise ValueError(f'DDR scratch mismatch at {address:#x}, trial{trial}: '
                                 f'actual={actual!r} expected={patterns[address]!r}')
            checked += 64
    return dict(status='PASS_SIX_LINE_SCRATCH_ONLY', addresses=list(addresses),
                trials=2, checked_bytes=checked, full_capacity_qualified=False)
