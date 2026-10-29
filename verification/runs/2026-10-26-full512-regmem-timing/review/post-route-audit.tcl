# Standalone read-only post-route audit; no implementation, bitstream or hardware commands.
# Root executes this only against the pinned completed full512 regmem checkpoint.
# Native command references: AMD UG835 report_route_status/report_pulse_width/get_waivers.
set expected_hashes [dict create \
    {/home/fedora/rknpu-fpga/build/full512-regmem-implementation/20261026T111740Z/run.json} {549a7c637bdaa1a49e7ec13f5f70ad89cdef784c658e4ee181ae6d8789ba5c59} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-implementation/20261026T111740Z/vivado.log} {ac66f1eca95bc4590a9245543c943f9f2ab17d4c6f5e8e4e50b00d0de9082cce} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/build.tcl} {ecda4325c745ae04dc19fbeb9a2fe7669f83c6605b8eb272639bffdc2570c880} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/implementation/routed.dcp} {9e3166635b11da4f44877991ee8c15fb9bc11d98727ce20038dba810819bba9f} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/report.json} {454a4a8125414f26c6559238ef2f140b28c76765614fad4a6b01bf1a893b13c0} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/root-build-review.json} {f3339a2b6a8961c9a0cafa489d27ca4d2dacdd7f9198381587eb3971973ddcc9} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-array-area/1792947201846706713/report.json} {90ac37edaf9c7d1d46314c4688d1f22da4fff4e0fc6f77258d8b12bc3334baaf} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-array-generated-top-replay/1792950494827304453/report.json} {14b1d5d6eda5d14a7e5753aff7ba1e79c0d288f8cafd31c876c675b2ead28133} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-array-native/1792947201927138428/report.json} {9d990fd582edf65cdba41932b9697d861864947b9825031f862b53bf22f2bd99} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-board-replay/1792947718359945807/report.json} {344e1c977516efa22d0d5e362ca0794182353cab69ede29906fd06309dae689d} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/area_snapshot.json} {90ac37edaf9c7d1d46314c4688d1f22da4fff4e0fc6f77258d8b12bc3334baaf} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/board_snapshot.json} {344e1c977516efa22d0d5e362ca0794182353cab69ede29906fd06309dae689d} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/mapped_snapshot.json} {14b1d5d6eda5d14a7e5753aff7ba1e79c0d288f8cafd31c876c675b2ead28133} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/native_snapshot.json} {9d990fd582edf65cdba41932b9697d861864947b9825031f862b53bf22f2bd99} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/profile_evidence.json} {a3d2fd87fc12680a9b34ef30bf667c504aca720ca6b47746d742de59d9671739} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/report.json} {b71c71aca1a2bccd80c263bd5e8854bc11b2688749a55aaf192a7eb2a261b635} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/rk_cmac_cacc_fp16_array.sv} {90f27bf34886173f3c7228d55f837139bbca65abb7a4411ea1bf230105700e4c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/array_sources.json} {aface51453933d919e833d5d9d8dac5a606ee287f1d9f42c371f12cb12dbd659} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/build_array.tcl.in} {fc721b15d329e531e5937a97bd8346c635a2458c779b2a8db82e34b362fb1275} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/startup/ypcb_cmac_array_regmem_top.sv} {0a76b3e1362f85e20deaa7894ee3d92d039d4096b00ada28f46b3828d26ce775} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/startup/ypcb_cmac_array_startup.xdc} {113ca200e9c86f967c16b6077f03d8e0882d4b5d4d858f65966016810f1a4647} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/startup/ypcb_cmac_array_startup_top.sv} {57cc07ce50aaa85ef556307948356c6360de72c147787ae6b2cedb9617cbe490} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/cmac/ypcb_cmac_array_top.sv} {2872f3470a267f8a2128631a082eacaa2ccaf39c799cee1eee298c42c60335ad} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/ew_checkpoint.tcl.in} {e598156491a55bdd5fd00f33a0b72bbfb978b487eda327267bba85e1b271a61b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/fpga/ypcb.xdc} {daa9aaddb8c02f539a58bb00faf9dedc260b205542a6d7851850c3b233325817} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/generated/rk_cmac_cacc_fp16_array.sv} {774c82e17445694dda784698c3d758f3fb69fbec48b2b988fd214fa34d513ef0} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_array_bram_demo_regmem.sv} {6ebd923159eb1bb746b48052cf907b33cb6f78a54b7877eff0a3c2c86b281f13} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_demo_memory_regport.sv} {c4ce96aa41db8616bfec1403886420ad27d0e524ccedd1f7fb191620eee03cb5} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv} {9d3c4b1775dbea2fe6f95a7364f762168091b3572ea5ebbbf2a88c19d144cf43} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix_pipe.sv} {1cf644cd2c0cfc29c2b50ae53520520b3e2152a593733d333ee74d0ab741453c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_array_fixed.sv} {f224977011f01de1f9772221c7be3d1fe11e2e5e9f2358991941f076f293b1ec} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv} {7e2de2abb8949c54e87220e0b0596db60a9bcbb1b4a1604a64473aa7b98b832d} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix_pipe.sv} {977961dcf3c0491d4c98e77d8bff14e97b367f4a569a285932ad6ef5b80b3924} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_cell_fixed.sv} {a5cd977ff063a50e0f77eabd087e5f71ba0101dc4914990c2c2e9c86e30034e7} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv} {265856695c352d9fee3f7f8858724c52103fe82b198717edccd7dec994f21f5b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv} {5d599f4efd6d8fe16dc54a5e0e1f426ba8735c416eabe886672d749f5a0aff2c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/experimental/rk_cmac_fp16_rows.sv} {eefcb5296112e958d9a9c30c1821d8364b9751a9dbd2ad7e0137cb3fc2c40574} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cacc_fp16_array.sv} {b55f02cdacc81ea2605f237d333d5cc4406bf8887a1649cec6914cd80e36f500} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_bram_demo.sv} {faa444d27e54562b3f1fe8fcc7a0b732ca6c2d4eae561dc723ab7acf1aeeeb38} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_core.sv} {95eefc20f818663a6a3cf7a3b8c7233842e70f60b97a158b0c41423fa35f092f} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_datapath.sv} {2c2fff0afa4000b394709c13e82903ea6e8f869e25b6bccc18c57093e938ae93} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_demo_rom.sv} {18a3abdd30c1c39ae22db5dcf9843b72dc20a26e528995a3943f25eb46c120ba} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_dma.sv} {cf5f0b098c1514f51ade0e8d88364637b05a8ab478417f01cf2f7297602fb0b0} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_array_front.sv} {03b28203092a37875363cb5b9b4539871a593838f7b3566c87c6b777e41fcfc7} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_cacc_fp16_array.sv} {b66904ee5a76325f72032adea874692179e981d459b57ad738414f39e9e209c6} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_demo_memory.sv} {d79444d1776d5664736da3d9d17405b0f890fda30759fa578f35a94cc69ae58d} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_fp16_array.sv} {62f8d10e064a21751b7b9e73713d8665d52a95f10151288a0167a8d7c4ec7223} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_fp16_cell.sv} {a44f54a1c8b76f5703d9807a05c308c03b7e2859aba06adadaa3772e79347109} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_frame_output.sv} {6be3150ce676e832a2af2d00f72162b86f9ec378827a8daec3eea3e2cb31217c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_output_nvdla.sv} {851a4ba7213ae749dc9ad445f4649abdb555385c2f17d4410164acfb86c19eb5} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_rw_arbiter.sv} {92c157082232bc7b74b90c4aee786e5269c6cf2303d6c7d17971f71d196cc5ac} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_cmac_writer.sv} {d2b1b6ea7c37c13f1cc601a2ae371d2625a75a637a8e5d10974af2a9b785ee25} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_nvdla_cacc.sv} {5a970a4d8c91660267815ba02a54bd0e8a50b755ce851806800c0db36e34654c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/cmac/rk_nvdla_fp32_to_fp16.sv} {bd71e8efbaecbd18263e8e8043a30614cacb04e966f336c2c5b031fe8506cdb3} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/rk_cmac_profile.sv} {01e1e4438e7787cf7a587287e7d4aa8f309511ef314f739a8db4cc5ebae2b995} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/rk_startup_reset.sv} {884afddfc59f0216a112990b63623251f3a951279ef6c5ea7ebb84e1a5d1bf09} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/HLS_fp32_to_fp16.v} {56755f347c87a7c8b33458dbdfd2630d57f4dbc4aa1f8f3b2a4dfefedc0401cd} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/LICENSE} {0f232029d97359752ac8a67f20e5fd6a703bb3af80f812ebff927a059a84cccb} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/NV_DW02_tree.v} {9c82f73fa7d7cfaed742a23b280b281bf2e1e965fa95600a0e9aa07f0f85a33e} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v} {ef3dbfb8b56f4359f6554af9e3c07e3b47b87423b255c17aaedeeb0dc94b7028} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v} {e3863ee66376dab62f7a07ec4cb86dc32084bc00999748cd65083342654394f6} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/assertion_header.h} {433144e681c5823d1e886c9872a8e6b2bd0b2d7e7f221f2dc8620ba04c2585e9} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/assertion_task.h} {1bff44cbd43cead87f9357c8ba25e1b7a1a639fabfc081082470655b69e25cbd} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/compat/NV_DW_lsd.v} {6a548e1fa7bd053f7eee59c32760c311f60b7595dff4043d8d4eb74fa9c0fee2} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/compat/nv_assert_never.v} {28a3ff37142647e9499cc0dd88095313c029acffe1bf7806160eb9fbbd288732} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/compat/nv_assert_no_x.v} {6eb56dc9ea269a4b071d3c00de3a23f5b75782b72403bcc72a7acc9e625a6e97} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/nv_assert_never.vlib} {d5b31a424e4518cdf58ef9fe303a749cd514bc1d134a9ac8198b454adc12c2ad} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/rtl/vendor/nvdla/nv_assert_no_x.vlib} {64ae1b6d9735257b681d3ad42ee0e05f425fc0ec11308c845cb7f668ce117a02} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/board_rom.hex} {7a56cabe51da7125e7259c3f423abaf69fde633a82269aa4ffce6238f47a1950} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/commands.hex} {4cbea40abde962107af9f438a69d7b94fd78839212d0116b11ecd3bc987f41c4} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/fixture.json} {98497400fd1ecc0c7cd94f2801ac42597a1d4a30f055c953c72ec1b5f2cc5a85} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/fp32.hex} {0725a51167e8a20b71350a12ab146cf43997812356cb2c495566aa6d094033ce} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/groups.hex} {fa427a46de9528ad0122f7304cc5f2d137e60a0bdcc118fa751802ada18d0416} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/input.hex} {3b68d117d69190b2100d5af71802a419ae31de587236654c4e04d76bfe0fec69} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/reads.hex} {975ef067253785dce6f9c60807bb92cf997d6ed044ea5276ac3c2491f4e5cdd6} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/source_report.json} {ce300a8a7349caf061e608a856d75e41eda1deb4433fcf576c43b0fac4af8248} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/weight.hex} {97279b0ffdeac95bc9c5d3548c21e70f83f40d90bf7f6e5882b2e53dd58100e1} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/array_data/writes.hex} {8ed44735a1c9271cf0b83c24d20d317ba517497b5c59b07bb0a0f43cbeae4dbf} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/startup/tb_array_startup.sv} {b861e0913aad677326a580880a167277e2218502ad52eed867848ff66842d3c0} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/startup/test_prepare.py} {9c62e707c2cbb828ceb21c78398fd925f9cdabe3fd320009020cebbd45d4efcd} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/cmac/startup/test_qualification.py} {102fefec73b9b07d6dd236cb69fae3fad805411e50e70afea04bd7dedb575aac} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tests/test_fpga_build.py} {2fa9140cecbc82e13274315536336313094b3a94e77ca003480524d85a3f3e13} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/audit_dsp_prefix_compile_inventory.py} {1aa44ce3df0af418a8ae636959138bdc081bd58e91b81057e7fe7fcf24b0ac82} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/audit_dsp_prefix_pin_cone.py} {d2fbe7cf11742acda2d940ee344739f2bd533b3f96497510725f8bf093c15717} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/audit_lane_dsp_product.py} {13bf929b6926de037196f25a0db1651840f095bcd01b2de16f0f506d676157fb} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/audit_lane_dsp_ranges.py} {35a7c42ff6a1fec392d137e570295056c601965744a70350ebff091fb62af3ea} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/balanced_max/prepare.py} {e3defc7ca9c095ec7e72b0e442fb7b93a05050f4877cdc2a9e57750db9a5dfc6} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/balanced_max/run.py} {1c5fba5f2a68b1e01fbf011f51b5d89d8ea4d07bff5ad9ad65cf810ec0664feb} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/check_lane_dsp.py} {17e920716c0a18db515094c53b5c7ee9a41fb52301daf712db9d211b4ca5f95c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_array_contract.py} {49905e33d4af52c06ed3e74e68037b18fb05a2444046e10eb7ab22ad52d57368} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_array_contract.py} {8bac0c7b674fbb5d21c3f97bc5340f27f416aac348917c21814ed436811c921f} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_build_contract.py} {5ef720a266b51c7de3df84f96a406691290cde4fd3862ac33c7b2ad6ef13e1b9} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_compile_admission.py} {4396df1950c6f56af47b67d186b5d97a0626810252cec666705966a42add46f9} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_mapped_contract.py} {bb550e278ad6dac9572d672d94c09a538db03383ecf73b5692a58e9f1e863b89} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_protected_library_contract.py} {13d2ff846881aaa48373cb9a77eeaff579cf498bfd402063d6b74904fd454f74} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/dsp_prefix_top_compile_admission.py} {000db28344e67219edfad141822c08329cf584457ce93b497b09190458748f3c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/gen_array_board.py} {fa27464c1ab58d0facd426e0aca893ecc123f604d6fcec349b44eeb4133270b2} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/lane_dsp_library.py} {697237ed52458fb8dafad09f3c2b05615f1aa41a4a997a4a67930f315fcb3c03} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/map_dsp_prefix_array.py} {ff44e73b6a4ef956627b302a383a688c7e8bb4500ac8b30d72dc58aa67d632d5} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/map_dsp_prefix_board.py} {3e7ff8d57dc01665d8f81e0825880aa7c2f46103e04c9932bccc0a3d0ff1fa6d} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/map_fixed_board.py} {d798e497bcb436d61278944f477a6ca89d2588837abb80e400bfcf0690d9b439} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/pipeline/prepare.py} {60daf7076df93d71dcdb7a60375f1900ac604b2bc908dd27b2399d44940e9915} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/pipeline/run.py} {2327f49ce80cb38b2965174a1be32bf49a77eb851dd8fa482bcc927a4ae63bd8} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prepare_dsp_prefix_array.py} {6456da3f40d98e80de6f9d16b6577d3a2500ae6c695f7e36f97b7a4ac9a9bd35} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prepare_dsp_prefix_board.py} {878cb06616fc460a088fbb18dd35ee232ac6a54c9b8a6ce47f630d54d2a4d71a} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prepare_dsp_prefix_checkpoint.py} {c9ac283ebb21a50e2fd78d76337b72e4a82246d06541880c94503c27887d9629} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prove_dsp_prefix_actual_model.py} {47efdcbbc88d0f93ed747e398214d57978dfaed82d53e7d5b6143fbb63072f83} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prove_lane_dsp_components.py} {c6ba910ec7aebf53cdb028b68a978071f03230ae2609fcb8edd6fed2949ab54b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prove_lane_dsp_composed.py} {fcd91f2eced2f14b4f6fe42ec5131c342e4a4e8ffa506ba4e21fe183857c4ea9} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/prove_lane_dsp_tree_ranges.py} {d4e7daa3ce35ed0af460cbbb0e9c3981b0aa22d1146adbf16a3d6dde9f1eeb10} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/regmem/prepare.py} {43ccb66812a7d08874a9f82c10a2a7185edb19e1064518ac3da44b75237d2597} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/regmem/run_memory.py} {62c4fbb68da30e3aa48202472a7c902209ce5c798abc67cffe12188c73a27e61} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/replay_dsp_prefix_board.py} {f10d734661edbe6c6134d2c26cf4a379ace1a7acc64f29bb38fd4768603c3295} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/startup/__init__.py} {0d21589252ac552e822c3b02da41720b8dd85b3dd65daa93c6511268c672df38} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/startup/prepare.py} {a4d74258640de9d856b5374146d08e5e4fa6704401934f8a601d7fcc1aeb7b86} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/startup/qualification.py} {b1ea244ce5e980387a7fbf3a2f05fbe10a8e76be03de0f88fb9ac8c5d44cd5af} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/startup/run.py} {65bd7dd4cefd961efefec7a328773adfeed220e1c7c36614e51952ad6a1ebd47} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_dsp_prefix_array_native.py} {1587a928863b5290a5161085ffad749d330665c6f11c6908d35529669e1dbbfe} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_dsp_prefix_carry.py} {f85adeb697e540ebbd61515a29427d1c49ffa2ca3b202e9488f898cd2f8c253c} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_dsp_prefix_fdce_startup.py} {8555eb593672e95f009c98714d1a58ac60d9a12d45279716ef89333bb1b68095} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_dsp_prefix_mapped_array.py} {49b0aded77c959e232c2db3bf92800e8ee9eda32a8abdd7c2e0e22bbf807537b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_dsp_prefix_primitive_models.py} {443d34ba4312ac4a724409b7fb18a436f30353114d15fac3f202c82de5f6eb7b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_fixed_array_board.py} {c1674b8a5c1eeedebbd96c5c7949371f1fa905ca8671491a39c8a70af0231928} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_fixed_mapped_array.py} {6ccc0efff1b87cb7424a5ab39a85812c932ad9d6548eb26a26a56fdfb3639a25} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/test_mapped_prefix_dsp.py} {2de4980c02d1478a2c8141f4678c71cb92e8ca5e7f91a364a56d271a44c07369} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/verify_dsp_prefix_clean_replay.py} {5d781c8560fafd8f0998b82a840bc07704495ffbd1014d8bc90a397cce383d23} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/vivado_array.py} {59e56a9dc53a924ae777f7ccf37d579d72cb641aa27afedb4010c1b9c25e652b} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/vivado_dsp_prefix_array.py} {0f94dd93dec5b3803d1136ae49afebc62dcc03c72ac346294874bf3803cc14c6} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/cmac/xc7_primitive_counts.py} {708a3e6b88a8b1889262291cc7c0a909e2ef9ba88c569a6d69477b9e2f81b8d7} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/evidence.py} {b660f509dd530516b77e45eedb6fd0d7430495dcc675a827971894cdc5cc2a54} \
    {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/source/tools/prepare_ew_fpga.py} {ac566b94c343baee21253f5389e624863d80bbf6f55cc755d2c40e18ba015dc6}]
