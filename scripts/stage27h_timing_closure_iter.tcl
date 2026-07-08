set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

if {[info exists ::env(T510_TIMING_STAGE_NAME)] && $::env(T510_TIMING_STAGE_NAME) ne ""} {
    set stage_name $::env(T510_TIMING_STAGE_NAME)
} else {
    set stage_name stage27h_timing_closure_iter
}
set synth_timing_rpt [file join $report_dir ${stage_name}_synth_timing_summary.rpt]
set synth_util_rpt [file join $report_dir ${stage_name}_synth_utilization.rpt]
set impl_timing_rpt [file join $report_dir ${stage_name}_impl_timing_summary.rpt]
set impl_util_rpt [file join $report_dir ${stage_name}_impl_utilization.rpt]
set route_status_rpt [file join $report_dir ${stage_name}_route_status.rpt]
set worst_paths_rpt [file join $report_dir ${stage_name}_worst_paths.rpt]
set post_phys_timing_rpt [file join $report_dir ${stage_name}_post_phys_timing_summary.rpt]
set post_phys_worst_paths_rpt [file join $report_dir ${stage_name}_post_phys_worst_paths.rpt]
set routed_dcp [file join $report_dir ${stage_name}_routed_latest.dcp]
set post_phys_dcp [file join $report_dir ${stage_name}_post_phys_latest.dcp]
set post_phys_ok [file join $report_dir ${stage_name}_post_phys_latest.ok]

foreach stale_artifact [list \
    $impl_timing_rpt \
    $impl_util_rpt \
    $route_status_rpt \
    $worst_paths_rpt \
    $post_phys_timing_rpt \
    $post_phys_worst_paths_rpt \
    [file join $report_dir ${stage_name}_post_phys_route_status.rpt] \
    $routed_dcp \
    $post_phys_dcp \
    $post_phys_ok \
] {
    if {[file exists $stale_artifact]} {
        file delete -force $stale_artifact
    }
}

proc stage27h_try_set {object property value label} {
    if {[catch {set_property $property $value $object} err]} {
        puts "STAGE27H_TIMING_CLOSURE: WARN unable to set $label ($property=$value): $err"
    } else {
        puts "STAGE27H_TIMING_CLOSURE: set $label ($property=$value)"
    }
}

proc stage27h_current_wns {} {
    set max_paths [get_timing_paths -delay_type max -max_paths 1 -quiet]
    if {[llength $max_paths] == 0} {
        return ""
    }
    return [get_property SLACK $max_paths]
}

open_project [file join $repo_root demo-ant.xpr]
set ::T510_STAGE27H_STREAMING_XFFT 1
source [file join $repo_root scripts stage27f_create_fengine_xfft_ip.tcl]
set ::T510_STAGE27H_PRODUCTION_ONLY 1
set ::T510_STAGE27I_RAW_WITNESS [expr {[info exists ::env(T510_STAGE27I_RAW_WITNESS)] && $::env(T510_STAGE27I_RAW_WITNESS) ne "" && $::env(T510_STAGE27I_RAW_WITNESS) ne "0"}]
set ::T510_STAGE27I_ANTI_ALIAS [expr {[info exists ::env(T510_STAGE27I_ANTI_ALIAS)] && $::env(T510_STAGE27I_ANTI_ALIAS) ne "" && $::env(T510_STAGE27I_ANTI_ALIAS) ne "0"}]
source [file join $repo_root scripts setup_project.tcl]

set sources_1 [get_filesets sources_1]
set sources_1_defines [get_property verilog_define $sources_1]
set cleaned_sources_1_defines [list]
foreach define $sources_1_defines {
    if {$define ni {T510_STAGE27H_PRODUCTION_ONLY T510_STAGE27I_RAW_WITNESS T510_STAGE27I_ANTI_ALIAS}} {
        lappend cleaned_sources_1_defines $define
    }
}
set sources_1_defines $cleaned_sources_1_defines
lappend sources_1_defines T510_STAGE27H_PRODUCTION_ONLY
if {$::T510_STAGE27I_RAW_WITNESS} {
    lappend sources_1_defines T510_STAGE27I_RAW_WITNESS
    puts "STAGE27H_TIMING_CLOSURE: Stage 27i raw-lane witness diagnostic define enabled"
}
if {$::T510_STAGE27I_ANTI_ALIAS} {
    lappend sources_1_defines T510_STAGE27I_ANTI_ALIAS
    puts "STAGE27H_TIMING_CLOSURE: Stage 27i 100MHz anti-alias define enabled"
}
set_property verilog_define $sources_1_defines $sources_1

