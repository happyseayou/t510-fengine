# Arm the complete current-project Vivado build chain without blocking the GUI.
#
# Fresh build:
#   source scripts/t510_arm_current_project_build_chain.tcl
#   ::t510_build_chain::start 8
#
# Attach the implementation/bitstream continuation to an already-running synth:
#   source scripts/t510_arm_current_project_build_chain.tcl
#   ::t510_build_chain::attach 8

namespace eval ::t510_build_chain {
    variable armed 0
    variable jobs 8
    variable poll_ms 10000
}

proc ::t510_build_chain::log {message} {
    puts "T510_BUILD_CHAIN $message"
    flush stdout
}

proc ::t510_build_chain::failed_status {status} {
    return [regexp -nocase {(error|fail|cancel)} $status]
}

proc ::t510_build_chain::launch_impl_to_bitstream {} {
    variable armed
    variable jobs

    set impl_run [get_runs -quiet impl_1]
    if {[llength $impl_run] != 1} {
        set armed 0
        log "ERROR missing impl_1; chain stopped"
        return
    }

    if {[catch {
        reset_run impl_1
        launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    } detail]} {
        set armed 0
        log "ERROR could not launch impl_1 through write_bitstream: $detail"
        return
    }

    set armed 0
    log "ARMED impl_1 through write_bitstream jobs=$jobs"
}

proc ::t510_build_chain::poll_synth {} {
    variable armed
    variable poll_ms

    if {!$armed} {
        return
    }

    set synth_run [get_runs -quiet synth_1]
    if {[llength $synth_run] != 1} {
        set armed 0
        log "ERROR missing synth_1; chain stopped"
        return
    }

    set status [get_property STATUS $synth_run]
    if {[string match "synth_design Complete*" $status]} {
        log "synth_1 complete; launching implementation through write_bitstream"
        launch_impl_to_bitstream
        return
    }
    if {[failed_status $status]} {
        set armed 0
        log "ERROR synth_1 status='$status'; chain stopped"
        return
    }

    after $poll_ms [namespace code poll_synth]
}

proc ::t510_build_chain::require_project {} {
    if {[current_project -quiet] eq ""} {
        error "no Vivado project is open"
    }
    if {[llength [get_runs -quiet synth_1]] != 1} {
        error "current project has no synth_1 run"
    }
    if {[llength [get_runs -quiet impl_1]] != 1} {
        error "current project has no impl_1 run"
    }
}

proc ::t510_build_chain::attach {{jobs_arg 8}} {
    variable armed
    variable jobs

    require_project
    if {$armed} {
        log "already armed"
        return
    }
    if {![string is integer -strict $jobs_arg] || $jobs_arg < 1} {
        error "jobs must be a positive integer"
    }

    set status [get_property STATUS [get_runs synth_1]]
    if {![string match "Running synth_design*" $status] &&
        ![string match "synth_design Complete*" $status]} {
        error "attach requires running or completed synth_1, got '$status'"
    }

    set jobs $jobs_arg
    set armed 1
    log "ATTACHED synth_1 status='$status'; automatic impl_1/write_bitstream continuation armed"
    after 0 [namespace code poll_synth]
}

proc ::t510_build_chain::start {{jobs_arg 8}} {
    variable armed
    variable jobs

    require_project
    if {$armed} {
        log "already armed"
        return
    }
    if {![string is integer -strict $jobs_arg] || $jobs_arg < 1} {
        error "jobs must be a positive integer"
    }

    set jobs $jobs_arg
    reset_run impl_1
    reset_run synth_1
    launch_runs synth_1 -jobs $jobs
    set armed 1
    log "ARMED synth_1 -> impl_1 -> write_bitstream jobs=$jobs"
    after 0 [namespace code poll_synth]
}