proc require {condition message} {if {!$condition} {error $message}}
proc finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} result] && $result}]
}
proc pin_hashes {} {
    global expected_hashes
    dict for {path expected} $expected_hashes {
        require [file isfile $path] "Missing bound input: $path"
        set actual [lindex [exec sha256sum -- $path] 0]
        require [expr {$actual eq $expected}] "Changed bound input: $path"
    }
}
proc one {items label} {
    require [expr {[llength $items] == 1}] "Expected one $label; got $items"
    return [lindex $items 0]
}
proc save_text {path text} {
    set fd [open $path w]; puts $fd $text; close $fd
}
proc prop {object key} {
    if {[lsearch -exact [list_property $object] $key] < 0} {return "-"}
    return [get_property $key $object]
}
require [expr {$argc == 1}] "Usage: post-route-review.tcl <fresh-output-directory>"
set work {/home/fedora/rknpu-fpga/build/full512-regmem-implementation/20261026T111740Z}
set out [file normalize [lindex $argv 0]]
require [expr {[string first "$work/" "$out/"] == 0 && ![file exists $out]}] "Use a fresh output under the hardware work directory"
pin_hashes
file mkdir $out
open_checkpoint {/home/fedora/rknpu-fpga/build/full512-regmem-preparation/1793013000/implementation/routed.dcp}
require [expr {[get_property PART [current_design]] eq "xc7k480tffg1156-2"}] "Wrong routed part"
require [expr {[get_property TOP [current_design]] eq "ypcb_cmac_array_regmem_top"}] "Wrong routed top"
require [expr {[get_property CFGBVS [current_design]] eq "GND" &&
               [get_property CONFIG_VOLTAGE [current_design]] == 1.8}] "Changed reviewed electrical pair"
