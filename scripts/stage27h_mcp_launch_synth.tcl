source [file join [file dirname [file normalize [info script]]] stage27h_mcp_timing_common.tcl]

stage27h_prepare_project
stage27h_clear_timing_artifacts
set runs [stage27h_config_timing_runs]
set synth_run [lindex $runs 0]

puts "STAGE27H_TIMING_CLOSURE: MCP launch top synthesis"
reset_run $synth_run
launch_runs $synth_run -jobs 8
puts "STAGE27H_TIMING_CLOSURE: MCP_SYNTH_LAUNCHED"
