set repo_root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $repo_root demo-ant.xpr]

set impl_status [get_property STATUS [get_runs impl_1]]
puts "IMPL_STATUS_BEFORE_BITGEN=$impl_status"
if {[string match "*write_bitstream ERROR*" $impl_status]} {
    reset_run impl_1 -from_step write_bitstream
    set impl_status [get_property STATUS [get_runs impl_1]]
    puts "IMPL_STATUS_AFTER_BITGEN_STEP_RESET=$impl_status"
}

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

set impl_status_after [get_property STATUS [get_runs impl_1]]
puts "IMPL_STATUS_AFTER_BITGEN=$impl_status_after"
if {![string match "*Complete*" $impl_status_after]} {
    error "Bitstream generation failed; refusing to export overlay metadata for a stale bitstream."
}

source [file join $repo_root scripts export_overlay.tcl]
exit