require [expr {[llength [get_waivers]] == 0}] "Waivers are forbidden"
set fully [report_route_status -boolean_check ROUTED_FULLY]
set errors [report_route_status -boolean_check ERRORS_IN_ROUTES]
require [expr {$fully == 1 && $errors == 0}] "Incomplete or erroneous routing"
report_route_status -file [file join $out route_status.rpt]
set ports [lsort [get_ports]]
set expected_ports [lsort {SYS_CLK led_3bits_tri_o[0] led_3bits_tri_o[1] led_3bits_tri_o[2]}]
require [expr {$ports eq $expected_ports}] "Unexpected top-level ports (including any reset input)"
set f [open [file join $out facts.tsv] w]
puts $f "PART\t[get_property PART [current_design]]"
puts $f "TOP\t[get_property TOP [current_design]]"
puts $f "CONFIG_VOLTAGE\t[get_property CONFIG_VOLTAGE [current_design]]"
puts $f "CFGBVS\t[get_property CFGBVS [current_design]]"
puts $f "ROUTED_FULLY\t$fully"
puts $f "ERRORS_IN_ROUTES\t$errors"
puts $f "WAIVERS\t[llength [get_waivers]]"
foreach {name pin direction} {SYS_CLK AA28 IN {led_3bits_tri_o[0]} P30 OUT {led_3bits_tri_o[1]} M30 OUT {led_3bits_tri_o[2]} N30 OUT} {
    set p [one [get_ports -quiet [list $name]] $name]
    require [expr {[get_property PACKAGE_PIN $p] eq $pin &&
                   [get_property IOSTANDARD $p] eq "LVCMOS18" &&
                   [get_property DIRECTION $p] eq $direction}] "Changed pin/standard/direction: $name"
    puts $f "PORT\t$name\t$pin\t[get_property IOSTANDARD $p]\t$direction"
}
set clock [one [get_clocks] clock]
require [expr {[get_property NAME $clock] eq "sys_clk"}] "Wrong clock name"
set period [get_property PERIOD $clock]
require [expr {[finite $period] && $period == 20.0}] "Wrong clock period"
set waveform [get_property WAVEFORM $clock]
require [expr {[llength $waveform] == 2 && [finite [lindex $waveform 0]] &&
               [finite [lindex $waveform 1]] && [lindex $waveform 0] == 0.0 &&
               [lindex $waveform 1] == 10.0}] "Wrong 50 percent waveform"
