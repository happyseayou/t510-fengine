set origin_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $origin_dir ".."]]

set rtl_files [list \
    [file join $repo_root rtl pl_mts_sync_clk.v] \
    [file join $repo_root rtl pl_mts_axis_recapture.v] \
    [file join $repo_root rtl sync_fsm.sv] \
    [file join $repo_root rtl station_sync_scheduler.sv] \
    [file join $repo_root rtl axis_stream_duplicator.sv] \
    [file join $repo_root rtl science_decim2_halfband_aa.sv] \
    [file join $repo_root rtl science_rate_selector.sv] \
    [file join $repo_root rtl requantizer.sv] \
    [file join $repo_root rtl monitor_counters.sv] \
    [file join $repo_root rtl adc_interleave_spur_corrector.sv] \
    [file join $repo_root rtl adc_interleave_sine_q17_1024.mem] \
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
]

set sim_files [list \
    [file join $repo_root sim tb_adc_interleave_spur_corrector.sv] \
    [file join $repo_root sim tb_pl_mts_sync_clk.sv] \
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

set tb_tops [list \
    tb_adc_interleave_spur_corrector \
    tb_pl_mts_sync_clk \
    tb_feng_ctrl_axi \
    tb_axi4_to_axil_bridge \
    tb_sync_fsm \
    tb_station_sync_scheduler \
    tb_t510_dac_loopback_source \
    tb_rfdc_adc_axis_adapter \
    tb_science_rate_selector \
    tb_rfdc_fullrate_preview \
    tb_axis_stream_duplicator \
    tb_pfb_channelizer \
    tb_axis512_register_slice \
    tb_time_axis512_ddr_ring \
    tb_time_udp_cmac512 \
    tb_spec_udp_cmac512 \
    tb_cmac_tx_source_mux \
    tb_t510_cmac_pause \
    tb_t510_fengine_top_smoke \
]

if {[llength [get_filesets -quiet sim_1]] == 0} {
    create_fileset -simset sim_1
}
foreach file [concat $rtl_files $sim_files] {
    if {![file exists $file]} {
        error "Current XSim list contains a missing file: $file"
    }
}
foreach file $rtl_files {
    if {[llength [get_files -quiet $file]] == 0} {
        add_files -norecurse -fileset sources_1 $file
    }
}
set spur_sine_mem [file join $repo_root rtl adc_interleave_sine_q17_1024.mem]
set_property file_type {Memory File} [get_files $spur_sine_mem]
foreach file $sim_files {
    if {[llength [get_files -quiet $file]] == 0} {
        add_files -norecurse -fileset sim_1 $file
    }
}

set header_file [file join $repo_root sim tb_common.svh]
set_property file_type {Verilog Header} [get_files $header_file]
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
        set sim_log [file join $repo_root demo-ant.sim sim_1 behav xsim simulate.log]
        set check_failed 0
        if {[file exists $sim_log]} {
            set handle [open $sim_log r]
            set sim_text [read $handle]
            close $handle
            if {[string first "CHECK FAILED" $sim_text] >= 0 ||
                [string first "Error:" $sim_text] >= 0 ||
                [string first "Fatal:" $sim_text] >= 0} {
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
    error "RTL simulation failed: $failed current testbench(es) failed"
}
puts "INFO: All current RTL simulations passed"
