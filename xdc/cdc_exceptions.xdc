# Control AXI-Lite is clocked by PS pl_clk0 so register reads remain alive even
# when RFDC/LMK clocks are absent. Datapath logic is clocked from the LMK/PL
# clock through clk_wiz_0, so only the PS/control domain is asynchronous to the
# RFDC AXIS domain.

set_false_path -from [get_ports pps_in]
set_false_path -from [get_ports -quiet pl_sys_ref_p]
set_false_path -to [get_ports -quiet {pl_led0 pl_led1 pl_led2 pl_led3}]

set_false_path -to [get_pins -quiet -filter {REF_PIN_NAME == D} -of_objects [get_cells -hier -quiet -filter {NAME =~ u_core/*_meta_reg*}]]
set_false_path -to [get_pins -quiet -filter {REF_PIN_NAME == D} -of_objects [get_cells -hier -quiet -filter {NAME =~ u_core/*_sync_reg[0]}]]

set ctrl_clks [get_clocks -quiet clk_pl_0]
set rfdc_axis_clks [get_clocks -quiet -of_objects [get_pins -quiet {
    u_rfdc_bd/t510_rfdc_bd_i/clk_wiz_0/inst/mmcme4_adv_inst/CLKOUT0
    u_rfdc_bd/t510_rfdc_bd_i/clk_wiz_0/inst/mmcme4_adv_inst/CLKOUT1
}]]
set cmac_clks [get_clocks -quiet {
    qsfp0_mgt_refclk_p
    qpll0outclk_out*
    qpll0outrefclk_out*
    GTYE4_CHANNEL_TXOUTCLKPCS*
    rxoutclk_out*
    txoutclk_out*
}]

set_clock_groups -asynchronous \
    -group $ctrl_clks \
    -group $rfdc_axis_clks \
    -group $cmac_clks