puts $f "CLOCK\t$clock\t$period\t[get_property WAVEFORM $clock]"
set timing [report_timing_summary -delay_type min_max -report_unconstrained -return_string]
save_text [file join $out timing.rpt] $timing
set summary 0
foreach line [split $timing \n] {
    if {[regexp {^\s*WNS\(ns\)\s+TNS\(ns\)} $line]} {set summary 1; continue}
    if {$summary == 1} {
        if {[string trim $line] eq "" || [regexp {^\s*-} $line]} {continue}
        set fields [regexp -all -inline {\S+} $line]
        require [expr {[llength $fields] == 12}] "Unknown timing summary layout"
        foreach number $fields {require [finite $number] "Invalid timing summary number"}
        foreach index {0 4 8} {require [expr {[lindex $fields $index] >= 0}] "Negative setup/hold/pulse slack"}
        foreach index {1 2 5 6 9 10} {require [expr {[lindex $fields $index] == 0}] "Failing timing endpoint/total slack"}
        foreach index {3 7 11} {require [expr {[lindex $fields $index] > 0}] "Missing timing endpoint coverage"}
        puts $f "TIMING_SUMMARY\t[join $fields \t]"
        set summary 2; break
    }
}
require [expr {$summary == 2}] "Missing timing summary"
foreach delay {max min} {
    set path [one [get_timing_paths -delay_type $delay -max_paths 1] "$delay timing path"]
    set slack [get_property SLACK $path]
    require [expr {[finite $slack] && $slack >= 0}] "Invalid/negative $delay slack"
    puts $f "WORST_PATH\t$delay\t$slack"
}
set pulse [report_pulse_width -return_string]
save_text [file join $out pulse_width.rpt] $pulse
set in_table 0; set seen {}
foreach line [split $pulse \n] {
    if {[regexp {^Check Type\s+Corner\s+Lib Pin} $line]} {set in_table 1; continue}
    if {!$in_table || [string trim $line] eq "" || [regexp {^\s*-+$} $line]} {continue}
    require [regexp {^(Min Period|Low Pulse Width|High Pulse Width)\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+\S+\s+\S+\s*$} $line -> kind required actual slack] "Unrecognized pulse check: $line"
    foreach number [list $required $actual $slack] {require [finite $number] "Invalid pulse number"}
    require [expr {$slack >= 0 && $required > 0 && $actual > 0}] "Pulse width failed"
    require [expr {[lsearch -exact $seen $kind] < 0}] "Duplicate pulse check type"
    lappend seen $kind
    puts $f "PULSE\t$kind\t$required\t$actual\t$slack"
}
require [expr {[lsort $seen] eq [lsort {"Min Period" "Low Pulse Width" "High Pulse Width"}]}] "Incomplete pulse checks"
set checked [check_timing -verbose -return_string]
save_text [file join $out check_timing.rpt] $checked
set counts [dict create]
foreach line [split $checked \n] {
    if {[regexp {^\s*[0-9]+\. checking ([a-z_]+) \(([0-9]+)\)\s*$} $line -> key count]} {
        dict set counts $key $count
    }
}
foreach key {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops} {
    require [expr {[dict exists $counts $key] && [dict get $counts $key] == 0}] "Missing or failed check_timing: $key"
}
require [expr {[dict exists $counts no_output_delay] && [dict get $counts no_output_delay] == 3}] "Changed LED-only output exception inventory"
require [expr {[string first "There are 0 ports with no output delay specified." $checked] >= 0 &&
               [string first "There are 3 ports with no output delay but user has a false path constraint" $checked] >= 0}] "Unexpected unconstrained output"
