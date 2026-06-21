set repo_root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $repo_root demo-ant.xpr]
reset_run impl_1
launch_runs impl_1 -jobs 8
wait_on_run impl_1
puts "IMPL_STATUS=[get_property STATUS [get_runs impl_1]]"
exit
