set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

open_project [file join $repo_root demo-ant.xpr]

# Stage 27h keeps the Stage 27f production wire contract and rebuilds the
# overlay for TIME_SPEC 100MHz board + host convergence.
source [file join $repo_root scripts stage24d_recreate_cmac_ip.tcl]
source [file join $repo_root scripts stage27f_create_fengine_xfft_ip.tcl]
set ::T510_STAGE27H_PRODUCTION_ONLY 1
source [file join $repo_root scripts setup_project.tcl]

set sources_1 [get_filesets sources_1]
set sources_1_defines [get_property verilog_define $sources_1]
lappend sources_1_defines T510_STAGE27H_PRODUCTION_ONLY
set_property verilog_define $sources_1_defines $sources_1

set ip [get_ips t510_cmac_usplus_0]
set used_license [get_property USED_LICENSE_KEYS $ip]
puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: USED_LICENSE_KEYS_AFTER_RECREATE=$used_license"
if {![regexp {cmac_usplus@2020\.05 bought} $used_license]} {
    error "Fresh CMAC IP did not bind cmac_usplus to bought license."
}

report_environment -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_environment.rpt]
report_ip_status -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_ip_status.rpt]

set cmac_run [get_runs -quiet t510_cmac_usplus_0_synth_1]
if {[llength $cmac_run] != 0} {
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: rebuild CMAC OOC"
    reset_run t510_cmac_usplus_0_synth_1
    launch_runs t510_cmac_usplus_0_synth_1 -jobs 8
    wait_on_run t510_cmac_usplus_0_synth_1
    set cmac_status [get_property STATUS [get_runs t510_cmac_usplus_0_synth_1]]
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: CMAC_OOC_STATUS=$cmac_status"
    if {![string match "*Complete*" $cmac_status]} {
        error "CMAC OOC synthesis did not complete."
    }
} else {
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: no CMAC OOC run found"
}

set xfft_run [get_runs -quiet t510_fengine_xfft_4096_synth_1]
set xfft_ip [get_ips -quiet t510_fengine_xfft_4096]
set xfft_disk_run_dir [file join $repo_root demo-ant.runs t510_fengine_xfft_4096_synth_1]
set xfft_disk_dcp [file join $xfft_disk_run_dir t510_fengine_xfft_4096.dcp]
set xfft_disk_done [file join $xfft_disk_run_dir __synthesis_is_complete__]
if {[llength $xfft_run] == 0 && [llength $xfft_ip] != 0} {
    if {[file exists $xfft_disk_dcp] && [file exists $xfft_disk_done]} {
        puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: reuse disk F-engine XFFT OOC DCP=$xfft_disk_dcp"
    } else {
        puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: create missing F-engine XFFT OOC run"
        create_ip_run $xfft_ip -force
        set xfft_run [get_runs -quiet t510_fengine_xfft_4096_synth_1]
    }
}
if {[llength $xfft_run] != 0} {
    set xfft_run_dir [get_property DIRECTORY [get_runs t510_fengine_xfft_4096_synth_1]]
    set xfft_dcp [file join $xfft_run_dir t510_fengine_xfft_4096.dcp]
    set xfft_done [file join $xfft_run_dir __synthesis_is_complete__]
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: rebuild F-engine XFFT OOC for nonrealtime throttle"
    reset_run t510_fengine_xfft_4096_synth_1
    launch_runs t510_fengine_xfft_4096_synth_1 -jobs 8
    set xfft_deadline [expr {[clock seconds] + 1800}]
    while {![file exists $xfft_dcp] || ![file exists $xfft_done]} {
        if {[clock seconds] > $xfft_deadline} {
            error "F-engine XFFT OOC synthesis timeout; DCP not generated."
        }
        after 30000
    }
    set xfft_status [get_property STATUS [get_runs t510_fengine_xfft_4096_synth_1]]
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: XFFT_OOC_STATUS=$xfft_status"
    if {![file exists $xfft_dcp]} {
        error "F-engine XFFT OOC DCP missing after synthesis."
    }
} elseif {[file exists $xfft_disk_dcp] && [file exists $xfft_disk_done]} {
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: XFFT_OOC_STATUS=disk DCP reused"
} elseif {[llength $xfft_ip] != 0} {
    error "F-engine XFFT OOC run not found; refusing black-box/global-synth fallback."
} else {
    error "F-engine XFFT IP not found."
}

puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: rebuild top synthesis"
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Top synthesis did not complete."
}
open_run synth_1
report_utilization -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_synth_utilization.rpt]
report_timing_summary -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_synth_timing_summary.rpt]

puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: rebuild implementation through write_bitstream"
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete."
}

open_run impl_1
report_route_status -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_route_status.rpt]
report_utilization -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_impl_utilization.rpt]
report_bus_skew -warn_on_violation -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_bus_skew.rpt]
report_timing_summary -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_impl_timing_summary.rpt]
report_timing -max_paths 20 -file [file join $report_dir stage27h_time_spec_100mhz_fft_fullrate_worst_paths.rpt]

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
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: NEGATIVE_WNS=$wns"
}
if {$whs ne "" && $whs < 0} {
    set timing_ok 0
    puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: NEGATIVE_WHS=$whs"
}
if {!$timing_ok} {
    error "Stage 27h FFT-only full-rate timing is negative; refusing to export overlay."
}

source [file join $repo_root scripts export_overlay.tcl]
puts "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE: overlay export complete"

exit
