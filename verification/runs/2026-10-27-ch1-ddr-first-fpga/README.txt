First CH1 DDR volatile physical trial evidence archive.
Source tag: a2dfec21 (SHA256 a2dfec2162c2df789e3510bd547429592341d8bebd59c835eb4cec1f5af451b7).
Image SHA256: 45bd540cfaf7327ad8db5ba4e3a7548a209db1aeba4423f37159a72287296339. One volatile SRAM load, flash not written.
Observed: six 64-byte scratch addresses in two orders (768 bytes total), followed by one raw SUB9 job with 2 tasks and 102400-byte complete BO readback before ACK. The preserved native scan trace records 24238 scans / 8078 commands.
Scope limits: this does not qualify full-capacity DDR, ECC fault injection, full512 DDR, PCIe, RK silicon equivalence, or electrical signoff. Software CRC validation was NOT_PERFORMED. The archive is evidence preservation, not permission to program hardware.
