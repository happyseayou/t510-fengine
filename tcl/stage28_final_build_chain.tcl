namespace eval ::stage28_final_chain {
    variable synth_run synth_1
    variable impl_run impl_1
    variable report_dir [file normalize "/home/astrolab/demo-ant/reports/vivado/stage28_final_0x00010030_realtime_xfft"]
    variable poll_ms 10000
    variable armed 0
}

proc ::stage28_final_chain::write_state {name text} {
    variable report_dir
    file mkdir $report_dir
    set fh [open [file join $report_dir $name] w]
    puts $fh $text
    close $fh
}

proc ::stage28_final_chain::poll_synth {} {
    variable synth_run
    variable impl_run
    variable poll_ms
    variable armed

    if {!$armed} {
        return
    }
    set synth_status [get_property STATUS [get_runs $synth_run]]
    puts "STAGE28_FINAL_CHAIN: synth status=$synth_status"
    if {[string match "*Complete*" $synth_status]} {
        set armed 0
        set_property STEPS.WRITE_BITSTREAM.TCL.POST \
            /home/astrolab/demo-ant/tcl/stage28_final_post_bitstream.tcl \
            [get_runs $impl_run]
        reset_run $impl_run
        launch_runs $impl_run -to_step write_bitstream -jobs 8
        write_state build_chain_state.txt \
            "stage=implementation_and_bitstream\nsynth_status=$synth_status\nimpl_status=[get_property STATUS [get_runs $impl_run]]\npost_hook=[get_property STEPS.WRITE_BITSTREAM.TCL.POST [get_runs $impl_run]]"
        puts "STAGE28_FINAL_CHAIN: implementation through write_bitstream launched"
        return
    }
    if {[string match "*ERROR*" [string toupper $synth_status]] ||
        [string match "*FAIL*" [string toupper $synth_status]]} {
        set armed 0
        write_state build_chain_error.txt "synth_status=$synth_status"
        puts "STAGE28_FINAL_CHAIN: synthesis failed; implementation not launched"
        return
    }
    after $poll_ms ::stage28_final_chain::poll_synth
}

set ::stage28_final_chain::armed 1
::stage28_final_chain::write_state build_chain_state.txt \
    "stage=synthesis\nsynth_status=[get_property STATUS [get_runs $::stage28_final_chain::synth_run]]\npost_hook=[get_property STEPS.WRITE_BITSTREAM.TCL.POST [get_runs $::stage28_final_chain::impl_run]]"
after 0 ::stage28_final_chain::poll_synth
puts "STAGE28_FINAL_CHAIN: armed non-blocking synthesis -> implementation -> write_bitstream chain"
