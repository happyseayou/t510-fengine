# Export the completed current build from the existing demo-ant project.
# Generated artifacts are deliberately latest-only and are replaced on every export.

set script_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $script_dir ".."]]
set sysref_input_delay_min_ns "2.879166"
set sysref_input_delay_max_ns "3.120834"
set sysref_selected_phase_ps "3000.0"
set sysref_phase_error_envelope_ps "120.834"
set sysref_10m_profile_id "160m_10m_request_clkin2_sdclkout3_phase_15"
set sysref_10m_profile_sha256 "2dee613b9c267ffc452a904f22f19d69009187b33a080c57282cc93def8dffc6"
set sysref_5m_profile_id "160m_5m_request_clkin2_sdclkout3_phase_15"
set sysref_5m_profile_sha256 "31eb4c56ec9bfacedab4a1246e2d43a601698fc8f785c32c10a56a23953b88d9"
set tics_manifest_sha256 "695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009"
set export_mode "diagnostic"
if {[info exists ::env(T510_STAGE34C2R_EXPORT_MODE)]} {
    set export_mode [string tolower [string trim $::env(T510_STAGE34C2R_EXPORT_MODE)]]
}
if {$export_mode eq "release"} {
    set build_dir [file normalize [file join $repo_root build vivado latest]]
    set expected_build_dir [file normalize [file join $repo_root build vivado latest]]
    set report_dir [file join $build_dir reports]
    set overlay_dir [file join $build_dir overlay]
    set release_label "latest"
} elseif {$export_mode eq "diagnostic" || $export_mode eq "candidate"} {
    # The attached Vivado GUI runs as the unprivileged board user.  Keep the
    # candidate below /run, but use that user's standard writable runtime
    # directory instead of attempting to create a root-owned /run child.
    if {[info exists ::env(XDG_RUNTIME_DIR)] && [string match "/run/*" $::env(XDG_RUNTIME_DIR)]} {
        set runtime_root [file normalize $::env(XDG_RUNTIME_DIR)]
    } else {
        set runtime_root [file normalize [file join /run user [exec id -u]]]
    }
    if {$export_mode eq "candidate"} {
        set build_dir [file normalize [file join $runtime_root t510-stage34c2r-v35-candidate]]
        set expected_build_dir [file normalize [file join $runtime_root t510-stage34c2r-v35-candidate]]
        set report_dir [file normalize [file join $repo_root build board latest evidence clock_sysref_causality final_candidate_bit]]
        set release_label "stage34c2r-final-candidate"
    } else {
        set build_dir [file normalize [file join $runtime_root t510-stage34c2r-v35-diagnostic]]
        set expected_build_dir [file normalize [file join $runtime_root t510-stage34c2r-v35-diagnostic]]
        set report_dir [file normalize [file join $repo_root build board latest evidence clock_sysref_causality diagnostic_bit]]
        set release_label "stage34c2r-diagnostic-candidate"
    }
    set overlay_dir [file join $build_dir overlay]
} else {
    error "T510_STAGE34C2R_EXPORT_MODE must be diagnostic, candidate, or release, got '$export_mode'"
}

if {[current_project -quiet] eq ""} {
    error "current T510 release export requires the existing demo-ant project to be open"
}
set project_name [get_property NAME [current_project]]
set project_dir [file normalize [get_property DIRECTORY [current_project]]]
if {$project_name ne "demo-ant" || $project_dir ne $repo_root} {
    error "current T510 release export only accepts the current demo-ant project at $repo_root"
}
if {$build_dir ne $expected_build_dir} {
    error "Refusing to replace unexpected build directory: $build_dir"
}

set source_defines [get_property verilog_define [get_filesets sources_1]]
if {[llength $source_defines] != 0} {
    error "current T510 release current RTL must export without build defines; found $source_defines"
}
set synth_status [get_property STATUS [get_runs synth_1]]
set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match "synth_design Complete*" $synth_status]} {
    error "current T510 release synthesis is incomplete: $synth_status"
}
if {![string match "write_bitstream Complete*" $impl_status]} {
    error "current T510 release implementation/bitstream is incomplete: $impl_status"
}

