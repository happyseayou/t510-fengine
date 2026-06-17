create_clock -name pl_clk -period 4.069 [get_ports pl_clk_p]

# PPS is asynchronous to the PL fabric. The synchronizer lives in RTL.
set_input_delay -clock [get_clocks pl_clk] 0.0 [get_ports pps_in]
