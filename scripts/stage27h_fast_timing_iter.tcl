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

open_project [file join $repo_root demo-ant.xpr]
set ::T510_STAGE27H_STREAMING_XFFT 1
source [file join $repo_root scripts stage27f_create_fengine_xfft_ip.tcl]
set ::T510_STAGE27H_PRODUCTION_ONLY 1
set ::T510_STAGE27I_RAW_WITNESS [expr {[info exists ::env(T510_STAGE27I_RAW_WITNESS)] && $::env(T510_STAGE27I_RAW_WITNESS) ne "" && $::env(T510_STAGE27I_RAW_WITNESS) ne "0"}]
set ::T510_STAGE27I_ANTI_ALIAS [expr {[info exists ::env(T510_STAGE27I_ANTI_ALIAS)] && $::env(T510_STAGE27I_ANTI_ALIAS) ne "" && $::env(T510_STAGE27I_ANTI_ALIAS) ne "0"}]
set ::T510_STAGE27J_PFB [expr {[info exists ::env(T510_STAGE27J_PFB)] && $::env(T510_STAGE27J_PFB) ne "" && $::env(T510_STAGE27J_PFB) ne "0"}]
source [file join $repo_root scripts setup_project.tcl]

set sources_1 [get_filesets sources_1]
set sources_1_defines [get_property verilog_define $sources_1]
set cleaned_sources_1_defines [list]
foreach define $sources_1_defines {
    if {$define ni {T510_STAGE27H_PRODUCTION_ONLY T510_STAGE27I_RAW_WITNESS T510_STAGE27I_ANTI_ALIAS T510_STAGE27J_PFB}} {
        lappend cleaned_sources_1_defines $define
    }
}
set sources_1_defines $cleaned_sources_1_defines
lappend sources_1_defines T510_STAGE27H_PRODUCTION_ONLY
if {$::T510_STAGE27I_RAW_WITNESS} {
    lappend sources_1_defines T510_STAGE27I_RAW_WITNESS
    puts "STAGE27H_FAST_TIMING: Stage 27i raw-lane witness diagnostic define enabled"
}
if {$::T510_STAGE27I_ANTI_ALIAS} {
    lappend sources_1_defines T510_STAGE27I_ANTI_ALIAS
    puts "STAGE27H_FAST_TIMING: Stage 27i 100MHz anti-alias define enabled"
}
if {$::T510_STAGE27J_PFB} {
    lappend sources_1_defines T510_STAGE27J_PFB
    puts "STAGE27H_FAST_TIMING: Stage 27j RTL PFB define enabled"
}
set_property verilog_define $sources_1_defines $sources_1

if {![file exists [file join $repo_root demo-ant.runs t510_cmac_usplus_0_synth_1 t510_cmac_usplus_0.dcp]]} {
    error "Stage 27h fast timing requires CMAC OOC DCP. Run clean export once to build CMAC OOC IP."
}
set xfft_run [get_runs -quiet t510_fengine_xfft_4096_lane_synth_1]
set xfft_ip [get_ips -quiet t510_fengine_xfft_4096_lane]
set xfft_disk_run_dir [file join $repo_root demo-ant.runs t510_fengine_xfft_4096_lane_synth_1]
set xfft_disk_dcp [file join $xfft_disk_run_dir t510_fengine_xfft_4096_lane.dcp]
set xfft_xci [get_property IP_FILE [get_ips t510_fengine_xfft_4096_lane]]
if {[llength $xfft_run] == 0 && [llength $xfft_ip] != 0} {
    puts "STAGE27H_FAST_TIMING: create nonrealtime streaming F-engine lane XFFT OOC run"
    create_ip_run $xfft_ip -force
    set xfft_run [get_runs -quiet t510_fengine_xfft_4096_lane_synth_1]
}
if {[llength $xfft_run] == 0} {
    error "Stage 27h fast timing could not find/create F-engine lane XFFT OOC run."
}
set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_lane_synth_1]]
if {
    $::T510_STAGE27H_XFFT_LANE_CONFIG_CHANGED ||
    ![file exists $xfft_disk_dcp] ||
    ([file exists $xfft_xci] && [file exists $xfft_disk_dcp] && ([file mtime $xfft_disk_dcp] < [file mtime $xfft_xci])) ||
    ![string match "*Complete*" $xfft_status]
} {
    puts "STAGE27H_FAST_TIMING: rebuild nonrealtime streaming F-engine lane XFFT OOC"
    reset_run t510_fengine_xfft_4096_lane_synth_1
    launch_runs t510_fengine_xfft_4096_lane_synth_1 -jobs 8
    wait_on_run t510_fengine_xfft_4096_lane_synth_1
    set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_lane_synth_1]]
} else {
    puts "STAGE27H_FAST_TIMING: reuse nonrealtime streaming F-engine lane XFFT OOC DCP $xfft_disk_dcp"
}
puts "STAGE27H_FAST_TIMING: XFFT_LANE_OOC_STATUS=$xfft_status"
if {![string match "*Complete*" $xfft_status]} {
    error "Stage 27h nonrealtime streaming F-engine lane XFFT OOC synthesis did not complete."
}

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
set use_incremental [expr {[info exists ::env(STAGE27H_USE_INCREMENTAL)] && $::env(STAGE27H_USE_INCREMENTAL) eq "1"}]
if {$use_incremental && [file exists $latest_routed_dcp]} {
    puts "STAGE27H_FAST_TIMING: using incremental checkpoint $latest_routed_dcp"
    set_property INCREMENTAL_CHECKPOINT $latest_routed_dcp $impl_run
} else {
    if {$use_incremental} {
        puts "STAGE27H_FAST_TIMING: incremental requested but no checkpoint exists; this route will seed one"
    } else {
        puts "STAGE27H_FAST_TIMING: incremental disabled by default to avoid stale pre-fix checkpoints"
    }
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
