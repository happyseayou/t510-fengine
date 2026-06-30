source [file join [file dirname [file normalize [info script]]] stage27h_mcp_timing_common.tcl]

stage27h_prepare_project
set runs [stage27h_config_timing_runs]
set impl_run [lindex $runs 1]

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
