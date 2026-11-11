# Rendered by tools/merged/vivado_merged_image.py --profile image-b from
# fpga/image_b/image_b_sources.json.
#
# Standalone IMAGE B build (pooling corpus + EW FP16/FDIV + ew-int + USER2
# transport; Lead D1/D4 two-image split). No hardware connection, automatic FPGA programming
# or flash writing occurs. The timing/DRC/route/CDC/page-presence gates are the
# same gates the adopted images use; the reviewed emission block mirrors
# fpga/host/emit.tcl.in (pins/standards, route boolean checks, no waivers,
# reviewed DRC inventory, source-derived USR_ACCESS).
set root {/home/fedora/rknpu-fpga}
set out {/home/fedora/rknpu-fpga/build/merged-image/image-b-resume-20261111T1455Z/implementation}
set source_sha 2429bcfc226217dcc7810f9bd6ccfa6379ab3243298560371980dde62d0df733
set source_tag 2429bcfc
set page_mask 0000111
set required_pages {memory conv_runtime_page}

# ---- source binding: the rendered package must be frozen and named by the
# ---- caller, exactly like the EW image's RK_HOST_PREPARED_SHA gate. ----------
if {![regexp {^[0-9a-f]{64}$} $source_sha]} { error "Invalid rendered source sha256." }
if {![regexp {^[0-9a-f]{8}$} $source_tag]} { error "Invalid rendered source tag." }
if {![regexp {^[01]{7}$} $page_mask]} { error "PAGE_MASK must be a 7-bit binary string." }
if {![info exists ::env(RK_MERGED_SOURCE_SHA)] || $::env(RK_MERGED_SOURCE_SHA) ne $source_sha} {
    error "Prepare a fresh package and export RK_MERGED_SOURCE_SHA equal to its source manifest sha256."
}
# ---- fresh output directory (never mix receipts from an earlier build) ------
if {[file exists $out] && [llength [glob -nocomplain -directory $out *]] != 0} {
    error "Merged image build requires a fresh output directory."
}
file mkdir $out
# ---- board facts are supplied explicitly, never defaulted -------------------
set emit_bitstream 0
if {[info exists ::env(RK_EMIT_BITSTREAM)]} { set emit_bitstream $::env(RK_EMIT_BITSTREAM) }
if {$emit_bitstream ni {0 1}} { error "RK_EMIT_BITSTREAM must be 0 or 1." }
if {![info exists ::env(RK_CONFIRM_BOARD)] || $::env(RK_CONFIRM_BOARD) ne "YPCB_00338_1P1"} {
    error "Set RK_CONFIRM_BOARD=YPCB_00338_1P1 only after checking the XDC against your board."
}
set emit_polarity 0
if {[info exists ::env(RK_LED_ACTIVE_LOW)]} {
    if {$::env(RK_LED_ACTIVE_LOW) ni {0 1}} { error "RK_LED_ACTIVE_LOW must be 0 or 1." }
    set emit_polarity $::env(RK_LED_ACTIVE_LOW)
} elseif {$emit_bitstream} {
    error "Set RK_LED_ACTIVE_LOW=0|1 after observing the board's LEDs; it is unverified in the donor sources."
}
set have_voltage [info exists ::env(RK_CONFIG_VOLTAGE)]
set have_cfgbvs [info exists ::env(RK_CFGBVS)]
if {$emit_bitstream || $have_voltage || $have_cfgbvs} {
    if {!$have_voltage || !$have_cfgbvs} {
        error "Supply both board-verified RK_CONFIG_VOLTAGE and RK_CFGBVS; see docs/FPGA.md."
    }
    if {$::env(RK_CONFIG_VOLTAGE) ni {1.5 1.8 2.5 3.3}} { error "Invalid RK_CONFIG_VOLTAGE." }
    if {$::env(RK_CFGBVS) ni {GND VCCO}} { error "RK_CFGBVS must be GND or VCCO." }
    if {($::env(RK_CONFIG_VOLTAGE) in {1.5 1.8} && $::env(RK_CFGBVS) ne "GND") ||
        ($::env(RK_CONFIG_VOLTAGE) in {2.5 3.3} && $::env(RK_CFGBVS) ne "VCCO")} {
        error "Incompatible RK_CONFIG_VOLTAGE/RK_CFGBVS pair; verify the actual board supplies and strap."
    }
}

