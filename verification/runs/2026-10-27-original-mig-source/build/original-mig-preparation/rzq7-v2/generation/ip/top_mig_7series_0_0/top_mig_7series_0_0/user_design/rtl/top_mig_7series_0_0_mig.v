//*****************************************************************************
// (c) Copyright 2023 Advanced Micro Devices, Inc. All rights reserved.
//
// This file contains confidential and proprietary information
// of AMD and is protected under U.S. and international copyright
// and other intellectual property laws.
//
// DISCLAIMER
// This disclaimer is not a license and does not grant any
// rights to the materials distributed herewith. Except as
// otherwise provided in a valid license issued to you by
// AMD, and to the maximum extent permitted by applicable
// law: (1) THESE MATERIALS ARE MADE AVAILABLE "AS IS" AND
// WITH ALL FAULTS, AND AMD HEREBY DISCLAIMS ALL WARRANTIES
// AND CONDITIONS, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING
// BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, NON-
// INFRINGEMENT, OR FITNESS FOR ANY PARTICULAR PURPOSE; and
// (2) AMD shall not be liable (whether in contract or tort,
// including negligence, or under any other theory of
// liability) for any loss or damage of any kind or nature
// related to, arising under or in connection with these
// materials, including for any direct, or any indirect,
// special, incidental, or consequential loss or damage
// (including loss of data, profits, goodwill, or any type of
// loss or damage suffered as a result of any action brought
// by a third party) even if such damage or loss was
// reasonably foreseeable or AMD had been advised of the
// possibility of the same.
//
// CRITICAL APPLICATIONS
// AMD products are not designed or intended to be fail-
// safe, or for use in any application requiring fail-safe
// performance, such as life-support or safety devices or
// systems, Class III medical devices, nuclear facilities,
// applications related to the deployment of airbags, or any
// other applications that could lead to death, personal
// injury, or severe property or environmental damage
// (individually and collectively, "Critical
// Applications"). Customer assumes the sole risk and
// liability of any use of AMD products in Critical
// Applications, subject only to applicable laws and
// regulations governing limitations on product liability.
//
// THIS COPYRIGHT NOTICE AND DISCLAIMER MUST BE RETAINED AS
// PART OF THIS FILE AT ALL TIMES.
//
//*****************************************************************************
//   ____  ____
//  /   /\/   /
// /___/  \  /    Vendor             : AMD
// \   \   \/     Version            : 4.2
//  \   \         Application        : MIG
//  /   /         Filename           : top_mig_7series_0_0_mig.v
// /___/   /\     Date Last Modified : $Date: 2011/06/02 08:35:03 $
// \   \  /  \    Date Created       : Tue Sept 21 2010
//  \___\/\___\
//
// Device           : 7 Series
// Design Name      : DDR3 SDRAM
// Purpose          :
//   Top-level  module. This module can be instantiated in the
//   system and interconnect as shown in user design wrapper file (user top module).
//   In addition to the memory controller, the module instantiates:
//     1. Clock generation/distribution, reset logic
//     2. IDELAY control block
//     3. Debug logic
// Reference        :
// Revision History :
//*****************************************************************************

