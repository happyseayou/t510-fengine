set out_dir [file normalize ".stage24d_license_probe"]
file mkdir $out_dir

puts "STAGE24D_PROBE: create isolated CMAC project"
create_project probe_cmac $out_dir/probe_cmac -part xczu47dr-ffve1156-2-i -force

create_ip -name cmac_usplus -vendor xilinx.com -library ip -version 3.1 -module_name probe_cmac_usplus
set ip [get_ips probe_cmac_usplus]
set_property -dict [list \
    CONFIG.CMAC_CAUI4_MODE {1} \
    CONFIG.NUM_LANES {4x25} \
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

report_environment -file [file join $out_dir probe_environment_before.rpt]
report_property -file [file join $out_dir probe_ip_property_before.rpt] $ip
report_ip_status -file [file join $out_dir probe_ip_status_before.rpt]
puts "STAGE24D_PROBE: BEFORE_USED_LICENSE_KEYS=[get_property USED_LICENSE_KEYS $ip]"

generate_target all $ip

report_property -file [file join $out_dir probe_ip_property_after_generate.rpt] $ip
report_ip_status -file [file join $out_dir probe_ip_status_after_generate.rpt]
puts "STAGE24D_PROBE: AFTER_USED_LICENSE_KEYS=[get_property USED_LICENSE_KEYS $ip]"

exit
