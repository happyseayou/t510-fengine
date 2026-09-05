# Run only in the attached Vivado GUI, after the ordinary RTL regression.
# Caller must set ::stage36_fft_fixture to the directory prepared by
# t510_stage36_fft_precision.py. This script never launches synthesis.
set stage36_root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists ::stage36_fft_fixture]} {error "stage36_fft_fixture is required"}
set fixture [file normalize $::stage36_fft_fixture]
if {![file exists [file join $fixture input.mem]]} {error "missing input.mem"}
if {[info exists ::stage36_regression_state] && $::stage36_regression_state ne "complete"} {
    error "ordinary RTL regression has not passed"
}
catch {close_sim -force}
set ip [get_ips -quiet t510_fengine_xfft_4096_lane]
if {[llength $ip] != 1} {error "expected the production lane XFFT IP"}
generate_target simulation $ip
set fs sim_stage36_precision
if {[llength [get_filesets -quiet $fs]] == 0} {create_fileset -simset $fs}
current_fileset -simset [get_filesets $fs]
set_property SOURCE_SET sources_1 [get_filesets $fs]
set_property verilog_define {} [get_filesets $fs]
set tb [file join $stage36_root sim tb_stage36_xfft_precision.sv]
if {[llength [get_files -quiet -of_objects [get_filesets $fs] $tb]] == 0} {
    add_files -fileset $fs -norecurse $tb
}
set_property top tb_stage36_xfft_precision [get_filesets $fs]
set_property xsim.simulate.runtime 0ns [get_filesets $fs]
set_property -dict [list xsim.simulate.xsim.more_options [list \
    -testplusarg INPUT=[file join $fixture input.mem] \
    -testplusarg OUTPUT=[file join $fixture real_xfft_output.txt]]] [get_filesets $fs]
update_compile_order -fileset $fs
launch_simulation -simset $fs -mode behavioral
run all
set log_path [file join $stage36_root demo-ant.sim $fs behav xsim simulate.log]
# Vivado GUI also writes the simulation messages to its session log. Check
# a nonempty complete output independently; the Python checker verifies all bins.
set output_path [file join $fixture real_xfft_output.txt]
if {![file exists $output_path] || [file size $output_path] == 0} {
    error "real XFFT produced no numerical output"
}
if {[file exists $log_path]} {
    file copy -force $log_path [file join $fixture simulate.log]
    set fh [open $log_path r]; set msg [read $fh]; close $fh
    if {[regexp {(Fatal:|Error:|CHECK FAILED)} $msg]} {error "real XFFT simulation failed"}
}
catch {close_sim -force}
current_fileset -simset [get_filesets sim_1]
puts "STAGE36_REAL_XFFT_SIMULATION_FINISHED output=$output_path"
