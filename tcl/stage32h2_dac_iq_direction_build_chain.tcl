namespace eval ::stage32h2_dac_iq_direction_build {
    variable synth_run synth_1
    variable impl_run impl_1
    variable poll_ms 10000
    variable armed 0
}

set stage32h2_bd [lindex [get_files -quiet */t510_rfdc_bd.bd] 0]
if {$stage32h2_bd eq ""} {
    error "STAGE32H2_DAC_IQ_BUILD: t510_rfdc_bd.bd is absent"
}
open_bd_design $stage32h2_bd
set stage32h2_rfdc [lindex [get_bd_cells -quiet usp_rf_data_converter_0] 0]
if {$stage32h2_rfdc eq ""} {
    error "STAGE32H2_DAC_IQ_BUILD: RFDC BD cell is absent"
}
foreach stage32h2_path {00 02 10 12 20 22 30 32} {
    set stage32h2_type [get_property CONFIG.DAC_Data_Type${stage32h2_path} $stage32h2_rfdc]
    set stage32h2_mixer_type [get_property CONFIG.DAC_Mixer_Type${stage32h2_path} $stage32h2_rfdc]
    set stage32h2_mixer_mode [get_property CONFIG.DAC_Mixer_Mode${stage32h2_path} $stage32h2_rfdc]
    set stage32h2_width [get_property CONFIG.DAC_Data_Width${stage32h2_path} $stage32h2_rfdc]
    if {$stage32h2_type ne "0"} {
        error "STAGE32H2_DAC_IQ_BUILD: DAC path ${stage32h2_path} analog output is not Real (type=$stage32h2_type)"
    }
    if {$stage32h2_mixer_type ne "2" || $stage32h2_mixer_mode ne "0"} {
        error "STAGE32H2_DAC_IQ_BUILD: DAC path ${stage32h2_path} is not Fine I/Q-to-Real (mixer_type=$stage32h2_mixer_type mixer_mode=$stage32h2_mixer_mode)"
    }
    if {$stage32h2_width ne "8"} {
        error "STAGE32H2_DAC_IQ_BUILD: DAC path ${stage32h2_path} width changed (width=$stage32h2_width)"
    }
    set stage32h2_axis s${stage32h2_path}_axis
    if {[llength [get_bd_intf_ports -quiet $stage32h2_axis]] != 1 ||
        [llength [get_bd_intf_pins -quiet usp_rf_data_converter_0/$stage32h2_axis]] != 1} {
        error "STAGE32H2_DAC_IQ_BUILD: DAC AXIS ${stage32h2_axis} is absent"
    }
    if {[llength [get_bd_intf_nets -quiet -of_objects [get_bd_intf_ports $stage32h2_axis]]] != 1 ||
        [llength [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins usp_rf_data_converter_0/$stage32h2_axis]]] != 1} {
        error "STAGE32H2_DAC_IQ_BUILD: DAC AXIS ${stage32h2_axis} is not fully connected"
    }
}
puts "STAGE32H2_DAC_IQ_BUILD: RFDC DAC I/Q-to-Real contract PASS (8 connected paths, 8 x 16-bit words, 128-bit AXIS)"

proc ::stage32h2_dac_iq_direction_build::poll_synth {} {
    variable synth_run
    variable impl_run
    variable poll_ms
    variable armed

    if {!$armed} {
        return
    }

    set synth_status [get_property STATUS [get_runs $synth_run]]
    puts "STAGE32H2_DAC_IQ_BUILD: synth status=$synth_status"

    if {[string match "*Complete*" $synth_status]} {
        set armed 0
        launch_runs $impl_run -to_step write_bitstream -jobs 8
        puts "STAGE32H2_DAC_IQ_BUILD: implementation through write_bitstream launched"
        return
    }

    set upper_status [string toupper $synth_status]
    if {[string match "*ERROR*" $upper_status] ||
        [string match "*FAIL*" $upper_status]} {
        set armed 0
        puts "STAGE32H2_DAC_IQ_BUILD: synthesis failed; implementation not launched"
        return
    }

    after $poll_ms ::stage32h2_dac_iq_direction_build::poll_synth
}

set synth_status [get_property STATUS [get_runs $::stage32h2_dac_iq_direction_build::synth_run]]
set impl_status [get_property STATUS [get_runs $::stage32h2_dac_iq_direction_build::impl_run]]
if {[string match "*Running*" $synth_status] || [string match "*Running*" $impl_status]} {
    error "A Vivado run is already active: synth='$synth_status', impl='$impl_status'"
}

reset_run $::stage32h2_dac_iq_direction_build::impl_run
reset_run $::stage32h2_dac_iq_direction_build::synth_run
launch_runs $::stage32h2_dac_iq_direction_build::synth_run -jobs 8

set ::stage32h2_dac_iq_direction_build::armed 1
after 1000 ::stage32h2_dac_iq_direction_build::poll_synth
puts "STAGE32H2_DAC_IQ_BUILD: armed non-blocking synthesis -> implementation -> write_bitstream chain"