if {[file exists $build_dir]} {
    file delete -force $build_dir
}
if {$export_mode ne "release" && [file exists $report_dir]} {
    file delete -force $report_dir
}
file mkdir $overlay_dir $report_dir

# Preserve candidate identity before any routed gate can stop the export.  A
# rejected diagnostic bit must still remain attributable and recoverable for
# failure analysis; it is never copied to the production latest directory.
set top_name [get_property TOP [get_filesets sources_1]]
set bit_src [file join [get_property DIRECTORY [get_runs impl_1]] "${top_name}.bit"]
if {![file exists $bit_src]} {
    error "current T510 release bitstream not found at $bit_src"
}
set bit_dst [file join $overlay_dir t510_fengine.bit]
file copy $bit_src $bit_dst
set bit_sha256 [lindex [exec sha256sum $bit_dst] 0]

set synth_log [file join [get_property DIRECTORY [get_runs synth_1]] runme.log]
set impl_log [file join [get_property DIRECTORY [get_runs impl_1]] runme.log]
if {[file exists $synth_log]} {
    file copy $synth_log [file join $report_dir synthesis_run.log]
}
if {[file exists $impl_log]} {
    file copy $impl_log [file join $report_dir implementation_run.log]
}
set candidate_identity [file join $report_dir candidate_identity.txt]
set fh [open $candidate_identity w]
puts $fh "export_mode=$export_mode"
puts $fh "core_version=0x00010035"
puts $fh "synth_status=$synth_status"
puts $fh "impl_status=$impl_status"
puts $fh "bit=$bit_dst"
puts $fh "bit_sha256=$bit_sha256"
close $fh

open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_dir timing_summary.rpt]
report_route_status -file [file join $report_dir route_status.rpt]
report_drc -file [file join $report_dir drc.rpt]
report_methodology -file [file join $report_dir methodology.rpt]
report_design_analysis -congestion -file [file join $report_dir congestion.rpt]
report_high_fanout_nets -timing -max_nets 100 -file [file join $report_dir high_fanout_nets.rpt]
report_utilization -hierarchical -file [file join $report_dir utilization_hierarchical.rpt]
report_clock_utilization -file [file join $report_dir clock_utilization.rpt]
report_datasheet -file [file join $report_dir datasheet.rpt]
report_timing -delay_type min_max -from [get_ports -quiet {pl_sys_ref_p pl_sys_ref_n}] \
    -max_paths 20 -file [file join $report_dir pl_sysref_input_timing.rpt]
