set repo_root [file normalize [file join [file dirname [info script]] ..]]
set out_dir [file join $repo_root reports board]
file mkdir $out_dir

open_project [file join $repo_root demo-ant.xpr]

set report_file [file join $out_dir stage24_cmac_license_audit.txt]
set fh [open $report_file w]

proc emit {fh text} {
    puts $fh $text
    puts $text
}

emit $fh "project=[current_project]"
emit $fh "part=[get_property PART [current_project]]"

set ip [get_ips -quiet t510_cmac_usplus_0]
if {[llength $ip] == 0} {
    emit $fh "cmac_ip_found=0"
    close $fh
    error "CMAC IP t510_cmac_usplus_0 was not found."
}

emit $fh "cmac_ip_found=1"
foreach prop {NAME IPDEF VLNV IP_NAME IP_VERSION IS_LOCKED IP_STATE GENERATE_SYNTH_CHECKPOINT CORE_CONTAINER} {
    if {[catch {set value [get_property $prop $ip]} err]} {
        emit $fh "$prop=<unavailable: $err>"
    } else {
        emit $fh "$prop=$value"
    }
}

set ip_status_file [file join $out_dir stage24_ip_status.rpt]
if {[catch {report_ip_status -file $ip_status_file} err]} {
    emit $fh "report_ip_status_error=$err"
} else {
    emit $fh "ip_status_report=$ip_status_file"
}

set prop_file [file join $out_dir stage24_cmac_ip_properties.rpt]
if {[catch {report_property -file $prop_file $ip} err]} {
    emit $fh "report_property_error=$err"
} else {
    emit $fh "ip_property_report=$prop_file"
}

emit $fh "license_related_help_begin"
if {[catch {help -quiet *license*} help_text]} {
    emit $fh "help_license_error=$help_text"
} else {
    emit $fh $help_text
}
emit $fh "license_related_help_end"

foreach cmd {
    {get_license}
    {get_licenses}
    {report_license}
} {
    set label [lindex $cmd 0]
    if {[catch {eval $cmd} result]} {
        emit $fh "${label}_error=$result"
    } else {
        emit $fh "${label}_ok=$result"
    }
}

set env_file [file join $out_dir stage24_environment.rpt]
if {[catch {report_environment -file $env_file} result]} {
    emit $fh "report_environment_error=$result"
} else {
    emit $fh "environment_report=$env_file"
}

close $fh
puts "INFO: wrote CMAC license audit to $report_file"
exit
