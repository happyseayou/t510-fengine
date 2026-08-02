# Prepare the current Stage 33 implementation in the already-open demo-ant project.
# This script never creates a second project and never launches a run.

set script_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $script_dir ".."]]

if {[current_project -quiet] eq ""} {
    error "Stage 33 requires the existing demo-ant project to be open"
}
set project_name [get_property NAME [current_project]]
set project_dir [file normalize [get_property DIRECTORY [current_project]]]
set project_part [get_property PART [current_project]]
if {$project_name ne "demo-ant" || $project_dir ne $repo_root} {
    error "Stage 33 must update demo-ant at $repo_root; open project is $project_name at $project_dir"
}
if {$project_part ne "xczu47dr-ffve1156-2-i"} {
    error "Stage 33 project part mismatch: expected xczu47dr-ffve1156-2-i, read $project_part"
}
foreach run_name {synth_1 impl_1} {
    set run [get_runs -quiet $run_name]
    if {[llength $run] != 1} {
        error "Stage 33 requires existing run $run_name"
    }
    set status [get_property STATUS $run]
    if {[string match -nocase "*running*" $status]} {
        error "Refusing to change the source set while $run_name is running: $status"
    }
}

source [file join $repo_root scripts setup_project.tcl]

# Recreate the one generated RFDC design from its authoritative Tcl source.
if {[llength [get_bd_designs -quiet t510_rfdc_bd]] != 0} {
    close_bd_design [get_bd_designs t510_rfdc_bd]
}
foreach old_file [concat \
    [get_files -quiet -all */t510_rfdc_bd.bd] \
    [get_files -quiet -all */t510_rfdc_bd_wrapper.v] \
] {
    remove_files $old_file
}
foreach generated_dir [list \
    [file join $repo_root demo-ant.srcs sources_1 bd t510_rfdc_bd] \
    [file join $repo_root demo-ant.gen sources_1 bd t510_rfdc_bd] \
] {
    if {[file exists $generated_dir]} {
        file delete -force $generated_dir
    }
}
source [file join $repo_root bd t510_rfdc_bd.tcl]

set source_defines [get_property verilog_define [get_filesets sources_1]]
if {[llength $source_defines] != 0} {
    error "Stage 33 current RTL must not depend on build defines; found $source_defines"
}
set sim_defines [get_property verilog_define [get_filesets sim_1]]
if {$sim_defines ne "T510_SIM_FFT_MODEL" && $sim_defines ne {T510_SIM_FFT_MODEL}} {
    error "Stage 33 simulation must use only T510_SIM_FFT_MODEL; found $sim_defines"
}
set bd_file [get_files -quiet -all */t510_rfdc_bd.bd]
if {[llength $bd_file] != 1} {
    error "Stage 33 expected exactly one t510_rfdc_bd.bd, found $bd_file"
}
open_bd_design [lindex $bd_file 0]
validate_bd_design
save_bd_design
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1

puts "STAGE33_CURRENT_PROJECT_PREPARED project=$project_name directory=$project_dir part=$project_part"
puts "STAGE33_CURRENT_PROJECT_DEFINES source=$source_defines sim=$sim_defines"
