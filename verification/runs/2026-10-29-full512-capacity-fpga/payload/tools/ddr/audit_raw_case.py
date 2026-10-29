"""Independent byte/descriptor audit for one fixed raw DDR job session.

Consumes actual decoded scans; no transport, compiler or arithmetic oracle.
Image admission and fixture provenance remain the containing runner's job.
"""
from pathlib import Path
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fixture(path):
    result = []
    for row in Path(path).read_text().splitlines():
        require(re.fullmatch(r'[0-9a-f]{8} [0-9a-f]{128}', row), 'Malformed raw fixture')
        address, value = (int(part, 16) for part in row.split())
        require(address % 64 == 0 and address + 64 <= 1 << 31 and
                (not result or address > result[-1][0]), 'Unordered or unmapped BO')
        result.append((address, value))
    require(result, 'Empty raw fixture')
    return result


def replay(wire, upload, expected, *, profile, command_address, amount, tasks, tag):
    require(profile in ('ew', 'cmac'), 'Unknown raw profile')
    require(all(type(n) is int and 0 < n < 1 << 32 for n in
                (command_address, amount, tasks, tag)) and command_address % 16 == 0,
            'Invalid fixed descriptor')
    before, after = fixture(upload), fixture(expected)
    require([a for a, _ in before] == [a for a, _ in after] and before != after,
            'Incomplete or inert BO pair')
    base = 0 if profile == 'ew' else 0x100
    identities = set()
    last_status = {}
    uploaded = readbacks = staged = 0
    active = complete = acked = False
    result_regs = set()
    final_idle = False
    for row in wire:
        require(isinstance(row, dict) and all(type(row.get(k)) is int and row[k] >= 0
                for k in ('op', 'address', 'data', 'response')), 'Malformed raw command')
        op, address, data, response = (row[k] for k in ('op', 'address', 'data', 'response'))
        require(op in (1, 2, 3, 4) and (op not in (2, 4) or response == 0),
                'Unknown operation or failed write')
        if op == 1:
            require(data == 0 and response < 1 << 32, 'Malformed CSR read')
            if address in (0, 4, 0x100, 0x104):
                require(not active and not staged and not acked,
                        'Identity read during owned job')
                wanted = {0: 0x524b4144, 4: 0x10000, 0x100: 0x524b4344, 0x104: 0x10000}[address]
                require(response == wanted and (address % 256 == 0 or address - 4 in identities),
                        'Wrong namespace identity/ABI')
                identities.add(address)
            elif address in (8, 0x108):
                require(identities == {0, 4, 0x100, 0x104} and
                        not response & ~0x77f and not response & (8 | 32),
                        'Status before identity or faulted/unknown status')
                bank = address - 8
                require(not active or bank == base, 'Peer status during owned job')
                require(not (active and complete) or response & 4,
                        'Successful completion regressed before ACK')
                # The real register contract retains address/amount/tag valid
                # bits10:8 through execution and result readback. Derive them
                # from the observed descriptor writes, never mask them away.
                expected_fields = (1 << staged) - 1 if bank == base and not acked else 0
                require((response >> 8) & 7 == expected_fields,
                        'Descriptor-valid status disagrees with observed staging')
                if active and response & 4:
                    require(not response & (2 | 64), 'Completion while busy')
                    complete = True
                elif active:
                    require(response & 2 and not response & 1,
                            'Active status lost ownership or advertised submit')
                elif not active:
                    low_status = response & 0x7f
                    allowed = ((0x10,) if acked else
                               ((0, 0x10, 0x11) if expected_fields == 7 else (0, 0x10)))
                    require(low_status in allowed,
                            'Unexpected idle/staged status')
                last_status[bank] = response
                if acked and bank == base:
                    final_idle = response == 0x10
            else:
                require(active and complete and address in (base + 28, base + 32, base + 36),
                        'Unexpected result CSR or premature completion')
                offset = address - base
                require(offset not in result_regs and response == {28: tag, 32: tasks, 36: 0}[offset],
                        'Wrong or duplicate result register')
                result_regs.add(offset)
        elif op == 4:
            require(not active and not acked and staged == 0 and
                    identities == {0, 4, 0x100, 0x104} and last_status.get(base) == 0x10 and
                    uploaded < len(before) and (address, data) == before[uploaded],
                    'Raw upload changed or outside idle memory')
            uploaded += 1
        elif op == 3:
            require(data == 0 and active and complete and result_regs == {28, 32, 36} and
                    readbacks < len(after) and (address, response) == after[readbacks],
                    'Premature, incomplete or changed output readback')
            readbacks += 1
        elif address in (base + 16, base + 20, base + 24):
            require(not active and not acked and uploaded == len(before) and staged < 3 and
                    (address, data) == [(base + 16, command_address), (base + 20, amount),
                                        (base + 24, tag)][staged], 'Wrong raw descriptor/order')
            staged += 1
        elif address == base + 12 and data == 1:
            require(not active and not acked and staged == 3 and
                    last_status.get(base) == 0x711, 'Submit without staged ready descriptor')
            active = True
        elif address == base + 12 and data == 2:
            require(active and complete and result_regs == {28, 32, 36} and
                    readbacks == len(after), 'ACK before complete successful BO readback')
            active = False
            acked = True
        else:
            raise ValueError('Unexpected raw CSR write/reset attempt')
    require(acked and not active and final_idle and uploaded == readbacks == len(before),
            'Incomplete raw job/ACK/final health history')
    return dict(status='PASS_INDEPENDENT_SINGLE_RAW_JOB_WIRE_ONLY', profile=profile,
                jobs=1, tasks=tasks, complete_bo_bytes=64 * readbacks,
                complete_readback_before_ack=True, physical_image_qualified=False)
