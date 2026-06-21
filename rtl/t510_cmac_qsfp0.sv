`default_nettype none

module t510_cmac_qsfp0 (
    input  wire         init_clk,
    input  wire         reset_n,
    input  wire         gt_ref_clk_p,
    input  wire         gt_ref_clk_n,
    input  wire [3:0]   gt_rxp_in,
    input  wire [3:0]   gt_rxn_in,
    output wire [3:0]   gt_txp_out,
    output wire [3:0]   gt_txn_out,
    output wire         tx_clk,
    output wire         tx_rst_n,
    input  wire [511:0] tx_axis_tdata,
    input  wire [63:0]  tx_axis_tkeep,
    input  wire         tx_axis_tvalid,
    input  wire         tx_axis_tlast,
    output wire         tx_axis_tready,
    output wire         gt_refclk_seen,
    output wire         gt_powergood,
    output wire         gt_tx_reset_done,
    output wire         gt_rx_reset_done,
    output wire         gt_locked,
    output wire         cmac_reset_done,
    output wire         cmac_tx_ready,
    output wire         local_fault,
    output wire         remote_fault,
    output wire         link_up,
    output wire         tx_underflow,
    output wire         tx_overflow,
    output wire         rx_aligned,
    output wire         rx_status,
    output wire         rx_local_fault,
    output wire         rx_internal_local_fault,
    output wire         tx_local_fault_detail,
    output wire         an_autoneg_complete,
    output wire         an_lp_ability_valid,
    output wire         an_lp_autoneg_able,
    output wire         an_lp_ability_100gbase_cr4,
    output wire         an_rs_fec_enable,
    output wire [3:0]   lt_signal_detect,
    output wire [3:0]   lt_training,
    output wire [3:0]   lt_training_fail,
    output wire [3:0]   lt_frame_lock
);

`ifndef SYNTHESIS
    assign gt_txp_out        = 4'd0;
    assign gt_txn_out        = 4'd0;
    assign tx_clk            = init_clk;
    assign tx_rst_n          = reset_n;
    assign tx_axis_tready    = reset_n;
    assign gt_refclk_seen    = reset_n;
    assign gt_powergood      = reset_n;
    assign gt_tx_reset_done  = reset_n;
    assign gt_rx_reset_done  = reset_n;
    assign gt_locked         = reset_n;
    assign cmac_reset_done   = reset_n;
    assign cmac_tx_ready     = reset_n;
    assign local_fault       = 1'b0;
    assign remote_fault      = 1'b0;
    assign link_up           = reset_n;
    assign tx_underflow      = 1'b0;
    assign tx_overflow       = 1'b0;
    assign rx_aligned        = reset_n;
    assign rx_status         = reset_n;
    assign rx_local_fault    = 1'b0;
    assign rx_internal_local_fault = 1'b0;
    assign tx_local_fault_detail = 1'b0;
    assign an_autoneg_complete = reset_n;
    assign an_lp_ability_valid = reset_n;
    assign an_lp_autoneg_able = reset_n;
    assign an_lp_ability_100gbase_cr4 = reset_n;
    assign an_rs_fec_enable = 1'b1;
    assign lt_signal_detect = {4{reset_n}};
    assign lt_training      = 4'd0;
    assign lt_training_fail = 4'd0;
    assign lt_frame_lock    = {4{reset_n}};
