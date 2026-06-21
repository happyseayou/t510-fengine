set repo_root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $repo_root demo-ant.xpr]

set cmac_ip [get_ips -quiet t510_cmac_usplus_0]
if {[llength $cmac_ip] == 0} {
    error "Could not find IP t510_cmac_usplus_0 in project."
}

set cmac_xci [get_files -quiet "*/t510_cmac_usplus_0.xci"]
if {[llength $cmac_xci] == 0} {
    set cmac_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_cmac_usplus_0 t510_cmac_usplus_0.xci]
    if {![file exists $cmac_xci]} {
        error "Could not find t510_cmac_usplus_0.xci."
    }
}

puts "STAGE24_REFRESH: resetting CMAC IP output products"
reset_target all $cmac_xci
generate_target all $cmac_xci

set cmac_run [get_runs -quiet t510_cmac_usplus_0_synth_1]
if {[llength $cmac_run] != 0} {
    puts "STAGE24_REFRESH: rebuilding CMAC OOC run"
    reset_run t510_cmac_usplus_0_synth_1
    launch_runs t510_cmac_usplus_0_synth_1 -jobs 8
    wait_on_run t510_cmac_usplus_0_synth_1
    set cmac_status [get_property STATUS [get_runs t510_cmac_usplus_0_synth_1]]
    puts "STAGE24_REFRESH: CMAC_OOC_STATUS=$cmac_status"
    if {![string match "*Complete*" $cmac_status]} {
        error "CMAC OOC synthesis did not complete."
    }
} else {
    puts "STAGE24_REFRESH: no separate CMAC OOC run found; continuing with top-level rebuild."
}

puts "STAGE24_REFRESH: rebuilding top-level synth/impl/write_bitstream"
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "STAGE24_REFRESH: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Top-level synthesis did not complete."
}

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "STAGE24_REFRESH: IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete."
}

source [file join $repo_root scripts export_overlay.tcl]
exit
