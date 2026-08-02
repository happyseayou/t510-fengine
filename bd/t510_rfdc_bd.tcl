proc create_t510_rfdc_bd {} {
    if {[current_project -quiet] eq ""} {
        error "Open the Vivado project before sourcing bd/t510_rfdc_bd.tcl"
    }

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
    set mts_src [file join $repo_root rtl pl_mts_sync_clk.v]
    if {[llength [get_files -quiet $mts_src]] == 0} {
        add_files -norecurse -fileset sources_1 $mts_src
    }
    update_compile_order -fileset sources_1

    if {[llength [get_bd_designs -quiet t510_rfdc_bd]]} {
        close_bd_design [get_bd_designs t510_rfdc_bd]
    }
    if {[llength [get_files -quiet */t510_rfdc_bd.bd]]} {
        remove_files [get_files -quiet */t510_rfdc_bd.bd]
    }

    create_bd_design t510_rfdc_bd

    proc _externalize_intf {pin new_name} {
        set before [get_bd_intf_ports -quiet]
        make_bd_intf_pins_external $pin
        set after [get_bd_intf_ports -quiet]
        set created ""
        foreach port $after {
            if {[lsearch -exact $before $port] < 0} {
                set created $port
            }
        }
        if {$created eq ""} {
            set created [lindex [get_bd_intf_ports -quiet ${new_name}_0] 0]
        }
        if {$created eq ""} {
            error "Failed to externalize interface pin $pin as $new_name"
        }
        set_property name $new_name $created
    }

    proc _externalize_pin {pin new_name} {
        set before [get_bd_ports -quiet]
        make_bd_pins_external $pin
        set after [get_bd_ports -quiet]
        set created ""
        foreach port $after {
            if {[lsearch -exact $before $port] < 0} {
                set created $port
            }
        }
        if {$created eq ""} {
            set created [lindex [get_bd_ports -quiet ${new_name}_0] 0]
        }
        if {$created eq ""} {
            error "Failed to externalize pin $pin as $new_name"
        }
        set_property name $new_name $created
    }

    proc _pin_freq_or_default {pin default_freq} {
        set freq [get_property -quiet CONFIG.FREQ_HZ $pin]
        if {$freq eq ""} {
            return $default_freq
        }
        return $freq
    }

    proc _assert_bd_property {cell property expected} {
        set actual [get_property -quiet $property $cell]
        if {$actual eq ""} {
            error "Stage 33 RFDC invariant missing property $property on $cell"
        }
        if {[string is double -strict $actual] && [string is double -strict $expected]} {
            if {[expr {abs(double($actual) - double($expected))}] > 1.0e-6} {
                error "Stage 33 RFDC invariant failed: $property expected $expected, read $actual"
            }
        } elseif {![string equal -nocase $actual $expected]} {
            error "Stage 33 RFDC invariant failed: $property expected $expected, read $actual"
        }
    }

    set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.4 zynq_ultra_ps_e_0]
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "0"} $ps
    set_property -dict [list \
        CONFIG.PSU__USE__M_AXI_GP2 {1} \
        CONFIG.PSU__USE__S_AXI_GP0 {1} \
        CONFIG.PSU__SAXIGP0__DATA_WIDTH {128} \
        CONFIG.PSU__USE__IRQ0 {1} \
        CONFIG.PSU__GPIO_EMIO__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__GPIO_EMIO__PERIPHERAL__IO {1} \
        CONFIG.PSU__GPIO_EMIO_WIDTH {1} \
        CONFIG.PSU__GPIO0_MIO__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__GPIO0_MIO__IO {MIO 0 .. 25} \
        CONFIG.PSU__GPIO1_MIO__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__GPIO1_MIO__IO {MIO 26 .. 51} \
        CONFIG.PSU__I2C1__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__I2C1__PERIPHERAL__IO {EMIO} \
        CONFIG.PSU__SPI1__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__SPI1__PERIPHERAL__IO {MIO 32 .. 37} \
        CONFIG.PSU__SPI1__GRP_SS0__ENABLE {1} \
        CONFIG.PSU__SPI1__GRP_SS0__IO {MIO 35} \
        CONFIG.SPI1_BOARD_INTERFACE {custom} \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__SRCSEL {RPLL} \
    ] $ps

    set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps8_0_100M]
    set axi [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 ps8_0_axi_periph]
    set_property -dict [list CONFIG.NUM_MI {2} CONFIG.NUM_SI {1}] $axi

    set clk_wiz [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_0]
    set_property -dict [list \
        CONFIG.PRIM_IN_FREQ {160.000} \
        CONFIG.PRIM_SOURCE {No_buffer} \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {80.000} \
        CONFIG.CLKOUT2_USED {true} \
        CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {80.000} \
        CONFIG.RESET_TYPE {ACTIVE_LOW} \
    ] $clk_wiz

    set mts [create_bd_cell -type module -reference pl_mts_sync_clk pl_mts_sync_clk_0]
    set_property CONFIG.FREQ_HZ 160000000 [get_bd_pins pl_mts_sync_clk_0/pl_clk]

    set rfdc [create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter:2.6 usp_rf_data_converter_0]
    # DAC_Data_Type describes the analog converter output: Stage 33 uses a
    # real RF output.  The fine mixer mode below is I/Q->Real, so the PL side
    # remains four interleaved complex samples (I0,Q0,...,I3,Q3) per beat.
    set_property -dict [list \
        CONFIG.ADC0_Clock_Source {1} \
        CONFIG.ADC0_Multi_Tile_Sync {true} \
        CONFIG.ADC0_Sampling_Rate {3.8400} \
        CONFIG.ADC1_Clock_Dist {2} \
        CONFIG.ADC1_Multi_Tile_Sync {true} \
        CONFIG.ADC1_PLL_Enable {true} \
        CONFIG.ADC1_Refclk_Freq {160.000} \
        CONFIG.ADC1_Sampling_Rate {3.8400} \
        CONFIG.ADC2_Clock_Source {1} \
        CONFIG.ADC2_Multi_Tile_Sync {true} \
        CONFIG.ADC2_Sampling_Rate {3.8400} \
        CONFIG.ADC3_Clock_Source {1} \
        CONFIG.ADC3_Multi_Tile_Sync {true} \
        CONFIG.ADC3_Sampling_Rate {3.8400} \
        CONFIG.ADC_Data_Type00 {1} \
        CONFIG.ADC_Data_Type02 {1} \
        CONFIG.ADC_Data_Type10 {1} \
        CONFIG.ADC_Data_Type12 {1} \
        CONFIG.ADC_Data_Type20 {1} \
        CONFIG.ADC_Data_Type22 {1} \
        CONFIG.ADC_Data_Type30 {1} \
        CONFIG.ADC_Data_Type32 {1} \
        CONFIG.ADC_Data_Width00 {4} \
        CONFIG.ADC_Data_Width02 {4} \
        CONFIG.ADC_Data_Width10 {4} \
        CONFIG.ADC_Data_Width12 {4} \
        CONFIG.ADC_Data_Width20 {4} \
        CONFIG.ADC_Data_Width22 {4} \
        CONFIG.ADC_Data_Width30 {4} \
        CONFIG.ADC_Data_Width32 {4} \
        CONFIG.ADC_Decimation_Mode00 {12} \
        CONFIG.ADC_Decimation_Mode02 {12} \
        CONFIG.ADC_Decimation_Mode10 {12} \
        CONFIG.ADC_Decimation_Mode12 {12} \
        CONFIG.ADC_Decimation_Mode20 {12} \
        CONFIG.ADC_Decimation_Mode22 {12} \
        CONFIG.ADC_Decimation_Mode30 {12} \
        CONFIG.ADC_Decimation_Mode32 {12} \
        CONFIG.ADC_Dither00 {true} \
        CONFIG.ADC_Dither02 {true} \
        CONFIG.ADC_Dither10 {true} \
        CONFIG.ADC_Dither12 {true} \
        CONFIG.ADC_Dither20 {true} \
        CONFIG.ADC_Dither22 {true} \
        CONFIG.ADC_Dither30 {true} \
        CONFIG.ADC_Dither32 {true} \
        CONFIG.ADC_Mixer_Type00 {2} \
        CONFIG.ADC_Mixer_Type02 {2} \
        CONFIG.ADC_Mixer_Type10 {2} \
        CONFIG.ADC_Mixer_Type12 {2} \
        CONFIG.ADC_Mixer_Type20 {2} \
        CONFIG.ADC_Mixer_Type22 {2} \
        CONFIG.ADC_Mixer_Type30 {2} \
        CONFIG.ADC_Mixer_Type32 {2} \
        CONFIG.ADC_Mixer_Mode00 {0} \
        CONFIG.ADC_Mixer_Mode02 {0} \
        CONFIG.ADC_Mixer_Mode10 {0} \
        CONFIG.ADC_Mixer_Mode12 {0} \
        CONFIG.ADC_Mixer_Mode20 {0} \
        CONFIG.ADC_Mixer_Mode22 {0} \
        CONFIG.ADC_Mixer_Mode30 {0} \
        CONFIG.ADC_Mixer_Mode32 {0} \
        CONFIG.ADC_NCO_Freq00 {1.5} \
        CONFIG.ADC_NCO_Freq02 {1.5} \
        CONFIG.ADC_NCO_Freq10 {1.5} \
        CONFIG.ADC_NCO_Freq12 {1.5} \
        CONFIG.ADC_NCO_Freq20 {1.5} \
        CONFIG.ADC_NCO_Freq22 {1.5} \
        CONFIG.ADC_NCO_Freq30 {1.5} \
        CONFIG.ADC_NCO_Freq32 {1.5} \
        CONFIG.ADC_Slice00_Enable {true} \
        CONFIG.ADC_Slice02_Enable {true} \
        CONFIG.ADC_Slice10_Enable {true} \
        CONFIG.ADC_Slice12_Enable {true} \
        CONFIG.ADC_Slice20_Enable {true} \
        CONFIG.ADC_Slice22_Enable {true} \
        CONFIG.ADC_Slice30_Enable {true} \
        CONFIG.ADC_Slice32_Enable {true} \
        CONFIG.DAC0_Clock_Source {6} \
        CONFIG.DAC0_Multi_Tile_Sync {true} \
        CONFIG.DAC0_Sampling_Rate {3.8400} \
        CONFIG.DAC1_Multi_Tile_Sync {true} \
        CONFIG.DAC1_Sampling_Rate {3.8400} \
        CONFIG.DAC2_Clock_Dist {2} \
        CONFIG.DAC2_Multi_Tile_Sync {true} \
        CONFIG.DAC2_PLL_Enable {true} \
        CONFIG.DAC2_Refclk_Freq {160.000} \
        CONFIG.DAC2_Sampling_Rate {3.8400} \
        CONFIG.DAC3_Multi_Tile_Sync {true} \
        CONFIG.DAC3_Sampling_Rate {3.8400} \
        CONFIG.DAC_Data_Type00 {0} \
        CONFIG.DAC_Data_Type02 {0} \
        CONFIG.DAC_Data_Type10 {0} \
        CONFIG.DAC_Data_Type12 {0} \
        CONFIG.DAC_Data_Type20 {0} \
        CONFIG.DAC_Data_Type22 {0} \
        CONFIG.DAC_Data_Type30 {0} \
        CONFIG.DAC_Data_Type32 {0} \
        CONFIG.DAC_Data_Width00 {8} \
        CONFIG.DAC_Data_Width02 {8} \
        CONFIG.DAC_Data_Width10 {8} \
        CONFIG.DAC_Data_Width12 {8} \
        CONFIG.DAC_Data_Width20 {8} \
        CONFIG.DAC_Data_Width22 {8} \
        CONFIG.DAC_Data_Width30 {8} \
        CONFIG.DAC_Data_Width32 {8} \
        CONFIG.DAC_Interpolation_Mode00 {12} \
        CONFIG.DAC_Interpolation_Mode02 {12} \
        CONFIG.DAC_Interpolation_Mode10 {12} \
        CONFIG.DAC_Interpolation_Mode12 {12} \
        CONFIG.DAC_Interpolation_Mode20 {12} \
        CONFIG.DAC_Interpolation_Mode22 {12} \
        CONFIG.DAC_Interpolation_Mode30 {12} \
        CONFIG.DAC_Interpolation_Mode32 {12} \
        CONFIG.DAC_Mixer_Type00 {2} \
        CONFIG.DAC_Mixer_Type02 {2} \
        CONFIG.DAC_Mixer_Type10 {2} \
        CONFIG.DAC_Mixer_Type12 {2} \
        CONFIG.DAC_Mixer_Type20 {2} \
        CONFIG.DAC_Mixer_Type22 {2} \
        CONFIG.DAC_Mixer_Type30 {2} \
        CONFIG.DAC_Mixer_Type32 {2} \
        CONFIG.DAC_Mixer_Mode00 {0} \
        CONFIG.DAC_Mixer_Mode02 {0} \
        CONFIG.DAC_Mixer_Mode10 {0} \
        CONFIG.DAC_Mixer_Mode12 {0} \
        CONFIG.DAC_Mixer_Mode20 {0} \
        CONFIG.DAC_Mixer_Mode22 {0} \
        CONFIG.DAC_Mixer_Mode30 {0} \
        CONFIG.DAC_Mixer_Mode32 {0} \
        CONFIG.DAC_NCO_Freq00 {1.5} \
        CONFIG.DAC_NCO_Freq02 {1.5} \
        CONFIG.DAC_NCO_Freq10 {1.5} \
        CONFIG.DAC_NCO_Freq12 {1.5} \
        CONFIG.DAC_NCO_Freq20 {1.5} \
        CONFIG.DAC_NCO_Freq22 {1.5} \
        CONFIG.DAC_NCO_Freq30 {1.5} \
        CONFIG.DAC_NCO_Freq32 {1.5} \
        CONFIG.DAC_Slice00_Enable {true} \
        CONFIG.DAC_Slice02_Enable {true} \
        CONFIG.DAC_Slice10_Enable {true} \
        CONFIG.DAC_Slice12_Enable {true} \
        CONFIG.DAC_Slice20_Enable {true} \
        CONFIG.DAC_Slice22_Enable {true} \
        CONFIG.DAC_Slice30_Enable {true} \
        CONFIG.DAC_Slice32_Enable {true} \
    ] $rfdc

    foreach tile {0 1 2 3} {
        _assert_bd_property $rfdc CONFIG.ADC${tile}_Sampling_Rate 3.84
        _assert_bd_property $rfdc CONFIG.DAC${tile}_Sampling_Rate 3.84
        _assert_bd_property $rfdc CONFIG.ADC${tile}_Fabric_Freq 80.0
        _assert_bd_property $rfdc CONFIG.DAC${tile}_Fabric_Freq 80.0
    }
    _assert_bd_property $rfdc CONFIG.ADC1_Refclk_Freq 160.0
    _assert_bd_property $rfdc CONFIG.DAC2_Refclk_Freq 160.0
    # In RFDC 2.6 each of the eight user-selectable real ADC converters
    # expands to two derived R2C digital paths.  Vivado therefore reads all
    # 16 ADC Slice*_Enable properties as true and exposes 16 m*_axis ports,
    # while xrfdc still presents eight physical ADC blocks.  Check every
    # derived path so regenerated IP cannot silently change its inherited
    # factor/dither/mixer settings.  DAC remains eight C2R converter paths.
    foreach slice {00 01 02 03 10 11 12 13 20 21 22 23 30 31 32 33} {
        _assert_bd_property $rfdc CONFIG.ADC_Slice${slice}_Enable true
        _assert_bd_property $rfdc CONFIG.ADC_Data_Width${slice} 4
        _assert_bd_property $rfdc CONFIG.ADC_Data_Type${slice} 1
        _assert_bd_property $rfdc CONFIG.ADC_Mixer_Type${slice} 2
        _assert_bd_property $rfdc CONFIG.ADC_Mixer_Mode${slice} 0
        _assert_bd_property $rfdc CONFIG.ADC_Decimation_Mode${slice} 12
        _assert_bd_property $rfdc CONFIG.ADC_Dither${slice} true
    }
    foreach slice {00 02 10 12 20 22 30 32} {
        _assert_bd_property $rfdc CONFIG.DAC_Slice${slice}_Enable true
        _assert_bd_property $rfdc CONFIG.DAC_Data_Width${slice} 8
        _assert_bd_property $rfdc CONFIG.DAC_Data_Type${slice} 0
        _assert_bd_property $rfdc CONFIG.DAC_Mixer_Type${slice} 2
        _assert_bd_property $rfdc CONFIG.DAC_Mixer_Mode${slice} 0
        _assert_bd_property $rfdc CONFIG.DAC_Interpolation_Mode${slice} 12
    }
    foreach {kind expected_count} {ADC 16 DAC 8} {
        set enabled_count 0
        foreach property [list_property $rfdc] {
            if {[regexp "^CONFIG\\.${kind}_Slice[0-3][0-3]_Enable$" $property] &&
                [string equal -nocase [get_property -quiet $property $rfdc] true]} {
                incr enabled_count
            }
        }
        if {$enabled_count != $expected_count} {
            error "Stage 33 RFDC invariant failed: expected $expected_count enabled $kind digital paths, read $enabled_count"
        }
    }
    _assert_bd_property $clk_wiz CONFIG.PRIM_IN_FREQ 160.0
    _assert_bd_property $clk_wiz CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 80.0
    _assert_bd_property $clk_wiz CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 80.0

    connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] \
        [get_bd_pins zynq_ultra_ps_e_0/maxihpm0_lpd_aclk] \
        [get_bd_pins ps8_0_axi_periph/ACLK] \
        [get_bd_pins ps8_0_axi_periph/S00_ACLK] \
        [get_bd_pins ps8_0_axi_periph/M00_ACLK] \
        [get_bd_pins ps8_0_axi_periph/M01_ACLK] \
        [get_bd_pins rst_ps8_0_100M/slowest_sync_clk] \
        [get_bd_pins usp_rf_data_converter_0/s_axi_aclk]
    connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins rst_ps8_0_100M/ext_reset_in]
    connect_bd_net [get_bd_pins rst_ps8_0_100M/peripheral_aresetn] \
        [get_bd_pins ps8_0_axi_periph/ARESETN] \
        [get_bd_pins ps8_0_axi_periph/S00_ARESETN] \
        [get_bd_pins ps8_0_axi_periph/M00_ARESETN] \
        [get_bd_pins ps8_0_axi_periph/M01_ARESETN] \
        [get_bd_pins clk_wiz_0/resetn] \
        [get_bd_pins usp_rf_data_converter_0/s_axi_aresetn]

    connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_LPD] [get_bd_intf_pins ps8_0_axi_periph/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins ps8_0_axi_periph/M00_AXI] [get_bd_intf_pins usp_rf_data_converter_0/s_axi]
    _externalize_intf [get_bd_intf_pins ps8_0_axi_periph/M01_AXI] core_s_axi
    _externalize_intf [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HPC0_FPD] time_ddr_s_axi
    _externalize_pin [get_bd_pins zynq_ultra_ps_e_0/saxihpc0_fpd_aclk] time_ddr_s_axi_aclk
    set ctrl_freq_hz [_pin_freq_or_default [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] 100000000]

    create_bd_port -dir I -type clk -freq_hz 160000000 pl_clk_p
    create_bd_port -dir I -type clk -freq_hz 160000000 pl_clk_n
    create_bd_port -dir I pl_sys_ref_p
    create_bd_port -dir I pl_sys_ref_n
    connect_bd_net [get_bd_ports pl_clk_p] [get_bd_pins pl_mts_sync_clk_0/pl_clk_p]
    connect_bd_net [get_bd_ports pl_clk_n] [get_bd_pins pl_mts_sync_clk_0/pl_clk_n]
    connect_bd_net [get_bd_ports pl_sys_ref_p] [get_bd_pins pl_mts_sync_clk_0/pl_sys_ref_p]
    connect_bd_net [get_bd_ports pl_sys_ref_n] [get_bd_pins pl_mts_sync_clk_0/pl_sys_ref_n]
    # Stage 33: RFDC ADC and DAC AXIS both run at 80 MHz.  The existing data
    # widths represent four complex samples per beat, so the RFDC/PL complex
    # rate is 320 MS/s while the 1024-bit ADC aggregate and 128-bit DAC ports
    # remain unchanged.
    # PS pl_clk0 stays on AXI/control and RFDC s_axi only.
    connect_bd_net [get_bd_pins pl_mts_sync_clk_0/pl_clk] [get_bd_pins clk_wiz_0/clk_in1]
    connect_bd_net [get_bd_pins pl_mts_sync_clk_0/user_sysref_adc] [get_bd_pins usp_rf_data_converter_0/user_sysref_adc]
    connect_bd_net [get_bd_pins pl_mts_sync_clk_0/user_sysref_dac] [get_bd_pins usp_rf_data_converter_0/user_sysref_dac]
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] \
        [get_bd_pins usp_rf_data_converter_0/m0_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/m1_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/m2_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/m3_axis_aclk]
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] \
        [get_bd_pins usp_rf_data_converter_0/s0_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/s1_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/s2_axis_aclk] \
        [get_bd_pins usp_rf_data_converter_0/s3_axis_aclk]
    connect_bd_net [get_bd_pins clk_wiz_0/locked] \
        [get_bd_pins usp_rf_data_converter_0/m0_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/m1_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/m2_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/m3_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/s0_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/s1_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/s2_axis_aresetn] \
        [get_bd_pins usp_rf_data_converter_0/s3_axis_aresetn]
    set adc_axis_freq_hz [_pin_freq_or_default [get_bd_pins clk_wiz_0/clk_out1] 80000000]
    set dac_axis_freq_hz [_pin_freq_or_default [get_bd_pins clk_wiz_0/clk_out2] 80000000]
    create_bd_port -dir O -type clk adc_m_axis_clk
    create_bd_port -dir O -type clk dac_s_axis_clk
    create_bd_port -dir O -type clk ctrl_clk
    create_bd_port -dir O data_rst_n
    create_bd_port -dir O ctrl_rst_n
    set_property CONFIG.FREQ_HZ $adc_axis_freq_hz [get_bd_ports adc_m_axis_clk]
    set_property CONFIG.FREQ_HZ $dac_axis_freq_hz [get_bd_ports dac_s_axis_clk]
    set_property CONFIG.FREQ_HZ $ctrl_freq_hz [get_bd_ports ctrl_clk]
    set_property CONFIG.FREQ_HZ 322265625 [get_bd_ports time_ddr_s_axi_aclk]
    set_property CONFIG.ASSOCIATED_BUSIF {m00_axis:m01_axis:m02_axis:m03_axis:m10_axis:m11_axis:m12_axis:m13_axis:m20_axis:m21_axis:m22_axis:m23_axis:m30_axis:m31_axis:m32_axis:m33_axis} [get_bd_ports adc_m_axis_clk]
    set_property CONFIG.ASSOCIATED_BUSIF {s00_axis:s02_axis:s10_axis:s12_axis:s20_axis:s22_axis:s30_axis:s32_axis} [get_bd_ports dac_s_axis_clk]
    set_property CONFIG.ASSOCIATED_BUSIF {core_s_axi} [get_bd_ports ctrl_clk]
    set_property CONFIG.ASSOCIATED_BUSIF {time_ddr_s_axi} [get_bd_ports time_ddr_s_axi_aclk]
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_ports adc_m_axis_clk]
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] [get_bd_ports dac_s_axis_clk]
    connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_ports ctrl_clk]
    connect_bd_net [get_bd_pins clk_wiz_0/locked] [get_bd_ports data_rst_n]
    connect_bd_net [get_bd_pins rst_ps8_0_100M/peripheral_aresetn] [get_bd_ports ctrl_rst_n]

    _externalize_intf [get_bd_intf_pins zynq_ultra_ps_e_0/GPIO_0] emio
    _externalize_intf [get_bd_intf_pins zynq_ultra_ps_e_0/IIC_1] iic

    foreach intf {
        adc1_clk dac2_clk sysref_in
        vin0_01 vin0_23 vin1_01 vin1_23 vin2_01 vin2_23 vin3_01 vin3_23
        vout00 vout02 vout10 vout12 vout20 vout22 vout30 vout32
        m00_axis m01_axis m02_axis m03_axis m10_axis m11_axis m12_axis m13_axis
        m20_axis m21_axis m22_axis m23_axis m30_axis m31_axis m32_axis m33_axis
        s00_axis s02_axis s10_axis s12_axis s20_axis s22_axis s30_axis s32_axis
    } {
        _externalize_intf [get_bd_intf_pins usp_rf_data_converter_0/$intf] $intf
        if {$intf eq "adc1_clk" || $intf eq "dac2_clk"} {
            # Both enabled ADC/DAC clock-distribution roots use the stable
            # 160 MHz LMK reference. Keep the external
            # interface metadata aligned with the RFDC PLL configuration.
            set_property CONFIG.FREQ_HZ 160000000 [get_bd_intf_ports $intf]
        } elseif {[regexp {^m[0-9][0-9]_axis$} $intf]} {
            set_property CONFIG.FREQ_HZ $adc_axis_freq_hz [get_bd_intf_ports $intf]
        } elseif {[regexp {^s[0-9][0-9]_axis$} $intf]} {
            set_property CONFIG.FREQ_HZ $dac_axis_freq_hz [get_bd_intf_ports $intf]
        }
    }
    _assert_bd_property [get_bd_ports adc_m_axis_clk] CONFIG.FREQ_HZ 80000000
    _assert_bd_property [get_bd_ports dac_s_axis_clk] CONFIG.FREQ_HZ 80000000
    foreach intf {
        m00_axis m01_axis m02_axis m03_axis m10_axis m11_axis m12_axis m13_axis
        m20_axis m21_axis m22_axis m23_axis m30_axis m31_axis m32_axis m33_axis
    } {
        _assert_bd_property [get_bd_intf_ports $intf] CONFIG.FREQ_HZ 80000000
    }
    foreach intf {s00_axis s02_axis s10_axis s12_axis s20_axis s22_axis s30_axis s32_axis} {
        _assert_bd_property [get_bd_intf_ports $intf] CONFIG.FREQ_HZ 80000000
    }
    assign_bd_address
    set core_seg [lindex [get_bd_addr_segs -quiet zynq_ultra_ps_e_0/Data/SEG_core_s_axi_Reg] 0]
    set rfdc_seg [lindex [get_bd_addr_segs -quiet zynq_ultra_ps_e_0/Data/SEG_usp_rf_data_converter_0_Reg] 0]
    if {$core_seg ne ""} {
        set_property OFFSET 0x80080000 $core_seg
    }
    if {$rfdc_seg ne ""} {
        set_property OFFSET 0x80000000 $rfdc_seg
        set_property RANGE 256K $rfdc_seg
    }
    if {$core_seg ne ""} {
        set_property OFFSET 0x80040000 $core_seg
        set_property RANGE 128K $core_seg
    }

    validate_bd_design
    save_bd_design
    make_wrapper -files [get_files [get_property FILE_NAME [current_bd_design]]] -top
    add_files -norecurse [file join [get_property DIRECTORY [current_project]] [get_property NAME [current_project]].gen sources_1 bd t510_rfdc_bd hdl t510_rfdc_bd_wrapper.v]
    update_compile_order -fileset sources_1
}

create_t510_rfdc_bd
