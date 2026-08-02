# Export a completed Stage 33 build from the current demo-ant project.
# T510_STAGE33_BUILD_DIR must be a new directory below build/stage33-vivado/.

if {![info exists ::env(T510_STAGE33_BUILD_DIR)] || $::env(T510_STAGE33_BUILD_DIR) eq ""} {
    error "T510_STAGE33_BUILD_DIR must name a new Stage 33 artifact directory"
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $script_dir ".."]]
set archive_root [file normalize [file join $repo_root build stage33-vivado]]
set build_dir [file normalize $::env(T510_STAGE33_BUILD_DIR)]
set build_id [file tail $build_dir]
set report_dir [file normalize [file join $repo_root reports vivado stage33 $build_id]]
set overlay_dir [file join $build_dir overlay]

if {[current_project -quiet] eq ""} {
    error "Stage 33 export requires the existing demo-ant project to be open"
}
set project_name [get_property NAME [current_project]]
set project_dir [file normalize [get_property DIRECTORY [current_project]]]
if {$project_name ne "demo-ant" || $project_dir ne $repo_root} {
    error "Stage 33 export only accepts the current demo-ant project at $repo_root"
}
if {![string match "${archive_root}/*" $build_dir] || $build_dir eq $archive_root} {
    error "T510_STAGE33_BUILD_DIR must be a child of $archive_root"
}
if {![regexp {^[A-Za-z0-9][A-Za-z0-9._-]*$} $build_id]} {
    error "Invalid Stage 33 build id: $build_id"
}
if {[file exists $build_dir] || [file exists $report_dir]} {
    error "Refusing to overwrite Stage 33 artifacts: $build_dir or $report_dir already exists"
}

set source_defines [get_property verilog_define [get_filesets sources_1]]
if {[llength $source_defines] != 0} {
    error "Stage 33 current RTL must export without build defines; found $source_defines"
}
set synth_status [get_property STATUS [get_runs synth_1]]
set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match "synth_design Complete*" $synth_status]} {
    error "Stage 33 synthesis is incomplete: $synth_status"
}
if {![string match "write_bitstream Complete*" $impl_status]} {
    error "Stage 33 implementation/bitstream is incomplete: $impl_status"
}

file mkdir $overlay_dir $report_dir
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_dir timing_summary.rpt]
report_route_status -file [file join $report_dir route_status.rpt]
report_drc -file [file join $report_dir drc.rpt]
report_methodology -file [file join $report_dir methodology.rpt]
report_utilization -hierarchical -file [file join $report_dir utilization_hierarchical.rpt]
report_clock_utilization -file [file join $report_dir clock_utilization.rpt]
write_checkpoint -force [file join $report_dir t510_fengine_board_top_routed.dcp]

set setup_paths [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1]
set hold_paths [get_timing_paths -quiet -delay_type min -max_paths 1 -nworst 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {
    error "Stage 33 timing gate could not obtain setup and hold paths"
}
set wns [get_property SLACK [lindex $setup_paths 0]]
set whs [get_property SLACK [lindex $hold_paths 0]]
if {$wns < 0.0 || $whs < 0.0} {
    error "Stage 33 timing failed: WNS=$wns WHS=$whs"
}
foreach violation [get_drc_violations -quiet] {
    set severity [string toupper [get_property SEVERITY $violation]]
    if {$severity eq "ERROR" || $severity eq "CRITICAL WARNING"} {
        error "Stage 33 DRC failed: [get_property ID $violation] $severity"
    }
}

set bd_file [get_files -quiet */t510_rfdc_bd.bd]
if {[llength $bd_file] != 1} {
    error "Stage 33 export expected one block design, found $bd_file"
}
generate_target all [lindex $bd_file 0]
open_bd_design [lindex $bd_file 0]
validate_bd_design
write_bd_tcl -force [file join $overlay_dir t510_fengine.tcl]

set top_name [get_property TOP [get_filesets sources_1]]
set bit_src [file join [get_property DIRECTORY [get_runs impl_1]] "${top_name}.bit"]
if {![file exists $bit_src]} {
    error "Stage 33 bitstream not found at $bit_src"
}
file copy $bit_src [file join $overlay_dir t510_fengine.bit]

set hwh_candidates [get_files -quiet */t510_rfdc_bd.hwh]
if {[llength $hwh_candidates] != 1} {
    error "Stage 33 expected one generated HWH, found $hwh_candidates"
}
file copy [lindex $hwh_candidates 0] [file join $overlay_dir t510_fengine.hwh]

set rfdc_xci_candidates [get_files -quiet -all *usp_rf_data_converter*.xci]
if {[llength $rfdc_xci_candidates] != 1} {
    error "Stage 33 expected one active RFDC XCI, found $rfdc_xci_candidates"
}
file copy [lindex $rfdc_xci_candidates 0] [file join $overlay_dir t510_fengine_rfdc.xci]

set synth_log [file join [get_property DIRECTORY [get_runs synth_1]] runme.log]
set impl_log [file join [get_property DIRECTORY [get_runs impl_1]] runme.log]
if {[file exists $synth_log]} {
    file copy $synth_log [file join $report_dir synthesis_run.log]
}
if {[file exists $impl_log]} {
    file copy $impl_log [file join $report_dir implementation_run.log]
}

set manifest [file join $overlay_dir t510_fengine.manifest.txt]
set fh [open $manifest w]
puts $fh "stage=33"
puts $fh "core_version=0x00010033"
puts $fh "project=$project_name"
puts $fh "project_dir=$project_dir"
puts $fh "part=[get_property PART [current_project]]"
puts $fh "top=$top_name"
puts $fh "source_defines=$source_defines"
puts $fh "bit=[file join $overlay_dir t510_fengine.bit]"
puts $fh "hwh=[file join $overlay_dir t510_fengine.hwh]"
puts $fh "bd_tcl=[file join $overlay_dir t510_fengine.tcl]"
puts $fh "rfdc_xci=[file join $overlay_dir t510_fengine_rfdc.xci]"
puts $fh "report_dir=$report_dir"
puts $fh "wns=$wns"
puts $fh "whs=$whs"
close $fh

set summary [file join $report_dir build_summary.txt]
set fh [open $summary w]
puts $fh "stage=33"
puts $fh "core_version=0x00010033"
puts $fh "project=$project_name"
puts $fh "project_dir=$project_dir"
puts $fh "part=[get_property PART [current_project]]"
puts $fh "top=$top_name"
puts $fh "synth_status=$synth_status"
puts $fh "impl_status=$impl_status"
puts $fh "wns=$wns"
puts $fh "whs=$whs"
close $fh

puts "STAGE33_CURRENT_PROJECT_EXPORT_PASS build_dir=$build_dir report_dir=$report_dir WNS=$wns WHS=$whs"
