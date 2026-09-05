# Executed by impl_1's WRITE_BITSTREAM.TCL.PRE in the GUI-submitted run.
# Keep routed evidence and fail the run before writing an unqualified bitstream.
source [file join [file dirname [info script]] t510_timing_gate_common.tcl]
set timing_file [file normalize current_final_timing_summary.rpt]
set route_file [file normalize current_final_route_status.rpt]
set status_file [file normalize current_pre_bitstream_gate.txt]
set fh [open $status_file w]; puts $fh "RUNNING"; close $fh
if {[catch {
    report_timing_summary -max_paths 10 -report_unconstrained -file $timing_file
    report_route_status -file $route_file
    set fh [open $timing_file r]; set timing [read $fh]; close $fh
    set summary [::t510_timing_gate::parse_summary $timing]
    # Also consult exact tool slack rather than relying solely on report rounding.
    foreach delay {max min} {
        set bad [get_timing_paths -quiet -delay_type $delay -slack_lesser_than 0 -max_paths 1]
        if {[llength $bad]} {error "negative exact $delay slack: [get_property SLACK [lindex $bad 0]]"}
    }
    set fh [open $route_file r]; set route [read $fh]; close $fh
    if {![regexp {nets with routing errors[^:]*:\s*([0-9]+)} $route -> errors] || $errors != 0} {
        error "routing errors or missing route status"
    }
} detail]} {
    set fh [open $status_file w]; puts $fh "FAIL $detail"; close $fh
    error "T510_PRE_BITSTREAM_GATE_FAIL: $detail; reports preserved in [pwd]"
}
set fh [open $status_file w]; puts $fh "PASS $summary"; close $fh
puts "T510_PRE_BITSTREAM_GATE_PASS $summary"