//`define SKIP_CALIB
`timescale 1ps/1ps

module top_mig_7series_0_0_mig #
  (

   //***************************************************************************
   // The following parameters refer to width of various ports
   //***************************************************************************
   parameter C0_BANK_WIDTH            = 3,
                                     // # of memory Bank Address bits.
   parameter C0_CK_WIDTH              = 1,
                                     // # of CK/CK# outputs to memory.
   parameter C0_COL_WIDTH             = 10,
                                     // # of memory Column Address bits.
   parameter C0_CS_WIDTH              = 1,
                                     // # of unique CS outputs to memory.
   parameter C0_nCS_PER_RANK          = 1,
                                     // # of unique CS outputs per rank for phy
   parameter C0_CKE_WIDTH             = 1,
                                     // # of CKE outputs to memory.
   parameter C0_DATA_BUF_ADDR_WIDTH   = 5,
   parameter C0_DQ_CNT_WIDTH          = 7,
                                     // = ceil(log2(DQ_WIDTH))
   parameter C0_DQ_PER_DM             = 8,
   parameter C0_DQ_WIDTH              = 72,
                                     // # of DQ (data)
   parameter C0_DQS_WIDTH             = 9,
   parameter C0_DQS_CNT_WIDTH         = 4,
                                     // = ceil(log2(DQS_WIDTH))
   parameter C0_DRAM_WIDTH            = 8,
                                     // # of DQ per DQS
   parameter C0_ECC                   = "ON",
   parameter C0_DATA_WIDTH            = 64,
   parameter C0_ECC_TEST              = "OFF",
   parameter C0_PAYLOAD_WIDTH         = (C0_ECC_TEST == "OFF") ? C0_DATA_WIDTH : C0_DQ_WIDTH,
   parameter C0_MEM_ADDR_ORDER        = "BANK_ROW_COLUMN",
                                      //Possible Parameters
                                      //1.BANK_ROW_COLUMN : Address mapping is
                                      //                    in form of Bank Row Column.
                                      //2.ROW_BANK_COLUMN : Address mapping is
                                      //                    in the form of Row Bank Column.
                                      //3.TG_TEST : Scrambles Address bits
                                      //            for distributed Addressing.
      
   //parameter C0_nBANK_MACHS           = 4,
   parameter C0_nBANK_MACHS           = 4,
   parameter C0_RANKS                 = 1,
                                     // # of Ranks.
   parameter C0_ODT_WIDTH             = 1,
                                     // # of ODT outputs to memory.
   parameter C0_ROW_WIDTH             = 15,
                                     // # of memory Row Address bits.
   parameter C0_ADDR_WIDTH            = 29,
                                     // # = RANK_WIDTH + BANK_WIDTH
                                     //     + ROW_WIDTH + COL_WIDTH;
                                     // Chip Select is always tied to low for
                                     // single rank devices
   parameter C0_USE_CS_PORT          = 1,
                                     // # = 1, When Chip Select (CS#) output is enabled
                                     //   = 0, When Chip Select (CS#) output is disabled
                                     // If CS_N disabled, user must connect
                                     // DRAM CS_N input(s) to ground
   parameter C0_USE_DM_PORT           = 0,
                                     // # = 1, When Data Mask option is enabled
                                     //   = 0, When Data Mask option is disbaled
                                     // When Data Mask option is disabled in
                                     // MIG Controller Options page, the logic
                                     // related to Data Mask should not get
                                     // synthesized
   parameter C0_USE_ODT_PORT          = 1,
                                     // # = 1, When ODT output is enabled
                                     //   = 0, When ODT output is disabled
                                     // Parameter configuration for Dynamic ODT support:
                                     // USE_ODT_PORT = 0, RTT_NOM = "DISABLED", RTT_WR = "60/120".
                                     // This configuration allows to save ODT pin mapping from FPGA.
                                     // The user can tie the ODT input of DRAM to HIGH.
   parameter C0_IS_CLK_SHARED          = "FALSE",
                                      // # = "true" when clock is shared
                                      //   = "false" when clock is not shared

   parameter C0_PHY_CONTROL_MASTER_BANK = 1,
                                     // The bank index where master PHY_CONTROL resides,
                                     // equal to the PLL residing bank
   parameter C0_MEM_DENSITY           = "2Gb",
                                     // Indicates the density of the Memory part
                                     // Added for the sake of Vivado simulations
   parameter C0_MEM_SPEEDGRADE        = "125",
                                     // Indicates the Speed grade of Memory Part
                                     // Added for the sake of Vivado simulations
   parameter C0_MEM_DEVICE_WIDTH      = 8,
                                     // Indicates the device width of the Memory Part
                                     // Added for the sake of Vivado simulations

   //***************************************************************************
   // The following parameters are mode register settings
   //***************************************************************************
   parameter C0_AL                    = "0",
                                     // DDR3 SDRAM:
                                     // Additive Latency (Mode Register 1).
                                     // # = "0", "CL-1", "CL-2".
                                     // DDR2 SDRAM:
                                     // Additive Latency (Extended Mode Register).
   parameter C0_nAL                   = 0,
                                     // # Additive Latency in number of clock
                                     // cycles.
   parameter C0_BURST_MODE            = "8",
                                     // DDR3 SDRAM:
                                     // Burst Length (Mode Register 0).
                                     // # = "8", "4", "OTF".
                                     // DDR2 SDRAM:
                                     // Burst Length (Mode Register).
                                     // # = "8", "4".
   parameter C0_BURST_TYPE            = "SEQ",
                                     // DDR3 SDRAM: Burst Type (Mode Register 0).
                                     // DDR2 SDRAM: Burst Type (Mode Register).
                                     // # = "SEQ" - (Sequential),
                                     //   = "INT" - (Interleaved).
   parameter C0_CL                    = 7,
                                     // in number of clock cycles
                                     // DDR3 SDRAM: CAS Latency (Mode Register 0).
                                     // DDR2 SDRAM: CAS Latency (Mode Register).
   parameter C0_CWL                   = 6,
                                     // in number of clock cycles
                                     // DDR3 SDRAM: CAS Write Latency (Mode Register 2).
                                     // DDR2 SDRAM: Can be ignored
   parameter C0_OUTPUT_DRV            = "HIGH",
                                     // Output Driver Impedance Control (Mode Register 1).
                                     // # = "HIGH" - RZQ/7,
                                     //   = "LOW" - RZQ/6.
   parameter C0_RTT_NOM               = "60",
                                     // RTT_NOM (ODT) (Mode Register 1).
                                     //   = "120" - RZQ/2,
                                     //   = "60"  - RZQ/4,
                                     //   = "40"  - RZQ/6.
   parameter C0_RTT_WR                = "OFF",
                                     // RTT_WR (ODT) (Mode Register 2).
                                     // # = "OFF" - Dynamic ODT off,
                                     //   = "120" - RZQ/2,
                                     //   = "60"  - RZQ/4,
   parameter C0_ADDR_CMD_MODE         = "1T" ,
                                     // # = "1T", "2T".
   parameter C0_REG_CTRL              = "OFF",
                                     // # = "ON" - RDIMMs,
                                     //   = "OFF" - Components, SODIMMs, UDIMMs.
   parameter C0_CA_MIRROR             = "OFF",
                                     // C/A mirror opt for DDR3 dual rank

   parameter C0_VDD_OP_VOLT           = "150",
                                     // # = "150" - 1.5V Vdd Memory part
                                     //   = "135" - 1.35V Vdd Memory part

   
   //***************************************************************************
   // The following parameters are multiplier and divisor factors for PLLE2.
   // Based on the selected design frequency these parameters vary.
   //***************************************************************************
   parameter C0_CLKIN_PERIOD          = 5000,
                                     // Input Clock Period
   parameter C0_CLKFBOUT_MULT         = 16,
                                     // write PLL VCO multiplier
   parameter C0_DIVCLK_DIVIDE         = 3,
                                     // write PLL VCO divisor
   parameter C0_CLKOUT0_PHASE         = 337.5,
                                     // Phase for PLL output clock (CLKOUT0)
   parameter C0_CLKOUT0_DIVIDE        = 2,
                                     // VCO output divisor for PLL output clock (CLKOUT0)
   parameter C0_CLKOUT1_DIVIDE        = 2,
                                     // VCO output divisor for PLL output clock (CLKOUT1)
   parameter C0_CLKOUT2_DIVIDE        = 32,
                                     // VCO output divisor for PLL output clock (CLKOUT2)
   parameter C0_CLKOUT3_DIVIDE        = 8,
                                     // VCO output divisor for PLL output clock (CLKOUT3)
   parameter C0_MMCM_VCO              = 1066,
                                     // Max Freq (MHz) of MMCM VCO
   parameter C0_MMCM_MULT_F           = 8,
                                     // write MMCM VCO multiplier
   parameter C0_MMCM_DIVCLK_DIVIDE    = 1,
                                     // write MMCM VCO divisor

   //***************************************************************************
   // Memory Timing Parameters. These parameters varies based on the selected
   // memory part.
   //***************************************************************************
   parameter C0_tCKE                  = 5000,
                                     // memory tCKE paramter in pS
   parameter C0_tFAW                  = 30000,
                                     // memory tRAW paramter in pS.
   parameter C0_tPRDI                 = 1_000_000,
                                     // memory tPRDI paramter in pS.
   parameter C0_tRAS                  = 35000,
                                     // memory tRAS paramter in pS.
   parameter C0_tRCD                  = 13750,
                                     // memory tRCD paramter in pS.
   parameter C0_tREFI                 = 7800000,
                                     // memory tREFI paramter in pS.
   parameter C0_tRFC                  = 160000,
                                     // memory tRFC paramter in pS.
   parameter C0_tRP                   = 13750,
                                     // memory tRP paramter in pS.
   parameter C0_tRRD                  = 6000,
                                     // memory tRRD paramter in pS.
   parameter C0_tRTP                  = 7500,
                                     // memory tRTP paramter in pS.
   parameter C0_tWTR                  = 7500,
                                     // memory tWTR paramter in pS.
   parameter C0_tZQI                  = 128_000_000,
                                     // memory tZQI paramter in nS.
   parameter C0_tZQCS                 = 64,//64,
                                     // memory tZQCS paramter in clock cycles.

   //***************************************************************************
   // Simulation parameters
   //***************************************************************************
   parameter C0_SIM_BYPASS_INIT_CAL   = "OFF",
                                     // # = "OFF" -  Complete memory init &
                                     //              calibration sequence
                                     // # = "SKIP" - Not supported
                                     // # = "FAST" - Complete memory init & use
                                     //              abbreviated calib sequence

   parameter C0_SIMULATION            = "FALSE",
                                     // Should be TRUE during design simulations and
                                     // FALSE during implementations

   //***************************************************************************
   // The following parameters varies based on the pin out entered in MIG GUI.
   // Do not change any of these parameters directly by editing the RTL.
   // Any changes required should be done through GUI and the design regenerated.
   //***************************************************************************
   parameter C0_BYTE_LANES_B0         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C0_BYTE_LANES_B1         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C0_BYTE_LANES_B2         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C0_BYTE_LANES_B3         = 4'b0000,
                                     // Byte lanes used in an IO column.
   parameter C0_BYTE_LANES_B4         = 4'b0000,
                                     // Byte lanes used in an IO column.
   parameter C0_DATA_CTL_B0           = 4'b1111,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C0_DATA_CTL_B1           = 4'b0001,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C0_DATA_CTL_B2           = 4'b1111,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C0_DATA_CTL_B3           = 4'b0000,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C0_DATA_CTL_B4           = 4'b0000,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C0_PHY_0_BITLANES        = 48'h3FC_3D7_1FE_2FE,
   parameter C0_PHY_1_BITLANES        = 48'h37E_FFF_C30_0FF,
   parameter C0_PHY_2_BITLANES        = 48'h3FC_33F_0FF_0FF,

   // control/address/data pin mapping parameters
   parameter C0_CK_BYTE_MAP
     = 144'h00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_13,
   parameter C0_ADDR_MAP
     = 192'h000_131_12B_129_123_124_139_11A_114_122_11B_115_121_12A_138_120,
   parameter C0_BANK_MAP   = 36'h132_136_128,
   parameter C0_CAS_MAP    = 12'h135,
   parameter C0_CKE_ODT_BYTE_MAP = 8'h00,
   parameter C0_CKE_MAP    = 96'h000_000_000_000_000_000_000_134,
   parameter C0_ODT_MAP    = 96'h000_000_000_000_000_000_000_126,
   parameter C0_CS_MAP     = 120'h000_000_000_000_000_000_000_000_000_125,
   parameter C0_PARITY_MAP = 12'h000,
   parameter C0_RAS_MAP    = 12'h127,
   parameter C0_WE_MAP     = 12'h133,
   parameter C0_DQS_BYTE_MAP
     = 144'h00_00_00_00_00_00_00_00_00_00_10_03_02_01_20_23_22_21,
   parameter C0_DATA0_MAP  = 96'h214_215_217_212_216_213_211_210,
   parameter C0_DATA1_MAP  = 96'h228_222_225_221_224_220_229_223,
   parameter C0_DATA2_MAP  = 96'h234_237_233_236_232_239_235_238,
   parameter C0_DATA3_MAP  = 96'h201_200_205_203_204_206_202_207,
   parameter C0_DATA4_MAP  = 96'h011_015_012_014_013_018_016_017,
   parameter C0_DATA5_MAP  = 96'h027_020_026_021_029_024_022_028,
   parameter C0_DATA6_MAP  = 96'h033_035_037_036_039_034_038_032,
   parameter C0_DATA7_MAP  = 96'h101_104_100_102_107_103_106_105,
   parameter C0_DATA8_MAP  = 96'h005_009_003_004_001_007_002_006,
   parameter C0_DATA9_MAP  = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA10_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA11_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA12_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA13_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA14_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA15_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA16_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_DATA17_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C0_MASK0_MAP  = 108'h000_000_000_000_000_000_000_000_000,
   parameter C0_MASK1_MAP  = 108'h000_000_000_000_000_000_000_000_000,

   parameter C0_SLOT_0_CONFIG         = 8'b0000_0001,
                                     // Mapping of Ranks.
   parameter C0_SLOT_1_CONFIG         = 8'b0000_0000,
                                     // Mapping of Ranks.

   //***************************************************************************
   // IODELAY and PHY related parameters
   //***************************************************************************
   parameter C0_IBUF_LPWR_MODE        = "OFF",
                                     // to phy_top
   parameter C0_DATA_IO_IDLE_PWRDWN   = "ON",
                                     // # = "ON", "OFF"
   parameter C0_BANK_TYPE             = "HR_IO",
                                     // # = "HP_IO", "HPL_IO", "HR_IO", "HRL_IO"
   parameter C0_DATA_IO_PRIM_TYPE     = "HR_LP",
                                     // # = "HP_LP", "HR_LP", "DEFAULT"
   parameter C0_CKE_ODT_AUX           = "FALSE",
   parameter C0_USER_REFRESH          = "OFF",
   parameter C0_WRLVL                 = "ON",
                                     // # = "ON" - DDR3 SDRAM
                                     //   = "OFF" - DDR2 SDRAM.
   parameter C0_ORDERING              = "NORM",
                                     // # = "NORM", "STRICT", "RELAXED".
   parameter C0_CALIB_ROW_ADD         = 16'h0000,
                                     // Calibration row address will be used for
                                     // calibration read and write operations
   parameter C0_CALIB_COL_ADD         = 12'h000,
                                     // Calibration column address will be used for
                                     // calibration read and write operations
   parameter C0_CALIB_BA_ADD          = 3'h0,
                                     // Calibration bank address will be used for
                                     // calibration read and write operations
   parameter C0_TCQ                   = 100,
   parameter C0_IDELAY_ADJ            = "OFF",
   parameter C0_FINE_PER_BIT          = "OFF",
   parameter C0_CENTER_COMP_MODE      = "OFF",
   parameter C0_PI_VAL_ADJ            = "OFF",
   parameter IODELAY_GRP0          = "TOP_MIG_7SERIES_0_0_IODELAY_MIG0",
                                     // It is associated to a set of IODELAYs with
                                     // an IDELAYCTRL that have same IODELAY CONTROLLER
                                     // clock frequency (200MHz).
   parameter IODELAY_GRP1          = "TOP_MIG_7SERIES_0_0_IODELAY_MIG1",
                                     // It is associated to a set of IODELAYs with
                                     // an IDELAYCTRL that have same IODELAY CONTROLLER
                                     // clock frequency (300MHz/400MHz).
   parameter SYSCLK_TYPE           = "DIFFERENTIAL",
                                     // System clock type DIFFERENTIAL, SINGLE_ENDED,
                                     // NO_BUFFER
   parameter REFCLK_TYPE           = "USE_SYSTEM_CLOCK",
                                     // Reference clock type DIFFERENTIAL, SINGLE_ENDED,
                                     // NO_BUFFER, USE_SYSTEM_CLOCK
   parameter SYS_RST_PORT          = "FALSE",
                                     // "TRUE" - if pin is selected for sys_rst
                                     //          and IBUF will be instantiated.
                                     // "FALSE" - if pin is not selected for sys_rst
   parameter FPGA_SPEED_GRADE      = 2,
                                     // FPGA speed grade
      
   parameter C0_CMD_PIPE_PLUS1        = "ON",
                                     // add pipeline stage between MC and PHY
   parameter DRAM_TYPE             = "DDR3",
   parameter CAL_WIDTH             = "HALF",
   parameter STARVE_LIMIT          = 2,
                                     // # = 2,3,4.
   parameter REF_CLK_MMCM_IODELAY_CTRL    = "FALSE",
      

   //***************************************************************************
   // Referece clock frequency parameters
   //***************************************************************************
   parameter REFCLK_FREQ           = 200.0,
                                     // IODELAYCTRL reference clock frequency
   parameter DIFF_TERM_REFCLK      = "TRUE",
                                     // Differential Termination for idelay
                                     // reference clock input pins
   //***************************************************************************
   // System clock frequency parameters
   //***************************************************************************
   parameter C0_tCK                   = 1875,
                                     // memory tCK paramter.
                                     // # = Clock Period in pS.
   parameter C0_nCK_PER_CLK           = 4,
   // # of memory CKs per fabric CLK
   
   parameter C0_DIFF_TERM_SYSCLK      = "FALSE",
                                     // Differential Termination for System
                                     // clock input pins
      

   
   //***************************************************************************
   // AXI4 Shim parameters
   //***************************************************************************
   
   parameter C0_UI_EXTRA_CLOCKS = "FALSE",
                                     // Generates extra clocks as
                                     // 1/2, 1/4 and 1/8 of fabrick clock.
                                     // Valid for DDR2/DDR3 AXI interfaces
                                     // based on GUI selection
   parameter C0_C_S_AXI_ID_WIDTH              = 4,
                                             // Width of all master and slave ID signals.
                                             // # = >= 1.
   parameter C0_C_S_AXI_MEM_SIZE              = "2147483648",
                                     // Address Space required for this component
   parameter C0_C_S_AXI_ADDR_WIDTH            = 31,
                                             // Width of S_AXI_AWADDR, S_AXI_ARADDR, M_AXI_AWADDR and
                                             // M_AXI_ARADDR for all SI/MI slots.
                                             // # = 32.
   parameter C0_C_S_AXI_DATA_WIDTH            = 512,
                                             // Width of WDATA and RDATA on SI slot.
                                             // Must be <= APP_DATA_WIDTH.
                                             // # = 32, 64, 128, 256.
   parameter C0_C_MC_nCK_PER_CLK              = 4,
                                             // Indicates whether to instatiate upsizer
                                             // Range: 0, 1
   parameter C0_C_S_AXI_SUPPORTS_NARROW_BURST = 0,
                                             // Indicates whether to instatiate upsizer
                                             // Range: 0, 1
   parameter C0_C_RD_WR_ARB_ALGORITHM          = "RD_PRI_REG",
                                             // Indicates the Arbitration
                                             // Allowed values - "TDM", "ROUND_ROBIN",
                                             // "RD_PRI_REG", "RD_PRI_REG_STARVE_LIMIT"
                                             // "WRITE_PRIORITY", "WRITE_PRIORITY_REG"
   parameter C0_C_S_AXI_REG_EN0               = 20'h00000,
                                             // C_S_AXI_REG_EN0[00] = Reserved
                                             // C_S_AXI_REG_EN0[04] = AW CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[05] =  W CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[06] =  B CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[07] =  R CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[08] = AW CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[09] =  W CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[10] = AR CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[11] =  R CHANNEL UPSIZER REGISTER SLICE
   parameter C0_C_S_AXI_REG_EN1               = 20'h00000,
                                             // Instatiates register slices after the upsizer.
                                             // The type of register is specified for each channel
                                             // in a vector. 4 bits per channel are used.
                                             // C_S_AXI_REG_EN1[03:00] = AW CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[07:04] =  W CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[11:08] =  B CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[15:12] = AR CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[20:16] =  R CHANNEL REGISTER SLICE
                                             // Possible values for each channel are:
                                             //
                                             //   0 => BYPASS    = The channel is just wired through the
                                             //                    module.
                                             //   1 => FWD       = The master VALID and payload signals
                                             //                    are registrated.
                                             //   2 => REV       = The slave ready signal is registrated
                                             //   3 => FWD_REV   = Both FWD and REV
                                             //   4 => SLAVE_FWD = All slave side signals and master
                                             //                    VALID and payload are registrated.
                                             //   5 => SLAVE_RDY = All slave side signals and master
                                             //                    READY are registrated.
                                             //   6 => INPUTS    = Slave and Master side inputs are
                                             //                    registrated.
                                             //   7 => ADDRESS   = Optimized for address channel
   parameter C0_C_S_AXI_CTRL_ADDR_WIDTH       = 32,
                                             // Width of AXI-4-Lite address bus
   parameter C0_C_S_AXI_CTRL_DATA_WIDTH       = 32,
                                             // Width of AXI-4-Lite data buses
   parameter C0_C_S_AXI_BASEADDR              = 32'h0000_0000,
                                             // Base address of AXI4 Memory Mapped bus.
   parameter C0_C_ECC_ONOFF_RESET_VALUE       = 1,
                                             // Controls ECC on/off value at startup/reset
   parameter C0_C_ECC_CE_COUNTER_WIDTH        = 8,
                                             // The external memory to controller clock ratio.

   //***************************************************************************
   // Debug parameters
   //***************************************************************************
   parameter C0_DEBUG_PORT            = "OFF",
                                     // # = "ON" Enable debug signals/controls.
                                     //   = "OFF" Disable debug signals/controls.

   //***************************************************************************
   // Temparature monitor parameter
   //***************************************************************************
   parameter C0_TEMP_MON_CONTROL      = "INTERNAL",
                                     // # = "INTERNAL", "EXTERNAL"
   //***************************************************************************
   // FPGA Voltage Type parameter
   //***************************************************************************
   parameter C0_FPGA_VOLT_TYPE        = "N",
                                     // # = "L", "N". When FPGA VccINT is 0.9v,
                                     // the value is "L", else it is "N"
      
   //***************************************************************************
   // The following parameters refer to width of various ports
   //***************************************************************************
   parameter C1_BANK_WIDTH            = 3,
                                     // # of memory Bank Address bits.
   parameter C1_CK_WIDTH              = 1,
                                     // # of CK/CK# outputs to memory.
   parameter C1_COL_WIDTH             = 10,
                                     // # of memory Column Address bits.
   parameter C1_CS_WIDTH              = 1,
                                     // # of unique CS outputs to memory.
   parameter C1_nCS_PER_RANK          = 1,
                                     // # of unique CS outputs per rank for phy
   parameter C1_CKE_WIDTH             = 1,
                                     // # of CKE outputs to memory.
   parameter C1_DATA_BUF_ADDR_WIDTH   = 5,
   parameter C1_DQ_CNT_WIDTH          = 7,
                                     // = ceil(log2(DQ_WIDTH))
   parameter C1_DQ_PER_DM             = 8,
   parameter C1_DQ_WIDTH              = 72,
                                     // # of DQ (data)
   parameter C1_DQS_WIDTH             = 9,
   parameter C1_DQS_CNT_WIDTH         = 4,
                                     // = ceil(log2(DQS_WIDTH))
   parameter C1_DRAM_WIDTH            = 8,
                                     // # of DQ per DQS
   parameter C1_ECC                   = "ON",
   parameter C1_DATA_WIDTH            = 64,
   parameter C1_ECC_TEST              = "OFF",
   parameter C1_PAYLOAD_WIDTH         = (C1_ECC_TEST == "OFF") ? C1_DATA_WIDTH : C1_DQ_WIDTH,
   parameter C1_MEM_ADDR_ORDER        = "BANK_ROW_COLUMN",
                                      //Possible Parameters
                                      //1.BANK_ROW_COLUMN : Address mapping is
                                      //                    in form of Bank Row Column.
                                      //2.ROW_BANK_COLUMN : Address mapping is
                                      //                    in the form of Row Bank Column.
                                      //3.TG_TEST : Scrambles Address bits
                                      //            for distributed Addressing.
      
   //parameter C1_nBANK_MACHS           = 4,
   parameter C1_nBANK_MACHS           = 4,
   parameter C1_RANKS                 = 1,
                                     // # of Ranks.
   parameter C1_ODT_WIDTH             = 1,
                                     // # of ODT outputs to memory.
   parameter C1_ROW_WIDTH             = 15,
                                     // # of memory Row Address bits.
   parameter C1_ADDR_WIDTH            = 29,
                                     // # = RANK_WIDTH + BANK_WIDTH
                                     //     + ROW_WIDTH + COL_WIDTH;
                                     // Chip Select is always tied to low for
                                     // single rank devices
   parameter C1_USE_CS_PORT          = 1,
                                     // # = 1, When Chip Select (CS#) output is enabled
                                     //   = 0, When Chip Select (CS#) output is disabled
                                     // If CS_N disabled, user must connect
                                     // DRAM CS_N input(s) to ground
   parameter C1_USE_DM_PORT           = 0,
                                     // # = 1, When Data Mask option is enabled
                                     //   = 0, When Data Mask option is disbaled
                                     // When Data Mask option is disabled in
                                     // MIG Controller Options page, the logic
                                     // related to Data Mask should not get
                                     // synthesized
   parameter C1_USE_ODT_PORT          = 1,
                                     // # = 1, When ODT output is enabled
                                     //   = 0, When ODT output is disabled
                                     // Parameter configuration for Dynamic ODT support:
                                     // USE_ODT_PORT = 0, RTT_NOM = "DISABLED", RTT_WR = "60/120".
                                     // This configuration allows to save ODT pin mapping from FPGA.
                                     // The user can tie the ODT input of DRAM to HIGH.
   parameter C1_IS_CLK_SHARED          = "FALSE",
                                      // # = "true" when clock is shared
                                      //   = "false" when clock is not shared

   parameter C1_PHY_CONTROL_MASTER_BANK = 1,
                                     // The bank index where master PHY_CONTROL resides,
                                     // equal to the PLL residing bank
   parameter C1_MEM_DENSITY           = "2Gb",
                                     // Indicates the density of the Memory part
                                     // Added for the sake of Vivado simulations
   parameter C1_MEM_SPEEDGRADE        = "125",
                                     // Indicates the Speed grade of Memory Part
                                     // Added for the sake of Vivado simulations
   parameter C1_MEM_DEVICE_WIDTH      = 8,
                                     // Indicates the device width of the Memory Part
                                     // Added for the sake of Vivado simulations

   //***************************************************************************
   // The following parameters are mode register settings
   //***************************************************************************
   parameter C1_AL                    = "0",
                                     // DDR3 SDRAM:
                                     // Additive Latency (Mode Register 1).
                                     // # = "0", "CL-1", "CL-2".
                                     // DDR2 SDRAM:
                                     // Additive Latency (Extended Mode Register).
   parameter C1_nAL                   = 0,
                                     // # Additive Latency in number of clock
                                     // cycles.
   parameter C1_BURST_MODE            = "8",
                                     // DDR3 SDRAM:
                                     // Burst Length (Mode Register 0).
                                     // # = "8", "4", "OTF".
                                     // DDR2 SDRAM:
                                     // Burst Length (Mode Register).
                                     // # = "8", "4".
   parameter C1_BURST_TYPE            = "SEQ",
                                     // DDR3 SDRAM: Burst Type (Mode Register 0).
                                     // DDR2 SDRAM: Burst Type (Mode Register).
                                     // # = "SEQ" - (Sequential),
                                     //   = "INT" - (Interleaved).
   parameter C1_CL                    = 7,
                                     // in number of clock cycles
                                     // DDR3 SDRAM: CAS Latency (Mode Register 0).
                                     // DDR2 SDRAM: CAS Latency (Mode Register).
   parameter C1_CWL                   = 6,
                                     // in number of clock cycles
                                     // DDR3 SDRAM: CAS Write Latency (Mode Register 2).
                                     // DDR2 SDRAM: Can be ignored
   parameter C1_OUTPUT_DRV            = "HIGH",
                                     // Output Driver Impedance Control (Mode Register 1).
                                     // # = "HIGH" - RZQ/7,
                                     //   = "LOW" - RZQ/6.
   parameter C1_RTT_NOM               = "60",
                                     // RTT_NOM (ODT) (Mode Register 1).
                                     //   = "120" - RZQ/2,
                                     //   = "60"  - RZQ/4,
                                     //   = "40"  - RZQ/6.
   parameter C1_RTT_WR                = "OFF",
                                     // RTT_WR (ODT) (Mode Register 2).
                                     // # = "OFF" - Dynamic ODT off,
                                     //   = "120" - RZQ/2,
                                     //   = "60"  - RZQ/4,
   parameter C1_ADDR_CMD_MODE         = "1T" ,
                                     // # = "1T", "2T".
   parameter C1_REG_CTRL              = "OFF",
                                     // # = "ON" - RDIMMs,
                                     //   = "OFF" - Components, SODIMMs, UDIMMs.
   parameter C1_CA_MIRROR             = "OFF",
                                     // C/A mirror opt for DDR3 dual rank

   parameter C1_VDD_OP_VOLT           = "150",
                                     // # = "150" - 1.5V Vdd Memory part
                                     //   = "135" - 1.35V Vdd Memory part

   
   //***************************************************************************
   // The following parameters are multiplier and divisor factors for PLLE2.
   // Based on the selected design frequency these parameters vary.
   //***************************************************************************
   parameter C1_CLKIN_PERIOD          = 5000,
                                     // Input Clock Period
   parameter C1_CLKFBOUT_MULT         = 16,
                                     // write PLL VCO multiplier
   parameter C1_DIVCLK_DIVIDE         = 3,
                                     // write PLL VCO divisor
   parameter C1_CLKOUT0_PHASE         = 337.5,
                                     // Phase for PLL output clock (CLKOUT0)
   parameter C1_CLKOUT0_DIVIDE        = 2,
                                     // VCO output divisor for PLL output clock (CLKOUT0)
   parameter C1_CLKOUT1_DIVIDE        = 2,
                                     // VCO output divisor for PLL output clock (CLKOUT1)
   parameter C1_CLKOUT2_DIVIDE        = 32,
                                     // VCO output divisor for PLL output clock (CLKOUT2)
   parameter C1_CLKOUT3_DIVIDE        = 8,
                                     // VCO output divisor for PLL output clock (CLKOUT3)
   parameter C1_MMCM_VCO              = 1066,
                                     // Max Freq (MHz) of MMCM VCO
   parameter C1_MMCM_MULT_F           = 8,
                                     // write MMCM VCO multiplier
   parameter C1_MMCM_DIVCLK_DIVIDE    = 1,
                                     // write MMCM VCO divisor

   //***************************************************************************
   // Memory Timing Parameters. These parameters varies based on the selected
   // memory part.
   //***************************************************************************
   parameter C1_tCKE                  = 5000,
                                     // memory tCKE paramter in pS
   parameter C1_tFAW                  = 30000,
                                     // memory tRAW paramter in pS.
   parameter C1_tPRDI                 = 1_000_000,
                                     // memory tPRDI paramter in pS.
   parameter C1_tRAS                  = 35000,
                                     // memory tRAS paramter in pS.
   parameter C1_tRCD                  = 13750,
                                     // memory tRCD paramter in pS.
   parameter C1_tREFI                 = 7800000,
                                     // memory tREFI paramter in pS.
   parameter C1_tRFC                  = 160000,
                                     // memory tRFC paramter in pS.
   parameter C1_tRP                   = 13750,
                                     // memory tRP paramter in pS.
   parameter C1_tRRD                  = 6000,
                                     // memory tRRD paramter in pS.
   parameter C1_tRTP                  = 7500,
                                     // memory tRTP paramter in pS.
   parameter C1_tWTR                  = 7500,
                                     // memory tWTR paramter in pS.
   parameter C1_tZQI                  = 128_000_000,
                                     // memory tZQI paramter in nS.
   parameter C1_tZQCS                 = 64,//64,
                                     // memory tZQCS paramter in clock cycles.

   //***************************************************************************
   // Simulation parameters
   //***************************************************************************
   parameter C1_SIM_BYPASS_INIT_CAL   = "OFF",
                                     // # = "OFF" -  Complete memory init &
                                     //              calibration sequence
                                     // # = "SKIP" - Not supported
                                     // # = "FAST" - Complete memory init & use
                                     //              abbreviated calib sequence

   parameter C1_SIMULATION            = "FALSE",
                                     // Should be TRUE during design simulations and
                                     // FALSE during implementations

   //***************************************************************************
   // The following parameters varies based on the pin out entered in MIG GUI.
   // Do not change any of these parameters directly by editing the RTL.
   // Any changes required should be done through GUI and the design regenerated.
   //***************************************************************************
   parameter C1_BYTE_LANES_B0         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C1_BYTE_LANES_B1         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C1_BYTE_LANES_B2         = 4'b1111,
                                     // Byte lanes used in an IO column.
   parameter C1_BYTE_LANES_B3         = 4'b0000,
                                     // Byte lanes used in an IO column.
   parameter C1_BYTE_LANES_B4         = 4'b0000,
                                     // Byte lanes used in an IO column.
   parameter C1_DATA_CTL_B0           = 4'b1111,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C1_DATA_CTL_B1           = 4'b0001,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C1_DATA_CTL_B2           = 4'b1111,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C1_DATA_CTL_B3           = 4'b0000,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C1_DATA_CTL_B4           = 4'b0000,
                                     // Indicates Byte lane is data byte lane
                                     // or control Byte lane. '1' in a bit
                                     // position indicates a data byte lane and
                                     // a '0' indicates a control byte lane
   parameter C1_PHY_0_BITLANES        = 48'h3FC_3FC_0FF_0FF,
   parameter C1_PHY_1_BITLANES        = 48'h3FE_FFF_C10_2FE,
   parameter C1_PHY_2_BITLANES        = 48'h3FC_3FC_0FF_2FE,

   // control/address/data pin mapping parameters
   parameter C1_CK_BYTE_MAP
     = 144'h00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_00_13,
   parameter C1_ADDR_MAP
     = 192'h000_135_12A_114_127_122_11B_136_137_138_12B_139_126_133_131_120,
   parameter C1_BANK_MAP   = 36'h128_11A_129,
   parameter C1_CAS_MAP    = 12'h121,
   parameter C1_CKE_ODT_BYTE_MAP = 8'h00,
   parameter C1_CKE_MAP    = 96'h000_000_000_000_000_000_000_132,
   parameter C1_ODT_MAP    = 96'h000_000_000_000_000_000_000_134,
   parameter C1_CS_MAP     = 120'h000_000_000_000_000_000_000_000_000_125,
   parameter C1_PARITY_MAP = 12'h000,
   parameter C1_RAS_MAP    = 12'h124,
   parameter C1_WE_MAP     = 12'h123,
   parameter C1_DQS_BYTE_MAP
     = 144'h00_00_00_00_00_00_00_00_00_20_02_03_10_01_21_00_22_23,
   parameter C1_DATA0_MAP  = 96'h234_237_238_233_232_236_235_239,
   parameter C1_DATA1_MAP  = 96'h227_223_226_224_229_228_225_222,
   parameter C1_DATA2_MAP  = 96'h005_007_002_003_006_001_004_000,
   parameter C1_DATA3_MAP  = 96'h213_211_210_214_216_215_212_217,
   parameter C1_DATA4_MAP  = 96'h014_017_012_010_013_016_015_011,
   parameter C1_DATA5_MAP  = 96'h103_109_102_105_101_106_107_104,
   parameter C1_DATA6_MAP  = 96'h036_033_038_037_039_034_032_035,
   parameter C1_DATA7_MAP  = 96'h025_027_022_029_028_024_026_023,
   parameter C1_DATA8_MAP  = 96'h201_205_209_207_204_206_202_203,
   parameter C1_DATA9_MAP  = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA10_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA11_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA12_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA13_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA14_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA15_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA16_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_DATA17_MAP = 96'h000_000_000_000_000_000_000_000,
   parameter C1_MASK0_MAP  = 108'h000_000_000_000_000_000_000_000_000,
   parameter C1_MASK1_MAP  = 108'h000_000_000_000_000_000_000_000_000,

   parameter C1_SLOT_0_CONFIG         = 8'b0000_0001,
                                     // Mapping of Ranks.
   parameter C1_SLOT_1_CONFIG         = 8'b0000_0000,
                                     // Mapping of Ranks.

   //***************************************************************************
   // IODELAY and PHY related parameters
   //***************************************************************************
   parameter C1_IBUF_LPWR_MODE        = "OFF",
                                     // to phy_top
   parameter C1_DATA_IO_IDLE_PWRDWN   = "ON",
                                     // # = "ON", "OFF"
   parameter C1_BANK_TYPE             = "HR_IO",
                                     // # = "HP_IO", "HPL_IO", "HR_IO", "HRL_IO"
   parameter C1_DATA_IO_PRIM_TYPE     = "HR_LP",
                                     // # = "HP_LP", "HR_LP", "DEFAULT"
   parameter C1_CKE_ODT_AUX           = "FALSE",
   parameter C1_USER_REFRESH          = "OFF",
   parameter C1_WRLVL                 = "ON",
                                     // # = "ON" - DDR3 SDRAM
                                     //   = "OFF" - DDR2 SDRAM.
   parameter C1_ORDERING              = "NORM",
                                     // # = "NORM", "STRICT", "RELAXED".
   parameter C1_CALIB_ROW_ADD         = 16'h0000,
                                     // Calibration row address will be used for
                                     // calibration read and write operations
   parameter C1_CALIB_COL_ADD         = 12'h000,
                                     // Calibration column address will be used for
                                     // calibration read and write operations
   parameter C1_CALIB_BA_ADD          = 3'h0,
                                     // Calibration bank address will be used for
                                     // calibration read and write operations
   parameter C1_TCQ                   = 100,
   parameter C1_IDELAY_ADJ            = "OFF",
   parameter C1_FINE_PER_BIT          = "OFF",
   parameter C1_CENTER_COMP_MODE      = "OFF",
   parameter C1_PI_VAL_ADJ            = "OFF",
   
   parameter C1_CMD_PIPE_PLUS1        = "ON",
                                     // add pipeline stage between MC and PHY

   
   //***************************************************************************
   // System clock frequency parameters
   //***************************************************************************
   parameter C1_tCK                   = 1875,
                                     // memory tCK paramter.
                                     // # = Clock Period in pS.
   parameter C1_nCK_PER_CLK           = 4,
   // # of memory CKs per fabric CLK
   
   parameter C1_DIFF_TERM_SYSCLK      = "FALSE",
                                     // Differential Termination for System
                                     // clock input pins
      

   
   //***************************************************************************
   // AXI4 Shim parameters
   //***************************************************************************
   
   parameter C1_UI_EXTRA_CLOCKS = "FALSE",
                                     // Generates extra clocks as
                                     // 1/2, 1/4 and 1/8 of fabrick clock.
                                     // Valid for DDR2/DDR3 AXI interfaces
                                     // based on GUI selection
   parameter C1_C_S_AXI_ID_WIDTH              = 4,
                                             // Width of all master and slave ID signals.
                                             // # = >= 1.
   parameter C1_C_S_AXI_MEM_SIZE              = "2147483648",
                                     // Address Space required for this component
   parameter C1_C_S_AXI_ADDR_WIDTH            = 31,
                                             // Width of S_AXI_AWADDR, S_AXI_ARADDR, M_AXI_AWADDR and
                                             // M_AXI_ARADDR for all SI/MI slots.
                                             // # = 32.
   parameter C1_C_S_AXI_DATA_WIDTH            = 512,
                                             // Width of WDATA and RDATA on SI slot.
                                             // Must be <= APP_DATA_WIDTH.
                                             // # = 32, 64, 128, 256.
   parameter C1_C_MC_nCK_PER_CLK              = 4,
                                             // Indicates whether to instatiate upsizer
                                             // Range: 0, 1
   parameter C1_C_S_AXI_SUPPORTS_NARROW_BURST = 0,
                                             // Indicates whether to instatiate upsizer
                                             // Range: 0, 1
   parameter C1_C_RD_WR_ARB_ALGORITHM          = "RD_PRI_REG",
                                             // Indicates the Arbitration
                                             // Allowed values - "TDM", "ROUND_ROBIN",
                                             // "RD_PRI_REG", "RD_PRI_REG_STARVE_LIMIT"
                                             // "WRITE_PRIORITY", "WRITE_PRIORITY_REG"
   parameter C1_C_S_AXI_REG_EN0               = 20'h00000,
                                             // C_S_AXI_REG_EN0[00] = Reserved
                                             // C_S_AXI_REG_EN0[04] = AW CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[05] =  W CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[06] =  B CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[07] =  R CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN0[08] = AW CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[09] =  W CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[10] = AR CHANNEL UPSIZER REGISTER SLICE
                                             // C_S_AXI_REG_EN0[11] =  R CHANNEL UPSIZER REGISTER SLICE
   parameter C1_C_S_AXI_REG_EN1               = 20'h00000,
                                             // Instatiates register slices after the upsizer.
                                             // The type of register is specified for each channel
                                             // in a vector. 4 bits per channel are used.
                                             // C_S_AXI_REG_EN1[03:00] = AW CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[07:04] =  W CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[11:08] =  B CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[15:12] = AR CHANNEL REGISTER SLICE
                                             // C_S_AXI_REG_EN1[20:16] =  R CHANNEL REGISTER SLICE
                                             // Possible values for each channel are:
                                             //
                                             //   0 => BYPASS    = The channel is just wired through the
                                             //                    module.
                                             //   1 => FWD       = The master VALID and payload signals
                                             //                    are registrated.
                                             //   2 => REV       = The slave ready signal is registrated
                                             //   3 => FWD_REV   = Both FWD and REV
                                             //   4 => SLAVE_FWD = All slave side signals and master
                                             //                    VALID and payload are registrated.
                                             //   5 => SLAVE_RDY = All slave side signals and master
                                             //                    READY are registrated.
                                             //   6 => INPUTS    = Slave and Master side inputs are
                                             //                    registrated.
                                             //   7 => ADDRESS   = Optimized for address channel
   parameter C1_C_S_AXI_CTRL_ADDR_WIDTH       = 32,
                                             // Width of AXI-4-Lite address bus
   parameter C1_C_S_AXI_CTRL_DATA_WIDTH       = 32,
                                             // Width of AXI-4-Lite data buses
   parameter C1_C_S_AXI_BASEADDR              = 32'h0000_0000,
                                             // Base address of AXI4 Memory Mapped bus.
   parameter C1_C_ECC_ONOFF_RESET_VALUE       = 1,
                                             // Controls ECC on/off value at startup/reset
   parameter C1_C_ECC_CE_COUNTER_WIDTH        = 8,
                                             // The external memory to controller clock ratio.

   //***************************************************************************
   // Debug parameters
   //***************************************************************************
   parameter C1_DEBUG_PORT            = "OFF",
                                     // # = "ON" Enable debug signals/controls.
                                     //   = "OFF" Disable debug signals/controls.

   //***************************************************************************
   // Temparature monitor parameter
   //***************************************************************************
   parameter C1_TEMP_MON_CONTROL      = "EXTERNAL",
                                     // # = "INTERNAL", "EXTERNAL"
   //***************************************************************************
   // FPGA Voltage Type parameter
   //***************************************************************************
   parameter C1_FPGA_VOLT_TYPE        = "N",
                                     // # = "L", "N". When FPGA VccINT is 0.9v,
                                     // the value is "L", else it is "N"
      
   parameter RST_ACT_LOW           = 1
                                     // =1 for active low reset,
                                     // =0 for active high.
   )
  (

   // Inouts
   inout [C0_DQ_WIDTH-1:0]                         c0_ddr3_dq,
   inout [C0_DQS_WIDTH-1:0]                        c0_ddr3_dqs_n,
   inout [C0_DQS_WIDTH-1:0]                        c0_ddr3_dqs_p,

   // Outputs
   output [C0_ROW_WIDTH-1:0]                       c0_ddr3_addr,
   output [C0_BANK_WIDTH-1:0]                      c0_ddr3_ba,
   output                                       c0_ddr3_ras_n,
   output                                       c0_ddr3_cas_n,
   output                                       c0_ddr3_we_n,
   output                                       c0_ddr3_reset_n,
   output [C0_CK_WIDTH-1:0]                        c0_ddr3_ck_p,
   output [C0_CK_WIDTH-1:0]                        c0_ddr3_ck_n,
   output [C0_CKE_WIDTH-1:0]                       c0_ddr3_cke,
   
   output [(C0_CS_WIDTH*C0_nCS_PER_RANK)-1:0]           c0_ddr3_cs_n,
   
   
   output [C0_ODT_WIDTH-1:0]                       c0_ddr3_odt,
   

   // Inputs
   
   // Differential system clocks
   input                                        c0_sys_clk_p,
   input                                        c0_sys_clk_n,
   
   
   // user interface signals
   output                                       c0_ui_clk,
   output                                       c0_ui_clk_sync_rst,
   
   output                                       c0_mmcm_locked,
   
   output [(2*C0_nCK_PER_CLK)-1:0]                   c0_app_ecc_multiple_err,
   output [(2*C0_nCK_PER_CLK)-1:0]                   c0_app_ecc_single_err,
   input                                        c0_aresetn,
   input                                        c0_app_sr_req,
   input                                        c0_app_ref_req,
   input                                        c0_app_zq_req,
   output                                       c0_app_sr_active,
   output                                       c0_app_ref_ack,
   output                                       c0_app_zq_ack,

   // Slave Interface Write Address Ports
   input  [C0_C_S_AXI_ID_WIDTH-1:0]                c0_s_axi_awid,
   input  [C0_C_S_AXI_ADDR_WIDTH-1:0]              c0_s_axi_awaddr,
   input  [7:0]                                 c0_s_axi_awlen,
   input  [2:0]                                 c0_s_axi_awsize,
   input  [1:0]                                 c0_s_axi_awburst,
   input  [0:0]                                 c0_s_axi_awlock,
   input  [3:0]                                 c0_s_axi_awcache,
   input  [2:0]                                 c0_s_axi_awprot,
   input  [3:0]                                 c0_s_axi_awqos,
   input                                        c0_s_axi_awvalid,
   output                                       c0_s_axi_awready,
   // Slave Interface Write Data Ports
   input  [C0_C_S_AXI_DATA_WIDTH-1:0]              c0_s_axi_wdata,
   input  [(C0_C_S_AXI_DATA_WIDTH/8)-1:0]            c0_s_axi_wstrb,
   input                                        c0_s_axi_wlast,
   input                                        c0_s_axi_wvalid,
   output                                       c0_s_axi_wready,
   // Slave Interface Write Response Ports
   input                                        c0_s_axi_bready,
   output [C0_C_S_AXI_ID_WIDTH-1:0]                c0_s_axi_bid,
   output [1:0]                                 c0_s_axi_bresp,
   output                                       c0_s_axi_bvalid,
   // Slave Interface Read Address Ports
   input  [C0_C_S_AXI_ID_WIDTH-1:0]                c0_s_axi_arid,
   input  [C0_C_S_AXI_ADDR_WIDTH-1:0]              c0_s_axi_araddr,
   input  [7:0]                                 c0_s_axi_arlen,
   input  [2:0]                                 c0_s_axi_arsize,
   input  [1:0]                                 c0_s_axi_arburst,
   input  [0:0]                                 c0_s_axi_arlock,
   input  [3:0]                                 c0_s_axi_arcache,
   input  [2:0]                                 c0_s_axi_arprot,
   input  [3:0]                                 c0_s_axi_arqos,
   input                                        c0_s_axi_arvalid,
   output                                       c0_s_axi_arready,
   // Slave Interface Read Data Ports
   input                                        c0_s_axi_rready,
   output [C0_C_S_AXI_ID_WIDTH-1:0]                c0_s_axi_rid,
   output [C0_C_S_AXI_DATA_WIDTH-1:0]              c0_s_axi_rdata,
   output [1:0]                                 c0_s_axi_rresp,
   output                                       c0_s_axi_rlast,
   output                                       c0_s_axi_rvalid,

   
   // AXI CTRL port
   input                                        c0_s_axi_ctrl_awvalid,
   output                                       c0_s_axi_ctrl_awready,
   input  [C0_C_S_AXI_CTRL_ADDR_WIDTH-1:0]         c0_s_axi_ctrl_awaddr,
   // Slave Interface Write Data Ports
   input                                        c0_s_axi_ctrl_wvalid,
   output                                       c0_s_axi_ctrl_wready,
   input  [C0_C_S_AXI_CTRL_DATA_WIDTH-1:0]         c0_s_axi_ctrl_wdata,
   // Slave Interface Write Response Ports
   output                                       c0_s_axi_ctrl_bvalid,
   input                                        c0_s_axi_ctrl_bready,
   output [1:0]                                 c0_s_axi_ctrl_bresp,
   // Slave Interface Read Address Ports
   input                                        c0_s_axi_ctrl_arvalid,
   output                                       c0_s_axi_ctrl_arready,
   input  [C0_C_S_AXI_CTRL_ADDR_WIDTH-1:0]         c0_s_axi_ctrl_araddr,
   // Slave Interface Read Data Ports
   output                                       c0_s_axi_ctrl_rvalid,
   input                                        c0_s_axi_ctrl_rready,
   output [C0_C_S_AXI_CTRL_DATA_WIDTH-1:0]         c0_s_axi_ctrl_rdata,
   output [1:0]                                 c0_s_axi_ctrl_rresp,

   // Interrupt output
   output                                       c0_interrupt,
   
      
   
   output                                       c0_init_calib_complete,
   
   output [11:0]                                 c0_device_temp,
`ifdef SKIP_CALIB
   output                                      c0_calib_tap_req,
   input                                       c0_calib_tap_load,
   input [6:0]                                 c0_calib_tap_addr,
   input [7:0]                                 c0_calib_tap_val,
   input                                       c0_calib_tap_load_done,