set sysref_capture_cells [get_cells -hier -quiet -filter {NAME =~ *pl_mts_sync_clk_0*pl_sys_ref_capture_reg}]
if {[llength $sysref_capture_cells] != 1} {
    error "v35 expected exactly one PL SYSREF first-stage capture register, found $sysref_capture_cells"
}
set sysref_capture_loc [get_property LOC [lindex $sysref_capture_cells 0]]
if {$sysref_capture_loc eq "" || [string match "SLICE*" $sysref_capture_loc]} {
    error "v35 PL SYSREF first-stage capture is not placed in an input IOB: LOC=$sysref_capture_loc"
}
set sysref_capture_d [get_pins -quiet -of_objects [lindex $sysref_capture_cells 0] -filter {REF_PIN_NAME == D}]
set sysref_capture_q [get_pins -quiet -of_objects [lindex $sysref_capture_cells 0] -filter {REF_PIN_NAME == Q}]
set sysref_timing_paths [get_timing_paths -quiet -from [get_ports -quiet {pl_sys_ref_p pl_sys_ref_n}] -to $sysref_capture_d -max_paths 1]
if {[llength $sysref_capture_d] != 1 || [llength $sysref_capture_q] != 1 || [llength $sysref_timing_paths] == 0} {
    error "v35 PL SYSREF input has no timed capture path"
}
set adc_recapture_cells [get_cells -hier -quiet -filter {NAME =~ *pl_mts_axis_recapture_0*adc_sysref_level_reg}]
set dac_recapture_cells [get_cells -hier -quiet -filter {NAME =~ *pl_mts_axis_recapture_0*dac_sysref_level_reg}]
if {[llength $adc_recapture_cells] != 1 || [llength $dac_recapture_cells] != 1} {
    error "v35 expected exactly one ADC and DAC SYSREF recapture register: ADC=$adc_recapture_cells DAC=$dac_recapture_cells"
}
set adc_recapture_d [get_pins -quiet -of_objects [lindex $adc_recapture_cells 0] -filter {REF_PIN_NAME == D}]
set dac_recapture_d [get_pins -quiet -of_objects [lindex $dac_recapture_cells 0] -filter {REF_PIN_NAME == D}]
report_timing -delay_type min_max -from $sysref_capture_q -to $adc_recapture_d \
    -max_paths 20 -file [file join $report_dir pl_to_adc_sysref_recapture_timing.rpt]
report_timing -delay_type min_max -from $sysref_capture_q -to $dac_recapture_d \
    -max_paths 20 -file [file join $report_dir pl_to_dac_sysref_recapture_timing.rpt]
foreach endpoint [list $adc_recapture_d $dac_recapture_d] {
    foreach delay_type {max min} {
        set path [get_timing_paths -quiet -delay_type $delay_type -from $sysref_capture_q -to $endpoint -max_paths 1]
        if {[llength $path] != 1 || [get_property SLACK [lindex $path 0]] < 0.0} {
            error "v35 PL-to-AXIS SYSREF recapture timing failed delay_type=$delay_type endpoint=$endpoint path=$path"
        }
    }
}
set timing18 [get_methodology_violations -quiet -filter {ID == TIMING-18}]
if {[llength $timing18] != 0} {
    error "v35 methodology still reports TIMING-18: $timing18"
}
write_checkpoint -force [file join $report_dir t510_fengine_board_top_routed.dcp]

