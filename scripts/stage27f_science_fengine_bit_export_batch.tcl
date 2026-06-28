set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

open_project [file join $repo_root demo-ant.xpr]

# Keep the proven Stage 24d CMAC configuration: 156.25 MHz, no AN/LT, RS-FEC on.
source [file join $repo_root scripts stage24d_recreate_cmac_ip.tcl]

# Stage 27f adds a production 4096-channel XFFT backend and full 64-block
# FENGINE_IQ16 packet contract on top of the Stage 27e TIME/SPEC live path.
source [file join $repo_root scripts stage27f_create_fengine_xfft_ip.tcl]
source [file join $repo_root scripts setup_project.tcl]

set ip [get_ips t510_cmac_usplus_0]
set used_license [get_property USED_LICENSE_KEYS $ip]
puts "STAGE27F_SCIENCE_FENGINE: USED_LICENSE_KEYS_AFTER_RECREATE=$used_license"
if {![regexp {cmac_usplus@2020\.05 bought} $used_license]} {
    error "Fresh CMAC IP did not bind cmac_usplus to bought license."
}

report_environment -file [file join $report_dir stage27f_science_fengine_environment.rpt]
report_ip_status -file [file join $report_dir stage27f_science_fengine_ip_status.rpt]

set cmac_run [get_runs -quiet t510_cmac_usplus_0_synth_1]
if {[llength $cmac_run] != 0} {
    puts "STAGE27F_SCIENCE_FENGINE: rebuild CMAC OOC"
    reset_run t510_cmac_usplus_0_synth_1
    launch_runs t510_cmac_usplus_0_synth_1 -jobs 8
    wait_on_run t510_cmac_usplus_0_synth_1
    set cmac_status [get_property STATUS [get_runs t510_cmac_usplus_0_synth_1]]
    puts "STAGE27F_SCIENCE_FENGINE: CMAC_OOC_STATUS=$cmac_status"
    if {![string match "*Complete*" $cmac_status]} {
        error "CMAC OOC synthesis did not complete."
    }
} else {
    puts "STAGE27F_SCIENCE_FENGINE: no CMAC OOC run found"
}

set xfft_run [get_runs -quiet t510_fengine_xfft_4096_synth_1]
set xfft_ip [get_ips -quiet t510_fengine_xfft_4096]
if {[llength $xfft_run] != 0} {
    set xfft_run_dir [get_property DIRECTORY [get_runs t510_fengine_xfft_4096_synth_1]]
    set xfft_dcp [file join $xfft_run_dir t510_fengine_xfft_4096.dcp]
    set xfft_done [file join $xfft_run_dir __synthesis_is_complete__]
    if {[file exists $xfft_dcp] && [file exists $xfft_done]} {
        puts "STAGE27F_SCIENCE_FENGINE: reuse existing F-engine XFFT OOC DCP=$xfft_dcp"
    } else {
        puts "STAGE27F_SCIENCE_FENGINE: rebuild F-engine XFFT OOC"
        reset_run t510_fengine_xfft_4096_synth_1
        launch_runs t510_fengine_xfft_4096_synth_1 -jobs 8
        set xfft_deadline [expr {[clock seconds] + 1800}]
        while {![file exists $xfft_dcp] || ![file exists $xfft_done]} {
            if {[clock seconds] > $xfft_deadline} {
                error "F-engine XFFT OOC synthesis timeout; DCP not generated."
            }
            after 30000
        }
    }
    set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_synth_1]]
    puts "STAGE27F_SCIENCE_FENGINE: XFFT_OOC_STATUS=$xfft_status"
    if {![file exists $xfft_dcp]} {
        error "F-engine XFFT OOC DCP missing after synthesis."
    }
} elseif {[llength $xfft_ip] != 0} {
    error "F-engine XFFT OOC run not found; refusing black-box/global-synth fallback."
} else {
    error "F-engine XFFT IP not found."
}

puts "STAGE27F_SCIENCE_FENGINE: rebuild top synthesis"
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "STAGE27F_SCIENCE_FENGINE: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Top synthesis did not complete."
}
open_run synth_1
report_utilization -file [file join $report_dir stage27f_science_fengine_synth_utilization.rpt]
report_timing_summary -file [file join $report_dir stage27f_science_fengine_synth_timing_summary.rpt]

puts "STAGE27F_SCIENCE_FENGINE: rebuild implementation through write_bitstream"
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "STAGE27F_SCIENCE_FENGINE: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete."
}

open_run impl_1
report_route_status -file [file join $report_dir stage27f_science_fengine_route_status.rpt]
report_utilization -file [file join $report_dir stage27f_science_fengine_impl_utilization.rpt]
report_bus_skew -warn_on_violation -file [file join $report_dir stage27f_science_fengine_bus_skew.rpt]
report_timing_summary -file [file join $report_dir stage27f_science_fengine_impl_timing_summary.rpt]
report_timing -max_paths 20 -file [file join $report_dir stage27f_science_fengine_worst_paths.rpt]

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
    puts "STAGE27F_SCIENCE_FENGINE: NEGATIVE_WNS=$wns"
}
if {$whs ne "" && $whs < 0} {
    set timing_ok 0
    puts "STAGE27F_SCIENCE_FENGINE: NEGATIVE_WHS=$whs"
}
if {!$timing_ok} {
    error "Stage 27f timing is negative; refusing to export overlay."
}

source [file join $repo_root scripts export_overlay.tcl]
puts "STAGE27F_SCIENCE_FENGINE: overlay export complete"

exit
