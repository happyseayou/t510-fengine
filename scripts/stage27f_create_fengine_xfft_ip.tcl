set script_path [info script]
if {$script_path eq ""} {
    set origin_dir [pwd]
} else {
    set origin_dir [file dirname [file normalize $script_path]]
}
set repo_root [file normalize [file join $origin_dir ".."]]
set ip_name t510_fengine_xfft_4096
set canonical_xci [file join $repo_root demo-ant.srcs sources_1 ip $ip_name ${ip_name}.xci]
set use_streaming_27h [expr {[info exists ::T510_STAGE27H_STREAMING_XFFT] && $::T510_STAGE27H_STREAMING_XFFT}]
set ::T510_STAGE27H_XFFT_LANE_CONFIG_CHANGED 0

if {[llength [get_projects -quiet]] == 0} {
    open_project [file join $repo_root demo-ant.xpr]
}

set existing [get_ips -quiet $ip_name]
if {[llength $existing] != 0} {
    set existing_ip_file [file normalize [get_property IP_FILE [lindex $existing 0]]]
    if {$existing_ip_file ne [file normalize $canonical_xci]} {
        puts "STAGE27F_XFFT: replacing non-canonical IP_FILE=$existing_ip_file"
        set existing_files [get_files -quiet $existing_ip_file]
        if {[llength $existing_files] != 0} {
            remove_files $existing_files
        }
        set existing [get_ips -quiet $ip_name]
    }
}
foreach stale_dir [list \
    [file join $repo_root demo-ant.srcs sources_1 ip ${ip_name}_1] \
    [file join $repo_root demo-ant.gen sources_1 ip ${ip_name}_1] \
] {
    if {[file exists $stale_dir]} {
        puts "STAGE27F_XFFT: deleting stale duplicate $stale_dir"
        file delete -force $stale_dir
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
    set prop "CONFIG.$key"
    if {[catch {set_property $prop $value $ip} msg]} {
        if {$required} {
            error "failed to set $prop=$value: $msg"
        } else {
            puts "WARN: skipped $prop=$value: $msg"
        }
        return 0
    }
    return 1
}

set_cfg $ip channels 8
set_cfg $ip transform_length 4096
set_cfg $ip target_clock_frequency 250
set_cfg $ip run_time_configurable_transform_length false
set_cfg $ip data_format fixed_point
set_cfg $ip input_width 16
set_cfg $ip phase_factor_width 16
set_cfg $ip scaling_options scaled
set_cfg $ip rounding_modes truncation
set_cfg $ip aclken false
set_cfg $ip aresetn false
set_cfg $ip ovflo true 0
set_cfg $ip xk_index true 0
set_cfg $ip output_ordering natural_order 0
set_cfg $ip cyclic_prefix_insertion false
set_cfg $ip memory_options_data block_ram
set_cfg $ip memory_options_phase_factors block_ram
set_cfg $ip memory_options_reorder block_ram
set_cfg $ip complex_mult_type use_mults_resources

set_cfg $ip target_data_throughput 100 0
set_cfg $ip throttle_scheme nonrealtime 0
set impl_ok 0
foreach impl {automatically_select radix_4_burst_io radix_2_burst_io radix_2_lite_burst_io} {
    if {[set_cfg $ip implementation_options $impl 0]} {
        set impl_ok 1
        puts "STAGE27F_XFFT_IMPLEMENTATION_OPTIONS=$impl throttle=nonrealtime"
        break
    }
}
if {!$impl_ok} {
    error "no supported XFFT implementation_options value accepted"
}

set ip_file_obj [get_files -quiet [get_property IP_FILE $ip]]
if {[llength $ip_file_obj] != 0} {
    set_property GENERATE_SYNTH_CHECKPOINT true $ip_file_obj
}
generate_target all $ip

if {$use_streaming_27h} {
    set lane_ip_name t510_fengine_xfft_4096_lane
    set lane_canonical_xci [file join $repo_root demo-ant.srcs sources_1 ip $lane_ip_name ${lane_ip_name}.xci]
    set lane_existing [get_ips -quiet $lane_ip_name]
    if {[llength $lane_existing] != 0} {
        set lane_existing_ip_file [file normalize [get_property IP_FILE [lindex $lane_existing 0]]]
        if {$lane_existing_ip_file ne [file normalize $lane_canonical_xci]} {
            puts "STAGE27H_XFFT_LANE: replacing non-canonical IP_FILE=$lane_existing_ip_file"
            set lane_existing_files [get_files -quiet $lane_existing_ip_file]
            if {[llength $lane_existing_files] != 0} {
                remove_files $lane_existing_files
            }
            set lane_existing [get_ips -quiet $lane_ip_name]
        }
    }
    foreach stale_dir [list \
        [file join $repo_root demo-ant.srcs sources_1 ip ${lane_ip_name}_1] \
        [file join $repo_root demo-ant.gen sources_1 ip ${lane_ip_name}_1] \
    ] {
        if {[file exists $stale_dir]} {
            puts "STAGE27H_XFFT_LANE: deleting stale duplicate $stale_dir"
            file delete -force $stale_dir
        }
    }
    if {[llength $lane_existing] == 0 && [file exists $lane_canonical_xci]} {
        add_files -norecurse -fileset sources_1 $lane_canonical_xci
        set lane_existing [get_ips -quiet $lane_ip_name]
    }
    if {[llength $lane_existing] == 0} {
        create_ip -name xfft -vendor xilinx.com -library ip -version 9.1 -module_name $lane_ip_name
        set lane_ip [get_ips $lane_ip_name]
    } else {
        set lane_ip [lindex $lane_existing 0]
    }

    set lane_prev_channels [get_property CONFIG.channels $lane_ip]
    set lane_prev_impl [get_property CONFIG.implementation_options $lane_ip]
    set lane_prev_throttle [get_property CONFIG.throttle_scheme $lane_ip]
    set lane_prev_clock [get_property CONFIG.target_clock_frequency $lane_ip]
    set lane_prev_throughput [get_property CONFIG.target_data_throughput $lane_ip]
    if {
        ($lane_prev_channels ne "1") ||
        ($lane_prev_impl ne "pipelined_streaming_io") ||
        ($lane_prev_throttle ne "nonrealtime") ||
        ($lane_prev_clock ne "325")
    } {
        set ::T510_STAGE27H_XFFT_LANE_CONFIG_CHANGED 1
        puts "STAGE27H_XFFT_LANE_CONFIG_CHANGED previous channels=$lane_prev_channels implementation_options=$lane_prev_impl throttle_scheme=$lane_prev_throttle target_clock_frequency=$lane_prev_clock target_data_throughput=$lane_prev_throughput"
    }

    set_cfg $lane_ip channels 1
    set_cfg $lane_ip transform_length 4096
    set_cfg $lane_ip target_clock_frequency 325
    set_cfg $lane_ip run_time_configurable_transform_length false
    set_cfg $lane_ip data_format fixed_point
    set_cfg $lane_ip input_width 16
    set_cfg $lane_ip phase_factor_width 16
    set_cfg $lane_ip scaling_options scaled
    set_cfg $lane_ip rounding_modes truncation
    set_cfg $lane_ip aclken false
    set_cfg $lane_ip aresetn false
    set_cfg $lane_ip ovflo true 0
    set_cfg $lane_ip xk_index true 0
    set_cfg $lane_ip output_ordering natural_order 0
    set_cfg $lane_ip cyclic_prefix_insertion false
    set_cfg $lane_ip memory_options_data block_ram
    set_cfg $lane_ip memory_options_phase_factors block_ram
    set_cfg $lane_ip memory_options_reorder block_ram
    set_cfg $lane_ip complex_mult_type use_mults_resources
    set_cfg $lane_ip target_data_throughput 100 0
    set_cfg $lane_ip throttle_scheme nonrealtime
    set_cfg $lane_ip implementation_options pipelined_streaming_io

    set lane_ip_file_obj [get_files -quiet [get_property IP_FILE $lane_ip]]
    if {[llength $lane_ip_file_obj] != 0} {
        set_property GENERATE_SYNTH_CHECKPOINT true $lane_ip_file_obj
    }
    generate_target all $lane_ip

    set lane_actual_impl [get_property CONFIG.implementation_options $lane_ip]
    set lane_actual_throttle [get_property CONFIG.throttle_scheme $lane_ip]
    set lane_actual_throughput [get_property CONFIG.target_data_throughput $lane_ip]
    set lane_actual_clock [get_property CONFIG.target_clock_frequency $lane_ip]
    set lane_actual_channels [get_property CONFIG.channels $lane_ip]
    puts "STAGE27H_XFFT_LANE_VERIFY channels=$lane_actual_channels implementation_options=$lane_actual_impl throttle_scheme=$lane_actual_throttle target_clock_frequency=$lane_actual_clock target_data_throughput=$lane_actual_throughput"
    if {$lane_actual_channels ne "1"} {
        error "Stage 27h lane XFFT must be single-channel; got $lane_actual_channels"
    }
    if {$lane_actual_impl ne "pipelined_streaming_io"} {
        error "Stage 27h lane XFFT requires pipelined_streaming_io; got $lane_actual_impl"
    }
    if {$lane_actual_throttle ne "nonrealtime"} {
        error "Stage 27h lane XFFT requires nonrealtime throttle; got $lane_actual_throttle"
    }
    if {$lane_actual_clock ne "325"} {
        error "Stage 27h lane XFFT requires target_clock_frequency=325 for CMAC-domain FFT; got $lane_actual_clock"
    }
    puts "STAGE27H_XFFT_LANE_NOTE nonrealtime pipelined streaming keeps full-rate ready/valid semantics; board SPEC 480kpps remains the production gate"

    set lane_ooc_run [get_runs -quiet ${lane_ip_name}_synth_1]
    if {[llength $lane_ooc_run] == 0} {
        create_ip_run $lane_ip
    }
    export_ip_user_files -of_objects $lane_ip -no_script -sync -force -quiet
    puts "STAGE27H_XFFT_LANE_IP_READY name=$lane_ip_name xci=[get_property IP_FILE $lane_ip]"
}

set ooc_run [get_runs -quiet ${ip_name}_synth_1]
if {[llength $ooc_run] == 0} {
    create_ip_run $ip
}
export_ip_user_files -of_objects $ip -no_script -sync -force -quiet
puts "STAGE27F_XFFT_IP_READY name=$ip_name xci=[get_property IP_FILE $ip]"
