set script_path [info script]
if {$script_path eq ""} {
    set origin_dir [pwd]
} else {
    set origin_dir [file dirname [file normalize $script_path]]
}
set repo_root [file normalize [file join $origin_dir ".."]]
if {![file exists [file join $repo_root rtl pl_mts_sync_clk.v]]} {
    error "Unable to resolve the T510 repository root from $script_path"
}
if {[current_project -quiet] eq ""} {
    error "Open demo-ant.xpr before sourcing scripts/setup_project.tcl"
}

set rtl_files [list \
    [file join $repo_root rtl pl_mts_sync_clk.v] \
    [file join $repo_root rtl sync_fsm.sv] \
    [file join $repo_root rtl station_sync_scheduler.sv] \
    [file join $repo_root rtl axis_stream_duplicator.sv] \
    [file join $repo_root rtl science_decim2_halfband_aa.sv] \
    [file join $repo_root rtl science_rate_selector.sv] \
    [file join $repo_root rtl requantizer.sv] \
    [file join $repo_root rtl monitor_counters.sv] \
    [file join $repo_root rtl pfb_channelizer.sv] \
    [file join $repo_root rtl axis_sideband_async_fifo.sv] \
    [file join $repo_root rtl axis512_register_slice.sv] \
    [file join $repo_root rtl time_axis512_ddr_ring.sv] \
    [file join $repo_root rtl time_udp_cmac512.sv] \
    [file join $repo_root rtl spec_udp_cmac512.sv] \
    [file join $repo_root rtl cmac_tx_source_mux.sv] \
    [file join $repo_root rtl t510_cmac_qsfp0.sv] \
    [file join $repo_root rtl multi_preview_observer.sv] \
    [file join $repo_root rtl feng_ctrl_axi.sv] \
    [file join $repo_root rtl axi4_to_axil_bridge.sv] \
    [file join $repo_root rtl rfdc_adc_axis_adapter.sv] \
    [file join $repo_root rtl t510_dac_loopback_source.sv] \
    [file join $repo_root rtl t510_fengine_top.sv] \
    [file join $repo_root rtl t510_fengine_board_top.sv] \
]

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
    [file join $repo_root sim tb_station_sync_scheduler.sv] \
    [file join $repo_root sim tb_t510_dac_loopback_source.sv] \
    [file join $repo_root sim tb_rfdc_adc_axis_adapter.sv] \
    [file join $repo_root sim tb_science_rate_selector.sv] \
    [file join $repo_root sim tb_rfdc_fullrate_preview.sv] \
    [file join $repo_root sim tb_axis_stream_duplicator.sv] \
    [file join $repo_root sim tb_pfb_channelizer.sv] \
    [file join $repo_root sim tb_axis512_register_slice.sv] \
    [file join $repo_root sim tb_time_axis512_ddr_ring.sv] \
    [file join $repo_root sim tb_time_udp_cmac512.sv] \
    [file join $repo_root sim tb_spec_udp_cmac512.sv] \
    [file join $repo_root sim tb_cmac_tx_source_mux.sv] \
    [file join $repo_root sim tb_t510_cmac_pause.sv] \
    [file join $repo_root sim tb_t510_fengine_top_smoke.sv] \
]

foreach file [concat $rtl_files $xdc_files $sim_files] {
    if {![file exists $file]} {
        error "Current source list contains a missing file: $file"
    }
}

proc _t510_remove_stale_repo_sources {fileset_name root_dir keep_files} {
    if {[llength [get_filesets -quiet $fileset_name]] == 0} {
        return
    }
    foreach file_obj [get_files -quiet -of_objects [get_filesets $fileset_name]] {
        set file_name [file normalize [get_property NAME $file_obj]]
        if {[string match "${root_dir}/*" $file_name] &&
            [lsearch -exact $keep_files $file_name] < 0} {
            remove_files -fileset $fileset_name $file_obj
        }
    }
}

_t510_remove_stale_repo_sources sources_1 [file join $repo_root rtl] $rtl_files
_t510_remove_stale_repo_sources sim_1 [file join $repo_root sim] $sim_files

