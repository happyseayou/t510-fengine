set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

open_project [file join $repo_root demo-ant.xpr]

source [file join $repo_root scripts stage24d_recreate_cmac_ip.tcl]

set ip [get_ips t510_cmac_usplus_0]
set used_license [get_property USED_LICENSE_KEYS $ip]
puts "STAGE24D_CLEAN: USED_LICENSE_KEYS_AFTER_RECREATE=$used_license"
if {![regexp {cmac_usplus@2020\.05 bought} $used_license]} {
    error "Fresh CMAC IP did not bind cmac_usplus to bought license."
}

report_environment -file [file join $report_dir stage24d_clean_environment_after_recreate.rpt]
report_ip_status -file [file join $report_dir stage24d_clean_ip_status_after_recreate.rpt]

set cmac_run [get_runs -quiet t510_cmac_usplus_0_synth_1]
if {[llength $cmac_run] != 0} {
    puts "STAGE24D_CLEAN: rebuild CMAC OOC"
    reset_run t510_cmac_usplus_0_synth_1
    launch_runs t510_cmac_usplus_0_synth_1 -jobs 8
    wait_on_run t510_cmac_usplus_0_synth_1
    set cmac_status [get_property STATUS [get_runs t510_cmac_usplus_0_synth_1]]
    puts "STAGE24D_CLEAN: CMAC_OOC_STATUS=$cmac_status"
    if {![string match "*Complete*" $cmac_status]} {
        error "CMAC OOC synthesis did not complete."
    }
} else {
    puts "STAGE24D_CLEAN: no CMAC OOC run found"
}

puts "STAGE24D_CLEAN: rebuild top synthesis"
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "STAGE24D_CLEAN: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Top synthesis did not complete."
}

puts "STAGE24D_CLEAN: rebuild implementation through write_bitstream"
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "STAGE24D_CLEAN: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete."
}

source [file join $repo_root scripts export_overlay.tcl]
puts "STAGE24D_CLEAN: overlay export complete"

exit
