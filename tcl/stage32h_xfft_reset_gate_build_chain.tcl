namespace eval ::stage32h_xfft_reset_gate_build {
    variable synth_run synth_1
    variable impl_run impl_1
    variable poll_ms 10000
    variable armed 0
}

proc ::stage32h_xfft_reset_gate_build::poll_synth {} {
    variable synth_run
    variable impl_run
    variable poll_ms
    variable armed

    if {!$armed} {
        return
    }

    set synth_status [get_property STATUS [get_runs $synth_run]]
    puts "STAGE32H_XFFT_RESET_GATE_BUILD: synth status=$synth_status"

    if {[string match "*Complete*" $synth_status]} {
        set armed 0
        launch_runs $impl_run -to_step write_bitstream -jobs 8
        puts "STAGE32H_XFFT_RESET_GATE_BUILD: implementation through write_bitstream launched"
        return
    }

    set upper_status [string toupper $synth_status]
    if {[string match "*ERROR*" $upper_status] ||
        [string match "*FAIL*" $upper_status]} {
        set armed 0
        puts "STAGE32H_XFFT_RESET_GATE_BUILD: synthesis failed; implementation not launched"
        return
    }

    after $poll_ms ::stage32h_xfft_reset_gate_build::poll_synth
}

set synth_status [get_property STATUS [get_runs $::stage32h_xfft_reset_gate_build::synth_run]]
set impl_status [get_property STATUS [get_runs $::stage32h_xfft_reset_gate_build::impl_run]]
if {[string match "*Running*" $synth_status] || [string match "*Running*" $impl_status]} {
    error "A Vivado run is already active: synth='$synth_status', impl='$impl_status'"
}

reset_run $::stage32h_xfft_reset_gate_build::impl_run
reset_run $::stage32h_xfft_reset_gate_build::synth_run
launch_runs $::stage32h_xfft_reset_gate_build::synth_run -jobs 8

set ::stage32h_xfft_reset_gate_build::armed 1
after 1000 ::stage32h_xfft_reset_gate_build::poll_synth
puts "STAGE32H_XFFT_RESET_GATE_BUILD: armed non-blocking synthesis -> implementation -> write_bitstream chain"