foreach pattern [list \
    "*/t510_debug_xfft.xci" \
    "*/t510_fengine_xfft_4096.xci" \
    "*/t510_fengine_bd.bd" \
] {
    set stale [get_files -quiet -all $pattern]
    if {[llength $stale] != 0} {
        remove_files $stale
    }
}
foreach run_name {t510_debug_xfft_impl_1 t510_fengine_xfft_4096_impl_1 t510_debug_xfft_synth_1 t510_fengine_xfft_4096_synth_1} {
    if {[llength [get_runs -quiet $run_name]] != 0} {
        delete_runs [get_runs $run_name]
    }
}
foreach fileset_name {t510_debug_xfft t510_fengine_xfft_4096} {
    if {[llength [get_filesets -quiet $fileset_name]] != 0} {
        delete_fileset [get_filesets $fileset_name]
    }
}

foreach file $rtl_files {
    if {[llength [get_files -quiet $file]] == 0} {
        add_files -norecurse -fileset sources_1 $file
    }
}
foreach file $xdc_files {
    if {[llength [get_files -quiet $file]] == 0} {
        add_files -norecurse -fileset constrs_1 $file
    }
}
if {[llength [get_filesets -quiet sim_1]] == 0} {
    create_fileset -simset sim_1
}
foreach file $sim_files {
    if {[llength [get_files -quiet $file]] == 0} {
        add_files -norecurse -fileset sim_1 $file
    }
}

set lane_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_fengine_xfft_4096_lane t510_fengine_xfft_4096_lane.xci]
set cmac_xci [file join $repo_root demo-ant.srcs sources_1 ip t510_cmac_usplus_0 t510_cmac_usplus_0.xci]
foreach xci [list $lane_xci $cmac_xci] {
    if {![file exists $xci]} {
        error "Required current IP configuration is missing: $xci"
    }
    if {[llength [get_files -quiet $xci]] == 0} {
        add_files -norecurse -fileset sources_1 $xci
    }
}

# IP source sets can retain defines copied from older project revisions even
# after the main design fileset has been cleaned.  The current implementation
# is unconditional, so keep every block source set define-free as well.
foreach block_fileset [get_filesets -quiet -filter {FILESET_TYPE == "BlockSrcs"}] {
    set_property verilog_define {} $block_fileset
}

set sim_header [file join $repo_root sim tb_common.svh]
set_property file_type {Verilog Header} [get_files $sim_header]
set_property include_dirs [list [file join $repo_root sim]] [get_filesets sim_1]
set_property verilog_define {} [get_filesets sources_1]
set_property verilog_define {T510_SIM_FFT_MODEL} [get_filesets sim_1]
set_property top t510_fengine_board_top [get_filesets sources_1]

set cdc_xdc [file join $repo_root xdc cdc_exceptions.xdc]
set_property PROCESSING_ORDER LATE [get_files $cdc_xdc]
set_property USED_IN_SYNTHESIS false [get_files $cdc_xdc]
set_property USED_IN_IMPLEMENTATION true [get_files $cdc_xdc]
set impl_clocks_xdc [file join $repo_root xdc implementation_clocks.xdc]
set_property PROCESSING_ORDER NORMAL [get_files $impl_clocks_xdc]
set_property USED_IN_SYNTHESIS false [get_files $impl_clocks_xdc]
set_property USED_IN_IMPLEMENTATION true [get_files $impl_clocks_xdc]

set msg_policy_tcl [file join $repo_root scripts vivado_msg_policy.tcl]
if {[file exists $msg_policy_tcl]} {
    if {[llength [get_filesets -quiet utils_1]] == 0} {
        create_fileset -utilsset utils_1
    }
    if {[llength [get_files -quiet $msg_policy_tcl]] == 0} {
        add_files -norecurse -fileset utils_1 $msg_policy_tcl
    }
    if {[llength [get_runs -quiet synth_1]] != 0} {
        set_property STEPS.SYNTH_DESIGN.TCL.PRE $msg_policy_tcl [get_runs synth_1]
    }
}

update_compile_order -fileset sources_1
update_compile_order -fileset sim_1
puts "T510_CURRENT_SOURCE_SET_READY rtl=[llength $rtl_files] sim=[llength $sim_files]"
