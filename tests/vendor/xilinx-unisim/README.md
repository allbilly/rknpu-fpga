# Xilinx functional simulation models

These unmodified files are from [Xilinx/XilinxUnisimLibrary](https://github.com/Xilinx/XilinxUnisimLibrary/tree/1c8e05fd1e9a79ceb8b996a0996674122eed086f), commit `1c8e05fd1e9a79ceb8b996a0996674122eed086f` (the upstream README identifies Vivado 2020.1). Copyright notices and the Apache-2.0 `LICENSE` are preserved.

Only the mapped XC7 primitives needed by the YPCB demo, RAMB18E1 as an alternate block-RAM mapping, and the global startup model are included. This is test infrastructure, not imported NPU RTL. These files are never passed to FPGA synthesis as implementation sources.

Yosys's installed `xilinx/cells_sim.v` declares RAMB36E1 ports and timing arcs without implementing its memory behavior. Using it alone cannot verify the mapped RAM. `tools/run_synth.py` therefore uses these functional models through Icarus's library search and includes `glbl` as a root module. It records all model hashes with the synthesized netlist's provenance.

No routed delays or SDF are supplied. The models' internal functional delays do not establish board setup/hold timing or an operating frequency. Dynamic-register (`XIL_DR`) and timing-backannotation (`XIL_TIMING`) variants are not enabled by this test.
