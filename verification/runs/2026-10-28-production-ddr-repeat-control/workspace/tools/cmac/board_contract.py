"""Exact result contract for the serialized CMAC BRAM board regression."""
import re

FIELDS = ('mode', 'success', 'resets', 'faults', 'init', 'check', 'cmd_reads',
          'operand_reads', 'writes', 'acks', 'cycles')
RESULT = re.compile(r'PASS CMAC BRAM board RTL ' +
                    ' '.join(name + r'=(\d+)' for name in FIELDS) +
                    r'; no physical FPGA test')


def validate_board_result(line, mode):
    """Keep full field boundaries; prefix matches must never qualify counts."""
    match = RESULT.fullmatch(line)
    if match is None or type(mode) is not int or mode not in range(9):
        raise ValueError('Malformed serialized board result')
    fields = dict(zip(FIELDS, map(int, match.groups())))
    good = mode in (0, 3, 4, 5, 6)
    expected = dict(mode=mode, success=2 if mode == 6 else int(good),
                    resets=int(mode in (3, 4, 5, 6)), faults=int(not good))
    if good:
        expected.update(init=4096, check=4096, cmd_reads=196,
                        operand_reads=12288, writes=64, acks=64)
    if any(fields[name] != value for name, value in expected.items()) or fields['cycles'] <= 0:
        raise ValueError('Wrong serialized board result counts')
    return fields
