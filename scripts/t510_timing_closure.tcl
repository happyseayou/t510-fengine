# Apply only through the existing attached GUI, before a fresh full build.
# R1: 603 failing setup endpoints, WNS -0.195381 ns, dominated by routes to
# frame-memory/FIFO BRAM control pins (92-97% route delay in worst paths).
# Keep datapath, clock periods and timing exceptions unchanged.
set current_script_dir [file normalize [file dirname [info script]]]
set current_impl [get_runs impl_1]
if {[regexp -nocase {running|queued} [get_property STATUS $current_impl]]} {
    error "cannot change implementation settings while a run is active"
}
set current_gate [file join $current_script_dir t510_pre_bitstream_gate.tcl]
set current_old_hook [get_property STEPS.WRITE_BITSTREAM.TCL.PRE $current_impl]
if {$current_old_hook ne "" && [file normalize $current_old_hook] ne $current_gate} {
    error "existing pre-bitstream hook requires explicit integration: $current_old_hook"
}
set_property strategy Performance_WLBlockPlacementFanoutOpt $current_impl
set_property -dict [list \
    STEPS.PHYS_OPT_DESIGN.IS_ENABLED true \
    STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveFanoutOpt \
    STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE AggressiveExplore \
    {STEPS.ROUTE_DESIGN.ARGS.MORE OPTIONS} {-tns_cleanup} \
    STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED true \
    STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveExplore \
    STEPS.WRITE_BITSTREAM.TCL.PRE $current_gate] $current_impl
puts "T510_TIMING_CLOSURE_PROFILE_APPLIED fanout_opt/post_route_opt/pre_bitstream_gate"
