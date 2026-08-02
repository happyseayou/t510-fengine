set script_path [info script]
if {$script_path eq ""} {
    set origin_dir [pwd]
} else {
    set origin_dir [file dirname [file normalize $script_path]]
}
set repo_root [file normalize [file join $origin_dir ".."]]
set ip_name t510_fengine_xfft_4096_lane
set canonical_xci [file join $repo_root demo-ant.srcs sources_1 ip $ip_name ${ip_name}.xci]

if {[llength [get_projects -quiet]] == 0} {
    open_project [file join $repo_root demo-ant.xpr]
}

set existing [get_ips -quiet $ip_name]
if {[llength $existing] != 0} {
    set existing_ip_file [file normalize [get_property IP_FILE [lindex $existing 0]]]
    if {$existing_ip_file ne [file normalize $canonical_xci]} {
        set existing_files [get_files -quiet $existing_ip_file]
        if {[llength $existing_files] != 0} {
            remove_files $existing_files
        }
        set existing [get_ips -quiet $ip_name]
    }
}
if {[llength $existing] == 0 && [file exists $canonical_xci]} {
    add_files -norecurse -fileset sources_1 $canonical_xci
    set existing [get_ips -quiet $ip_name]
}
if {[llength $existing] == 0} {
    create_ip -name xfft -vendor xilinx.com -library ip -version 9.1 -module_name $ip_name
    set ip [get_ips $ip_name]
} else {
    set ip [lindex $existing 0]
}

proc set_cfg {ip key value {required 1}} {
    set property "CONFIG.$key"
    if {[catch {set_property $property $value $ip} message]} {
        if {$required} {
            error "failed to set $property=$value: $message"
        }
        puts "WARN: skipped $property=$value: $message"
        return 0
    }
    return 1
}

set_cfg $ip channels 1
set_cfg $ip transform_length 4096
set_cfg $ip target_clock_frequency 325
set_cfg $ip run_time_configurable_transform_length false
set_cfg $ip data_format fixed_point
set_cfg $ip input_width 16
set_cfg $ip phase_factor_width 16
set_cfg $ip scaling_options scaled
set_cfg $ip rounding_modes convergent_rounding
set_cfg $ip aclken false
set_cfg $ip aresetn true
set_cfg $ip ovflo true 0
set_cfg $ip xk_index true 0
set_cfg $ip output_ordering natural_order 0
set_cfg $ip cyclic_prefix_insertion false
set_cfg $ip memory_options_data block_ram
set_cfg $ip memory_options_phase_factors block_ram
set_cfg $ip memory_options_reorder block_ram
set_cfg $ip complex_mult_type use_mults_resources
set_cfg $ip target_data_throughput 100 0
set_cfg $ip throttle_scheme realtime
set_cfg $ip implementation_options pipelined_streaming_io

set ip_file [get_files -quiet [get_property IP_FILE $ip]]
if {[llength $ip_file] != 0} {
    set_property GENERATE_SYNTH_CHECKPOINT true $ip_file
}
generate_target all $ip

foreach {property expected} {
    channels 1
    transform_length 4096
    implementation_options pipelined_streaming_io
    throttle_scheme realtime
    target_clock_frequency 325
    rounding_modes convergent_rounding
} {
    set actual [get_property CONFIG.$property $ip]
    if {$actual ne $expected} {
        error "Current XFFT requires CONFIG.$property=$expected; read $actual"
    }
}

if {[llength [get_runs -quiet ${ip_name}_synth_1]] == 0} {
    create_ip_run $ip
}
export_ip_user_files -of_objects $ip -no_script -sync -force -quiet
puts "T510_REALTIME_XFFT_IP_READY name=$ip_name xci=[get_property IP_FILE $ip]"
