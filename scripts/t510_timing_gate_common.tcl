# Pure report parser shared by the Vivado pre-bitstream hook and its tests.
namespace eval ::t510_timing_gate {}
proc ::t510_timing_gate::parse_summary {report} {
    set in_summary 0
    foreach line [split $report \n] {
        if {[regexp {^\s*WNS\(ns\)\s+TNS\(ns\)\s+TNS Failing Endpoints} $line]} {
            set in_summary 1
            continue
        }
        if {!$in_summary || [string trim $line] eq "" || [regexp {^\s*-+\s+-+} $line]} {continue}
        set fields [regexp -all -inline {\S+} $line]
        if {[llength $fields] != 12} {error "malformed design timing summary"}
        foreach value $fields {
            if {![regexp {^-?[0-9]+(?:\.[0-9]+)?$} $value]} {error "non-numeric timing summary"}
        }
        set result [dict create WNS [lindex $fields 0] TNS [lindex $fields 1] \
            setup_failing [lindex $fields 2] WHS [lindex $fields 4] \
            hold_failing [lindex $fields 6] WPWS [lindex $fields 8] \
            pulse_width_failing [lindex $fields 10]]
        # Counts also catch sub-ps failures printed as -0.000 ns.
        foreach key {WNS WHS WPWS} {
            if {[dict get $result $key] < 0} {error "timing gate failed: $key=[dict get $result $key]; $result"}
        }
        foreach key {setup_failing hold_failing pulse_width_failing} {
            if {[dict get $result $key] != 0} {error "timing gate failed: $key=[dict get $result $key]; $result"}
        }
        return $result
    }
    error "design timing summary header not found"
}