set setup_paths [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1]
set hold_paths [get_timing_paths -quiet -delay_type min -max_paths 1 -nworst 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {
    error "current T510 release timing gate could not obtain setup and hold paths"
}
set wns [get_property SLACK [lindex $setup_paths 0]]
set whs [get_property SLACK [lindex $hold_paths 0]]
if {$wns < 0.0 || $whs < 0.0} {
    error "current T510 release timing failed: WNS=$wns WHS=$whs"
}
foreach violation [get_drc_violations -quiet] {
    set severity [string toupper [get_property SEVERITY $violation]]
    if {$severity eq "ERROR" || $severity eq "CRITICAL WARNING"} {
        error "current T510 release DRC failed: [get_property ID $violation] $severity"
    }
}

set bd_file [get_files -quiet */t510_rfdc_bd.bd]
if {[llength $bd_file] != 1} {
    error "current T510 release export expected one block design, found $bd_file"
}
generate_target all [lindex $bd_file 0]
open_bd_design [lindex $bd_file 0]
validate_bd_design
write_bd_tcl -force [file join $overlay_dir t510_fengine.tcl]

set hwh_candidates [get_files -quiet */t510_rfdc_bd.hwh]
if {[llength $hwh_candidates] != 1} {
    error "current T510 release expected one generated HWH, found $hwh_candidates"
}
file copy [lindex $hwh_candidates 0] [file join $overlay_dir t510_fengine.hwh]

set rfdc_xci_candidates [get_files -quiet -all *usp_rf_data_converter*.xci]
if {[llength $rfdc_xci_candidates] != 1} {
    error "current T510 release expected one active RFDC XCI, found $rfdc_xci_candidates"
}
file copy [lindex $rfdc_xci_candidates 0] [file join $overlay_dir t510_fengine_rfdc.xci]

set manifest [file join $overlay_dir t510_fengine.manifest.txt]
set fh [open $manifest w]
puts $fh "release=$release_label"
puts $fh "export_mode=$export_mode"
puts $fh "core_version=0x00010035"
puts $fh "project=$project_name"
puts $fh "project_dir=$project_dir"
puts $fh "part=[get_property PART [current_project]]"
puts $fh "top=$top_name"
puts $fh "source_defines=$source_defines"
puts $fh "bit=[file join $overlay_dir t510_fengine.bit]"
puts $fh "bit_sha256=$bit_sha256"
puts $fh "hwh=[file join $overlay_dir t510_fengine.hwh]"
puts $fh "bd_tcl=[file join $overlay_dir t510_fengine.tcl]"
puts $fh "rfdc_xci=[file join $overlay_dir t510_fengine_rfdc.xci]"
puts $fh "report_dir=$report_dir"
puts $fh "wns=$wns"
puts $fh "whs=$whs"
puts $fh "pl_sysref_capture_loc=$sysref_capture_loc"
puts $fh "pl_sysref_input_delay_min_ns=$sysref_input_delay_min_ns"
puts $fh "pl_sysref_input_delay_max_ns=$sysref_input_delay_max_ns"
puts $fh "pl_sysref_input_delay_status=FINAL_PHASE_EYE_FROZEN"
puts $fh "pl_sysref_selected_phase_ps=$sysref_selected_phase_ps"
puts $fh "pl_sysref_phase_error_envelope_ps=$sysref_phase_error_envelope_ps"
puts $fh "pl_sysref_10m_profile_id=$sysref_10m_profile_id"
puts $fh "pl_sysref_10m_profile_sha256=$sysref_10m_profile_sha256"
puts $fh "pl_sysref_5m_profile_id=$sysref_5m_profile_id"
puts $fh "pl_sysref_5m_profile_sha256=$sysref_5m_profile_sha256"
puts $fh "tics_manifest_sha256=$tics_manifest_sha256"
close $fh

set summary [file join $report_dir build_summary.txt]
set fh [open $summary w]
puts $fh "release=$release_label"
puts $fh "export_mode=$export_mode"
puts $fh "core_version=0x00010035"
puts $fh "project=$project_name"
puts $fh "project_dir=$project_dir"
puts $fh "part=[get_property PART [current_project]]"
puts $fh "top=$top_name"
puts $fh "synth_status=$synth_status"
puts $fh "impl_status=$impl_status"
puts $fh "bit_sha256=$bit_sha256"
puts $fh "wns=$wns"
puts $fh "whs=$whs"
puts $fh "pl_sysref_capture_loc=$sysref_capture_loc"
puts $fh "pl_sysref_input_delay_min_ns=$sysref_input_delay_min_ns"
puts $fh "pl_sysref_input_delay_max_ns=$sysref_input_delay_max_ns"
puts $fh "pl_sysref_input_delay_status=FINAL_PHASE_EYE_FROZEN"
puts $fh "pl_sysref_selected_phase_ps=$sysref_selected_phase_ps"
puts $fh "pl_sysref_phase_error_envelope_ps=$sysref_phase_error_envelope_ps"
puts $fh "pl_sysref_10m_profile_id=$sysref_10m_profile_id"
puts $fh "pl_sysref_10m_profile_sha256=$sysref_10m_profile_sha256"
puts $fh "pl_sysref_5m_profile_id=$sysref_5m_profile_id"
puts $fh "pl_sysref_5m_profile_sha256=$sysref_5m_profile_sha256"
puts $fh "tics_manifest_sha256=$tics_manifest_sha256"
close $fh

puts "T510_CURRENT_PROJECT_EXPORT_PASS build_dir=$build_dir report_dir=$report_dir WNS=$wns WHS=$whs"
