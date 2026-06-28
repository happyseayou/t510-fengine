set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

open_project [file join $repo_root demo-ant.xpr]

# Keep the proven Stage 24d CMAC configuration: 156.25 MHz, no AN/LT, RS-FEC on.
source [file join $repo_root scripts stage24d_recreate_cmac_ip.tcl]

# Stage 27c refreshes the Stage 27b multiflow RTL into a new hardware build.
source [file join $repo_root scripts setup_project.tcl]

set ip [get_ips t510_cmac_usplus_0]
set used_license [get_property USED_LICENSE_KEYS $ip]
puts "STAGE27C_MULTIFLOW_RSS: USED_LICENSE_KEYS_AFTER_RECREATE=$used_license"
if {![regexp {cmac_usplus@2020\.05 bought} $used_license]} {
    error "Fresh CMAC IP did not bind cmac_usplus to bought license."
}

report_environment -file [file join $report_dir stage27c_multiflow_rss_environment.rpt]
report_ip_status -file [file join $report_dir stage27c_multiflow_rss_ip_status.rpt]

set cmac_run [get_runs -quiet t510_cmac_usplus_0_synth_1]
if {[llength $cmac_run] != 0} {
    puts "STAGE27C_MULTIFLOW_RSS: rebuild CMAC OOC"
    reset_run t510_cmac_usplus_0_synth_1
    launch_runs t510_cmac_usplus_0_synth_1 -jobs 8
    wait_on_run t510_cmac_usplus_0_synth_1
    set cmac_status [get_property STATUS [get_runs t510_cmac_usplus_0_synth_1]]
    puts "STAGE27C_MULTIFLOW_RSS: CMAC_OOC_STATUS=$cmac_status"
    if {![string match "*Complete*" $cmac_status]} {
        error "CMAC OOC synthesis did not complete."
    }
} else {
    puts "STAGE27C_MULTIFLOW_RSS: no CMAC OOC run found"
}

puts "STAGE27C_MULTIFLOW_RSS: rebuild top synthesis"
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "STAGE27C_MULTIFLOW_RSS: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Top synthesis did not complete."
}
open_run synth_1
report_utilization -file [file join $report_dir stage27c_multiflow_rss_synth_utilization.rpt]
report_timing_summary -file [file join $report_dir stage27c_multiflow_rss_synth_timing_summary.rpt]

puts "STAGE27C_MULTIFLOW_RSS: rebuild implementation through write_bitstream"
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "STAGE27C_MULTIFLOW_RSS: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete."
}

open_run impl_1
report_route_status -file [file join $report_dir stage27c_multiflow_rss_route_status.rpt]
report_utilization -file [file join $report_dir stage27c_multiflow_rss_impl_utilization.rpt]
report_timing_summary -file [file join $report_dir stage27c_multiflow_rss_impl_timing_summary.rpt]
report_timing -max_paths 20 -file [file join $report_dir stage27c_multiflow_rss_worst_paths.rpt]

set timing_ok 1
set max_paths [get_timing_paths -delay_type max -max_paths 1 -quiet]
set min_paths [get_timing_paths -delay_type min -max_paths 1 -quiet]
set wns ""
set whs ""
if {[llength $max_paths] != 0} {
    set wns [get_property SLACK $max_paths]
}
if {[llength $min_paths] != 0} {
    set whs [get_property SLACK $min_paths]
}
if {$wns ne "" && $wns < 0} {
    set timing_ok 0
    puts "STAGE27C_MULTIFLOW_RSS: NEGATIVE_WNS=$wns"
}
if {$whs ne "" && $whs < 0} {
    set timing_ok 0
    puts "STAGE27C_MULTIFLOW_RSS: NEGATIVE_WHS=$whs"
}
if {!$timing_ok} {
    error "Stage 27c timing is negative; refusing to export overlay."
}

source [file join $repo_root scripts export_overlay.tcl]
puts "STAGE27C_MULTIFLOW_RSS: overlay export complete"

exit