`endif
      
   // Inouts
   inout [C1_DQ_WIDTH-1:0]                         c1_ddr3_dq,
   inout [C1_DQS_WIDTH-1:0]                        c1_ddr3_dqs_n,
   inout [C1_DQS_WIDTH-1:0]                        c1_ddr3_dqs_p,

   // Outputs
   output [C1_ROW_WIDTH-1:0]                       c1_ddr3_addr,
   output [C1_BANK_WIDTH-1:0]                      c1_ddr3_ba,
   output                                       c1_ddr3_ras_n,
   output                                       c1_ddr3_cas_n,
   output                                       c1_ddr3_we_n,
   output                                       c1_ddr3_reset_n,
   output [C1_CK_WIDTH-1:0]                        c1_ddr3_ck_p,
   output [C1_CK_WIDTH-1:0]                        c1_ddr3_ck_n,
   output [C1_CKE_WIDTH-1:0]                       c1_ddr3_cke,
   
   output [(C1_CS_WIDTH*C1_nCS_PER_RANK)-1:0]           c1_ddr3_cs_n,
   
   
   output [C1_ODT_WIDTH-1:0]                       c1_ddr3_odt,
   

   // Inputs
   
   // Differential system clocks
   input                                        c1_sys_clk_p,
   input                                        c1_sys_clk_n,
   
   
   // user interface signals
   output                                       c1_ui_clk,
   output                                       c1_ui_clk_sync_rst,
   
   output                                       c1_mmcm_locked,
   
   output [(2*C1_nCK_PER_CLK)-1:0]                   c1_app_ecc_multiple_err,
   output [(2*C1_nCK_PER_CLK)-1:0]                   c1_app_ecc_single_err,
   input                                        c1_aresetn,
   input                                        c1_app_sr_req,
   input                                        c1_app_ref_req,
   input                                        c1_app_zq_req,
   output                                       c1_app_sr_active,
   output                                       c1_app_ref_ack,
   output                                       c1_app_zq_ack,

   // Slave Interface Write Address Ports
   input  [C1_C_S_AXI_ID_WIDTH-1:0]                c1_s_axi_awid,
   input  [C1_C_S_AXI_ADDR_WIDTH-1:0]              c1_s_axi_awaddr,
   input  [7:0]                                 c1_s_axi_awlen,
   input  [2:0]                                 c1_s_axi_awsize,
   input  [1:0]                                 c1_s_axi_awburst,
   input  [0:0]                                 c1_s_axi_awlock,
   input  [3:0]                                 c1_s_axi_awcache,
   input  [2:0]                                 c1_s_axi_awprot,
   input  [3:0]                                 c1_s_axi_awqos,
   input                                        c1_s_axi_awvalid,
   output                                       c1_s_axi_awready,
   // Slave Interface Write Data Ports
   input  [C1_C_S_AXI_DATA_WIDTH-1:0]              c1_s_axi_wdata,
   input  [(C1_C_S_AXI_DATA_WIDTH/8)-1:0]            c1_s_axi_wstrb,
   input                                        c1_s_axi_wlast,
   input                                        c1_s_axi_wvalid,
   output                                       c1_s_axi_wready,
   // Slave Interface Write Response Ports
   input                                        c1_s_axi_bready,
   output [C1_C_S_AXI_ID_WIDTH-1:0]                c1_s_axi_bid,
   output [1:0]                                 c1_s_axi_bresp,
   output                                       c1_s_axi_bvalid,
   // Slave Interface Read Address Ports
   input  [C1_C_S_AXI_ID_WIDTH-1:0]                c1_s_axi_arid,
   input  [C1_C_S_AXI_ADDR_WIDTH-1:0]              c1_s_axi_araddr,
   input  [7:0]                                 c1_s_axi_arlen,
   input  [2:0]                                 c1_s_axi_arsize,
   input  [1:0]                                 c1_s_axi_arburst,
   input  [0:0]                                 c1_s_axi_arlock,
   input  [3:0]                                 c1_s_axi_arcache,
   input  [2:0]                                 c1_s_axi_arprot,
   input  [3:0]                                 c1_s_axi_arqos,
   input                                        c1_s_axi_arvalid,
   output                                       c1_s_axi_arready,
   // Slave Interface Read Data Ports
   input                                        c1_s_axi_rready,
   output [C1_C_S_AXI_ID_WIDTH-1:0]                c1_s_axi_rid,
   output [C1_C_S_AXI_DATA_WIDTH-1:0]              c1_s_axi_rdata,
   output [1:0]                                 c1_s_axi_rresp,
   output                                       c1_s_axi_rlast,
   output                                       c1_s_axi_rvalid,

   
   // AXI CTRL port
   input                                        c1_s_axi_ctrl_awvalid,
   output                                       c1_s_axi_ctrl_awready,
   input  [C1_C_S_AXI_CTRL_ADDR_WIDTH-1:0]         c1_s_axi_ctrl_awaddr,
   // Slave Interface Write Data Ports
   input                                        c1_s_axi_ctrl_wvalid,
   output                                       c1_s_axi_ctrl_wready,
   input  [C1_C_S_AXI_CTRL_DATA_WIDTH-1:0]         c1_s_axi_ctrl_wdata,
   // Slave Interface Write Response Ports
   output                                       c1_s_axi_ctrl_bvalid,
   input                                        c1_s_axi_ctrl_bready,
   output [1:0]                                 c1_s_axi_ctrl_bresp,
   // Slave Interface Read Address Ports
   input                                        c1_s_axi_ctrl_arvalid,
   output                                       c1_s_axi_ctrl_arready,
   input  [C1_C_S_AXI_CTRL_ADDR_WIDTH-1:0]         c1_s_axi_ctrl_araddr,
   // Slave Interface Read Data Ports
   output                                       c1_s_axi_ctrl_rvalid,
   input                                        c1_s_axi_ctrl_rready,
   output [C1_C_S_AXI_CTRL_DATA_WIDTH-1:0]         c1_s_axi_ctrl_rdata,
   output [1:0]                                 c1_s_axi_ctrl_rresp,

   // Interrupt output
   output                                       c1_interrupt,
   
      
   
   output                                       c1_init_calib_complete,
   
   output [11:0]                                 c1_device_temp,
`ifdef SKIP_CALIB
   output                                      c1_calib_tap_req,
   input                                       c1_calib_tap_load,
   input [6:0]                                 c1_calib_tap_addr,
   input [7:0]                                 c1_calib_tap_val,
   input                                       c1_calib_tap_load_done,
