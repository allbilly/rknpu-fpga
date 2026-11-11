#!/usr/bin/env python3
"""Contract test for the S1 runtime page AXI wrapper (Icarus, light sim).

Compiles rk_conv_runtime_page_axi + rk_conv_runtime_core with the additive
experimental cell/array/cacc/stage copies and runs tb_page_axi_contract.
Must be launched through the host guard (heavy lock).
"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'build/runtime-conv-lab/page-contract'

SOURCES = [
    'rtl/vendor/nvdla/compat/nv_assert_never.v',
    'rtl/vendor/nvdla/compat/nv_assert_no_x.v',
    'rtl/vendor/nvdla/NV_DW_lsd.v',
    'rtl/vendor/nvdla/NV_DW02_tree.v',
    'rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',
    'rtl/vendor/nvdla/HLS_fp32_to_fp16.v',
    'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv',
    'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv',
    'rtl/cmac/rk_cmac_frame_output.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_writer.sv',
    'rtl/cmac/rk_cmac_fp32_writer.sv',
    'rtl/cmac/rk_cmac_output_fp32.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_fp32_output.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_core.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_frame_stage.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_cell.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_array.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_cacc_fp16_array.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_page_axi.sv',
    'tests/conv/runtime/tb_page_axi_contract.sv',
]

def main() -> int:
    if 'BENCH_MIN_BATTERY' not in os.environ:
        print('refused: launch only through build/verif/host_guard/safe_run.sh',
              file=sys.stderr)
        return 2
    stamp = subprocess.run(['date', '-u', '+%Y%m%dT%H%M%SZ'], text=True,
                           capture_output=True, check=True).stdout.strip()
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    # The vendor donor files include `nv_assert_never.vlib` / `nv_assert_no_x.vlib`
    # from rtl/vendor/nvdla/compat, so the include path is required (its absence
    # made every detached run fail in the preprocessor, not in the bench).
    compile_cmd = ['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST',
                   '-I', str(ROOT / 'rtl/vendor/nvdla'),
                   '-o', str(out / 'contract.vvp'),
                   '-s', 'tb_page_axi_contract'] + [str(ROOT / s) for s in SOURCES]
    comp = subprocess.run(compile_cmd, cwd=ROOT, text=True,
                          capture_output=True, check=False)
    (out / 'compile.log').write_text(comp.stdout + comp.stderr)
    if comp.returncode:
        print('COMPILE FAILED:', (comp.stdout + comp.stderr)[-2000:])
        return 1
    run = subprocess.run(['vvp', str(out / 'contract.vvp')], cwd=ROOT,
                         text=True, capture_output=True, check=False, timeout=1800)
    text = run.stdout + run.stderr
    (out / 'sim.log').write_text(text)
    ok = 'PASS PAGE_AXI_CONTRACT' in text
    print(f'{"PASS" if ok else "FAIL"} PAGE_AXI_CONTRACT -> {out}/sim.log')
    print(text.strip().splitlines()[-1] if text.strip() else '(no output)')
    return 0 if ok else 1

if __name__ == '__main__':
    raise SystemExit(main())
