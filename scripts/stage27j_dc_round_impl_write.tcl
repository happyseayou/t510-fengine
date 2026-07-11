set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

set stage_name stage27j_dc_round
set impl_timing_rpt [file join $report_dir ${stage_name}_impl_timing_summary.rpt]
set impl_util_rpt [file join $report_dir ${stage_name}_impl_utilization.rpt]
set route_status_rpt [file join $report_dir ${stage_name}_route_status.rpt]
set worst_paths_rpt [file join $report_dir ${stage_name}_worst_paths.rpt]
set routed_dcp [file join $report_dir ${stage_name}_routed_latest.dcp]
set post_bit_timing_rpt [file join $report_dir ${stage_name}_post_bit_timing_summary.rpt]
set sha_file [file join $report_dir ${stage_name}_sha256.txt]

proc require_nonnegative_timing {label} {
    set setup [get_timing_paths -delay_type max -max_paths 1 -quiet]
    set hold [get_timing_paths -delay_type min -max_paths 1 -quiet]
    set wns [expr {[llength $setup] ? [get_property SLACK $setup] : ""}]
    set whs [expr {[llength $hold] ? [get_property SLACK $hold] : ""}]
    puts "STAGE27J_DC_ROUND: ${label}_WNS=$wns WHS=$whs"
    if {$wns ne "" && $wns < 0} {
        error "negative setup timing: $wns"
    }
    if {$whs ne "" && $whs < 0} {
        error "negative hold timing: $whs"
    }
}

open_project [file join $repo_root demo-ant.xpr]
set synth_run [get_runs synth_1]
set impl_run [get_runs impl_1]
set synth_status [get_property STATUS $synth_run]
puts "STAGE27J_DC_ROUND: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "synth_1 is not complete"
}

reset_run $impl_run
launch_runs $impl_run -to_step write_bitstream -jobs 8
wait_on_run $impl_run
set impl_status [get_property STATUS $impl_run]
puts "STAGE27J_DC_ROUND: IMPL_STATUS=$impl_status"
if {![string match "*write_bitstream Complete*" $impl_status]} {
    error "impl_1 did not complete write_bitstream"
}

open_run $impl_run
report_route_status -file $route_status_rpt
report_utilization -file $impl_util_rpt
report_timing_summary -delay_type min_max -file $impl_timing_rpt
report_timing -delay_type max -max_paths 30 -file $worst_paths_rpt
write_checkpoint -force $routed_dcp
require_nonnegative_timing ROUTED
report_timing_summary -delay_type min_max -file $post_bit_timing_rpt

source [file join $repo_root scripts export_overlay.tcl]
set overlay_bit [file join $repo_root overlay t510_fengine.bit]
if {![file exists $overlay_bit]} {
    error "overlay export did not produce $overlay_bit"
}
set sha_fh [open $sha_file w]
puts $sha_fh [exec sha256sum $overlay_bit]
close $sha_fh
puts "STAGE27J_DC_ROUND: COMPLETE"
exit
