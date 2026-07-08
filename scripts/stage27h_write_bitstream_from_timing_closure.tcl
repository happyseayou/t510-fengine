set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

if {[info exists ::env(T510_WRITE_STAGE_NAME)] && $::env(T510_WRITE_STAGE_NAME) ne ""} {
    set stage_name $::env(T510_WRITE_STAGE_NAME)
} else {
    set stage_name stage27h_write_bitstream
}
if {[info exists ::env(T510_TIMING_STAGE_NAME)] && $::env(T510_TIMING_STAGE_NAME) ne ""} {
    set timing_stage_name $::env(T510_TIMING_STAGE_NAME)
} else {
    set timing_stage_name stage27h_timing_closure_iter
}
set pre_timing_rpt [file join $report_dir ${stage_name}_pre_bit_timing_summary.rpt]
set post_timing_rpt [file join $report_dir ${stage_name}_post_bit_timing_summary.rpt]
set route_status_rpt [file join $report_dir ${stage_name}_route_status.rpt]
set bit_sha_file [file join $report_dir ${stage_name}_sha256.txt]
set timing_post_phys_dcp [file join $report_dir ${timing_stage_name}_post_phys_latest.dcp]
set timing_post_phys_ok [file join $report_dir ${timing_stage_name}_post_phys_latest.ok]

proc stage27h_best_slack {delay_type} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1 -quiet]
    if {[llength $paths] == 0} {
        return ""
    }
    return [get_property SLACK $paths]
}

proc stage27h_require_nonnegative_timing {label} {
    set wns [stage27h_best_slack max]
    set whs [stage27h_best_slack min]
    puts "STAGE27H_WRITE_BITSTREAM: ${label}_WNS=$wns"
    puts "STAGE27H_WRITE_BITSTREAM: ${label}_WHS=$whs"
    if {$wns ne "" && $wns < 0} {
        error "Stage 27h setup timing is negative before bitstream: WNS=$wns"
    }
    if {$whs ne "" && $whs < 0} {
        error "Stage 27h hold timing is negative before bitstream: WHS=$whs"
    }
}

proc stage27h_export_checkpoint_overlay {repo_root top_name bit_src bit_sha_file} {
    set out_dir [file join $repo_root overlay]
    set overlay_name t510_fengine
    set bd_name t510_rfdc_bd
    file mkdir $out_dir

    set bit_out [file join $out_dir ${overlay_name}.bit]
    file copy -force $bit_src $bit_out

    set hwh_src [file join $repo_root demo-ant.gen sources_1 bd $bd_name hw_handoff ${bd_name}.hwh]
    if {![file exists $hwh_src]} {
        error "Stage 27h checkpoint overlay export could not find HWH $hwh_src"
    }
    set hwh_out [file join $out_dir ${overlay_name}.hwh]
    file copy -force $hwh_src $hwh_out

    set bd_file [file join $repo_root demo-ant.srcs sources_1 bd $bd_name ${bd_name}.bd]
    set bd_tcl_out [file join $out_dir ${overlay_name}.tcl]
    set ltx_candidates [glob -nocomplain [file join $repo_root demo-ant.runs impl_1 *.ltx]]
    set ltx_out ""
    if {[llength $ltx_candidates] != 0} {
        set ltx_out [file join $out_dir ${overlay_name}.ltx]
        file copy -force [lindex $ltx_candidates 0] $ltx_out
    }

    set manifest [file join $out_dir ${overlay_name}.manifest.txt]
    set fh [open $manifest w]
    puts $fh "project=[current_project]"
    puts $fh "part=[get_property PART [current_project]]"
    puts $fh "top=$top_name"
    puts $fh "bd=$bd_file"
    puts $fh "bd_tcl=$bd_tcl_out"
    puts $fh "hwh=$hwh_out"
    puts $fh "bit=$bit_out"
    puts $fh "ltx=$ltx_out"
    close $fh

    if {[catch {exec sha256sum $bit_out} sha_out]} {
        puts "STAGE27H_WRITE_BITSTREAM: WARN unable to sha256sum $bit_out: $sha_out"
    } else {
        set sha_fh [open $bit_sha_file w]
        puts $sha_fh $sha_out
        close $sha_fh
        puts "STAGE27H_WRITE_BITSTREAM: BIT_SHA256=$sha_out"
    }
    puts "STAGE27H_WRITE_BITSTREAM: checkpoint overlay export complete"
}

open_project [file join $repo_root demo-ant.xpr]
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
    puts "STAGE27H_WRITE_BITSTREAM: Stage 27i raw-lane witness diagnostic define enabled"
}
if {$::T510_STAGE27I_ANTI_ALIAS} {
    lappend sources_1_defines T510_STAGE27I_ANTI_ALIAS
    puts "STAGE27H_WRITE_BITSTREAM: Stage 27i 100MHz anti-alias define enabled"
}
set_property verilog_define $sources_1_defines $sources_1
set project_top_name [get_property TOP $sources_1]
if {$project_top_name eq ""} {
    set project_top_name t510_fengine_board_top
}

