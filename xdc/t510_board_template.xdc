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