`endif
      

   // System reset - Default polarity of sys_rst pin is Active Low.
   // System reset polarity will change based on the option 
   // selected in GUI.
   input                                        sys_rst
   );

  function integer clogb2 (input integer size);
    begin
      size = size - 1;
      for (clogb2=1; size>1; clogb2=clogb2+1)
        size = size >> 1;
    end
  endfunction // clogb2


  localparam C0_BM_CNT_WIDTH = clogb2(C0_nBANK_MACHS);
  localparam C0_RANK_WIDTH = clogb2(C0_RANKS);

  localparam C0_ECC_WIDTH = (C0_ECC == "OFF")?
                           0 : (C0_DATA_WIDTH <= 4)?
                            4 : (C0_DATA_WIDTH <= 10)?
                             5 : (C0_DATA_WIDTH <= 26)?
                              6 : (C0_DATA_WIDTH <= 57)?
                               7 : (C0_DATA_WIDTH <= 120)?
                                8 : (C0_DATA_WIDTH <= 247)?
                                 9 : 10;
  localparam C0_DATA_BUF_OFFSET_WIDTH = 1;
  localparam C0_MC_ERR_ADDR_WIDTH = ((C0_CS_WIDTH == 1) ? 0 : C0_RANK_WIDTH)
                                 + C0_BANK_WIDTH + C0_ROW_WIDTH + C0_COL_WIDTH
                                 + C0_DATA_BUF_OFFSET_WIDTH;

  localparam C0_APP_DATA_WIDTH        = 2 * C0_nCK_PER_CLK * C0_PAYLOAD_WIDTH;
  localparam C0_APP_MASK_WIDTH        = C0_APP_DATA_WIDTH / 8;
  localparam TEMP_MON_EN           = (C0_SIMULATION == "FALSE") ? "ON" : "OFF";
                                                 // Enable or disable the temp monitor module
  localparam tTEMPSAMPLE           = 10000000;   // sample every 10 us
  localparam XADC_CLK_PERIOD       = 5000;       // Use 200 MHz IODELAYCTRL clock
  `ifdef SKIP_CALIB
  localparam SKIP_CALIB = "TRUE";
  `else
  localparam SKIP_CALIB = "FALSE";
  `endif
      

  localparam C0_TAPSPERKCLK = (56*C0_MMCM_MULT_F)/C0_nCK_PER_CLK;
  
  localparam C1_BM_CNT_WIDTH = clogb2(C1_nBANK_MACHS);
  localparam C1_RANK_WIDTH = clogb2(C1_RANKS);

  localparam C1_ECC_WIDTH = (C1_ECC == "OFF")?
                           0 : (C1_DATA_WIDTH <= 4)?
                            4 : (C1_DATA_WIDTH <= 10)?
                             5 : (C1_DATA_WIDTH <= 26)?
                              6 : (C1_DATA_WIDTH <= 57)?
                               7 : (C1_DATA_WIDTH <= 120)?
                                8 : (C1_DATA_WIDTH <= 247)?
                                 9 : 10;
  localparam C1_DATA_BUF_OFFSET_WIDTH = 1;
  localparam C1_MC_ERR_ADDR_WIDTH = ((C1_CS_WIDTH == 1) ? 0 : C1_RANK_WIDTH)
                                 + C1_BANK_WIDTH + C1_ROW_WIDTH + C1_COL_WIDTH
                                 + C1_DATA_BUF_OFFSET_WIDTH;

  localparam C1_APP_DATA_WIDTH        = 2 * C1_nCK_PER_CLK * C1_PAYLOAD_WIDTH;
  localparam C1_APP_MASK_WIDTH        = C1_APP_DATA_WIDTH / 8;

  localparam C1_TAPSPERKCLK = (56*C1_MMCM_MULT_F)/C1_nCK_PER_CLK;
  

  // Wire declarations
      
  wire [C0_BM_CNT_WIDTH-1:0]           c0_bank_mach_next;
  wire                              c0_clk;
  wire [1:0]                        clk_ref;
  wire [1:0]                        iodelay_ctrl_rdy;
  wire                              clk_ref_in;
  wire                              sys_rst_o;
  wire                              c0_clk_div2;
  wire                              c0_rst_div2;
  wire                              c0_freq_refclk ;
  wire                              c0_mem_refclk ;
  wire                              c0_pll_lock ;
  wire                              c0_sync_pulse;
  wire                              c0_mmcm_ps_clk;
  wire                              c0_poc_sample_pd;
  wire                              c0_psen;
  wire                              c0_psincdec;
  wire                              c0_psdone;
  wire                              c0_iddr_rst;
  wire                              c0_ref_dll_lock;
  wire                              c0_rst_phaser_ref;
  wire                              c0_pll_locked;

  wire                              c0_rst;
  
  wire                                c0_ddr3_parity;
      

  wire                              c0_sys_clk_i;
  wire                              c0_mmcm_clk;
  wire                              clk_ref_p;
  wire                              clk_ref_n;
  wire                              clk_ref_i;
  wire [11:0]                       c0_device_temp_s;
  wire [11:0]                       device_temp_i;

  // Debug port signals
  wire                              c0_dbg_idel_down_all;
  wire                              c0_dbg_idel_down_cpt;
  wire                              c0_dbg_idel_up_all;
  wire                              c0_dbg_idel_up_cpt;
  wire                              c0_dbg_sel_all_idel_cpt;
  wire [C0_DQS_CNT_WIDTH-1:0]          c0_dbg_sel_idel_cpt;
  wire                              c0_dbg_sel_pi_incdec;
  wire [C0_DQS_CNT_WIDTH:0]            c0_dbg_byte_sel;
  wire                              c0_dbg_pi_f_inc;
  wire                              c0_dbg_pi_f_dec;
  wire [5:0]                        c0_dbg_pi_counter_read_val;
  wire [8:0]                        c0_dbg_po_counter_read_val;

  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0]      c0_dbg_cpt_tap_cnt;
  wire [(5*C0_DQS_WIDTH*C0_RANKS)-1:0]      c0_dbg_dq_idelay_tap_cnt;
  wire [255:0]                      c0_dbg_calib_top;
  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0]      c0_dbg_cpt_first_edge_cnt;
  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0]      c0_dbg_cpt_second_edge_cnt;
  wire [(6*C0_RANKS)-1:0]                c0_dbg_rd_data_offset;
  wire [255:0]                      c0_dbg_phy_rdlvl;
  wire [99:0]                       c0_dbg_phy_wrcal;
  wire [(6*C0_DQS_WIDTH)-1:0]            c0_dbg_final_po_fine_tap_cnt;
  wire [(3*C0_DQS_WIDTH)-1:0]            c0_dbg_final_po_coarse_tap_cnt;
  wire [255:0]                      c0_dbg_phy_wrlvl;
  wire [255:0]                      c0_dbg_phy_init;
  wire [255:0]                      c0_dbg_prbs_rdlvl;
  wire [255:0]                      c0_dbg_dqs_found_cal;
  wire                              c0_dbg_pi_phaselock_start;
  wire                              c0_dbg_pi_phaselocked_done;
  wire                              c0_dbg_pi_phaselock_err;
  wire                              c0_dbg_pi_dqsfound_start;
  wire                              c0_dbg_pi_dqsfound_done;
  wire                              c0_dbg_pi_dqsfound_err;
  wire                              c0_dbg_wrcal_start;
  wire                              c0_dbg_wrcal_done;
  wire                              c0_dbg_wrcal_err;
  wire [11:0]                       c0_dbg_pi_dqs_found_lanes_phy4lanes;
  wire [11:0]                       c0_dbg_pi_phase_locked_phy4lanes;
  wire                              c0_dbg_oclkdelay_calib_start;
  wire                              c0_dbg_oclkdelay_calib_done;
  wire [255:0]                      c0_dbg_phy_oclkdelay_cal;
  wire [(C0_DRAM_WIDTH*16)-1:0]         c0_dbg_oclkdelay_rd_data;
  wire [C0_DQS_WIDTH-1:0]              c0_dbg_rd_data_edge_detect;
  wire [(2*C0_nCK_PER_CLK*C0_DQ_WIDTH)-1:0] c0_dbg_rddata;
  wire                              c0_dbg_rddata_valid;
  wire [1:0]                        c0_dbg_rdlvl_done;
  wire [1:0]                        c0_dbg_rdlvl_err;
  wire [1:0]                        c0_dbg_rdlvl_start;
  wire [(6*C0_DQS_WIDTH)-1:0]            c0_dbg_wrlvl_fine_tap_cnt;
  wire [(3*C0_DQS_WIDTH)-1:0]            c0_dbg_wrlvl_coarse_tap_cnt;
  wire [5:0]                        c0_dbg_tap_cnt_during_wrlvl;
  wire                              c0_dbg_wl_edge_detect_valid;
  wire                              c0_dbg_wrlvl_done;
  wire                              c0_dbg_wrlvl_err;
  wire                              c0_dbg_wrlvl_start;
  reg [63:0]                        c0_dbg_rddata_r;
  reg                               c0_dbg_rddata_valid_r;
  wire [53:0]                       c0_ocal_tap_cnt;
  wire [4:0]                        c0_dbg_dqs;
  wire [8:0]                        c0_dbg_bit;
  wire [8:0]                        c0_rd_data_edge_detect_r;
  wire [53:0]                       c0_wl_po_fine_cnt;
  wire [26:0]                       c0_wl_po_coarse_cnt;
  wire [(6*C0_RANKS)-1:0]                c0_dbg_calib_rd_data_offset_1;
  wire [(6*C0_RANKS)-1:0]                c0_dbg_calib_rd_data_offset_2;
  wire [5:0]                        c0_dbg_data_offset;
  wire [5:0]                        c0_dbg_data_offset_1;
  wire [5:0]                        c0_dbg_data_offset_2;

  wire [390:0]                      c0_ddr3_ila_wrpath_int;
  wire [1023:0]                     c0_ddr3_ila_rdpath_int;
  wire [119:0]                      c0_ddr3_ila_basic_int;
  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0] c0_dbg_prbs_final_dqs_tap_cnt_r_int;
  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0] c0_dbg_prbs_first_edge_taps_int;
  wire [(6*C0_DQS_WIDTH*C0_RANKS)-1:0] c0_dbg_prbs_second_edge_taps_int;
        // Wire declarations
      
  wire [C1_BM_CNT_WIDTH-1:0]           c1_bank_mach_next;
  wire                              c1_clk;
  wire                              c1_clk_div2;
  wire                              c1_rst_div2;
  wire                              c1_freq_refclk ;
  wire                              c1_mem_refclk ;
  wire                              c1_pll_lock ;
  wire                              c1_sync_pulse;
  wire                              c1_mmcm_ps_clk;
  wire                              c1_poc_sample_pd;
  wire                              c1_psen;
  wire                              c1_psincdec;
  wire                              c1_psdone;
  wire                              c1_iddr_rst;
  wire                              c1_ref_dll_lock;
  wire                              c1_rst_phaser_ref;
  wire                              c1_pll_locked;

  wire                              c1_rst;
  
  wire                                c1_ddr3_parity;
      

  wire                              c1_sys_clk_i;
  wire                              c1_mmcm_clk;
  wire [11:0]                       c1_device_temp_s;

  // Debug port signals
  wire                              c1_dbg_idel_down_all;
  wire                              c1_dbg_idel_down_cpt;
  wire                              c1_dbg_idel_up_all;
  wire                              c1_dbg_idel_up_cpt;
  wire                              c1_dbg_sel_all_idel_cpt;
  wire [C1_DQS_CNT_WIDTH-1:0]          c1_dbg_sel_idel_cpt;
  wire                              c1_dbg_sel_pi_incdec;
  wire [C1_DQS_CNT_WIDTH:0]            c1_dbg_byte_sel;
  wire                              c1_dbg_pi_f_inc;
  wire                              c1_dbg_pi_f_dec;
  wire [5:0]                        c1_dbg_pi_counter_read_val;
  wire [8:0]                        c1_dbg_po_counter_read_val;

  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0]      c1_dbg_cpt_tap_cnt;
  wire [(5*C1_DQS_WIDTH*C1_RANKS)-1:0]      c1_dbg_dq_idelay_tap_cnt;
  wire [255:0]                      c1_dbg_calib_top;
  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0]      c1_dbg_cpt_first_edge_cnt;
  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0]      c1_dbg_cpt_second_edge_cnt;
  wire [(6*C1_RANKS)-1:0]                c1_dbg_rd_data_offset;
  wire [255:0]                      c1_dbg_phy_rdlvl;
  wire [99:0]                       c1_dbg_phy_wrcal;
  wire [(6*C1_DQS_WIDTH)-1:0]            c1_dbg_final_po_fine_tap_cnt;
  wire [(3*C1_DQS_WIDTH)-1:0]            c1_dbg_final_po_coarse_tap_cnt;
  wire [255:0]                      c1_dbg_phy_wrlvl;
  wire [255:0]                      c1_dbg_phy_init;
  wire [255:0]                      c1_dbg_prbs_rdlvl;
  wire [255:0]                      c1_dbg_dqs_found_cal;
  wire                              c1_dbg_pi_phaselock_start;
  wire                              c1_dbg_pi_phaselocked_done;
  wire                              c1_dbg_pi_phaselock_err;
  wire                              c1_dbg_pi_dqsfound_start;
  wire                              c1_dbg_pi_dqsfound_done;
  wire                              c1_dbg_pi_dqsfound_err;
  wire                              c1_dbg_wrcal_start;
  wire                              c1_dbg_wrcal_done;
  wire                              c1_dbg_wrcal_err;
  wire [11:0]                       c1_dbg_pi_dqs_found_lanes_phy4lanes;
  wire [11:0]                       c1_dbg_pi_phase_locked_phy4lanes;
  wire                              c1_dbg_oclkdelay_calib_start;
  wire                              c1_dbg_oclkdelay_calib_done;
  wire [255:0]                      c1_dbg_phy_oclkdelay_cal;
  wire [(C1_DRAM_WIDTH*16)-1:0]         c1_dbg_oclkdelay_rd_data;
  wire [C1_DQS_WIDTH-1:0]              c1_dbg_rd_data_edge_detect;
  wire [(2*C1_nCK_PER_CLK*C1_DQ_WIDTH)-1:0] c1_dbg_rddata;
  wire                              c1_dbg_rddata_valid;
  wire [1:0]                        c1_dbg_rdlvl_done;
  wire [1:0]                        c1_dbg_rdlvl_err;
  wire [1:0]                        c1_dbg_rdlvl_start;
  wire [(6*C1_DQS_WIDTH)-1:0]            c1_dbg_wrlvl_fine_tap_cnt;
  wire [(3*C1_DQS_WIDTH)-1:0]            c1_dbg_wrlvl_coarse_tap_cnt;
  wire [5:0]                        c1_dbg_tap_cnt_during_wrlvl;
  wire                              c1_dbg_wl_edge_detect_valid;
  wire                              c1_dbg_wrlvl_done;
  wire                              c1_dbg_wrlvl_err;
  wire                              c1_dbg_wrlvl_start;
  reg [63:0]                        c1_dbg_rddata_r;
  reg                               c1_dbg_rddata_valid_r;
  wire [53:0]                       c1_ocal_tap_cnt;
  wire [4:0]                        c1_dbg_dqs;
  wire [8:0]                        c1_dbg_bit;
  wire [8:0]                        c1_rd_data_edge_detect_r;
  wire [53:0]                       c1_wl_po_fine_cnt;
  wire [26:0]                       c1_wl_po_coarse_cnt;
  wire [(6*C1_RANKS)-1:0]                c1_dbg_calib_rd_data_offset_1;
  wire [(6*C1_RANKS)-1:0]                c1_dbg_calib_rd_data_offset_2;
  wire [5:0]                        c1_dbg_data_offset;
  wire [5:0]                        c1_dbg_data_offset_1;
  wire [5:0]                        c1_dbg_data_offset_2;

  wire [390:0]                      c1_ddr3_ila_wrpath_int;
  wire [1023:0]                     c1_ddr3_ila_rdpath_int;
  wire [119:0]                      c1_ddr3_ila_basic_int;
  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0] c1_dbg_prbs_final_dqs_tap_cnt_r_int;
  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0] c1_dbg_prbs_first_edge_taps_int;
  wire [(6*C1_DQS_WIDTH*C1_RANKS)-1:0] c1_dbg_prbs_second_edge_taps_int;
      

