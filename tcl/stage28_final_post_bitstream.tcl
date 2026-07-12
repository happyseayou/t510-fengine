set stage28_report_dir [file normalize "/home/astrolab/demo-ant/reports/vivado/stage28_final_0x00010030_realtime_xfft"]
file mkdir $stage28_report_dir

report_timing_summary \
    -delay_type min_max \
    -report_unconstrained \
    -check_timing_verbose \
    -max_paths 50 \
    -file [file join $stage28_report_dir timing_summary.rpt]
report_utilization \
    -hierarchical \
    -file [file join $stage28_report_dir utilization_hierarchical.rpt]
report_route_status \
    -file [file join $stage28_report_dir route_status.rpt]
report_drc \
    -file [file join $stage28_report_dir drc.rpt]
report_methodology \
    -file [file join $stage28_report_dir methodology.rpt]
report_clock_utilization \
    -file [file join $stage28_report_dir clock_utilization.rpt]
write_checkpoint \
    -force \
    [file join $stage28_report_dir t510_fengine_board_top_routed.dcp]

set stage28_impl_dir [file normalize [pwd]]
set stage28_impl_run [get_runs -quiet impl_1]
if {[llength $stage28_impl_run] != 0} {
    set stage28_impl_dir [get_property DIRECTORY $stage28_impl_run]
}
set stage28_top t510_fengine_board_top
set stage28_sources [get_filesets -quiet sources_1]
if {[llength $stage28_sources] != 0} {
    set stage28_top [get_property TOP $stage28_sources]
}
set stage28_bit_files {}
set stage28_bit_path [file normalize [file join $stage28_impl_dir ${stage28_top}.bit]]
if {[file exists $stage28_bit_path]} {
    lappend stage28_bit_files $stage28_bit_path
}
set stage28_sha_path [file join $stage28_report_dir bitstream_sha256.txt]
set stage28_sha_file [open $stage28_sha_path w]
foreach stage28_bit $stage28_bit_files {
    if {[catch {exec sha256sum $stage28_bit} stage28_sha_line]} {
        puts $stage28_sha_file "SHA256_ERROR $stage28_bit: $stage28_sha_line"
    } else {
        puts $stage28_sha_file $stage28_sha_line
    }
}
close $stage28_sha_file

set stage28_summary [open [file join $stage28_report_dir run_summary.txt] w]
puts $stage28_summary "stage=28"
puts $stage28_summary "iteration=D-realtime-xfft-pfb-rounding-pipeline"
puts $stage28_summary "core_version=0x00010030"
set stage28_current_run "unknown"
if {[llength [current_run -quiet]] != 0} {
    set stage28_current_run [current_run]
}
set stage28_current_design "unknown"
if {[llength [current_design -quiet]] != 0} {
    set stage28_current_design [current_design]
}
puts $stage28_summary "run=$stage28_current_run"
puts $stage28_summary "design=$stage28_current_design"
set stage28_part "unknown"
if {[llength [current_project -quiet]] != 0} {
    set stage28_part [get_property PART [current_project]]
} elseif {[llength [current_design -quiet]] != 0} {
    set stage28_part [get_property PART [current_design]]
}
puts $stage28_summary "part=$stage28_part"
puts $stage28_summary "generated_at=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
puts $stage28_summary "bitstreams=[join $stage28_bit_files { }]"
close $stage28_summary

set stage28_cmac_audit [open [file join $stage28_report_dir cmac_license_audit.txt] w]
puts $stage28_cmac_audit "policy=base_cmac_plus_rsfec_no_an_lt"
set stage28_cmac_ip [get_ips -quiet t510_cmac_usplus_0]
if {[llength $stage28_cmac_ip] == 0} {
    puts $stage28_cmac_audit "cmac_ip_found=0"
} else {
    puts $stage28_cmac_audit "cmac_ip_found=1"
    puts $stage28_cmac_audit "include_auto_neg_lt_logic=[get_property CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC $stage28_cmac_ip]"
    puts $stage28_cmac_audit "include_an_lt_tx_trainer=[get_property CONFIG.INCLUDE_AN_LT_TX_TRAINER $stage28_cmac_ip]"
    puts $stage28_cmac_audit "include_rs_fec=[get_property CONFIG.INCLUDE_RS_FEC $stage28_cmac_ip]"
    puts $stage28_cmac_audit "used_license_keys=[get_property USED_LICENSE_KEYS $stage28_cmac_ip]"
}
puts $stage28_cmac_audit "vivado_2022_2_cmac_v3_1_catalog_declares_cmac_an_lt_unconditionally=1"
close $stage28_cmac_audit
