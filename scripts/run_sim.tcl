set origin_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $origin_dir ".."]]

set rtl_files [list \
    [file join $repo_root rtl sync_fsm.sv] \
    [file join $repo_root rtl station_sync_scheduler.sv] \
    [file join $repo_root rtl axis_stream_duplicator.sv] \
    [file join $repo_root rtl science_decim2_halfband_aa.sv] \
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
    [file join $repo_root rtl time_udp_cmac512.sv] \
    [file join $repo_root rtl spec_udp_cmac512.sv] \
    [file join $repo_root rtl cmac_tx_source_mux.sv] \
    [file join $repo_root rtl tx_header_capture.sv] \
    [file join $repo_root rtl tx_payload_witness_capture.sv] \
    [file join $repo_root rtl dac_tx_witness_capture.sv] \
    [file join $repo_root rtl rfdc_axis_raw_witness_capture.sv] \
    [file join $repo_root rtl t510_qsfp_test_frame_gen.sv] \
    [file join $repo_root rtl fft_debug_observer.sv] \
    [file join $repo_root rtl multi_preview_observer.sv] \
    [file join $repo_root rtl feng_ctrl_axi.sv] \
    [file join $repo_root rtl axi4_to_axil_bridge.sv] \
    [file join $repo_root rtl rfdc_adc_axis_adapter.sv] \
    [file join $repo_root rtl t510_fengine_top.sv] \
    [file join $repo_root rtl t510_cmac_qsfp0.sv] \
    [file join $repo_root rtl t510_fengine_synthetic_board_top.sv] \
]

set sim_files [list \
    [file join $repo_root sim tb_common.svh] \
    [file join $repo_root sim tb_feng_ctrl_axi.sv] \
    [file join $repo_root sim tb_axi4_to_axil_bridge.sv] \
    [file join $repo_root sim tb_sync_fsm.sv] \
    [file join $repo_root sim tb_station_sync_scheduler.sv] \
    [file join $repo_root sim tb_rfdc_adc_axis_adapter.sv] \
    [file join $repo_root sim tb_science_rate_selector.sv] \
    [file join $repo_root sim tb_science_stream_decimator.sv] \
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
    [file join $repo_root sim tb_cmac_tx_source_mux.sv] \
    [file join $repo_root sim tb_stage25_cmac_live_tx.sv] \
    [file join $repo_root sim tb_t510_qsfp_test_frame_gen.sv] \
    [file join $repo_root sim tb_tx_payload_witness_capture.sv] \
    [file join $repo_root sim tb_dac_tx_witness_capture.sv] \
    [file join $repo_root sim tb_rfdc_axis_raw_witness_capture.sv] \
    [file join $repo_root sim tb_fft_debug_observer.sv] \
    [file join $repo_root sim tb_t510_fengine_top_smoke.sv] \
    [file join $repo_root sim tb_t510_fengine_board_top.sv] \
]

set tb_tops [list \
    tb_feng_ctrl_axi \
    tb_axi4_to_axil_bridge \
    tb_sync_fsm \
    tb_rfdc_adc_axis_adapter \
    tb_science_rate_selector \
    tb_science_stream_decimator \
    tb_axis_stream_duplicator \
    tb_time_packetizer \
    tb_pfb_channelizer \
    tb_spectral_packetizer \
    tb_udp_tx_arbiter \
    tb_axis_packet_fifo \
    tb_tx_route_selector \
    tb_udp_frame_builder \
    tb_axis512_register_slice \
    tb_time_axis512_ddr_ring \
    tb_time_udp_cmac512 \
    tb_spec_udp_cmac512 \
    tb_cmac_tx_source_mux \
    tb_stage25_cmac_live_tx \
    tb_t510_qsfp_test_frame_gen \
    tb_tx_payload_witness_capture \
    tb_dac_tx_witness_capture \
    tb_rfdc_axis_raw_witness_capture \
    tb_fft_debug_observer \
    tb_t510_fengine_top_smoke \
    tb_t510_fengine_board_top \
]

if {[llength [get_filesets -quiet sim_1]] == 0} {
    create_fileset -simset sim_1
}

foreach f $rtl_files {
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset sources_1 $f
    }
}

foreach f $sim_files {
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset sim_1 $f
    }
}

set header_file [file join $repo_root sim tb_common.svh]
if {[llength [get_files -quiet $header_file]] != 0} {
    set_property file_type {Verilog Header} [get_files $header_file]
}

set_property include_dirs [list [file join $repo_root sim]] [get_filesets sim_1]
set_property verilog_define {T510_SIM_FFT_MODEL} [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]

set failed 0

foreach tb $tb_tops {
    puts "INFO: Running $tb"
    catch {close_sim -force}
    set_property top $tb [get_filesets sim_1]
    update_compile_order -fileset sim_1

    set launch_rc [catch {launch_simulation -simset sim_1 -mode behavioral} launch_msg]
    if {$launch_rc != 0} {
        puts "ERROR: launch_simulation failed for $tb"
        puts $launch_msg
        incr failed
        catch {close_sim -force}
        continue
    }

    set run_rc [catch {run all} run_msg]
    if {$run_rc != 0} {
        puts "ERROR: run all failed for $tb"
        puts $run_msg
        incr failed
    } else {
        set sim_log [file join $repo_root "demo-ant.sim" "sim_1" "behav" "xsim" "simulate.log"]
        set check_failed 0
        if {[file exists $sim_log]} {
            set fh [open $sim_log r]
            set sim_text [read $fh]
            close $fh
            if {[string first "CHECK FAILED" $sim_text] >= 0} {
                set check_failed 1
            }
        }
        if {$check_failed} {
            puts "ERROR: $tb reported CHECK FAILED in simulate.log"
            incr failed
        } else {
            puts "INFO: $tb completed"
        }
    }
    catch {close_sim -force}
}

if {$failed != 0} {
    error "RTL simulation failed: $failed testbench(es) failed"
}

puts "INFO: All RTL simulations passed"
