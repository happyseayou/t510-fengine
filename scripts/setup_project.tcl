set script_path [info script]
if {$script_path eq ""} {
    set origin_dir [pwd]
} else {
    set origin_dir [file dirname [file normalize $script_path]]
}
set repo_root [file normalize [file join $origin_dir ".."]]
if {![file exists [file join $repo_root rtl pl_mts_sync_clk.v]]} {
    set pwd_root [file normalize [pwd]]
    if {[file exists [file join $pwd_root rtl pl_mts_sync_clk.v]]} {
        set repo_root $pwd_root
    } elseif {[file exists [file join $pwd_root demo-ant rtl pl_mts_sync_clk.v]]} {
        set repo_root [file normalize [file join $pwd_root demo-ant]]
    } else {
        error "Unable to resolve repo root from script_path='$script_path' pwd='[pwd]'"
    }
}

set t510_stage27h_production_only [expr {[info exists ::T510_STAGE27H_PRODUCTION_ONLY] && $::T510_STAGE27H_PRODUCTION_ONLY}]

set rtl_files [list \
    [file join $repo_root rtl pl_mts_sync_clk.v] \
    [file join $repo_root rtl sync_fsm.sv] \
    [file join $repo_root rtl axis_stream_duplicator.sv] \
    [file join $repo_root rtl science_rate_selector.sv] \
    [file join $repo_root rtl science_stream_decimator.sv] \
    [file join $repo_root rtl requantizer.sv] \
    [file join $repo_root rtl monitor_counters.sv] \
    [file join $repo_root rtl time_packetizer.sv] \
    [file join $repo_root rtl pfb_channelizer.sv] \
    [file join $repo_root rtl spectral_packetizer.sv] \
    [file join $repo_root rtl udp_tx_arbiter.sv] \
    [file join $repo_root rtl axis_packet_fifo.sv] \
    [file join $repo_root rtl tx_route_selector.sv] \
    [file join $repo_root rtl udp_frame_builder.sv] \
    [file join $repo_root rtl axis64_to_cmac512_async.sv] \
    [file join $repo_root rtl axis512_register_slice.sv] \
    [file join $repo_root rtl time_axis512_ddr_ring.sv] \
    [file join $repo_root rtl time_udp_cmac512.sv] \
    [file join $repo_root rtl spec_udp_cmac512.sv] \
    [file join $repo_root rtl cmac_tx_source_mux.sv] \
    [file join $repo_root rtl t510_qsfp_test_frame_gen.sv] \
    [file join $repo_root rtl t510_cmac_qsfp0.sv] \
    [file join $repo_root rtl tx_header_capture.sv] \
    [file join $repo_root rtl tx_payload_witness_capture.sv] \
    [file join $repo_root rtl dac_tx_witness_capture.sv] \
    [file join $repo_root rtl rfdc_axis_raw_witness_capture.sv] \
    [file join $repo_root rtl fft_debug_observer.sv] \
    [file join $repo_root rtl multi_preview_observer.sv] \
    [file join $repo_root rtl feng_ctrl_axi.sv] \
    [file join $repo_root rtl axi4_to_axil_bridge.sv] \
    [file join $repo_root rtl rfdc_adc_axis_adapter.sv] \
    [file join $repo_root rtl t510_dac_loopback_source.sv] \
    [file join $repo_root rtl t510_fengine_top.sv] \
    [file join $repo_root rtl t510_fengine_stub_top.sv] \
    [file join $repo_root rtl t510_fengine_synthetic_board_top.sv] \
    [file join $repo_root rtl t510_fengine_board_top.sv] \
]

if {$t510_stage27h_production_only} {
    set stage27h_archived_bringup_rtl [list \
        [file join $repo_root rtl science_stream_decimator.sv] \
        [file join $repo_root rtl time_packetizer.sv] \
        [file join $repo_root rtl spectral_packetizer.sv] \
        [file join $repo_root rtl udp_tx_arbiter.sv] \
        [file join $repo_root rtl axis_packet_fifo.sv] \
        [file join $repo_root rtl tx_route_selector.sv] \
        [file join $repo_root rtl udp_frame_builder.sv] \
        [file join $repo_root rtl axis64_to_cmac512_async.sv] \
        [file join $repo_root rtl tx_header_capture.sv] \
        [file join $repo_root rtl tx_payload_witness_capture.sv] \
        [file join $repo_root rtl rfdc_axis_raw_witness_capture.sv] \
        [file join $repo_root rtl fft_debug_observer.sv] \
    ]
    set filtered_rtl_files [list]
    foreach f $rtl_files {
        if {[lsearch -exact $stage27h_archived_bringup_rtl $f] < 0} {
            lappend filtered_rtl_files $f
        }
    }
    set rtl_files $filtered_rtl_files
}

set xdc_files [list \
    [file join $repo_root xdc base_clocks.xdc] \
    [file join $repo_root xdc implementation_clocks.xdc] \
    [file join $repo_root xdc cdc_exceptions.xdc] \
    [file join $repo_root xdc t510_board_template.xdc] \
]

