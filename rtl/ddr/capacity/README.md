# Full512 DDR capacity profile

This is an explicit alternative source profile. Select this directory's
`rk_jtag_dual_ddr_async.sv` **instead of** `rtl/ddr/rk_jtag_dual_ddr_async.sv`;
the two files intentionally declare the same endpoint module. Do not compile
both definitions. Include the other eight RTL files in this directory and the
ordinary four `rtl/ddr/rk_ddr_capacity_*.sv` BIST files, plus the original
qualified normal DMA, full512 arithmetic, CDC/reset and MIG source closure.

The alternate parent preserves raw final-QWORD execution and both original
RKAD/RKCD job banks. Only `0x200..0x2ff` selects the separate RKMT management
bank. Its single destructive START requires idle initialized memory and
exclusive ownership. The sweep retains DDR ownership after completion or
fault; only the audited whole-domain reset permits normal work again.

The capacity parent now selects `rk_dual_job_control_admission` and
`rk_job_control_admission`. Their descriptor-write/SUBMIT/ACK guards use the
parent's direct `live_block | dma_busy | job_active` predicate, with the same
peer/scheduler restrictions. The original busy/error/status/cause reporting
remains intact, including the four-state status-can-submit expression.
The caller contract requires that a clear live block implies a clear core
error. Paired controller tests and the full-parent fast model check that
contract; they do not establish FPGA timing or physical DDR qualification.
The ordinary generic controllers remain separate, unchanged modules.

The ordinary numerical datapath, all 512 products, both original controllers,
physical pads and clocks remain requirements of the full board composition.
The standalone/modeled results do not establish physical capacity or recovery.
See [capacity preparation](../../../docs/DDR_CAPACITY_PREPARATION.md) for
contracts, validation receipts and the current full-design build.
