set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

set stage_name stage27h_fast_timing_iter
set latest_routed_dcp [file join $report_dir ${stage_name}_routed_latest.dcp]
set synth_timing_rpt [file join $report_dir ${stage_name}_synth_timing_summary.rpt]
set impl_timing_rpt [file join $report_dir ${stage_name}_impl_timing_summary.rpt]
set worst_paths_rpt [file join $report_dir ${stage_name}_worst_paths.rpt]
set route_status_rpt [file join $report_dir ${stage_name}_route_status.rpt]
set utilization_rpt [file join $report_dir ${stage_name}_impl_utilization.rpt]

proc stage27h_require_file {path label} {
    if {![file exists $path]} {
        error "Stage 27h fast timing requires $label at $path. Run the clean export script once to build OOC IP."
    }
}

open_project [file join $repo_root demo-ant.xpr]
set ::T510_STAGE27H_PRODUCTION_ONLY 1
source [file join $repo_root scripts setup_project.tcl]

set sources_1 [get_filesets sources_1]
set sources_1_defines [get_property verilog_define $sources_1]
lappend sources_1_defines T510_STAGE27H_PRODUCTION_ONLY
set_property verilog_define $sources_1_defines $sources_1

stage27h_require_file \
    [file join $repo_root demo-ant.runs t510_cmac_usplus_0_synth_1 t510_cmac_usplus_0.dcp] \
    "CMAC OOC DCP"
stage27h_require_file \
    [file join $repo_root demo-ant.runs t510_fengine_xfft_4096_synth_1 t510_fengine_xfft_4096.dcp] \
    "F-engine XFFT OOC DCP"

puts "STAGE27H_FAST_TIMING: reusing existing CMAC and XFFT OOC DCPs"

set synth_run [get_runs synth_1]
set impl_run [get_runs impl_1]

set_property STRATEGY Flow_RuntimeOptimized $synth_run
set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE RuntimeOptimized $synth_run
set_property STRATEGY Flow_Quick $impl_run
set_property STEPS.OPT_DESIGN.ARGS.DIRECTIVE RuntimeOptimized $impl_run
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Quick $impl_run
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE Quick $impl_run

puts "STAGE27H_FAST_TIMING: synth strategy=Flow_RuntimeOptimized directive=RuntimeOptimized"
puts "STAGE27H_FAST_TIMING: impl strategy=Flow_Quick place/route=Quick"

reset_run $synth_run
launch_runs $synth_run -jobs 8
wait_on_run $synth_run
set synth_status [get_property STATUS $synth_run]
puts "STAGE27H_FAST_TIMING: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Stage 27h fast timing top synthesis did not complete."
}

open_run $synth_run
report_timing_summary -delay_type max -file $synth_timing_rpt
close_design

reset_run $impl_run
if {[file exists $latest_routed_dcp]} {
    puts "STAGE27H_FAST_TIMING: using incremental checkpoint $latest_routed_dcp"
    set_property INCREMENTAL_CHECKPOINT $latest_routed_dcp $impl_run
} else {
    puts "STAGE27H_FAST_TIMING: no incremental checkpoint yet; this first route will seed one"
    catch {reset_property INCREMENTAL_CHECKPOINT $impl_run}
}

launch_runs $impl_run -to_step route_design -jobs 8
wait_on_run $impl_run
set impl_status [get_property STATUS $impl_run]
puts "STAGE27H_FAST_TIMING: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Stage 27h fast timing implementation did not complete route_design."
}

open_run $impl_run
report_route_status -file $route_status_rpt
report_utilization -file $utilization_rpt
report_timing_summary -delay_type max -file $impl_timing_rpt
report_timing -delay_type max -max_paths 20 -file $worst_paths_rpt
write_checkpoint -force $latest_routed_dcp

set max_paths [get_timing_paths -delay_type max -max_paths 1 -quiet]
if {[llength $max_paths] != 0} {
    set wns [get_property SLACK $max_paths]
    puts "STAGE27H_FAST_TIMING: WNS=$wns"
    if {$wns < 0} {
        puts "STAGE27H_FAST_TIMING: NEGATIVE_WNS=$wns"
    } else {
        puts "STAGE27H_FAST_TIMING: TIMING_NONNEGATIVE"
    }
}

puts "STAGE27H_FAST_TIMING: routed checkpoint saved to $latest_routed_dcp"
exit
