# The PS-driven AXI/control domain clock is already created by the Zynq MPSoC
# IP XDC as clk_pl_0.  Do not create a second clock on PLCLK[0]: a duplicate
# ctrl_clk overrides clk_pl_0 during implementation and masks the real timing
# relationship used by the CDC constraints.
#
# RFDC AXIS clocks are auto-derived from clk_wiz_0; redefining them downstream
# of the MMCM/BUFG creates TIMING-2/TIMING-4 methodology violations.

# Some Zynq MPSoC EMIO peripheral clock outputs exist on the hard block even
# when the PL design leaves those peripherals unused.  They are not design
# clocks, so keep them out of timing rather than assigning artificial clocks
# that would introduce unrelated pulse-width failures.
set_false_path -from [get_pins -quiet {
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOENET0MDIOMDC
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOENET1MDIOMDC
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOENET2MDIOMDC
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOENET3MDIOMDC
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOSDIO0CLKOUT
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOSDIO1CLKOUT
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOSPI0SCLKO
    u_rfdc_bd/t510_rfdc_bd_i/zynq_ultra_ps_e_0/inst/PS8_i/EMIOSPI1SCLKO
}]
