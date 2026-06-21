proc create_t510_fengine_bd {} {
    if {[current_project -quiet] eq ""} {
        error "Open the Vivado project before sourcing bd/t510_fengine_bd.tcl"
    }

    if {[llength [get_bd_designs -quiet t510_fengine_bd]]} {
        delete_bd_objs [get_bd_designs t510_fengine_bd]
    }

    create_bd_design "t510_fengine_bd"

    create_bd_port -dir I -type clk clk
    create_bd_port -dir I -type rst rst_n
    create_bd_port -dir I pps_in
    create_bd_port -dir I ref_lock_in
    create_bd_port -dir I rfdc_ready_in
    create_bd_port -dir I -from 1023 -to 0 s_axis_adc_tdata
    create_bd_port -dir I -from 31 -to 0 s_axis_adc_tuser
    create_bd_port -dir I s_axis_adc_tvalid
    create_bd_port -dir I s_axis_adc_tlast
    create_bd_port -dir O s_axis_adc_tready
    create_bd_port -dir O -from 63 -to 0 m_axis_tx_tdata
    create_bd_port -dir O -from 7 -to 0 m_axis_tx_tkeep
    create_bd_port -dir O m_axis_tx_tvalid
    create_bd_port -dir O m_axis_tx_tlast
    create_bd_port -dir I m_axis_tx_tready
    create_bd_port -dir O irq

    if {[llength [get_ips -quiet ps_0]] == 0} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* ps_0
    }
    if {[llength [get_ips -quiet rst_ps8_0_100M]] == 0} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* rst_ps8_0_100M
    }
    if {[llength [get_ips -quiet usp_rf_data_converter_0]] == 0} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter:* usp_rf_data_converter_0
    }
    if {[llength [get_ips -quiet axi_dma_0]] == 0} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:* axi_dma_0
    }
    if {[llength [get_ips -quiet cmac_usplus_0]] == 0} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:cmac_usplus:* cmac_usplus_0
    }

    create_bd_cell -type module -reference t510_fengine_top t510_core

    connect_bd_net [get_bd_ports clk] [get_bd_pins t510_core/clk]
    connect_bd_net [get_bd_ports rst_n] [get_bd_pins t510_core/rst_n]
    connect_bd_net [get_bd_ports pps_in] [get_bd_pins t510_core/pps_in]
    connect_bd_net [get_bd_ports ref_lock_in] [get_bd_pins t510_core/ref_lock_in]
    connect_bd_net [get_bd_ports rfdc_ready_in] [get_bd_pins t510_core/rfdc_ready_in]
    connect_bd_net [get_bd_ports s_axis_adc_tdata] [get_bd_pins t510_core/s_axis_adc_tdata]
    connect_bd_net [get_bd_ports s_axis_adc_tuser] [get_bd_pins t510_core/s_axis_adc_tuser]
    connect_bd_net [get_bd_ports s_axis_adc_tvalid] [get_bd_pins t510_core/s_axis_adc_tvalid]
    connect_bd_net [get_bd_ports s_axis_adc_tlast] [get_bd_pins t510_core/s_axis_adc_tlast]
    connect_bd_net [get_bd_ports s_axis_adc_tready] [get_bd_pins t510_core/s_axis_adc_tready]
    connect_bd_net [get_bd_ports m_axis_tx_tdata] [get_bd_pins t510_core/m_axis_tx_tdata]
    connect_bd_net [get_bd_ports m_axis_tx_tkeep] [get_bd_pins t510_core/m_axis_tx_tkeep]
    connect_bd_net [get_bd_ports m_axis_tx_tvalid] [get_bd_pins t510_core/m_axis_tx_tvalid]
    connect_bd_net [get_bd_ports m_axis_tx_tlast] [get_bd_pins t510_core/m_axis_tx_tlast]
    connect_bd_net [get_bd_ports m_axis_tx_tready] [get_bd_pins t510_core/m_axis_tx_tready]
    connect_bd_net [get_bd_ports irq] [get_bd_pins t510_core/irq]

    # The AXI-Lite slave is kept as discrete ports in the current skeleton.
    # Integrate it with PS M_AXI_HPM at board bring-up time once the final
    # address map and reset tree are locked.
    make_bd_pins_external [get_bd_pins t510_core/s_axi_awaddr]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_awvalid]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_awready]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_wdata]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_wstrb]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_wvalid]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_wready]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_bresp]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_bvalid]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_bready]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_araddr]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_arvalid]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_arready]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_rdata]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_rresp]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_rvalid]
    make_bd_pins_external [get_bd_pins t510_core/s_axi_rready]

    regenerate_bd_layout
    save_bd_design
}

create_t510_fengine_bd