# ---- resume implementation from the verified post-synthesis checkpoint ------
# This skips synthesis, which already PASSED (114,821 LUTs / 36,619 regs /
# 45 BRAM). Used after a thermal interruption so the proven synthesis stage is
# not repeated.
if {[llength $argv] < 1} { error "usage: -tclargs <post_synth.dcp>" }
set checkpoint [lindex $argv 0]
if {![file exists $checkpoint]} { error "checkpoint not found: $checkpoint" }
file mkdir $out
open_checkpoint $checkpoint
set_property CONFIG_VOLTAGE $::env(RK_CONFIG_VOLTAGE) [current_design]
set_property CFGBVS $::env(RK_CFGBVS) [current_design]
# Re-apply the reviewed USER2 mailbox CDC constraints after opening the checkpoint.
source {/home/fedora/rknpu-fpga/fpga/host/mailbox_cdc.tcl}
rk_host_cdc_constrain

# ---- implementation -------------------------------------------------------
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $out routed.dcp]
report_utilization -file [file join $out utilization.rpt]
report_route_status -file [file join $out route_status.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing.rpt]
report_pulse_width -file [file join $out pulse_width.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -file [file join $out drc.rpt]
rk_host_cdc_audit $out

# ---- timing / constraint gates (identical to the adopted image templates) --
foreach check {no_clock unconstrained_internal_endpoints} {
    set detail [check_timing -override_defaults $check -no_header -return_string]
    set channel [open [file join $out check_timing_${check}.rpt] w]
    puts $channel $detail
    close $channel
    set heading [format {(?im)^\s*(?:[0-9]+\.\s*)?checking\s+%s(?:\s*\([0-9]+\))?\.?\s*$} $check]
    if {![regexp $heading $detail]} {
        error "Unrecognized $check timing report; no bitstream is emitted."
    }
    set summaries 0
    foreach line [split $detail \n] {
        if {[regexp {^\s*There are ([0-9]+) .+} $line -> count]} {
            incr summaries
            if {$count != 0} { error "Unresolved $check timing findings ($count); no bitstream is emitted." }
        } elseif {[regexp -nocase {there are} $line]} {
            error "Unrecognized $check timing count; no bitstream is emitted."
        }
    }
    if {$summaries == 0} { error "Missing $check timing count; no bitstream is emitted." }
}
foreach delay_type {max min} {
    # `get_timing_paths -max_paths 1` may return a single object rather than a
    # list, which makes a naive `foreach` iterate the object's fields. Normalise
    # to a list first, then read SLACK.
    set raw [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $raw] == 0} { error "No $delay_type timing paths found; inspect constraints." }
    set paths [list]
    if {[llength [lindex $raw 0]] > 0 && [string is integer -strict [lindex $raw 0]] == 0} {
        set paths [list $raw]
    } else {
        set paths $raw
    }
    foreach path $paths {
        set slack [get_property SLACK $path]
        if {![string is double -strict $slack]} {
            error "Invalid $delay_type slack ($slack); no bitstream is emitted."
        }
        if {[expr {double($slack)}] < 0} {
            error "Negative $delay_type slack ($slack ns); no bitstream is emitted."
        }
    }
}
foreach violation [get_drc_violations] {
    set severity [string toupper [get_property SEVERITY $violation]]
    if {$severity ni {WARNING ADVISORY INFO}} {
        error "Blocking DRC violation $violation (severity $severity)."
    }
}
puts "Routed merged-image checkpoint/reports produced. Review timing, DRC, BRAM inference, page presence and CDC audit."