foreach name {led_3bits_tri_o[0] led_3bits_tri_o[1] led_3bits_tri_o[2]} {
    require [expr {[string first $name $checked] >= 0}] "Missing reviewed LED false path: $name"
}
puts $f "CHECK_TIMING\t$counts"
report_drc -file [file join $out drc.rpt]
set drc_counts [dict create DPIP-1 0 DPOP-1 0 DPOP-2 0]
foreach violation [get_drc_violations] {
    set name [get_property NAME $violation]
    set severity [string toupper [get_property SEVERITY $violation]]
    require [expr {$severity eq "WARNING"}] "Blocking/unreviewed DRC severity: $name $severity"
    require [regexp {^(DPIP-1|DPOP-1|DPOP-2)#[0-9]+$} $name -> rule] "Unreviewed DRC rule: $name"
    dict incr drc_counts $rule
    puts $f "DRC\t$name\t$severity"
}
require [expr {[dict get $drc_counts DPIP-1] == 1030 && [dict get $drc_counts DPOP-1] == 515 &&
               [dict get $drc_counts DPOP-2] == 515}] "Changed DSP pipeline warning inventory"
set bram [get_cells -hier -filter {REF_NAME == RAMB18E1 || REF_NAME == RAMB36E1}]
set dsp [get_cells -hier -filter {REF_NAME == DSP48E1}]
require [expr {[llength $bram] == 6 && [llength $dsp] == 515}] "Missing implemented BRAM/math primitives"
puts $f "BRAM_COUNT\t[llength $bram]"
puts $f "DSP_COUNT\t[llength $dsp]"
proc require_full_dsp_cmac {} {
    set kernels [get_cells -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
    if {[llength $kernels] != 16} { error "Expected sixteen full C32 DSP kernels." }
    set all_dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E1}]
    set owned {}
    foreach kernel $kernels {
        set prefix "[get_property NAME $kernel]/"
        set count 0
        foreach dsp $all_dsps {
            set name [get_property NAME $dsp]
            if {[string first $prefix $name] == 0} {
                if {[dict exists $owned $name]} { error "DSP belongs to duplicate CMAC kernels." }
                dict set owned $name 1
                incr count
            }
        }
        if {$count != 32} { error "Expected 32 DSP48E1 products in every C32 kernel." }
    }
    if {[dict size $owned] != 512} { error "Expected 512 retained parallel CMAC DSP products." }
}
require_full_dsp_cmac
set init_file [open [file join $out startup-and-control-facts.tsv] w]
set startup_count 0
foreach cell [lsort [get_cells -hier -filter {IS_PRIMITIVE}]] {
    set name [get_property NAME $cell]; set ref [get_property REF_NAME $cell]
    if {[string match "startup/*" $name] || [string match "*release_pipe_reg*" $name] ||
        [string match "*reset_n_reg*" $name] || [string match "*state_reg*" $name] ||
        [string match "RAMB*" $ref] || $ref eq "DSP48E1" || [string match "heartbeat_reg*" $name]} {
        puts $init_file "CELL\t$name\t$ref\tINIT=[prop $cell INIT]\tLOC=[prop $cell LOC]"
        if {[string match "startup/*" $name] || [string match "*release_pipe_reg*" $name]} {incr startup_count}
        if {$ref eq "DSP48E1"} {
            foreach key {AREG BREG ACASCREG BCASCREG CREG DREG ADREG MREG PREG ALUMODEREG OPMODEREG INMODEREG CARRYINREG CARRYINSELREG USE_MULT USE_SIMD USE_DPORT} {
                puts $init_file "DSP_PROPERTY\t$name\t$key\t[prop $cell $key]"
            }
            set selected_pins [get_pins -of_objects $cell -filter {REF_PIN_NAME == CLK}]
        } else {
            set selected_pins [get_pins -of_objects $cell -filter {DIRECTION == IN}]
        }
        foreach pin [lsort $selected_pins] {
            set nets [get_nets -quiet -segments -of_objects $pin]
            set drivers {}
            foreach source [get_pins -quiet -of_objects $nets -filter {DIRECTION == OUT}] {
                set parent [get_cells -quiet -of_objects $source]
                if {[llength $parent] == 1 && [get_property IS_PRIMITIVE $parent]} {lappend drivers $source}
            }
            puts $init_file "PIN\t$pin\tNETS=$nets\tDRIVERS=[lsort -unique $drivers]"
        }
    }
}
close $init_file
puts $f "STARTUP_NAMED_CELL_COUNT\t$startup_count"
set cones [open [file join $out function-cones.tsv] w]
foreach port [get_ports {led_3bits_tri_o[*]}] {
    puts $cones "PAD\t$port\tSTARTPOINTS=[all_fanin -flat -startpoints_only -to $port]"
}
foreach cell [get_cells -hier -filter {NAME =~ *state_reg* && IS_PRIMITIVE}] {
    foreach pin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == D}] {
        puts $cones "STATE_D\t$pin\tSTARTPOINTS=[all_fanin -flat -startpoints_only -to $pin]"
    }
}
close $cones
write_xdc -force [file join $out implemented.xdc]
report_utilization -hierarchical -file [file join $out utilization_hierarchical.rpt]
report_exceptions -file [file join $out exceptions.rpt]
close $f
pin_hashes
save_text [file join $out result.txt] "PASS_ROUTE_TIMING_IO_DRC_REVIEW; startup INIT/function cone facts require independent inspection before image approval; no bitstream or hardware action"
close_design
exit 0


