# T510 RFDC bring-up constraints.
# RFDC analog and RF clocks are constrained by the RFDC IP generated XDC.

set_property -dict {PACKAGE_PIN AG17 IOSTANDARD LVDS} [get_ports pl_clk_p]
set_property -dict {PACKAGE_PIN AH17 IOSTANDARD LVDS} [get_ports pl_clk_n]
set_property -dict {PACKAGE_PIN AG15 IOSTANDARD LVDS} [get_ports pl_sys_ref_p]
set_property -dict {PACKAGE_PIN AH15 IOSTANDARD LVDS} [get_ports pl_sys_ref_n]

set_property -dict {PACKAGE_PIN A10 IOSTANDARD LVCMOS33} [get_ports pl_led0]
set_property -dict {PACKAGE_PIN A9  IOSTANDARD LVCMOS33} [get_ports pl_led1]
set_property -dict {PACKAGE_PIN G10 IOSTANDARD LVCMOS33} [get_ports pl_led2]
set_property -dict {PACKAGE_PIN H10 IOSTANDARD LVCMOS33} [get_ports pl_led3]

set_property -dict {PACKAGE_PIN K11 IOSTANDARD LVCMOS33} [get_ports clk_main_sel]
set_property -dict {PACKAGE_PIN C9  IOSTANDARD LVCMOS33} [get_ports lmk_sync]

set_property -dict {PACKAGE_PIN G12 IOSTANDARD LVCMOS33} [get_ports iic_scl_io]
set_property -dict {PACKAGE_PIN F12 IOSTANDARD LVCMOS33} [get_ports iic_sda_io]
set_property -dict {PACKAGE_PIN D9  IOSTANDARD LVCMOS33} [get_ports iic_rst_n]

set_property -dict {PACKAGE_PIN F10 IOSTANDARD LVCMOS33 PULLDOWN true} [get_ports pps_in]

set_property -dict {PACKAGE_PIN K10 IOSTANDARD LVCMOS33} [get_ports qsfp0_modprsl]
set_property -dict {PACKAGE_PIN H11 IOSTANDARD LVCMOS33} [get_ports qsfp0_intl]
set_property -dict {PACKAGE_PIN J11 IOSTANDARD LVCMOS33} [get_ports qsfp0_resetl]
set_property -dict {PACKAGE_PIN K12 IOSTANDARD LVCMOS33} [get_ports qsfp0_lpmode]
set_property -dict {PACKAGE_PIN J12 IOSTANDARD LVCMOS33} [get_ports qsfp0_modsell]

# QSFP0 100G CMAC / GTY Bank128. First bring-up uses refclk M28/M29;
# K28/K29 remains the fallback if the GT refclk never toggles.
set_property PACKAGE_PIN M28 [get_ports qsfp0_mgt_refclk_p]
set_property PACKAGE_PIN M29 [get_ports qsfp0_mgt_refclk_n]

set_property PACKAGE_PIN P33 [get_ports {qsfp0_rxp[0]}]
set_property PACKAGE_PIN P34 [get_ports {qsfp0_rxn[0]}]
set_property PACKAGE_PIN M33 [get_ports {qsfp0_rxp[1]}]
set_property PACKAGE_PIN M34 [get_ports {qsfp0_rxn[1]}]
set_property PACKAGE_PIN K33 [get_ports {qsfp0_rxp[2]}]
set_property PACKAGE_PIN K34 [get_ports {qsfp0_rxn[2]}]
set_property PACKAGE_PIN H33 [get_ports {qsfp0_rxp[3]}]
set_property PACKAGE_PIN H34 [get_ports {qsfp0_rxn[3]}]

set_property PACKAGE_PIN N30 [get_ports {qsfp0_txp[0]}]
set_property PACKAGE_PIN N31 [get_ports {qsfp0_txn[0]}]
set_property PACKAGE_PIN L30 [get_ports {qsfp0_txp[1]}]
set_property PACKAGE_PIN L31 [get_ports {qsfp0_txn[1]}]
set_property PACKAGE_PIN J30 [get_ports {qsfp0_txp[2]}]
set_property PACKAGE_PIN J31 [get_ports {qsfp0_txn[2]}]
set_property PACKAGE_PIN G30 [get_ports {qsfp0_txp[3]}]
set_property PACKAGE_PIN G31 [get_ports {qsfp0_txn[3]}]
