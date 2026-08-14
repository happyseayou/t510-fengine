create_clock -name pl_clk -period 6.250 [get_ports pl_clk_p]

# Stage 34c-2R final v35 candidate.  Both the 10 MHz and corrected 5 MHz
# TICS-Pro profiles passed all 32 native SDCLKout3 phase points and selected
# the same 3000 ps eye centre.  The largest unsampled native phase interval is
# 241.667 ps, so constrain the selected centre with a conservative half-gap
# error envelope of +/-120.834 ps.  This is a real timed IOB endpoint; the
# retired broad PL-SYSREF false path must not be restored.
set_input_delay -clock [get_clocks pl_clk] -min 2.879166 \
    [get_ports {pl_sys_ref_p pl_sys_ref_n}]
set_input_delay -clock [get_clocks pl_clk] -max 3.120834 \
    [get_ports {pl_sys_ref_p pl_sys_ref_n}]

# The IOB attribute carried by an out-of-context BD module reference was not
# retained by the first diagnostic implementation.  Reassert it on the linked
# top-level cell so the PL SYSREF pin is captured in the input IOB, as required
# by PG269, instead of routing 1.5 ns to a fabric SLICE register.
set pl_sysref_capture_cells [get_cells -hier -quiet -filter \
    {NAME =~ *pl_mts_sync_clk_0/inst/pl_sys_ref_capture_reg}]
# XDC accepts only constraint commands, not general Tcl control flow.  The
# quiet form is harmless during any synthesis phase where the linked cell is
# not yet visible; implementation sees the unique cell and export gates its
# count and physical LOC explicitly.
set_property -quiet IOB TRUE $pl_sysref_capture_cells

# PPS is asynchronous to the PL fabric. The synchronizer lives in RTL.
set_input_delay -clock [get_clocks pl_clk] 0.0 [get_ports pps_in]
