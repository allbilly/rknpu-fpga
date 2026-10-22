# Continuation rules

Read README.md, docs/INTERFACE.md and docs/REVIEW_AND_PLAN.md first. This is a strict FP16 EW slice, not full RK3588 or a completed soDLA fork.

Keep raw final command words as the execution boundary. Do not bypass the backend encoder by passing tensor operations directly. Do not introduce runtime CPU arithmetic/layout fixups into the FPGA path. The software reference is a test target, not a fallback for hardware execution.

Unsupported fields must remain explicit failures. Add support with source evidence, numerical/shape contracts and tests. Do not silently ignore unmodeled register writes. Do not change error expectations just to obtain a green run.

Generated sources come from tools/gen_regfile.py and tools/gen_demo.py. Run make generated-check after edits. Run make test when tools exist; record unavailable tools honestly. C++ numeric tests do not validate SystemVerilog, and Verilator tests do not validate the actual FPGA or RK silicon.

Do not copy old verification logs forward as evidence for modified RTL. Record the actual tool version, source revision, seeds and tests. Numerical special-value policy remains candidate behavior until hardware differential tests establish it.

Never weaken electrical constraints, DRC or timing checks merely to produce a bitstream. Do not program the card or flash without an explicit requested action and an audited target.
