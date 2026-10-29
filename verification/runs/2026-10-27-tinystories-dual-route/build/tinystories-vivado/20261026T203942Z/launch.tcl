set_param general.maxThreads 2
set failed [catch {source {/home/fedora/rknpu-fpga/build/tinystories-fpga-preparation/dual-v1/build.tcl}} problem options]
if {$failed} {
    # Debug only: an error checkpoint is never accepted as a passing stage.
    if {![catch {current_design} design] && $design ne ""} {
        catch {write_checkpoint {/home/fedora/rknpu-fpga/build/tinystories-vivado/20261026T203942Z/failed_stage_unqualified.dcp}}
    }
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