`else
    wire        sys_reset = !reset_n;
    wire        gt_txusrclk2_int;
    wire        gt_rxusrclk2_int;
    wire        gt_ref_clk_out_int;
    wire [3:0]  gt_powergoodout;
    wire [3:0]  gt_txresetdone;
    wire [3:0]  gt_rxresetdone;
    wire        usr_tx_reset;
    wire        usr_rx_reset;
    wire        stat_rx_aligned;
    wire        stat_rx_status;
    wire        stat_rx_local_fault;
    wire        stat_rx_internal_local_fault;
    wire        stat_rx_remote_fault;
    wire        stat_tx_local_fault;
    wire        tx_unfout;
    wire        tx_ovfout;
    wire        tx_axis_tready_int;
    wire        refclk_toggle_init;
    logic       refclk_toggle_gt = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic [2:0] refclk_toggle_sync = 3'b000;
    logic       refclk_seen_latched = 1'b0;

    always_ff @(posedge gt_ref_clk_out_int) begin
        refclk_toggle_gt <= ~refclk_toggle_gt;
    end

    always_ff @(posedge init_clk or posedge sys_reset) begin
        if (sys_reset) begin
            refclk_toggle_sync <= 3'b000;
            refclk_seen_latched <= 1'b0;
        end else begin
            refclk_toggle_sync <= {refclk_toggle_sync[1:0], refclk_toggle_gt};
            if (refclk_toggle_sync[2] ^ refclk_toggle_sync[1]) begin
                refclk_seen_latched <= 1'b1;
            end
        end
    end

    assign tx_clk           = gt_txusrclk2_int;
    assign tx_rst_n         = !usr_tx_reset;
    assign tx_axis_tready   = tx_axis_tready_int;
    assign gt_refclk_seen   = refclk_seen_latched;
    assign gt_powergood     = &gt_powergoodout;
    assign gt_tx_reset_done = &gt_txresetdone;
    assign gt_rx_reset_done = &gt_rxresetdone;
    assign gt_locked        = gt_powergood && gt_tx_reset_done && gt_rx_reset_done;
    assign cmac_reset_done  = !usr_tx_reset && !usr_rx_reset;
    assign cmac_tx_ready    = tx_axis_tready_int && !usr_tx_reset;
    assign local_fault      = stat_rx_local_fault || stat_rx_internal_local_fault || stat_tx_local_fault;
    assign remote_fault     = stat_rx_remote_fault;
    assign link_up          = gt_locked && cmac_reset_done && cmac_tx_ready &&
                              stat_rx_status && stat_rx_aligned &&
                              !local_fault && !remote_fault;
    assign tx_underflow     = tx_unfout;
    assign tx_overflow      = tx_ovfout;
    assign rx_aligned       = stat_rx_aligned;
    assign rx_status        = stat_rx_status;
    assign rx_local_fault   = stat_rx_local_fault;
    assign rx_internal_local_fault = stat_rx_internal_local_fault;
    assign tx_local_fault_detail = stat_tx_local_fault;
    assign an_autoneg_complete = 1'b1;
    assign an_lp_ability_valid = 1'b0;
    assign an_lp_autoneg_able = 1'b0;
    assign an_lp_ability_100gbase_cr4 = 1'b0;
    assign an_rs_fec_enable = 1'b1;
    assign lt_signal_detect = 4'hf;
    assign lt_training      = 4'd0;
    assign lt_training_fail = 4'd0;
    assign lt_frame_lock    = 4'hf;

    t510_cmac_usplus_0 u_cmac (
        .gt_txp_out(gt_txp_out),
        .gt_txn_out(gt_txn_out),
        .gt_rxp_in(gt_rxp_in),
        .gt_rxn_in(gt_rxn_in),
        .gt_txusrclk2(gt_txusrclk2_int),
        .gt_loopback_in(12'd0),
        .gt_eyescanreset(4'd0),
        .gt_eyescantrigger(4'd0),
        .gt_rxcdrhold(4'd0),
        .gt_rxpolarity(4'd0),
        .gt_rxrate(12'd0),
        .gt_txdiffctrl({4{5'b11000}}),
        .gt_txpolarity(4'd0),
        .gt_txinhibit(4'd0),
        .gt_txpippmen(4'd0),
        .gt_txpippmsel(4'd0),
        .gt_txpostcursor(20'd0),
        .gt_txprbsforceerr(4'd0),
        .gt_txprecursor(20'd0),
        .gt_ref_clk_out(gt_ref_clk_out_int),
        .gt_powergoodout(gt_powergoodout),
        .gt_rxdfelpmreset(4'd0),
        .gt_rxlpmen(4'd0),
        .gt_rxprbscntreset(4'd0),
        .gt_rxprbssel(16'd0),
        .gt_rxresetdone(gt_rxresetdone),
        .gt_txprbssel(16'd0),
        .gt_txresetdone(gt_txresetdone),
        .gtwiz_reset_tx_datapath(1'b0),
        .gtwiz_reset_rx_datapath(1'b0),
        .gt_drpclk(init_clk),
        .gt0_drpen(1'b0),
        .gt0_drpwe(1'b0),
        .gt0_drpaddr(10'd0),
        .gt0_drpdi(16'd0),
        .gt1_drpen(1'b0),
        .gt1_drpwe(1'b0),
        .gt1_drpaddr(10'd0),
        .gt1_drpdi(16'd0),
        .gt2_drpen(1'b0),
        .gt2_drpwe(1'b0),
        .gt2_drpaddr(10'd0),
        .gt2_drpdi(16'd0),
        .gt3_drpen(1'b0),
        .gt3_drpwe(1'b0),
        .gt3_drpaddr(10'd0),
        .gt3_drpdi(16'd0),
        .sys_reset(sys_reset),
        .gt_ref_clk_p(gt_ref_clk_p),
        .gt_ref_clk_n(gt_ref_clk_n),
        .init_clk(init_clk),
        .common0_drpaddr(16'd0),
        .common0_drpdi(16'd0),
        .common0_drpwe(1'b0),
        .common0_drpen(1'b0),
        .ctl_rx_check_etype_gcp(1'b0),
        .ctl_rx_check_etype_gpp(1'b0),
        .ctl_rx_check_etype_pcp(1'b0),
        .ctl_rx_check_etype_ppp(1'b0),
        .ctl_rx_check_mcast_gcp(1'b0),
        .ctl_rx_check_mcast_gpp(1'b0),
        .ctl_rx_check_mcast_pcp(1'b0),
        .ctl_rx_check_mcast_ppp(1'b0),
        .ctl_rx_check_opcode_gcp(1'b0),
        .ctl_rx_check_opcode_gpp(1'b0),
        .ctl_rx_check_opcode_pcp(1'b0),
        .ctl_rx_check_opcode_ppp(1'b0),
        .ctl_rx_check_sa_gcp(1'b0),
        .ctl_rx_check_sa_gpp(1'b0),
        .ctl_rx_check_sa_pcp(1'b0),
        .ctl_rx_check_sa_ppp(1'b0),
        .ctl_rx_check_ucast_gcp(1'b0),
        .ctl_rx_check_ucast_gpp(1'b0),
        .ctl_rx_check_ucast_pcp(1'b0),
        .ctl_rx_check_ucast_ppp(1'b0),
        .ctl_rx_enable_gcp(1'b0),
        .ctl_rx_enable_gpp(1'b0),
        .ctl_rx_enable_pcp(1'b0),
        .ctl_rx_enable_ppp(1'b0),
        .ctl_rx_pause_ack(9'd0),
        .ctl_rx_pause_enable(9'd0),
        .ctl_rx_enable(1'b1),
        .ctl_rx_force_resync(1'b0),
        .ctl_rx_test_pattern(1'b0),
        .ctl_rsfec_ieee_error_indication_mode(1'b0),
        .ctl_rx_rsfec_enable(1'b1),
        .ctl_rx_rsfec_enable_correction(1'b1),
        .ctl_rx_rsfec_enable_indication(1'b1),
        .core_rx_reset(sys_reset),
        .rx_clk(gt_rxusrclk2_int),
        .usr_rx_reset(usr_rx_reset),
        .gt_rxusrclk2(gt_rxusrclk2_int),
        .stat_rx_aligned(stat_rx_aligned),
        .stat_rx_local_fault(stat_rx_local_fault),
        .stat_rx_internal_local_fault(stat_rx_internal_local_fault),
        .stat_rx_remote_fault(stat_rx_remote_fault),
        .stat_rx_status(stat_rx_status),
        .ctl_tx_enable(1'b1),
        .ctl_tx_rsfec_enable(1'b1),
        .ctl_tx_send_idle(1'b0),
        .ctl_tx_send_rfi(1'b0),
        .ctl_tx_send_lfi(1'b0),
        .ctl_tx_test_pattern(1'b0),
        .core_tx_reset(sys_reset),
        .stat_tx_local_fault(stat_tx_local_fault),
        .ctl_tx_pause_enable(9'd0),
        .ctl_tx_pause_quanta0(16'd0),
        .ctl_tx_pause_quanta1(16'd0),
        .ctl_tx_pause_quanta2(16'd0),
        .ctl_tx_pause_quanta3(16'd0),
        .ctl_tx_pause_quanta4(16'd0),
        .ctl_tx_pause_quanta5(16'd0),
        .ctl_tx_pause_quanta6(16'd0),
        .ctl_tx_pause_quanta7(16'd0),
        .ctl_tx_pause_quanta8(16'd0),
        .ctl_tx_pause_refresh_timer0(16'd0),
        .ctl_tx_pause_refresh_timer1(16'd0),
        .ctl_tx_pause_refresh_timer2(16'd0),
        .ctl_tx_pause_refresh_timer3(16'd0),
        .ctl_tx_pause_refresh_timer4(16'd0),
        .ctl_tx_pause_refresh_timer5(16'd0),
        .ctl_tx_pause_refresh_timer6(16'd0),
        .ctl_tx_pause_refresh_timer7(16'd0),
        .ctl_tx_pause_refresh_timer8(16'd0),
        .ctl_tx_pause_req(9'd0),
        .ctl_tx_resend_pause(1'b0),
        .tx_axis_tready(tx_axis_tready_int),
        .tx_axis_tvalid(tx_axis_tvalid),
        .tx_axis_tdata(tx_axis_tdata),
        .tx_axis_tlast(tx_axis_tlast),
        .tx_axis_tkeep(tx_axis_tkeep),
        .tx_axis_tuser(1'b0),
        .tx_ovfout(tx_ovfout),
        .tx_unfout(tx_unfout),
        .tx_preamblein(56'd0),
        .usr_tx_reset(usr_tx_reset),
        .core_drp_reset(sys_reset),
        .drp_clk(init_clk),
        .drp_addr(10'd0),
        .drp_di(16'd0),
        .drp_en(1'b0),
        .drp_we(1'b0)
    );
`endif

endmodule

`default_nettype wire