set sim_files [list \
    [file join $repo_root sim tb_common.svh] \
    [file join $repo_root sim tb_feng_ctrl_axi.sv] \
    [file join $repo_root sim tb_axi4_to_axil_bridge.sv] \
    [file join $repo_root sim tb_sync_fsm.sv] \
    [file join $repo_root sim tb_t510_dac_loopback_source.sv] \
    [file join $repo_root sim tb_rfdc_adc_axis_adapter.sv] \
    [file join $repo_root sim tb_science_rate_selector.sv] \
    [file join $repo_root sim tb_science_stream_decimator.sv] \
    [file join $repo_root sim tb_rfdc_fullrate_preview.sv] \
    [file join $repo_root sim tb_axis_stream_duplicator.sv] \
    [file join $repo_root sim tb_time_packetizer.sv] \
    [file join $repo_root sim tb_pfb_channelizer.sv] \
    [file join $repo_root sim tb_spectral_packetizer.sv] \
    [file join $repo_root sim tb_udp_tx_arbiter.sv] \
    [file join $repo_root sim tb_axis_packet_fifo.sv] \
    [file join $repo_root sim tb_tx_route_selector.sv] \
    [file join $repo_root sim tb_udp_frame_builder.sv] \
    [file join $repo_root sim tb_axis512_register_slice.sv] \
    [file join $repo_root sim tb_time_axis512_ddr_ring.sv] \
    [file join $repo_root sim tb_time_udp_cmac512.sv] \
    [file join $repo_root sim tb_spec_udp_cmac512.sv] \
    [file join $repo_root sim tb_stage25_cmac_live_tx.sv] \
    [file join $repo_root sim tb_tx_payload_witness_capture.sv] \
    [file join $repo_root sim tb_dac_tx_witness_capture.sv] \
    [file join $repo_root sim tb_rfdc_axis_raw_witness_capture.sv] \
    [file join $repo_root sim tb_fft_debug_observer.sv] \
    [file join $repo_root sim tb_t510_fengine_top_smoke.sv] \
    [file join $repo_root sim tb_t510_fengine_board_top.sv] \
]

foreach f $rtl_files {
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset sources_1 $f
    }
}

if {$t510_stage27h_production_only} {
    foreach f $stage27h_archived_bringup_rtl {
        set old_files [get_files -quiet $f]
        if {[llength $old_files] != 0} {
            remove_files -fileset sources_1 $old_files
        }
    }
}

set debug_xfft_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_debug_xfft t510_debug_xfft.xci]
if {!$t510_stage27h_production_only && [file exists $debug_xfft_xci] && [llength [get_files -quiet $debug_xfft_xci]] == 0} {
    add_files -norecurse -fileset sources_1 $debug_xfft_xci
} elseif {$t510_stage27h_production_only && [llength [get_files -quiet $debug_xfft_xci]] != 0} {
    remove_files -fileset sources_1 [get_files -quiet $debug_xfft_xci]
}

set fengine_xfft_xci_candidates [list \
    [file join $repo_root demo-ant.srcs sources_1 ip t510_fengine_xfft_4096 t510_fengine_xfft_4096.xci] \
]
foreach fengine_xfft_extra [glob -nocomplain [file join $repo_root demo-ant.srcs sources_1 ip t510_fengine_xfft_4096* t510_fengine_xfft_4096.xci]] {
    if {[lsearch -exact $fengine_xfft_xci_candidates $fengine_xfft_extra] < 0} {
        lappend fengine_xfft_xci_candidates $fengine_xfft_extra
    }
}
foreach fengine_xfft_xci $fengine_xfft_xci_candidates {
    if {[file exists $fengine_xfft_xci] && [llength [get_ips -quiet t510_fengine_xfft_4096]] == 0 && [llength [get_files -quiet $fengine_xfft_xci]] == 0} {
        add_files -norecurse -fileset sources_1 $fengine_xfft_xci
    }
}
set cmac_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_cmac_usplus_0 t510_cmac_usplus_0.xci]
if {[file exists $cmac_xci] && [llength [get_files -quiet $cmac_xci]] == 0} {
    add_files -norecurse -fileset sources_1 $cmac_xci
}

foreach f $xdc_files {
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset constrs_1 $f
    }
}

set cdc_xdc [file join $repo_root xdc cdc_exceptions.xdc]
if {[llength [get_files -quiet $cdc_xdc]] != 0} {
    set_property PROCESSING_ORDER LATE [get_files $cdc_xdc]
    set_property USED_IN_SYNTHESIS false [get_files $cdc_xdc]
    set_property USED_IN_IMPLEMENTATION true [get_files $cdc_xdc]
}

set impl_clocks_xdc [file join $repo_root xdc implementation_clocks.xdc]
if {[llength [get_files -quiet $impl_clocks_xdc]] != 0} {
    set_property PROCESSING_ORDER NORMAL [get_files $impl_clocks_xdc]
    set_property USED_IN_SYNTHESIS false [get_files $impl_clocks_xdc]
    set_property USED_IN_IMPLEMENTATION true [get_files $impl_clocks_xdc]
}

if {[llength [get_filesets -quiet sim_1]] == 0} {
    create_fileset -simset sim_1
}

foreach f $sim_files {
    if {[file exists $f] && [llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset sim_1 $f
    }
}

set sim_header [file join $repo_root sim tb_common.svh]
if {[file exists $sim_header] && [llength [get_files -quiet $sim_header]] != 0} {
    set_property file_type {Verilog Header} [get_files $sim_header]
}
set_property include_dirs [list [file join $repo_root sim]] [get_filesets sim_1]
set_property verilog_define {T510_SIM_FFT_MODEL} [get_filesets sim_1]

set_property top t510_fengine_board_top [get_filesets sources_1]

set msg_policy_tcl [file join $repo_root scripts vivado_msg_policy.tcl]
if {[file exists $msg_policy_tcl]} {
    if {[llength [get_filesets -quiet utils_1]] == 0} {
        create_fileset -utilsset utils_1
    }
    if {[llength [get_files -quiet $msg_policy_tcl]] == 0} {
        add_files -norecurse -fileset utils_1 $msg_policy_tcl
    }
}
if {[file exists $msg_policy_tcl] && [llength [get_runs -quiet synth_1]] != 0} {
    set_property STEPS.SYNTH_DESIGN.TCL.PRE $msg_policy_tcl [get_runs synth_1]
}

update_compile_order -fileset sources_1
