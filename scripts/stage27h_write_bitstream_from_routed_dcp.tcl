set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

set stage_name stage27h_10028_direct_bitstream
set routed_dcp [file join $repo_root demo-ant.runs impl_1 t510_fengine_board_top_routed.dcp]
set pre_timing_rpt [file join $report_dir ${stage_name}_pre_bit_timing_summary.rpt]
set post_timing_rpt [file join $report_dir ${stage_name}_post_bit_timing_summary.rpt]
set route_status_rpt [file join $report_dir ${stage_name}_route_status.rpt]
set drc_rpt [file join $report_dir ${stage_name}_drc.rpt]
set bit_sha_file [file join $report_dir ${stage_name}_sha256.txt]
set bit_out [file join $repo_root overlay t510_fengine.bit]
set hwh_src [file join $repo_root demo-ant.gen sources_1 bd t510_rfdc_bd hw_handoff t510_rfdc_bd.hwh]
set hwh_out [file join $repo_root overlay t510_fengine.hwh]
set manifest [file join $repo_root overlay t510_fengine.manifest.txt]

proc stage27h_best_slack {delay_type} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1 -quiet]
    if {[llength $paths] == 0} {
        return ""
    }
    return [get_property SLACK [lindex $paths 0]]
}

proc stage27h_require_nonnegative_timing {label} {
    set wns [stage27h_best_slack max]
    set whs [stage27h_best_slack min]
    puts "STAGE27H_DIRECT_BITSTREAM: ${label}_WNS=$wns"
    puts "STAGE27H_DIRECT_BITSTREAM: ${label}_WHS=$whs"
    if {$wns eq ""} {
        error "Stage 27h direct bitstream could not read setup slack."
    }
    if {$whs eq ""} {
        error "Stage 27h direct bitstream could not read hold slack."
    }
    if {$wns < 0} {
        error "Stage 27h setup timing is negative before bitstream: WNS=$wns"
    }
    if {$whs < 0} {
        error "Stage 27h hold timing is negative before bitstream: WHS=$whs"
    }
}

if {![file exists $routed_dcp]} {
    error "Stage 27h routed DCP not found: $routed_dcp"
}

file mkdir [file join $repo_root overlay]
puts "STAGE27H_DIRECT_BITSTREAM: opening routed DCP $routed_dcp"
open_checkpoint $routed_dcp

report_route_status -file $route_status_rpt
report_drc -file $drc_rpt
report_timing_summary -delay_type min_max -file $pre_timing_rpt
stage27h_require_nonnegative_timing PRE_BIT

puts "STAGE27H_DIRECT_BITSTREAM: writing bitstream $bit_out"
write_bitstream -force $bit_out

report_timing_summary -delay_type min_max -file $post_timing_rpt
stage27h_require_nonnegative_timing POST_BIT

if {![file exists $hwh_src]} {
    error "Stage 27h direct bitstream could not find HWH $hwh_src"
}
file copy -force $hwh_src $hwh_out

set design_name [current_design]
set part_name "unknown"
if {[catch {set part_name [get_property PART [current_design]]}]} {
    set part_name "unknown"
}
if {$part_name eq "" || $part_name eq "unknown"} {
    catch {set part_name [current_part]}
}

set fh [open $manifest w]
puts $fh "project=[file join $repo_root demo-ant.xpr]"
puts $fh "part=$part_name"
puts $fh "top=$design_name"
puts $fh "routed_dcp=$routed_dcp"
puts $fh "hwh=$hwh_out"
puts $fh "bit=$bit_out"
close $fh

if {[catch {exec sha256sum $bit_out} sha_out]} {
    puts "STAGE27H_DIRECT_BITSTREAM: WARN unable to sha256sum $bit_out: $sha_out"
} else {
    set sha_fh [open $bit_sha_file w]
    puts $sha_fh $sha_out
    close $sha_fh
    puts "STAGE27H_DIRECT_BITSTREAM: BIT_SHA256=$sha_out"
}

puts "STAGE27H_DIRECT_BITSTREAM: overlay export complete"
exit
