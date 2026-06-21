set repo_root [file normalize [file join [file dirname [info script]] ".."]]
set out_dir [file join $repo_root "reports" "board"]
file mkdir $out_dir

set proj_dir [file normalize [file join $repo_root ".stage24c_cmac_probe"]]
file delete -force $proj_dir
create_project stage24c_cmac_probe $proj_dir -part xczu47dr-ffve1156-2-i -force

proc try_set {ip prop value} {
    puts "TRY $prop=$value"
    if {[catch {set_property $prop $value $ip} err opt]} {
        puts "  FAIL $err"
        if {[dict exists $opt -errorinfo]} {
            puts "  ERRORINFO [dict get $opt -errorinfo]"
        }
        return 0
    }
    puts "  OK [get_property $prop $ip]"
    return 1
}

proc dump_selected {ip label} {
    puts "--- $label ---"
    foreach p {
        CONFIG.CMAC_CAUI4_MODE
        CONFIG.NUM_LANES
        CONFIG.GT_REF_CLK_FREQ
        CONFIG.GT_GROUP_SELECT
        CONFIG.RX_EQ_MODE
        CONFIG.INCLUDE_SHARED_LOGIC
        CONFIG.ADD_GT_CNRL_STS_PORTS
        CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC
        CONFIG.INCLUDE_AN_LT_TX_TRAINER
        CONFIG.UPDATE_LT_COEFF
        CONFIG.INCLUDE_RS_FEC
        CONFIG.RS_FEC_TRANSCODE_BYPASS
        CONFIG.ENABLE_AXI_INTERFACE
    } {
        if {[catch {set v [get_property $p $ip]} err]} {
            puts "$p=<ERR:$err>"
        } else {
            puts "$p=$v"
        }
    }
}

proc create_base_ip {name} {
    create_ip -name cmac_usplus -vendor xilinx.com -library ip -version 3.1 -module_name $name
    set ip [get_ips $name]
    set_property -dict [list \
        CONFIG.CMAC_CAUI4_MODE {1} \
        CONFIG.NUM_LANES {4x25} \
        CONFIG.GT_REF_CLK_FREQ {161.1328125} \
        CONFIG.GT_GROUP_SELECT {X0Y4~X0Y7} \
        CONFIG.GT_DRP_CLK {96.968727} \
        CONFIG.OPERATING_MODE {Duplex} \
        CONFIG.USER_INTERFACE {AXIS} \
        CONFIG.ENABLE_AXIS {1} \
        CONFIG.TX_FRAME_CRC_CHECKING {Enable FCS Insertion} \
        CONFIG.RX_FRAME_CRC_CHECKING {Enable FCS Stripping} \
        CONFIG.RX_MAX_PACKET_LEN {9600} \
        CONFIG.ADD_GT_CNRL_STS_PORTS {1} \
        CONFIG.INCLUDE_SHARED_LOGIC {2} \
        CONFIG.GT_TYPE {GTY} \
    ] $ip
    return $ip
}

set rpt [file join $out_dir "stage24c_cmac_param_probe.txt"]
set fh [open $rpt w]
close $fh
set old_stdout [open $rpt a]
set old_stderr $old_stdout

puts "Stage 24c CMAC parameter probe"
puts "part=[get_property PART [current_project]]"

set probes {
    {variant_a_plan {CONFIG.RX_EQ_MODE AUTO CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 1 CONFIG.INCLUDE_RS_FEC 0}}
    {variant_a_no_trainer {CONFIG.RX_EQ_MODE AUTO CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 0 CONFIG.INCLUDE_RS_FEC 0}}
    {variant_a_lpm_no_trainer {CONFIG.RX_EQ_MODE LPM CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 0 CONFIG.INCLUDE_RS_FEC 0}}
    {variant_b_plan {CONFIG.RX_EQ_MODE AUTO CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 1 CONFIG.INCLUDE_RS_FEC 1}}
    {rsfec_only {CONFIG.RX_EQ_MODE AUTO CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 0 CONFIG.INCLUDE_AN_LT_TX_TRAINER 0 CONFIG.INCLUDE_RS_FEC 1}}
    {anlt_rsfec_no_trainer {CONFIG.RX_EQ_MODE AUTO CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 0 CONFIG.INCLUDE_RS_FEC 1}}
    {anlt_axi_no_trainer {CONFIG.RX_EQ_MODE AUTO CONFIG.ENABLE_AXI_INTERFACE 1 CONFIG.INCLUDE_AUTO_NEG_LT_LOGIC 1 CONFIG.INCLUDE_AN_LT_TX_TRAINER 0 CONFIG.INCLUDE_RS_FEC 0}}
}

foreach probe $probes {
    set name [lindex $probe 0]
    set seq [lindex $probe 1]
    puts "\n=== $name ==="
    set ip [create_base_ip "cmac_${name}"]
    set ok 1
    foreach {p v} $seq {
        if {![try_set $ip $p $v]} {
            set ok 0
            break
        }
    }
    dump_selected $ip "selected_after_$name"
    if {$ok} {
        if {[catch {validate_ip $ip} err opt]} {
            puts "VALIDATE_FAIL $err"
            set ok 0
        } else {
            puts "VALIDATE_OK"
        }
    }
    if {$ok} {
        set xci [get_property IP_FILE $ip]
        if {[catch {generate_target instantiation_template $ip} err opt]} {
            puts "GEN_TEMPLATE_FAIL $err"
        } else {
            puts "GEN_TEMPLATE_OK xci=$xci"
        }
    }
}

close_project
puts "Wrote $rpt"
