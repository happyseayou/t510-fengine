set stage28_report_dir [file normalize "/home/astrolab/demo-ant/reports/vivado/stage28_iter_a_0x0001002d"]
file mkdir $stage28_report_dir

report_timing_summary \
    -delay_type min_max \
    -report_unconstrained \
    -check_timing_verbose \
    -max_paths 50 \
    -file [file join $stage28_report_dir timing_summary.rpt]
report_utilization \
    -hierarchical \
    -file [file join $stage28_report_dir utilization_hierarchical.rpt]
report_route_status \
    -file [file join $stage28_report_dir route_status.rpt]
report_drc \
    -file [file join $stage28_report_dir drc.rpt]
report_clock_utilization \
    -file [file join $stage28_report_dir clock_utilization.rpt]
write_checkpoint \
    -force \
    [file join $stage28_report_dir t510_fengine_board_top_routed.dcp]

set stage28_summary [open [file join $stage28_report_dir run_summary.txt] w]
puts $stage28_summary "stage=28"
puts $stage28_summary "iteration=A"
puts $stage28_summary "core_version=0x0001002d"
puts $stage28_summary "run=[current_run]"
puts $stage28_summary "design=[current_design]"
puts $stage28_summary "part=[get_property PART [current_project]]"
puts $stage28_summary "generated_at=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
close $stage28_summary
