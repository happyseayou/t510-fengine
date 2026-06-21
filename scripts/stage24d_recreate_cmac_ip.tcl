set repo_root [file normalize [file join [file dirname [info script]] ..]]
set report_dir [file join $repo_root reports board]
file mkdir $report_dir

set old_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_cmac_usplus_0 t510_cmac_usplus_0.xci]
if {[file exists $old_xci]} {
    file copy -force $old_xci [file join $report_dir stage24d_t510_cmac_usplus_0_before_recreate.xci]
}

set old_ip [get_ips -quiet t510_cmac_usplus_0]
if {[llength $old_ip] != 0} {
    puts "STAGE24D_RECREATE: removing old IP object"
    set old_files [get_files -quiet $old_xci]
    if {[llength $old_files] != 0} {
        remove_files $old_files
    }
}

foreach path [list \
    [file join $repo_root demo-ant.srcs sources_1 ip t510_cmac_usplus_0] \
    [file join $repo_root demo-ant.gen sources_1 ip t510_cmac_usplus_0] \
    [file join $repo_root demo-ant.runs t510_cmac_usplus_0_synth_1] \
    [file join $repo_root demo-ant.runs t510_cmac_usplus_0_impl_1] \
] {
    if {[file exists $path]} {
        puts "STAGE24D_RECREATE: deleting $path"
        file delete -force $path
    }
}

set cache_dir [file join $repo_root demo-ant.cache ip]
if {[file exists $cache_dir]} {
    foreach cached [glob -nocomplain -directory $cache_dir -types d *] {
        puts "STAGE24D_RECREATE: deleting cache $cached"
        file delete -force $cached
    }
}

puts "STAGE24D_RECREATE: creating fresh no-AN/RS-FEC CMAC IP"
create_ip -name cmac_usplus -vendor xilinx.com -library ip -version 3.1 \
    -module_name t510_cmac_usplus_0 \
    -dir [file join $repo_root demo-ant.srcs sources_1 ip]

set ip [get_ips t510_cmac_usplus_0]
set_property -dict [list \
    CONFIG.CMAC_CAUI4_MODE {1} \
    CONFIG.NUM_LANES {4x25} \
    CONFIG.USER_INTERFACE {AXIS} \
    CONFIG.ENABLE_AXIS {1} \
    CONFIG.GT_REF_CLK_FREQ {156.25} \
    CONFIG.GT_DRP_CLK {96.968727} \
    CONFIG.GT_GROUP_SELECT {X0Y4~X0Y7} \
    CONFIG.LANE1_GT_LOC {X0Y4} \
    CONFIG.LANE2_GT_LOC {X0Y5} \
    CONFIG.LANE3_GT_LOC {X0Y6} \
    CONFIG.LANE4_GT_LOC {X0Y7} \
    CONFIG.INCLUDE_RS_FEC {1} \
    CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC {0} \
    CONFIG.INCLUDE_AN_LT_TX_TRAINER {0} \
    CONFIG.RX_EQ_MODE {AUTO} \
    CONFIG.ADD_GT_CNRL_STS_PORTS {1} \
    CONFIG.INCLUDE_SHARED_LOGIC {2} \
] $ip

config_ip_cache -disable_for_ip $ip
generate_target all $ip

report_property -file [file join $report_dir stage24d_cmac_ip_property_after_recreate.rpt] $ip
report_ip_status -file [file join $report_dir stage24d_ip_status_after_recreate.rpt]

puts "STAGE24D_RECREATE: USED_LICENSE_KEYS=[get_property USED_LICENSE_KEYS $ip]"
puts "STAGE24D_RECREATE: done"