//***************************************************************************



  assign c0_ui_clk = c0_clk;
  assign c0_ui_clk_sync_rst = c0_rst;
  
  assign c0_sys_clk_i = 1'b0;
  assign clk_ref_i = 1'b0;
  assign c0_device_temp = c0_device_temp_s;
        assign c1_ui_clk = c1_clk;
  assign c1_ui_clk_sync_rst = c1_rst;
  
  assign c1_sys_clk_i = 1'b0;
  assign c1_device_temp = c1_device_temp_s;
      

  generate
    if (REFCLK_TYPE == "USE_SYSTEM_CLOCK")
      assign clk_ref_in = c0_mmcm_clk;
    else
      assign clk_ref_in = clk_ref_i;
  endgenerate

  mig_7series_v4_2_iodelay_ctrl #
    (
     .TCQ                       (C0_TCQ),
     .IODELAY_GRP0              (IODELAY_GRP0),
     .IODELAY_GRP1              (IODELAY_GRP1),
     .REFCLK_TYPE               (REFCLK_TYPE),
     .SYSCLK_TYPE               (SYSCLK_TYPE),
     .SYS_RST_PORT              (SYS_RST_PORT),
     .RST_ACT_LOW               (RST_ACT_LOW),
     .DIFF_TERM_REFCLK          (DIFF_TERM_REFCLK),
     .FPGA_SPEED_GRADE          (FPGA_SPEED_GRADE),
     .REF_CLK_MMCM_IODELAY_CTRL (REF_CLK_MMCM_IODELAY_CTRL)
     )
    u_iodelay_ctrl
      (
       // Outputs
       .iodelay_ctrl_rdy (iodelay_ctrl_rdy),
       .sys_rst_o        (sys_rst_o),
       .clk_ref          (clk_ref),
       // Inputs
       .clk_ref_p        (clk_ref_p),
       .clk_ref_n        (clk_ref_n),
       .clk_ref_i        (clk_ref_in),
       .sys_rst          (sys_rst)
       );
  mig_7series_v4_2_clk_ibuf #
    (
     .SYSCLK_TYPE      (SYSCLK_TYPE),
     .DIFF_TERM_SYSCLK (C0_DIFF_TERM_SYSCLK)
     )
    c0_u_ddr3_clk_ibuf
      (
       .sys_clk_p        (c0_sys_clk_p),
       .sys_clk_n        (c0_sys_clk_n),
       .sys_clk_i        (c0_sys_clk_i),
       .mmcm_clk         (c0_mmcm_clk)
       );
  // Temperature monitoring logic

  generate
    if (TEMP_MON_EN == "ON") begin: c0_temp_mon_enabled

      mig_7series_v4_2_tempmon #
        (
         .TCQ              (C0_TCQ),
         .TEMP_MON_CONTROL (C0_TEMP_MON_CONTROL),
         .XADC_CLK_PERIOD  (XADC_CLK_PERIOD),
         .tTEMPSAMPLE      (tTEMPSAMPLE)
         )
        u_tempmon
          (
           .clk            (c0_clk),
           .xadc_clk       (clk_ref[0]),
           .rst            (c0_rst),
           .device_temp_i  (device_temp_i),
           .device_temp    (c0_device_temp_s)
          );
    end else begin: c0_temp_mon_disabled

      assign c0_device_temp_s = 'b0;

    end
  endgenerate
         
  mig_7series_v4_2_infrastructure #
    (
     .TCQ                (C0_TCQ),
     .nCK_PER_CLK        (C0_nCK_PER_CLK),
     .CLKIN_PERIOD       (C0_CLKIN_PERIOD),
     .SYSCLK_TYPE        (SYSCLK_TYPE),
     .CLKFBOUT_MULT      (C0_CLKFBOUT_MULT),
     .DIVCLK_DIVIDE      (C0_DIVCLK_DIVIDE),
     .CLKOUT0_PHASE      (C0_CLKOUT0_PHASE),
     .CLKOUT0_DIVIDE     (C0_CLKOUT0_DIVIDE),
     .CLKOUT1_DIVIDE     (C0_CLKOUT1_DIVIDE),
     .CLKOUT2_DIVIDE     (C0_CLKOUT2_DIVIDE),
     .CLKOUT3_DIVIDE     (C0_CLKOUT3_DIVIDE),
     .MMCM_VCO           (C0_MMCM_VCO),
     .MMCM_MULT_F        (C0_MMCM_MULT_F),
     .MMCM_DIVCLK_DIVIDE (C0_MMCM_DIVCLK_DIVIDE),
     .RST_ACT_LOW        (RST_ACT_LOW),
     .tCK                (C0_tCK),
     .MEM_TYPE           (DRAM_TYPE)
     )
    c0_u_ddr3_infrastructure
      (
       // Outputs
       .rstdiv0          (c0_rst),
       .clk              (c0_clk),
       .clk_div2         (c0_clk_div2),
       .rst_div2         (c0_rst_div2),
       .mem_refclk       (c0_mem_refclk),
       .freq_refclk      (c0_freq_refclk),
       .sync_pulse       (c0_sync_pulse),
       .mmcm_ps_clk      (c0_mmcm_ps_clk),
       .poc_sample_pd    (c0_poc_sample_pd),
       .psdone           (c0_psdone),
       .iddr_rst         (c0_iddr_rst),
//       .auxout_clk       (),
       .ui_addn_clk_0    (),
       .ui_addn_clk_1    (),
       .ui_addn_clk_2    (),
       .ui_addn_clk_3    (),
       .ui_addn_clk_4    (),
       .pll_locked       (c0_pll_locked),
       .mmcm_locked      (c0_mmcm_locked),
       .rst_phaser_ref   (c0_rst_phaser_ref),
       // Inputs
       .psen             (c0_psen),
       .psincdec         (c0_psincdec),
       .mmcm_clk         (c0_mmcm_clk),
       .sys_rst          (sys_rst_o),
       .iodelay_ctrl_rdy (iodelay_ctrl_rdy),
       .ref_dll_lock     (c0_ref_dll_lock)
       );
      
  mig_7series_v4_2_clk_ibuf #
    (
     .SYSCLK_TYPE      (SYSCLK_TYPE),
     .DIFF_TERM_SYSCLK (C1_DIFF_TERM_SYSCLK)
     )
    c1_u_ddr3_clk_ibuf
      (
       .sys_clk_p        (c1_sys_clk_p),
       .sys_clk_n        (c1_sys_clk_n),
       .sys_clk_i        (c1_sys_clk_i),
       .mmcm_clk         (c1_mmcm_clk)
       );
  // Temperature monitoring logic

  generate
    if (TEMP_MON_EN == "ON") begin: c1_temp_mon_enabled

      mig_7series_v4_2_tempmon #
        (
         .TCQ              (C1_TCQ),
         .TEMP_MON_CONTROL (C1_TEMP_MON_CONTROL),
         .XADC_CLK_PERIOD  (XADC_CLK_PERIOD),
         .tTEMPSAMPLE      (tTEMPSAMPLE)
         )
        u_tempmon
          (
           .clk            (c1_clk),
           .xadc_clk       (clk_ref[0]),
           .rst            (c1_rst),
           .device_temp_i  (c0_device_temp_s),
           .device_temp    (c1_device_temp_s)
          );
    end else begin: c1_temp_mon_disabled

      assign c1_device_temp_s = 'b0;

    end
  endgenerate
         
  mig_7series_v4_2_infrastructure #
    (
     .TCQ                (C1_TCQ),
     .nCK_PER_CLK        (C1_nCK_PER_CLK),
     .CLKIN_PERIOD       (C1_CLKIN_PERIOD),
     .SYSCLK_TYPE        (SYSCLK_TYPE),
     .CLKFBOUT_MULT      (C1_CLKFBOUT_MULT),
     .DIVCLK_DIVIDE      (C1_DIVCLK_DIVIDE),
     .CLKOUT0_PHASE      (C1_CLKOUT0_PHASE),
     .CLKOUT0_DIVIDE     (C1_CLKOUT0_DIVIDE),
     .CLKOUT1_DIVIDE     (C1_CLKOUT1_DIVIDE),
     .CLKOUT2_DIVIDE     (C1_CLKOUT2_DIVIDE),
     .CLKOUT3_DIVIDE     (C1_CLKOUT3_DIVIDE),
     .MMCM_VCO           (C1_MMCM_VCO),
     .MMCM_MULT_F        (C1_MMCM_MULT_F),
     .MMCM_DIVCLK_DIVIDE (C1_MMCM_DIVCLK_DIVIDE),
     .RST_ACT_LOW        (RST_ACT_LOW),
     .tCK                (C1_tCK),
     .MEM_TYPE           (DRAM_TYPE)
     )
    c1_u_ddr3_infrastructure
      (
       // Outputs
       .rstdiv0          (c1_rst),
       .clk              (c1_clk),
       .clk_div2         (c1_clk_div2),
       .rst_div2         (c1_rst_div2),
       .mem_refclk       (c1_mem_refclk),
       .freq_refclk      (c1_freq_refclk),
       .sync_pulse       (c1_sync_pulse),
       .mmcm_ps_clk      (c1_mmcm_ps_clk),
       .poc_sample_pd    (c1_poc_sample_pd),
       .psdone           (c1_psdone),
       .iddr_rst         (c1_iddr_rst),
//       .auxout_clk       (),
       .ui_addn_clk_0    (),
       .ui_addn_clk_1    (),
       .ui_addn_clk_2    (),
       .ui_addn_clk_3    (),
       .ui_addn_clk_4    (),
       .pll_locked       (c1_pll_locked),
       .mmcm_locked      (c1_mmcm_locked),
       .rst_phaser_ref   (c1_rst_phaser_ref),
       // Inputs
       .psen             (c1_psen),
       .psincdec         (c1_psincdec),
       .mmcm_clk         (c1_mmcm_clk),
       .sys_rst          (sys_rst_o),
       .iodelay_ctrl_rdy (iodelay_ctrl_rdy),
       .ref_dll_lock     (c1_ref_dll_lock)
       );
      

  mig_7series_v4_2_memc_ui_top_axi #
    (
     .TCQ                              (C0_TCQ),
     .ADDR_CMD_MODE                    (C0_ADDR_CMD_MODE),
     .AL                               (C0_AL),
     .PAYLOAD_WIDTH                    (C0_PAYLOAD_WIDTH),
     .BANK_WIDTH                       (C0_BANK_WIDTH),
     .BM_CNT_WIDTH                     (C0_BM_CNT_WIDTH),
     .BURST_MODE                       (C0_BURST_MODE),
     .BURST_TYPE                       (C0_BURST_TYPE),
     .CA_MIRROR                        (C0_CA_MIRROR),
     .DDR3_VDD_OP_VOLT                 (C0_VDD_OP_VOLT),
     .CK_WIDTH                         (C0_CK_WIDTH),
     .COL_WIDTH                        (C0_COL_WIDTH),
     .CMD_PIPE_PLUS1                   (C0_CMD_PIPE_PLUS1),
     .CS_WIDTH                         (C0_CS_WIDTH),
     .nCS_PER_RANK                     (C0_nCS_PER_RANK),
     .CKE_WIDTH                        (C0_CKE_WIDTH),
     .DATA_WIDTH                       (C0_DATA_WIDTH),
     .DATA_BUF_ADDR_WIDTH              (C0_DATA_BUF_ADDR_WIDTH),
     .DQ_CNT_WIDTH                     (C0_DQ_CNT_WIDTH),
     .DQ_WIDTH                         (C0_DQ_WIDTH),
     .DQS_CNT_WIDTH                    (C0_DQS_CNT_WIDTH),
     .DQS_WIDTH                        (C0_DQS_WIDTH),
     .DRAM_TYPE                        (DRAM_TYPE),
     .DRAM_WIDTH                       (C0_DRAM_WIDTH),
     .ECC                              (C0_ECC),
     .ECC_WIDTH                        (C0_ECC_WIDTH),
     .ECC_TEST                         (C0_ECC_TEST),
     .MC_ERR_ADDR_WIDTH                (C0_MC_ERR_ADDR_WIDTH),
     .REFCLK_FREQ                      (REFCLK_FREQ),
     .nAL                              (C0_nAL),
     .nBANK_MACHS                      (C0_nBANK_MACHS),
     .CKE_ODT_AUX                      (C0_CKE_ODT_AUX),
     .nCK_PER_CLK                      (C0_nCK_PER_CLK),
     .ORDERING                         (C0_ORDERING),
     .OUTPUT_DRV                       (C0_OUTPUT_DRV),
     .IBUF_LPWR_MODE                   (C0_IBUF_LPWR_MODE),
     .DATA_IO_IDLE_PWRDWN              (C0_DATA_IO_IDLE_PWRDWN),
     .BANK_TYPE                        (C0_BANK_TYPE),
     .DATA_IO_PRIM_TYPE                (C0_DATA_IO_PRIM_TYPE),
     .IODELAY_GRP0                     (IODELAY_GRP0),
     .IODELAY_GRP1                     (IODELAY_GRP1),
     .FPGA_SPEED_GRADE                 (FPGA_SPEED_GRADE),
     .REG_CTRL                         (C0_REG_CTRL),
     .RTT_NOM                          (C0_RTT_NOM),
     .RTT_WR                           (C0_RTT_WR),
     .CL                               (C0_CL),
     .CWL                              (C0_CWL),
     .tCK                              (C0_tCK),
     .tCKE                             (C0_tCKE),
     .tFAW                             (C0_tFAW),
     .tPRDI                            (C0_tPRDI),
     .tRAS                             (C0_tRAS),
     .tRCD                             (C0_tRCD),
     .tREFI                            (C0_tREFI),
     .tRFC                             (C0_tRFC),
     .tRP                              (C0_tRP),
     .tRRD                             (C0_tRRD),
     .tRTP                             (C0_tRTP),
     .tWTR                             (C0_tWTR),
     .tZQI                             (C0_tZQI),
     .tZQCS                            (C0_tZQCS),
     .USER_REFRESH                     (C0_USER_REFRESH),
     .TEMP_MON_EN                      (TEMP_MON_EN),
     .WRLVL                            (C0_WRLVL),
     .DEBUG_PORT                       (C0_DEBUG_PORT),
     .CAL_WIDTH                        (CAL_WIDTH),
     .RANK_WIDTH                       (C0_RANK_WIDTH),
     .RANKS                            (C0_RANKS),
     .ODT_WIDTH                        (C0_ODT_WIDTH),
     .ROW_WIDTH                        (C0_ROW_WIDTH),
     .ADDR_WIDTH                       (C0_ADDR_WIDTH),
     .APP_DATA_WIDTH                   (C0_APP_DATA_WIDTH),
     .APP_MASK_WIDTH                   (C0_APP_MASK_WIDTH),
     .SIM_BYPASS_INIT_CAL              (C0_SIM_BYPASS_INIT_CAL),
     .BYTE_LANES_B0                    (C0_BYTE_LANES_B0),
     .BYTE_LANES_B1                    (C0_BYTE_LANES_B1),
     .BYTE_LANES_B2                    (C0_BYTE_LANES_B2),
     .BYTE_LANES_B3                    (C0_BYTE_LANES_B3),
     .BYTE_LANES_B4                    (C0_BYTE_LANES_B4),
     .DATA_CTL_B0                      (C0_DATA_CTL_B0),
     .DATA_CTL_B1                      (C0_DATA_CTL_B1),
     .DATA_CTL_B2                      (C0_DATA_CTL_B2),
     .DATA_CTL_B3                      (C0_DATA_CTL_B3),
     .DATA_CTL_B4                      (C0_DATA_CTL_B4),
     .PHY_0_BITLANES                   (C0_PHY_0_BITLANES),
     .PHY_1_BITLANES                   (C0_PHY_1_BITLANES),
     .PHY_2_BITLANES                   (C0_PHY_2_BITLANES),
     .CK_BYTE_MAP                      (C0_CK_BYTE_MAP),
     .ADDR_MAP                         (C0_ADDR_MAP),
     .BANK_MAP                         (C0_BANK_MAP),
     .CAS_MAP                          (C0_CAS_MAP),
     .CKE_ODT_BYTE_MAP                 (C0_CKE_ODT_BYTE_MAP),
     .CKE_MAP                          (C0_CKE_MAP),
     .ODT_MAP                          (C0_ODT_MAP),
     .CS_MAP                           (C0_CS_MAP),
     .PARITY_MAP                       (C0_PARITY_MAP),
     .RAS_MAP                          (C0_RAS_MAP),
     .WE_MAP                           (C0_WE_MAP),
     .DQS_BYTE_MAP                     (C0_DQS_BYTE_MAP),
     .DATA0_MAP                        (C0_DATA0_MAP),
     .DATA1_MAP                        (C0_DATA1_MAP),
     .DATA2_MAP                        (C0_DATA2_MAP),
     .DATA3_MAP                        (C0_DATA3_MAP),
     .DATA4_MAP                        (C0_DATA4_MAP),
     .DATA5_MAP                        (C0_DATA5_MAP),
     .DATA6_MAP                        (C0_DATA6_MAP),
     .DATA7_MAP                        (C0_DATA7_MAP),
     .DATA8_MAP                        (C0_DATA8_MAP),
     .DATA9_MAP                        (C0_DATA9_MAP),
     .DATA10_MAP                       (C0_DATA10_MAP),
     .DATA11_MAP                       (C0_DATA11_MAP),
     .DATA12_MAP                       (C0_DATA12_MAP),
     .DATA13_MAP                       (C0_DATA13_MAP),
     .DATA14_MAP                       (C0_DATA14_MAP),
     .DATA15_MAP                       (C0_DATA15_MAP),
     .DATA16_MAP                       (C0_DATA16_MAP),
     .DATA17_MAP                       (C0_DATA17_MAP),
     .MASK0_MAP                        (C0_MASK0_MAP),
     .MASK1_MAP                        (C0_MASK1_MAP),
     .CALIB_ROW_ADD                    (C0_CALIB_ROW_ADD),
     .CALIB_COL_ADD                    (C0_CALIB_COL_ADD),
     .CALIB_BA_ADD                     (C0_CALIB_BA_ADD),
     .IDELAY_ADJ                       (C0_IDELAY_ADJ),
     .FINE_PER_BIT                     (C0_FINE_PER_BIT),
     .CENTER_COMP_MODE                 (C0_CENTER_COMP_MODE),
     .PI_VAL_ADJ                       (C0_PI_VAL_ADJ),
     .SLOT_0_CONFIG                    (C0_SLOT_0_CONFIG),
     .SLOT_1_CONFIG                    (C0_SLOT_1_CONFIG),
     .MEM_ADDR_ORDER                   (C0_MEM_ADDR_ORDER),
     .STARVE_LIMIT                     (STARVE_LIMIT),
     .C_S_AXI_ID_WIDTH                 (C0_C_S_AXI_ID_WIDTH),
     .C_S_AXI_ADDR_WIDTH               (C0_C_S_AXI_ADDR_WIDTH),
     .C_S_AXI_DATA_WIDTH               (C0_C_S_AXI_DATA_WIDTH),
     .C_S_AXI_SUPPORTS_NARROW_BURST    (C0_C_S_AXI_SUPPORTS_NARROW_BURST),
     .C_RD_WR_ARB_ALGORITHM            (C0_C_RD_WR_ARB_ALGORITHM),
     .C_S_AXI_REG_EN0                  (C0_C_S_AXI_REG_EN0),
     .C_S_AXI_REG_EN1                  (C0_C_S_AXI_REG_EN1),
     .C_S_AXI_CTRL_ADDR_WIDTH          (C0_C_S_AXI_CTRL_ADDR_WIDTH),
     .C_S_AXI_CTRL_DATA_WIDTH          (C0_C_S_AXI_CTRL_DATA_WIDTH),
     .C_S_AXI_BASEADDR                 (C0_C_S_AXI_BASEADDR),
     .C_ECC_ONOFF_RESET_VALUE          (C0_C_ECC_ONOFF_RESET_VALUE),
     .C_ECC_CE_COUNTER_WIDTH           (C0_C_ECC_CE_COUNTER_WIDTH),
     .USE_CS_PORT                      (C0_USE_CS_PORT),
     .USE_DM_PORT                      (C0_USE_DM_PORT),
     .USE_ODT_PORT                     (C0_USE_ODT_PORT),
     .MASTER_PHY_CTL                   (C0_PHY_CONTROL_MASTER_BANK),
     .TAPSPERKCLK                      (C0_TAPSPERKCLK),
     .SKIP_CALIB                       (SKIP_CALIB),
     .FPGA_VOLT_TYPE                   (C0_FPGA_VOLT_TYPE)
     )
    c0_u_memc_ui_top_axi
      (
       .clk                              (c0_clk),
       .clk_div2                         (c0_clk_div2),
       .rst_div2                         (c0_rst_div2),
       .clk_ref                          (clk_ref),
       .mem_refclk                       (c0_mem_refclk), //memory clock
       .freq_refclk                      (c0_freq_refclk),
       .pll_lock                         (c0_pll_locked),
       .sync_pulse                       (c0_sync_pulse),
       .mmcm_ps_clk                      (c0_mmcm_ps_clk),
       .poc_sample_pd                    (c0_poc_sample_pd),
       .psdone                           (c0_psdone),
       .iddr_rst                         (c0_iddr_rst),
       .psen                             (c0_psen),
       .psincdec                         (c0_psincdec),
       .rst                              (c0_rst),
       .rst_phaser_ref                   (c0_rst_phaser_ref),
       .ref_dll_lock                     (c0_ref_dll_lock),

// Memory interface ports
       .ddr_dq                           (c0_ddr3_dq),
       .ddr_dqs_n                        (c0_ddr3_dqs_n),
       .ddr_dqs                          (c0_ddr3_dqs_p),
       .ddr_addr                         (c0_ddr3_addr),
       .ddr_ba                           (c0_ddr3_ba),
       .ddr_cas_n                        (c0_ddr3_cas_n),
       .ddr_ck_n                         (c0_ddr3_ck_n),
       .ddr_ck                           (c0_ddr3_ck_p),
       .ddr_cke                          (c0_ddr3_cke),
       .ddr_cs_n                         (c0_ddr3_cs_n),
       .ddr_dm                           (),
       .ddr_odt                          (c0_ddr3_odt),
       .ddr_ras_n                        (c0_ddr3_ras_n),
       .ddr_reset_n                      (c0_ddr3_reset_n),
       .ddr_parity                       (c0_ddr3_parity),
       .ddr_we_n                         (c0_ddr3_we_n),
       .bank_mach_next                   (c0_bank_mach_next),

// Application interface ports
       .app_ecc_multiple_err_o           (c0_app_ecc_multiple_err),
       .app_ecc_single_err               (c0_app_ecc_single_err),

       .device_temp                      (c0_device_temp_s),

       // skip calibration ports
       `ifdef SKIP_CALIB
       .calib_tap_req                    (c0_calib_tap_req),
       .calib_tap_load                   (c0_calib_tap_load),
       .calib_tap_addr                   (c0_calib_tap_addr),
       .calib_tap_val                    (c0_calib_tap_val),
       .calib_tap_load_done              (c0_calib_tap_load_done),
       `else
       .calib_tap_req                    (),
       .calib_tap_load                   (1'b0),
       .calib_tap_addr                   (7'b0),
       .calib_tap_val                    (8'b0),
       .calib_tap_load_done              (1'b0),
       `endif

// Debug logic ports
       .dbg_idel_up_all                  (c0_dbg_idel_up_all),
       .dbg_idel_down_all                (c0_dbg_idel_down_all),
       .dbg_idel_up_cpt                  (c0_dbg_idel_up_cpt),
       .dbg_idel_down_cpt                (c0_dbg_idel_down_cpt),
       .dbg_sel_idel_cpt                 (c0_dbg_sel_idel_cpt),
       .dbg_sel_all_idel_cpt             (c0_dbg_sel_all_idel_cpt),
       .dbg_sel_pi_incdec                (c0_dbg_sel_pi_incdec),
       .dbg_sel_po_incdec                (c0_dbg_sel_po_incdec),
       .dbg_byte_sel                     (c0_dbg_byte_sel),
       .dbg_pi_f_inc                     (c0_dbg_pi_f_inc),
       .dbg_pi_f_dec                     (c0_dbg_pi_f_dec),
       .dbg_po_f_inc                     (c0_dbg_po_f_inc),
       .dbg_po_f_stg23_sel               (c0_dbg_po_f_stg23_sel),
       .dbg_po_f_dec                     (c0_dbg_po_f_dec),
       .dbg_cpt_tap_cnt                  (c0_dbg_cpt_tap_cnt),
       .dbg_dq_idelay_tap_cnt            (c0_dbg_dq_idelay_tap_cnt),
       .dbg_calib_top                    (c0_dbg_calib_top),
       .dbg_cpt_first_edge_cnt           (c0_dbg_cpt_first_edge_cnt),
       .dbg_cpt_second_edge_cnt          (c0_dbg_cpt_second_edge_cnt),
       .dbg_rd_data_offset               (c0_dbg_rd_data_offset),
       .dbg_phy_rdlvl                    (c0_dbg_phy_rdlvl),
       .dbg_phy_wrcal                    (c0_dbg_phy_wrcal),
       .dbg_final_po_fine_tap_cnt        (c0_dbg_final_po_fine_tap_cnt),
       .dbg_final_po_coarse_tap_cnt      (c0_dbg_final_po_coarse_tap_cnt),
       .dbg_rd_data_edge_detect          (c0_dbg_rd_data_edge_detect),
       .dbg_rddata                       (c0_dbg_rddata),
       .dbg_rddata_valid                 (c0_dbg_rddata_valid),
       .dbg_rdlvl_done                   (c0_dbg_rdlvl_done),
       .dbg_rdlvl_err                    (c0_dbg_rdlvl_err),
       .dbg_rdlvl_start                  (c0_dbg_rdlvl_start),
       .dbg_wrlvl_fine_tap_cnt           (c0_dbg_wrlvl_fine_tap_cnt),
       .dbg_wrlvl_coarse_tap_cnt         (c0_dbg_wrlvl_coarse_tap_cnt),
       .dbg_tap_cnt_during_wrlvl         (c0_dbg_tap_cnt_during_wrlvl),
       .dbg_wl_edge_detect_valid         (c0_dbg_wl_edge_detect_valid),
       .dbg_wrlvl_done                   (c0_dbg_wrlvl_done),
       .dbg_wrlvl_err                    (c0_dbg_wrlvl_err),
       .dbg_wrlvl_start                  (c0_dbg_wrlvl_start),
       .dbg_phy_wrlvl                    (c0_dbg_phy_wrlvl),
       .dbg_phy_init                     (c0_dbg_phy_init),
       .dbg_prbs_rdlvl                   (c0_dbg_prbs_rdlvl),
       .dbg_pi_counter_read_val          (c0_dbg_pi_counter_read_val),
       .dbg_po_counter_read_val          (c0_dbg_po_counter_read_val),
       .dbg_prbs_final_dqs_tap_cnt_r     (c0_dbg_prbs_final_dqs_tap_cnt_r_int),
       .dbg_prbs_first_edge_taps         (c0_dbg_prbs_first_edge_taps_int),
       .dbg_prbs_second_edge_taps        (c0_dbg_prbs_second_edge_taps_int),
       .dbg_pi_phaselock_start           (c0_dbg_pi_phaselock_start),
       .dbg_pi_phaselocked_done          (c0_dbg_pi_phaselocked_done),
       .dbg_pi_phaselock_err             (c0_dbg_pi_phaselock_err),
       .dbg_pi_phase_locked_phy4lanes    (c0_dbg_pi_phase_locked_phy4lanes),
       .dbg_pi_dqsfound_start            (c0_dbg_pi_dqsfound_start),
       .dbg_pi_dqsfound_done             (c0_dbg_pi_dqsfound_done),
       .dbg_pi_dqsfound_err              (c0_dbg_pi_dqsfound_err),
       .dbg_pi_dqs_found_lanes_phy4lanes (c0_dbg_pi_dqs_found_lanes_phy4lanes),
       .dbg_calib_rd_data_offset_1       (c0_dbg_calib_rd_data_offset_1),
       .dbg_calib_rd_data_offset_2       (c0_dbg_calib_rd_data_offset_2),
       .dbg_data_offset                  (c0_dbg_data_offset),
       .dbg_data_offset_1                (c0_dbg_data_offset_1),
       .dbg_data_offset_2                (c0_dbg_data_offset_2),
       .dbg_wrcal_start                  (c0_dbg_wrcal_start),
       .dbg_wrcal_done                   (c0_dbg_wrcal_done),
       .dbg_wrcal_err                    (c0_dbg_wrcal_err),
       .dbg_phy_oclkdelay_cal            (c0_dbg_phy_oclkdelay_cal),
       .dbg_oclkdelay_rd_data            (c0_dbg_oclkdelay_rd_data),
       .dbg_oclkdelay_calib_start        (c0_dbg_oclkdelay_calib_start),
       .dbg_oclkdelay_calib_done         (c0_dbg_oclkdelay_calib_done),
       .dbg_dqs_found_cal                (c0_dbg_dqs_found_cal),  
       .aresetn                          (c0_aresetn),
       .app_sr_req                       (c0_app_sr_req),
       .app_sr_active                    (c0_app_sr_active),
       .app_ref_req                      (c0_app_ref_req),
       .app_ref_ack                      (c0_app_ref_ack),
       .app_zq_req                       (c0_app_zq_req),
       .app_zq_ack                       (c0_app_zq_ack),

       // Slave Interface Write Address Ports
       .s_axi_awid                       (c0_s_axi_awid),
       .s_axi_awaddr                     (c0_s_axi_awaddr),
       .s_axi_awlen                      (c0_s_axi_awlen),
       .s_axi_awsize                     (c0_s_axi_awsize),
       .s_axi_awburst                    (c0_s_axi_awburst),
       .s_axi_awlock                     (c0_s_axi_awlock),
       .s_axi_awcache                    (c0_s_axi_awcache),
       .s_axi_awprot                     (c0_s_axi_awprot),
       .s_axi_awqos                      (c0_s_axi_awqos),
       .s_axi_awvalid                    (c0_s_axi_awvalid),
       .s_axi_awready                    (c0_s_axi_awready),
       // Slave Interface Write Data Ports
       .s_axi_wdata                      (c0_s_axi_wdata),
       .s_axi_wstrb                      (c0_s_axi_wstrb),
       .s_axi_wlast                      (c0_s_axi_wlast),
       .s_axi_wvalid                     (c0_s_axi_wvalid),
       .s_axi_wready                     (c0_s_axi_wready),
       // Slave Interface Write Response Ports
       .s_axi_bid                        (c0_s_axi_bid),
       .s_axi_bresp                      (c0_s_axi_bresp),
       .s_axi_bvalid                     (c0_s_axi_bvalid),
       .s_axi_bready                     (c0_s_axi_bready),
       // Slave Interface Read Address Ports
       .s_axi_arid                       (c0_s_axi_arid),
       .s_axi_araddr                     (c0_s_axi_araddr),
       .s_axi_arlen                      (c0_s_axi_arlen),
       .s_axi_arsize                     (c0_s_axi_arsize),
       .s_axi_arburst                    (c0_s_axi_arburst),
       .s_axi_arlock                     (c0_s_axi_arlock),
       .s_axi_arcache                    (c0_s_axi_arcache),
       .s_axi_arprot                     (c0_s_axi_arprot),
       .s_axi_arqos                      (c0_s_axi_arqos),
       .s_axi_arvalid                    (c0_s_axi_arvalid),
       .s_axi_arready                    (c0_s_axi_arready),
       // Slave Interface Read Data Ports
       .s_axi_rid                        (c0_s_axi_rid),
       .s_axi_rdata                      (c0_s_axi_rdata),
       .s_axi_rresp                      (c0_s_axi_rresp),
       .s_axi_rlast                      (c0_s_axi_rlast),
       .s_axi_rvalid                     (c0_s_axi_rvalid),
       .s_axi_rready                     (c0_s_axi_rready),
       // AXI CTRL port
       .s_axi_ctrl_awvalid               (c0_s_axi_ctrl_awvalid),
       .s_axi_ctrl_awready               (c0_s_axi_ctrl_awready),
       .s_axi_ctrl_awaddr                (c0_s_axi_ctrl_awaddr),
       // Slave Interface Write Data Ports
       .s_axi_ctrl_wvalid                (c0_s_axi_ctrl_wvalid),
       .s_axi_ctrl_wready                (c0_s_axi_ctrl_wready),
       .s_axi_ctrl_wdata                 (c0_s_axi_ctrl_wdata),
       // Slave Interface Write Response Ports
       .s_axi_ctrl_bvalid                (c0_s_axi_ctrl_bvalid),
       .s_axi_ctrl_bready                (c0_s_axi_ctrl_bready),
       .s_axi_ctrl_bresp                 (c0_s_axi_ctrl_bresp),
       // Slave Interface Read Address Ports
       .s_axi_ctrl_arvalid               (c0_s_axi_ctrl_arvalid),
       .s_axi_ctrl_arready               (c0_s_axi_ctrl_arready),
       .s_axi_ctrl_araddr                (c0_s_axi_ctrl_araddr),
       // Slave Interface Read Data Ports
       .s_axi_ctrl_rvalid                (c0_s_axi_ctrl_rvalid),
       .s_axi_ctrl_rready                (c0_s_axi_ctrl_rready),
       .s_axi_ctrl_rdata                 (c0_s_axi_ctrl_rdata),
       .s_axi_ctrl_rresp                 (c0_s_axi_ctrl_rresp),
       // Interrupt output
       .interrupt                        (c0_interrupt),
       .init_calib_complete              (c0_init_calib_complete),
       .dbg_poc                          ()
       );

      
  mig_7series_v4_2_memc_ui_top_axi #
    (
     .TCQ                              (C1_TCQ),
     .ADDR_CMD_MODE                    (C1_ADDR_CMD_MODE),
     .AL                               (C1_AL),
     .PAYLOAD_WIDTH                    (C1_PAYLOAD_WIDTH),
     .BANK_WIDTH                       (C1_BANK_WIDTH),
     .BM_CNT_WIDTH                     (C1_BM_CNT_WIDTH),
     .BURST_MODE                       (C1_BURST_MODE),
     .BURST_TYPE                       (C1_BURST_TYPE),
     .CA_MIRROR                        (C1_CA_MIRROR),
     .DDR3_VDD_OP_VOLT                 (C1_VDD_OP_VOLT),
     .CK_WIDTH                         (C1_CK_WIDTH),
     .COL_WIDTH                        (C1_COL_WIDTH),
     .CMD_PIPE_PLUS1                   (C1_CMD_PIPE_PLUS1),
     .CS_WIDTH                         (C1_CS_WIDTH),
     .nCS_PER_RANK                     (C1_nCS_PER_RANK),
     .CKE_WIDTH                        (C1_CKE_WIDTH),
     .DATA_WIDTH                       (C1_DATA_WIDTH),
     .DATA_BUF_ADDR_WIDTH              (C1_DATA_BUF_ADDR_WIDTH),
     .DQ_CNT_WIDTH                     (C1_DQ_CNT_WIDTH),
     .DQ_WIDTH                         (C1_DQ_WIDTH),
     .DQS_CNT_WIDTH                    (C1_DQS_CNT_WIDTH),
     .DQS_WIDTH                        (C1_DQS_WIDTH),
     .DRAM_TYPE                        (DRAM_TYPE),
     .DRAM_WIDTH                       (C1_DRAM_WIDTH),
     .ECC                              (C1_ECC),
     .ECC_WIDTH                        (C1_ECC_WIDTH),
     .ECC_TEST                         (C1_ECC_TEST),
     .MC_ERR_ADDR_WIDTH                (C1_MC_ERR_ADDR_WIDTH),
     .REFCLK_FREQ                      (REFCLK_FREQ),
     .nAL                              (C1_nAL),
     .nBANK_MACHS                      (C1_nBANK_MACHS),
     .CKE_ODT_AUX                      (C1_CKE_ODT_AUX),
     .nCK_PER_CLK                      (C1_nCK_PER_CLK),
     .ORDERING                         (C1_ORDERING),
     .OUTPUT_DRV                       (C1_OUTPUT_DRV),
     .IBUF_LPWR_MODE                   (C1_IBUF_LPWR_MODE),
     .DATA_IO_IDLE_PWRDWN              (C1_DATA_IO_IDLE_PWRDWN),
     .BANK_TYPE                        (C1_BANK_TYPE),
     .DATA_IO_PRIM_TYPE                (C1_DATA_IO_PRIM_TYPE),
     .IODELAY_GRP0                     (IODELAY_GRP0),
     .IODELAY_GRP1                     (IODELAY_GRP1),
     .FPGA_SPEED_GRADE                 (FPGA_SPEED_GRADE),
     .REG_CTRL                         (C1_REG_CTRL),
     .RTT_NOM                          (C1_RTT_NOM),
     .RTT_WR                           (C1_RTT_WR),
     .CL                               (C1_CL),
     .CWL                              (C1_CWL),
     .tCK                              (C1_tCK),
     .tCKE                             (C1_tCKE),
     .tFAW                             (C1_tFAW),
     .tPRDI                            (C1_tPRDI),
     .tRAS                             (C1_tRAS),
     .tRCD                             (C1_tRCD),
     .tREFI                            (C1_tREFI),
     .tRFC                             (C1_tRFC),
     .tRP                              (C1_tRP),
     .tRRD                             (C1_tRRD),
     .tRTP                             (C1_tRTP),
     .tWTR                             (C1_tWTR),
     .tZQI                             (C1_tZQI),
     .tZQCS                            (C1_tZQCS),
     .USER_REFRESH                     (C1_USER_REFRESH),
     .TEMP_MON_EN                      (TEMP_MON_EN),
     .WRLVL                            (C1_WRLVL),
     .DEBUG_PORT                       (C1_DEBUG_PORT),
     .CAL_WIDTH                        (CAL_WIDTH),
     .RANK_WIDTH                       (C1_RANK_WIDTH),
     .RANKS                            (C1_RANKS),
     .ODT_WIDTH                        (C1_ODT_WIDTH),
     .ROW_WIDTH                        (C1_ROW_WIDTH),
     .ADDR_WIDTH                       (C1_ADDR_WIDTH),
     .APP_DATA_WIDTH                   (C1_APP_DATA_WIDTH),
     .APP_MASK_WIDTH                   (C1_APP_MASK_WIDTH),
     .SIM_BYPASS_INIT_CAL              (C1_SIM_BYPASS_INIT_CAL),
     .BYTE_LANES_B0                    (C1_BYTE_LANES_B0),
     .BYTE_LANES_B1                    (C1_BYTE_LANES_B1),
     .BYTE_LANES_B2                    (C1_BYTE_LANES_B2),
     .BYTE_LANES_B3                    (C1_BYTE_LANES_B3),
     .BYTE_LANES_B4                    (C1_BYTE_LANES_B4),
     .DATA_CTL_B0                      (C1_DATA_CTL_B0),
     .DATA_CTL_B1                      (C1_DATA_CTL_B1),
     .DATA_CTL_B2                      (C1_DATA_CTL_B2),
     .DATA_CTL_B3                      (C1_DATA_CTL_B3),
     .DATA_CTL_B4                      (C1_DATA_CTL_B4),
     .PHY_0_BITLANES                   (C1_PHY_0_BITLANES),
     .PHY_1_BITLANES                   (C1_PHY_1_BITLANES),
     .PHY_2_BITLANES                   (C1_PHY_2_BITLANES),
     .CK_BYTE_MAP                      (C1_CK_BYTE_MAP),
     .ADDR_MAP                         (C1_ADDR_MAP),
     .BANK_MAP                         (C1_BANK_MAP),
     .CAS_MAP                          (C1_CAS_MAP),
     .CKE_ODT_BYTE_MAP                 (C1_CKE_ODT_BYTE_MAP),
     .CKE_MAP                          (C1_CKE_MAP),
     .ODT_MAP                          (C1_ODT_MAP),
     .CS_MAP                           (C1_CS_MAP),
     .PARITY_MAP                       (C1_PARITY_MAP),
     .RAS_MAP                          (C1_RAS_MAP),
     .WE_MAP                           (C1_WE_MAP),
     .DQS_BYTE_MAP                     (C1_DQS_BYTE_MAP),
     .DATA0_MAP                        (C1_DATA0_MAP),
     .DATA1_MAP                        (C1_DATA1_MAP),
     .DATA2_MAP                        (C1_DATA2_MAP),
     .DATA3_MAP                        (C1_DATA3_MAP),
     .DATA4_MAP                        (C1_DATA4_MAP),
     .DATA5_MAP                        (C1_DATA5_MAP),
     .DATA6_MAP                        (C1_DATA6_MAP),
     .DATA7_MAP                        (C1_DATA7_MAP),
     .DATA8_MAP                        (C1_DATA8_MAP),
     .DATA9_MAP                        (C1_DATA9_MAP),
     .DATA10_MAP                       (C1_DATA10_MAP),
     .DATA11_MAP                       (C1_DATA11_MAP),
     .DATA12_MAP                       (C1_DATA12_MAP),
     .DATA13_MAP                       (C1_DATA13_MAP),
     .DATA14_MAP                       (C1_DATA14_MAP),
     .DATA15_MAP                       (C1_DATA15_MAP),
     .DATA16_MAP                       (C1_DATA16_MAP),
     .DATA17_MAP                       (C1_DATA17_MAP),
     .MASK0_MAP                        (C1_MASK0_MAP),
     .MASK1_MAP                        (C1_MASK1_MAP),
     .CALIB_ROW_ADD                    (C1_CALIB_ROW_ADD),
     .CALIB_COL_ADD                    (C1_CALIB_COL_ADD),
     .CALIB_BA_ADD                     (C1_CALIB_BA_ADD),
     .IDELAY_ADJ                       (C1_IDELAY_ADJ),
     .FINE_PER_BIT                     (C1_FINE_PER_BIT),
     .CENTER_COMP_MODE                 (C1_CENTER_COMP_MODE),
     .PI_VAL_ADJ                       (C1_PI_VAL_ADJ),
     .SLOT_0_CONFIG                    (C1_SLOT_0_CONFIG),
     .SLOT_1_CONFIG                    (C1_SLOT_1_CONFIG),
     .MEM_ADDR_ORDER                   (C1_MEM_ADDR_ORDER),
     .STARVE_LIMIT                     (STARVE_LIMIT),
     .C_S_AXI_ID_WIDTH                 (C1_C_S_AXI_ID_WIDTH),
     .C_S_AXI_ADDR_WIDTH               (C1_C_S_AXI_ADDR_WIDTH),
     .C_S_AXI_DATA_WIDTH               (C1_C_S_AXI_DATA_WIDTH),
     .C_S_AXI_SUPPORTS_NARROW_BURST    (C1_C_S_AXI_SUPPORTS_NARROW_BURST),
     .C_RD_WR_ARB_ALGORITHM            (C1_C_RD_WR_ARB_ALGORITHM),
     .C_S_AXI_REG_EN0                  (C1_C_S_AXI_REG_EN0),
     .C_S_AXI_REG_EN1                  (C1_C_S_AXI_REG_EN1),
     .C_S_AXI_CTRL_ADDR_WIDTH          (C1_C_S_AXI_CTRL_ADDR_WIDTH),
     .C_S_AXI_CTRL_DATA_WIDTH          (C1_C_S_AXI_CTRL_DATA_WIDTH),
     .C_S_AXI_BASEADDR                 (C1_C_S_AXI_BASEADDR),
     .C_ECC_ONOFF_RESET_VALUE          (C1_C_ECC_ONOFF_RESET_VALUE),
     .C_ECC_CE_COUNTER_WIDTH           (C1_C_ECC_CE_COUNTER_WIDTH),
     .USE_CS_PORT                      (C1_USE_CS_PORT),
     .USE_DM_PORT                      (C1_USE_DM_PORT),
     .USE_ODT_PORT                     (C1_USE_ODT_PORT),
     .MASTER_PHY_CTL                   (C1_PHY_CONTROL_MASTER_BANK),
     .TAPSPERKCLK                      (C1_TAPSPERKCLK),
     .SKIP_CALIB                       (SKIP_CALIB),
     .FPGA_VOLT_TYPE                   (C1_FPGA_VOLT_TYPE)
     )
    c1_u_memc_ui_top_axi
      (
       .clk                              (c1_clk),
       .clk_div2                         (c1_clk_div2),
       .rst_div2                         (c1_rst_div2),
       .clk_ref                          (clk_ref),
       .mem_refclk                       (c1_mem_refclk), //memory clock
       .freq_refclk                      (c1_freq_refclk),
       .pll_lock                         (c1_pll_locked),
       .sync_pulse                       (c1_sync_pulse),
       .mmcm_ps_clk                      (c1_mmcm_ps_clk),
       .poc_sample_pd                    (c1_poc_sample_pd),
       .psdone                           (c1_psdone),
       .iddr_rst                         (c1_iddr_rst),
       .psen                             (c1_psen),
       .psincdec                         (c1_psincdec),
       .rst                              (c1_rst),
       .rst_phaser_ref                   (c1_rst_phaser_ref),
       .ref_dll_lock                     (c1_ref_dll_lock),

// Memory interface ports
       .ddr_dq                           (c1_ddr3_dq),
       .ddr_dqs_n                        (c1_ddr3_dqs_n),
       .ddr_dqs                          (c1_ddr3_dqs_p),
       .ddr_addr                         (c1_ddr3_addr),
       .ddr_ba                           (c1_ddr3_ba),
       .ddr_cas_n                        (c1_ddr3_cas_n),
       .ddr_ck_n                         (c1_ddr3_ck_n),
       .ddr_ck                           (c1_ddr3_ck_p),
       .ddr_cke                          (c1_ddr3_cke),
       .ddr_cs_n                         (c1_ddr3_cs_n),
       .ddr_dm                           (),
       .ddr_odt                          (c1_ddr3_odt),
       .ddr_ras_n                        (c1_ddr3_ras_n),
       .ddr_reset_n                      (c1_ddr3_reset_n),
       .ddr_parity                       (c1_ddr3_parity),
       .ddr_we_n                         (c1_ddr3_we_n),
       .bank_mach_next                   (c1_bank_mach_next),

// Application interface ports
       .app_ecc_multiple_err_o           (c1_app_ecc_multiple_err),
       .app_ecc_single_err               (c1_app_ecc_single_err),

       .device_temp                      (c1_device_temp_s),

       // skip calibration ports
       `ifdef SKIP_CALIB
       .calib_tap_req                    (c1_calib_tap_req),
       .calib_tap_load                   (c1_calib_tap_load),
       .calib_tap_addr                   (c1_calib_tap_addr),
       .calib_tap_val                    (c1_calib_tap_val),
       .calib_tap_load_done              (c1_calib_tap_load_done),
       `else
       .calib_tap_req                    (),
       .calib_tap_load                   (1'b0),
       .calib_tap_addr                   (7'b0),
       .calib_tap_val                    (8'b0),
       .calib_tap_load_done              (1'b0),
       `endif

// Debug logic ports
       .dbg_idel_up_all                  (c1_dbg_idel_up_all),
       .dbg_idel_down_all                (c1_dbg_idel_down_all),
       .dbg_idel_up_cpt                  (c1_dbg_idel_up_cpt),
       .dbg_idel_down_cpt                (c1_dbg_idel_down_cpt),
       .dbg_sel_idel_cpt                 (c1_dbg_sel_idel_cpt),
       .dbg_sel_all_idel_cpt             (c1_dbg_sel_all_idel_cpt),
       .dbg_sel_pi_incdec                (c1_dbg_sel_pi_incdec),
       .dbg_sel_po_incdec                (c1_dbg_sel_po_incdec),
       .dbg_byte_sel                     (c1_dbg_byte_sel),
       .dbg_pi_f_inc                     (c1_dbg_pi_f_inc),
       .dbg_pi_f_dec                     (c1_dbg_pi_f_dec),
       .dbg_po_f_inc                     (c1_dbg_po_f_inc),
       .dbg_po_f_stg23_sel               (c1_dbg_po_f_stg23_sel),
       .dbg_po_f_dec                     (c1_dbg_po_f_dec),
       .dbg_cpt_tap_cnt                  (c1_dbg_cpt_tap_cnt),
       .dbg_dq_idelay_tap_cnt            (c1_dbg_dq_idelay_tap_cnt),
       .dbg_calib_top                    (c1_dbg_calib_top),
       .dbg_cpt_first_edge_cnt           (c1_dbg_cpt_first_edge_cnt),
       .dbg_cpt_second_edge_cnt          (c1_dbg_cpt_second_edge_cnt),
       .dbg_rd_data_offset               (c1_dbg_rd_data_offset),
       .dbg_phy_rdlvl                    (c1_dbg_phy_rdlvl),
       .dbg_phy_wrcal                    (c1_dbg_phy_wrcal),
       .dbg_final_po_fine_tap_cnt        (c1_dbg_final_po_fine_tap_cnt),
       .dbg_final_po_coarse_tap_cnt      (c1_dbg_final_po_coarse_tap_cnt),
       .dbg_rd_data_edge_detect          (c1_dbg_rd_data_edge_detect),
       .dbg_rddata                       (c1_dbg_rddata),
       .dbg_rddata_valid                 (c1_dbg_rddata_valid),
       .dbg_rdlvl_done                   (c1_dbg_rdlvl_done),
       .dbg_rdlvl_err                    (c1_dbg_rdlvl_err),
       .dbg_rdlvl_start                  (c1_dbg_rdlvl_start),
       .dbg_wrlvl_fine_tap_cnt           (c1_dbg_wrlvl_fine_tap_cnt),
       .dbg_wrlvl_coarse_tap_cnt         (c1_dbg_wrlvl_coarse_tap_cnt),
       .dbg_tap_cnt_during_wrlvl         (c1_dbg_tap_cnt_during_wrlvl),
       .dbg_wl_edge_detect_valid         (c1_dbg_wl_edge_detect_valid),
       .dbg_wrlvl_done                   (c1_dbg_wrlvl_done),
       .dbg_wrlvl_err                    (c1_dbg_wrlvl_err),
       .dbg_wrlvl_start                  (c1_dbg_wrlvl_start),
       .dbg_phy_wrlvl                    (c1_dbg_phy_wrlvl),
       .dbg_phy_init                     (c1_dbg_phy_init),
       .dbg_prbs_rdlvl                   (c1_dbg_prbs_rdlvl),
       .dbg_pi_counter_read_val          (c1_dbg_pi_counter_read_val),
       .dbg_po_counter_read_val          (c1_dbg_po_counter_read_val),
       .dbg_prbs_final_dqs_tap_cnt_r     (c1_dbg_prbs_final_dqs_tap_cnt_r_int),
       .dbg_prbs_first_edge_taps         (c1_dbg_prbs_first_edge_taps_int),
       .dbg_prbs_second_edge_taps        (c1_dbg_prbs_second_edge_taps_int),
       .dbg_pi_phaselock_start           (c1_dbg_pi_phaselock_start),
       .dbg_pi_phaselocked_done          (c1_dbg_pi_phaselocked_done),
       .dbg_pi_phaselock_err             (c1_dbg_pi_phaselock_err),
       .dbg_pi_phase_locked_phy4lanes    (c1_dbg_pi_phase_locked_phy4lanes),
       .dbg_pi_dqsfound_start            (c1_dbg_pi_dqsfound_start),
       .dbg_pi_dqsfound_done             (c1_dbg_pi_dqsfound_done),
       .dbg_pi_dqsfound_err              (c1_dbg_pi_dqsfound_err),
       .dbg_pi_dqs_found_lanes_phy4lanes (c1_dbg_pi_dqs_found_lanes_phy4lanes),
       .dbg_calib_rd_data_offset_1       (c1_dbg_calib_rd_data_offset_1),
       .dbg_calib_rd_data_offset_2       (c1_dbg_calib_rd_data_offset_2),
       .dbg_data_offset                  (c1_dbg_data_offset),
       .dbg_data_offset_1                (c1_dbg_data_offset_1),
       .dbg_data_offset_2                (c1_dbg_data_offset_2),
       .dbg_wrcal_start                  (c1_dbg_wrcal_start),
       .dbg_wrcal_done                   (c1_dbg_wrcal_done),
       .dbg_wrcal_err                    (c1_dbg_wrcal_err),
       .dbg_phy_oclkdelay_cal            (c1_dbg_phy_oclkdelay_cal),
       .dbg_oclkdelay_rd_data            (c1_dbg_oclkdelay_rd_data),
       .dbg_oclkdelay_calib_start        (c1_dbg_oclkdelay_calib_start),
       .dbg_oclkdelay_calib_done         (c1_dbg_oclkdelay_calib_done),
       .dbg_dqs_found_cal                (c1_dbg_dqs_found_cal),  
       .aresetn                          (c1_aresetn),
       .app_sr_req                       (c1_app_sr_req),
       .app_sr_active                    (c1_app_sr_active),
       .app_ref_req                      (c1_app_ref_req),
       .app_ref_ack                      (c1_app_ref_ack),
       .app_zq_req                       (c1_app_zq_req),
       .app_zq_ack                       (c1_app_zq_ack),

       // Slave Interface Write Address Ports
       .s_axi_awid                       (c1_s_axi_awid),
       .s_axi_awaddr                     (c1_s_axi_awaddr),
       .s_axi_awlen                      (c1_s_axi_awlen),
       .s_axi_awsize                     (c1_s_axi_awsize),
       .s_axi_awburst                    (c1_s_axi_awburst),
       .s_axi_awlock                     (c1_s_axi_awlock),
       .s_axi_awcache                    (c1_s_axi_awcache),
       .s_axi_awprot                     (c1_s_axi_awprot),
       .s_axi_awqos                      (c1_s_axi_awqos),
       .s_axi_awvalid                    (c1_s_axi_awvalid),
       .s_axi_awready                    (c1_s_axi_awready),
       // Slave Interface Write Data Ports
       .s_axi_wdata                      (c1_s_axi_wdata),
       .s_axi_wstrb                      (c1_s_axi_wstrb),
       .s_axi_wlast                      (c1_s_axi_wlast),
       .s_axi_wvalid                     (c1_s_axi_wvalid),
       .s_axi_wready                     (c1_s_axi_wready),
       // Slave Interface Write Response Ports
       .s_axi_bid                        (c1_s_axi_bid),
       .s_axi_bresp                      (c1_s_axi_bresp),
       .s_axi_bvalid                     (c1_s_axi_bvalid),
       .s_axi_bready                     (c1_s_axi_bready),
       // Slave Interface Read Address Ports
       .s_axi_arid                       (c1_s_axi_arid),
       .s_axi_araddr                     (c1_s_axi_araddr),
       .s_axi_arlen                      (c1_s_axi_arlen),
       .s_axi_arsize                     (c1_s_axi_arsize),
       .s_axi_arburst                    (c1_s_axi_arburst),
       .s_axi_arlock                     (c1_s_axi_arlock),
       .s_axi_arcache                    (c1_s_axi_arcache),
       .s_axi_arprot                     (c1_s_axi_arprot),
       .s_axi_arqos                      (c1_s_axi_arqos),
       .s_axi_arvalid                    (c1_s_axi_arvalid),
       .s_axi_arready                    (c1_s_axi_arready),
       // Slave Interface Read Data Ports
       .s_axi_rid                        (c1_s_axi_rid),
       .s_axi_rdata                      (c1_s_axi_rdata),
       .s_axi_rresp                      (c1_s_axi_rresp),
       .s_axi_rlast                      (c1_s_axi_rlast),
       .s_axi_rvalid                     (c1_s_axi_rvalid),
       .s_axi_rready                     (c1_s_axi_rready),
       // AXI CTRL port
       .s_axi_ctrl_awvalid               (c1_s_axi_ctrl_awvalid),
       .s_axi_ctrl_awready               (c1_s_axi_ctrl_awready),
       .s_axi_ctrl_awaddr                (c1_s_axi_ctrl_awaddr),
       // Slave Interface Write Data Ports
       .s_axi_ctrl_wvalid                (c1_s_axi_ctrl_wvalid),
       .s_axi_ctrl_wready                (c1_s_axi_ctrl_wready),
       .s_axi_ctrl_wdata                 (c1_s_axi_ctrl_wdata),
       // Slave Interface Write Response Ports
       .s_axi_ctrl_bvalid                (c1_s_axi_ctrl_bvalid),
       .s_axi_ctrl_bready                (c1_s_axi_ctrl_bready),
       .s_axi_ctrl_bresp                 (c1_s_axi_ctrl_bresp),
       // Slave Interface Read Address Ports
       .s_axi_ctrl_arvalid               (c1_s_axi_ctrl_arvalid),
       .s_axi_ctrl_arready               (c1_s_axi_ctrl_arready),
       .s_axi_ctrl_araddr                (c1_s_axi_ctrl_araddr),
       // Slave Interface Read Data Ports
       .s_axi_ctrl_rvalid                (c1_s_axi_ctrl_rvalid),
       .s_axi_ctrl_rready                (c1_s_axi_ctrl_rready),
       .s_axi_ctrl_rdata                 (c1_s_axi_ctrl_rdata),
       .s_axi_ctrl_rresp                 (c1_s_axi_ctrl_rresp),
       // Interrupt output
       .interrupt                        (c1_interrupt),
       .init_calib_complete              (c1_init_calib_complete),
       .dbg_poc                          ()
       );

      




   //*********************************************************************
   // Resetting all RTL debug inputs as the debug ports are not enabled
   //*********************************************************************
   assign c0_dbg_idel_down_all    = 1'b0;
   assign c0_dbg_idel_down_cpt    = 1'b0;
   assign c0_dbg_idel_up_all      = 1'b0;
   assign c0_dbg_idel_up_cpt      = 1'b0;
   assign c0_dbg_sel_all_idel_cpt = 1'b0;
   assign c0_dbg_sel_idel_cpt     = 'b0;
   assign c0_dbg_byte_sel         = 'd0;
   assign c0_dbg_sel_pi_incdec    = 1'b0;
   assign c0_dbg_pi_f_inc         = 1'b0;
   assign c0_dbg_pi_f_dec         = 1'b0;
   assign c0_dbg_po_f_inc         = 'b0;
   assign c0_dbg_po_f_dec         = 'b0;
   assign c0_dbg_po_f_stg23_sel   = 'b0;
   assign c0_dbg_sel_po_incdec    = 'b0;

      
   //*********************************************************************
   // Resetting all RTL debug inputs as the debug ports are not enabled
   //*********************************************************************
   assign c1_dbg_idel_down_all    = 1'b0;
   assign c1_dbg_idel_down_cpt    = 1'b0;
   assign c1_dbg_idel_up_all      = 1'b0;
   assign c1_dbg_idel_up_cpt      = 1'b0;
   assign c1_dbg_sel_all_idel_cpt = 1'b0;
   assign c1_dbg_sel_idel_cpt     = 'b0;
   assign c1_dbg_byte_sel         = 'd0;
   assign c1_dbg_sel_pi_incdec    = 1'b0;
   assign c1_dbg_pi_f_inc         = 1'b0;
   assign c1_dbg_pi_f_dec         = 1'b0;
   assign c1_dbg_po_f_inc         = 'b0;
   assign c1_dbg_po_f_dec         = 'b0;
   assign c1_dbg_po_f_stg23_sel   = 'b0;
   assign c1_dbg_sel_po_incdec    = 'b0;

      

endmodule