if {![file exists [file join $repo_root demo-ant.runs t510_cmac_usplus_0_synth_1 t510_cmac_usplus_0.dcp]]} {
    error "Stage 27h timing closure requires CMAC OOC DCP. Run clean export once to build CMAC OOC IP."
}
set xfft_run [get_runs -quiet t510_fengine_xfft_4096_lane_synth_1]
set xfft_ip [get_ips -quiet t510_fengine_xfft_4096_lane]
set xfft_disk_run_dir [file join $repo_root demo-ant.runs t510_fengine_xfft_4096_lane_synth_1]
set xfft_disk_dcp [file join $xfft_disk_run_dir t510_fengine_xfft_4096_lane.dcp]
set xfft_xci [get_property IP_FILE [get_ips t510_fengine_xfft_4096_lane]]
if {[llength $xfft_run] == 0 && [llength $xfft_ip] != 0} {
    puts "STAGE27H_TIMING_CLOSURE: create nonrealtime streaming F-engine lane XFFT OOC run"
    create_ip_run $xfft_ip -force
    set xfft_run [get_runs -quiet t510_fengine_xfft_4096_lane_synth_1]
}
if {[llength $xfft_run] == 0} {
    error "Stage 27h timing closure could not find/create F-engine lane XFFT OOC run."
}
set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_lane_synth_1]]
if {
    $::T510_STAGE27H_XFFT_LANE_CONFIG_CHANGED ||
    ![file exists $xfft_disk_dcp] ||
    ([file exists $xfft_xci] && [file exists $xfft_disk_dcp] && ([file mtime $xfft_disk_dcp] < [file mtime $xfft_xci])) ||
    ![string match "*Complete*" $xfft_status]
} {
    puts "STAGE27H_TIMING_CLOSURE: rebuild nonrealtime streaming F-engine lane XFFT OOC"
    reset_run t510_fengine_xfft_4096_lane_synth_1
    launch_runs t510_fengine_xfft_4096_lane_synth_1 -jobs 8
    wait_on_run t510_fengine_xfft_4096_lane_synth_1
    set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_lane_synth_1]]
} else {
    puts "STAGE27H_TIMING_CLOSURE: reuse nonrealtime streaming F-engine lane XFFT OOC DCP $xfft_disk_dcp"
}
puts "STAGE27H_TIMING_CLOSURE: XFFT_LANE_OOC_STATUS=$xfft_status"
if {![string match "*Complete*" $xfft_status]} {
    error "Stage 27h nonrealtime streaming F-engine lane XFFT OOC synthesis did not complete."
}

puts "STAGE27H_TIMING_CLOSURE: production-only build; stale routed/post-phys checkpoints were cleared"
set_param general.maxThreads 8

set synth_run [get_runs synth_1]
set impl_run [get_runs impl_1]

stage27h_try_set $synth_run STRATEGY Flow_PerfOptimized_high "synth strategy"
stage27h_try_set $synth_run STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE AlternateRoutability "synth directive"

catch {reset_property INCREMENTAL_CHECKPOINT $impl_run}
stage27h_try_set $impl_run STRATEGY Performance_Explore "impl strategy"
stage27h_try_set $impl_run STEPS.OPT_DESIGN.ARGS.DIRECTIVE Explore "opt directive"
stage27h_try_set $impl_run STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore "place directive"
stage27h_try_set $impl_run STEPS.PHYS_OPT_DESIGN.IS_ENABLED true "phys_opt enable"
stage27h_try_set $impl_run STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE Explore "phys_opt directive"
stage27h_try_set $impl_run STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE Explore "route directive"
stage27h_try_set $impl_run STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED false "post-route phys_opt disable in run"

puts "STAGE27H_TIMING_CLOSURE: rebuild top synthesis"
reset_run $synth_run
launch_runs $synth_run -jobs 8
wait_on_run $synth_run
set synth_status [get_property STATUS $synth_run]
puts "STAGE27H_TIMING_CLOSURE: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Stage 27h timing closure synthesis did not complete."
}

open_run $synth_run
report_utilization -file $synth_util_rpt
report_timing_summary -delay_type max -file $synth_timing_rpt
close_design

puts "STAGE27H_TIMING_CLOSURE: rebuild implementation with timing-oriented strategy"
reset_run $impl_run
catch {reset_property INCREMENTAL_CHECKPOINT $impl_run}
launch_runs $impl_run -to_step route_design -jobs 8
wait_on_run $impl_run
set impl_status [get_property STATUS $impl_run]
puts "STAGE27H_TIMING_CLOSURE: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Stage 27h timing closure implementation did not complete."
}

open_run $impl_run
report_route_status -file $route_status_rpt
report_utilization -file $impl_util_rpt
report_timing_summary -delay_type max -file $impl_timing_rpt
report_timing -delay_type max -max_paths 30 -file $worst_paths_rpt
write_checkpoint -force $routed_dcp

set wns [stage27h_current_wns]
puts "STAGE27H_TIMING_CLOSURE: ROUTED_WNS=$wns"

if {$wns ne "" && $wns < 0} {
    puts "STAGE27H_TIMING_CLOSURE: negative WNS after route; running in-memory post-route phys_opt"
    if {[catch {phys_opt_design -directive AggressiveExplore} phys_err]} {
        puts "STAGE27H_TIMING_CLOSURE: WARN post-route phys_opt failed: $phys_err"
    } else {
        catch {route_design -directive Explore}
        report_route_status -file [file join $report_dir ${stage_name}_post_phys_route_status.rpt]
        report_timing_summary -delay_type max -file $post_phys_timing_rpt
        report_timing -delay_type max -max_paths 30 -file $post_phys_worst_paths_rpt
        write_checkpoint -force $post_phys_dcp
        set post_wns [stage27h_current_wns]
        puts "STAGE27H_TIMING_CLOSURE: POST_PHYS_WNS=$post_wns"
        if {$post_wns ne "" && $post_wns >= 0} {
            set ok_fh [open $post_phys_ok w]
            puts $ok_fh "post_phys_wns=$post_wns"
            puts $ok_fh "generated_at=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
            puts $ok_fh "dcp=$post_phys_dcp"
            close $ok_fh
            puts "STAGE27H_TIMING_CLOSURE: POST_PHYS_TIMING_NONNEGATIVE"
        }
    }
} elseif {$wns ne ""} {
    puts "STAGE27H_TIMING_CLOSURE: TIMING_NONNEGATIVE"
}

puts "STAGE27H_TIMING_CLOSURE: routed checkpoint saved to $routed_dcp"
exit