set lane_xfft_ip [get_ips -quiet t510_fengine_xfft_4096_lane]
set lane_xfft_run [get_runs -quiet t510_fengine_xfft_4096_lane_synth_1]
if {[llength $lane_xfft_ip] == 0 || [llength $lane_xfft_run] == 0} {
    error "Stage 27h write_bitstream requires nonrealtime streaming lane XFFT IP/OOC run; run timing closure first."
}
set lane_xfft_ip [lindex $lane_xfft_ip 0]
set lane_channels [get_property CONFIG.channels $lane_xfft_ip]
set lane_impl [get_property CONFIG.implementation_options $lane_xfft_ip]
set lane_throttle [get_property CONFIG.throttle_scheme $lane_xfft_ip]
set lane_clock [get_property CONFIG.target_clock_frequency $lane_xfft_ip]
set lane_throughput [get_property CONFIG.target_data_throughput $lane_xfft_ip]
puts "STAGE27H_WRITE_BITSTREAM: XFFT_LANE_VERIFY channels=$lane_channels implementation_options=$lane_impl throttle_scheme=$lane_throttle target_clock_frequency=$lane_clock target_data_throughput=$lane_throughput"
if {
    ($lane_channels ne "1") ||
    ($lane_impl ne "pipelined_streaming_io") ||
    ($lane_throttle ne "nonrealtime") ||
    ($lane_clock ne "325")
} {
    error "Stage 27h write_bitstream refuses non-production lane XFFT config."
}
puts "STAGE27H_WRITE_BITSTREAM: nonrealtime pipelined streaming XFFT keeps ready/valid semantics; full-rate gate remains board SPEC 480kpps"

set impl_run [get_runs impl_1]
set impl_status [get_property STATUS $impl_run]
puts "STAGE27H_WRITE_BITSTREAM: IMPL_STATUS_BEFORE=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Stage 27h implementation is not complete; refusing to write bitstream."
}

set use_post_phys_checkpoint [expr {[file exists $timing_post_phys_dcp] && [file exists $timing_post_phys_ok]}]
if {$use_post_phys_checkpoint} {
    puts "STAGE27H_WRITE_BITSTREAM: opening timing-met post-phys checkpoint $timing_post_phys_dcp"
    puts "STAGE27H_WRITE_BITSTREAM: post-phys ok marker $timing_post_phys_ok"
    open_checkpoint $timing_post_phys_dcp
} else {
    puts "STAGE27H_WRITE_BITSTREAM: no fresh post-phys checkpoint+ok marker found; opening impl_1 run"
    open_run $impl_run
}
report_route_status -file $route_status_rpt
report_timing_summary -delay_type min_max -file $pre_timing_rpt
stage27h_require_nonnegative_timing PRE_BIT

if {$use_post_phys_checkpoint} {
    set top_name [get_property TOP [get_filesets sources_1]]
    if {$top_name eq ""} {
        set top_name $project_top_name
    }
    set run_bit_path [file join $repo_root demo-ant.runs impl_1 ${top_name}.bit]
    puts "STAGE27H_WRITE_BITSTREAM: writing bitstream directly from post-phys checkpoint to $run_bit_path"
    write_bitstream -force $run_bit_path
    puts "STAGE27H_WRITE_BITSTREAM: CHECKPOINT_WRITE_BITSTREAM_COMPLETE"
} else {
    close_design
    puts "STAGE27H_WRITE_BITSTREAM: launching write_bitstream from existing routed impl_1"
    launch_runs $impl_run -to_step write_bitstream -jobs 8
    wait_on_run $impl_run
    set bit_status [get_property STATUS $impl_run]
    puts "STAGE27H_WRITE_BITSTREAM: IMPL_STATUS_AFTER=$bit_status"
    if {![string match "*write_bitstream Complete*" $bit_status]} {
        error "Stage 27h write_bitstream did not complete."
    }
    open_run $impl_run
}

report_timing_summary -delay_type min_max -file $post_timing_rpt
stage27h_require_nonnegative_timing POST_BIT

if {$use_post_phys_checkpoint} {
    stage27h_export_checkpoint_overlay $repo_root $top_name $run_bit_path $bit_sha_file
} else {
    source [file join $repo_root scripts export_overlay.tcl]

    set bit_path [file join $repo_root overlay t510_fengine.bit]
    if {![file exists $bit_path]} {
        error "Stage 27h overlay bitstream was not exported to $bit_path."
    }
    if {[catch {exec sha256sum $bit_path} sha_out]} {
        puts "STAGE27H_WRITE_BITSTREAM: WARN unable to sha256sum $bit_path: $sha_out"
    } else {
        set fh [open $bit_sha_file w]
        puts $fh $sha_out
        close $fh
        puts "STAGE27H_WRITE_BITSTREAM: BIT_SHA256=$sha_out"
    }
}

puts "STAGE27H_WRITE_BITSTREAM: overlay export complete"
exit
