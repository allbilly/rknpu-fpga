# Retained normal and SYS JTAG mailbox component

`rk_retained_jtag_mailbox` wraps the unchanged OpenTPU raw mailbox with a
clock-local, configuration-only INIT reset. Default startup takes exactly
65 local rising edges. There is no client, MIG, PCIe, PERST or TAP reset input.
A stopped clock preserves an already offered request. Startup is not a clock
stability detector; the host must wait for platform readiness before commands.
The original one-outstanding-request host contract remains required.

Run `make host-retained-mailbox-test`, or
`python3 tools/host/run_retained_mailbox.py --out build/retained-check-new` with a
fresh output path. This target is included in `make test`. Icarus and Verilator
must both pass 55 checks. The current exact inherited-warning baseline requires
Verilator 5.048 with the version recorded in `source-contract.json`; other
versions fail explicitly. The runner selects and hashes a direct C++ compiler,
records tool versions, source hashes and process cleanup, and sets no RAM or
swap limits. Compiler and linker commands are explicitly bound through Make.

The bench scans actual 640-bit LSB-first frames at at most 6 MHz. Two wrappers
share TCK/DR controls with independent USER2/USER3 selection. The normal UI
mailbox feeds the actual whole-reset frame gate and a labeled address-echo
protocol fixture. A frame is offered before client reset, remains held while
UI is stopped, and is denied by the sealed gate after release without reaching
the fixture. A fresh command then executes once. Meanwhile the SYS-clock
mailbox reads the actual reset controller identity without UI clock edges.
Both startup delays, sequence correlation, complete frames, zero denial payload
and duplicate prevention are checked.

USER2/UI and USER3/SYS describe the intended board selection. This component
instantiates no BSCANE2/TAP, MIG, physical FI witness, PCIe IP or NPU arithmetic.
The test issues no whole-reset START request. Board frontend admission/drain,
physical clock/reset/CDC constraints and actual ECC/warm recovery remain
separate integration and hardware gates.
