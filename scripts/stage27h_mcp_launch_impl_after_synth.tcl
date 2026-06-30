source [file join [file dirname [file normalize [info script]]] stage27h_mcp_timing_common.tcl]

stage27h_prepare_project
set runs [stage27h_config_timing_runs]
set synth_run [lindex $runs 0]
set impl_run [lindex $runs 1]

set synth_status [get_property STATUS $synth_run]
puts "STAGE27H_TIMING_CLOSURE: SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Stage 27h timing closure synthesis did not complete."
}

open_run $synth_run
report_utilization -file $synth_util_rpt
report_timing_summary -delay_type max -file $synth_timing_rpt
close_design

puts "STAGE27H_TIMING_CLOSURE: MCP launch implementation through route_design"
reset_run $impl_run
catch {reset_property INCREMENTAL_CHECKPOINT $impl_run}
launch_runs $impl_run -to_step route_design -jobs 8
puts "STAGE27H_TIMING_CLOSURE: MCP_IMPL_LAUNCHED"
