`default_nettype none

module t510_fengine_board_top (
    input  wire adc1_clk_clk_n,
    input  wire adc1_clk_clk_p,
    input  wire dac2_clk_clk_n,
    input  wire dac2_clk_clk_p,
    input  wire sysref_in_diff_n,
    input  wire sysref_in_diff_p,
    input  wire vin0_01_v_n,
    input  wire vin0_01_v_p,
    input  wire vin0_23_v_n,
    input  wire vin0_23_v_p,
    input  wire vin1_01_v_n,
    input  wire vin1_01_v_p,
    input  wire vin1_23_v_n,
    input  wire vin1_23_v_p,
    input  wire vin2_01_v_n,
    input  wire vin2_01_v_p,
    input  wire vin2_23_v_n,
    input  wire vin2_23_v_p,
    input  wire vin3_01_v_n,
    input  wire vin3_01_v_p,
    input  wire vin3_23_v_n,
    input  wire vin3_23_v_p,
    output wire vout00_v_n,
    output wire vout00_v_p,
    output wire vout02_v_n,
    output wire vout02_v_p,
    output wire vout10_v_n,
    output wire vout10_v_p,
    output wire vout12_v_n,
    output wire vout12_v_p,
    output wire vout20_v_n,
    output wire vout20_v_p,
    output wire vout22_v_n,
    output wire vout22_v_p,
    output wire vout30_v_n,
    output wire vout30_v_p,
    output wire vout32_v_n,
    output wire vout32_v_p,
    input  wire pl_clk_p,
    input  wire pl_clk_n,
    input  wire pl_sys_ref_p,
    input  wire pl_sys_ref_n,
    input  wire pps_in,
    input  wire qsfp0_modprsl,
    input  wire qsfp0_intl,
    input  wire qsfp0_mgt_refclk_p,
    input  wire qsfp0_mgt_refclk_n,
    input  wire [3:0] qsfp0_rxp,
    input  wire [3:0] qsfp0_rxn,
    output wire [3:0] qsfp0_txp,
    output wire [3:0] qsfp0_txn,
    output wire qsfp0_resetl,
    output wire qsfp0_lpmode,
    output wire qsfp0_modsell,
    output wire clk_main_sel,
    inout  wire lmk_sync,
    inout  wire iic_scl_io,
    inout  wire iic_sda_io,
    output wire iic_rst_n,
    output wire pl_led0,
    output wire pl_led1,
    output wire pl_led2,
    output wire pl_led3
);

    wire adc_m_axis_clk;
    wire dac_s_axis_clk;
    wire ctrl_clk;
    wire data_rst_n;
    wire ctrl_rst_n;

    wire [63:0] m00_axis_tdata;
    wire        m00_axis_tready;
    wire        m00_axis_tvalid;
    wire [63:0] m01_axis_tdata;
    wire        m01_axis_tready;
    wire        m01_axis_tvalid;
    wire [63:0] m02_axis_tdata;
    wire        m02_axis_tready;
    wire        m02_axis_tvalid;
    wire [63:0] m03_axis_tdata;
    wire        m03_axis_tready;
    wire        m03_axis_tvalid;
    wire [63:0] m10_axis_tdata;
    wire        m10_axis_tready;
    wire        m10_axis_tvalid;
    wire [63:0] m11_axis_tdata;
    wire        m11_axis_tready;
    wire        m11_axis_tvalid;
    wire [63:0] m12_axis_tdata;
    wire        m12_axis_tready;
    wire        m12_axis_tvalid;
    wire [63:0] m13_axis_tdata;
    wire        m13_axis_tready;
    wire        m13_axis_tvalid;
    wire [63:0] m20_axis_tdata;
    wire        m20_axis_tready;
    wire        m20_axis_tvalid;
    wire [63:0] m21_axis_tdata;
    wire        m21_axis_tready;
    wire        m21_axis_tvalid;
    wire [63:0] m22_axis_tdata;
    wire        m22_axis_tready;
    wire        m22_axis_tvalid;
    wire [63:0] m23_axis_tdata;
    wire        m23_axis_tready;
    wire        m23_axis_tvalid;
    wire [63:0] m30_axis_tdata;
    wire        m30_axis_tready;
    wire        m30_axis_tvalid;
    wire [63:0] m31_axis_tdata;
    wire        m31_axis_tready;
    wire        m31_axis_tvalid;
    wire [63:0] m32_axis_tdata;
    wire        m32_axis_tready;
    wire        m32_axis_tvalid;
    wire [63:0] m33_axis_tdata;
    wire        m33_axis_tready;
    wire        m33_axis_tvalid;

    wire [127:0] s00_axis_tdata;
    wire         s00_axis_tready;
    wire         s00_axis_tvalid;
    wire [127:0] s02_axis_tdata;
    wire         s02_axis_tready;
    wire         s02_axis_tvalid;
    wire [127:0] s10_axis_tdata;
    wire         s10_axis_tready;
    wire         s10_axis_tvalid;
    wire [127:0] s12_axis_tdata;
    wire         s12_axis_tready;
    wire         s12_axis_tvalid;
    wire [127:0] s20_axis_tdata;
    wire         s20_axis_tready;
    wire         s20_axis_tvalid;
    wire [127:0] s22_axis_tdata;
    wire         s22_axis_tready;
    wire         s22_axis_tvalid;
    wire [127:0] s30_axis_tdata;
    wire         s30_axis_tready;
    wire         s30_axis_tvalid;
    wire [127:0] s32_axis_tdata;
    wire         s32_axis_tready;
    wire         s32_axis_tvalid;

    wire [39:0] core_s_axi_awaddr_full;
    wire [39:0] core_s_axi_araddr_full;
    (* keep = "true" *) wire [17:0] core_s_axi_awaddr_offset;
    (* keep = "true" *) wire [17:0] core_s_axi_araddr_offset;
    wire        core_s_axi_awvalid;
    wire        core_s_axi_awready;
    wire [1:0]  core_s_axi_awburst;
    wire [3:0]  core_s_axi_awcache;
    wire [15:0] core_s_axi_awid;
    wire [7:0]  core_s_axi_awlen;
    wire        core_s_axi_awlock;
    wire [2:0]  core_s_axi_awprot;
    wire [3:0]  core_s_axi_awqos;
    wire [3:0]  core_s_axi_awregion;
    wire [2:0]  core_s_axi_awsize;
    wire [15:0] core_s_axi_awuser;
    wire [31:0] core_s_axi_wdata;
    wire [3:0]  core_s_axi_wstrb;
    wire        core_s_axi_wvalid;
    wire        core_s_axi_wready;
    wire        core_s_axi_wlast;
    wire [1:0]  core_s_axi_bresp;
    wire        core_s_axi_bvalid;
    wire        core_s_axi_bready;
    wire        core_s_axi_arvalid;
    wire        core_s_axi_arready;
    wire [1:0]  core_s_axi_arburst;
    wire [3:0]  core_s_axi_arcache;
    wire [15:0] core_s_axi_arid;
    wire [7:0]  core_s_axi_arlen;
    wire        core_s_axi_arlock;
    wire [2:0]  core_s_axi_arprot;
    wire [3:0]  core_s_axi_arqos;
    wire [3:0]  core_s_axi_arregion;
    wire [2:0]  core_s_axi_arsize;
    wire [15:0] core_s_axi_aruser;
    wire [31:0] core_s_axi_rdata;
    wire [1:0]  core_s_axi_rresp;
    wire        core_s_axi_rvalid;
    wire        core_s_axi_rready;
    wire [15:0] core_s_axi_bid;
    wire [15:0] core_s_axi_rid;
    wire        core_s_axi_rlast;

    wire [17:0] core_axil_awaddr_offset;
    wire [17:0] core_axil_araddr_offset;
    wire [31:0] core_axil_awaddr;
    wire        core_axil_awvalid;
    wire        core_axil_awready;
    wire [31:0] core_axil_wdata;
    wire [3:0]  core_axil_wstrb;
    wire        core_axil_wvalid;
    wire        core_axil_wready;
    wire [1:0]  core_axil_bresp;
    wire        core_axil_bvalid;
    wire        core_axil_bready;
    wire [31:0] core_axil_araddr;
    wire        core_axil_arvalid;
    wire        core_axil_arready;
    wire [31:0] core_axil_rdata;
    wire [1:0]  core_axil_rresp;
    wire        core_axil_rvalid;
    wire        core_axil_rready;

    wire [1023:0] adc_axis_tdata;
    wire [31:0]  adc_axis_tuser;
    wire [63:0]  adc_axis_sample0;
    wire         adc_axis_tvalid;
    wire         adc_axis_tlast;
    wire         adc_axis_tready;
    wire [255:0] adc_preview_tdata0;
    wire [255:0] adc_preview_tdata1;
    wire [255:0] adc_preview_tdata2;
    wire [255:0] adc_preview_tdata3;
    wire [63:0]  adc_preview_sample0;
    wire         adc_preview_tvalid;
    wire [255:0] adc_raw_preview_tdata0;
    wire [255:0] adc_raw_preview_tdata1;
    wire [255:0] adc_raw_preview_tdata2;
    wire [255:0] adc_raw_preview_tdata3;
    wire [63:0]  adc_raw_preview_sample0;
    wire         adc_raw_preview_tvalid;
    wire         all_adc_valid;
    wire [63:0]  rfdc_sample_count;
    wire [31:0]  rfdc_dropped_count;
    wire [15:0]  rfdc_active_port_mask;
    wire [15:0]  rfdc_current_valid_mask;
    wire [15:0]  rfdc_seen_valid_mask;

    wire [63:0] core_tx_tdata;
    wire [7:0]  core_tx_tkeep;
    wire        core_tx_tvalid;
    wire        core_tx_tlast;
    wire        cmac_tx_clk;
    wire        cmac_tx_rst_n;
    wire [511:0] cmac_tx_axis_tdata;
    wire [63:0]  cmac_tx_axis_tkeep;
    wire          cmac_tx_axis_tvalid;
    wire          cmac_tx_axis_tlast;
    wire          cmac_tx_axis_tready;
    wire [5:0]    time_ddr_s_axi_awid;
    wire [39:0]   time_ddr_core_awaddr;
    wire [48:0]   time_ddr_s_axi_awaddr;
    wire [7:0]    time_ddr_s_axi_awlen;
    wire [2:0]    time_ddr_s_axi_awsize;
    wire [1:0]    time_ddr_s_axi_awburst;
    wire          time_ddr_s_axi_awlock;
    wire [3:0]    time_ddr_s_axi_awcache;
    wire [2:0]    time_ddr_s_axi_awprot;
    wire [3:0]    time_ddr_s_axi_awqos;
    wire          time_ddr_s_axi_awvalid;
    wire          time_ddr_s_axi_awready;
    wire [127:0]  time_ddr_s_axi_wdata;
    wire [15:0]   time_ddr_s_axi_wstrb;
    wire          time_ddr_s_axi_wlast;
    wire          time_ddr_s_axi_wvalid;
    wire          time_ddr_s_axi_wready;
    wire [5:0]    time_ddr_s_axi_bid;
    wire [1:0]    time_ddr_s_axi_bresp;
    wire          time_ddr_s_axi_bvalid;
    wire          time_ddr_s_axi_bready;
    wire [5:0]    time_ddr_s_axi_arid;
    wire [39:0]   time_ddr_core_araddr;
    wire [48:0]   time_ddr_s_axi_araddr;
    wire [7:0]    time_ddr_s_axi_arlen;
    wire [2:0]    time_ddr_s_axi_arsize;
    wire [1:0]    time_ddr_s_axi_arburst;
    wire          time_ddr_s_axi_arlock;
    wire [3:0]    time_ddr_s_axi_arcache;
    wire [2:0]    time_ddr_s_axi_arprot;
    wire [3:0]    time_ddr_s_axi_arqos;
    wire          time_ddr_s_axi_arvalid;
    wire          time_ddr_s_axi_arready;
    wire [5:0]    time_ddr_s_axi_rid;
    wire [127:0]  time_ddr_s_axi_rdata;
    wire [1:0]    time_ddr_s_axi_rresp;
    wire          time_ddr_s_axi_rlast;
    wire          time_ddr_s_axi_rvalid;
    wire          time_ddr_s_axi_rready;
    wire          cmac_gt_refclk_seen;
    wire          cmac_gt_powergood;
    wire          cmac_gt_tx_reset_done;
    wire          cmac_gt_rx_reset_done;
    wire          cmac_gt_locked;
    wire          cmac_reset_done;
    wire          cmac_tx_ready;
    wire          cmac_local_fault;
    wire          cmac_remote_fault;
    wire          cmac_link_up;
    wire          cmac_tx_underflow;
    wire          cmac_tx_overflow;
    wire          cmac_rx_aligned;
    wire          cmac_rx_status;
    wire          cmac_rx_local_fault;
    wire          cmac_rx_internal_local_fault;
    wire          cmac_tx_local_fault_detail;
    wire          cmac_an_autoneg_complete;
    wire          cmac_an_lp_ability_valid;
    wire          cmac_an_lp_autoneg_able;
    wire          cmac_an_lp_ability_100gbase_cr4;
    wire          cmac_an_rs_fec_enable;
    wire [3:0]    cmac_lt_signal_detect;
    wire [3:0]    cmac_lt_training;
    wire [3:0]    cmac_lt_training_fail;
    wire [3:0]    cmac_lt_frame_lock;
    wire        core_irq;
    wire        all_dac_ready;
    wire        core_dac_tone_enable;
    wire [15:0] core_dac_tone_amplitude;
    wire [31:0] core_dac_tone_phase_step;
    wire [7:0]  core_dac_enable_mask;
    wire [127:0] core_dac_tone_amplitude_vec;
    wire [255:0] core_dac_tone_phase_step_vec;
    wire [255:0] core_dac_tone_phase0_vec;
    wire [255:0] core_dac_tone_phase_inject_vec;
    wire [15:0]  core_dac_tone_mode_vec;
    wire [31:0]  core_dac_phase_epoch;
    wire         core_diag_adc_force_zero;
    wire         core_diag_adc_force_hold;
    wire [7:0]  core_diag_adc_channel_mask;
    wire         core_diag_dac_gate;
    wire         core_dac_tx_witness_arm_pulse;
    wire         core_dac_tx_witness_clear_pulse;
    wire [8:0]   core_dac_tx_witness_capture_words;
    wire [9:0]   core_dac_tx_witness_rd_word;
    wire [31:0]  dac_audit_phase_epoch_seen_raw;
    wire [31:0]  dac_audit_ch0_phase_acc_raw;
    wire [31:0]  dac_audit_ch0_phase_step_raw;
    wire [31:0]  dac_audit_ch0_phase0_raw;
    wire [31:0]  dac_audit_ch0_mode_raw;
    wire         dac_tx_witness_armed_ctrl;
    wire         dac_tx_witness_valid_ctrl;
    wire         dac_tx_witness_capturing_ctrl;
    wire         dac_tx_witness_overflow_ctrl;
    wire         dac_tx_witness_tvalid_seen_ctrl;
    wire         dac_tx_witness_tready_seen_ctrl;
    wire         dac_tx_witness_ready_gap_seen_ctrl;
    wire [8:0]   dac_tx_witness_word_count_ctrl;
    wire [31:0]  dac_tx_witness_phase_epoch_ctrl;
    wire [31:0]  dac_tx_witness_phase_acc_ctrl;
    wire [31:0]  dac_tx_witness_phase_step_ctrl;
    wire [31:0]  dac_tx_witness_phase0_ctrl;
    wire [31:0]  dac_tx_witness_mode_ctrl;
    wire [31:0]  dac_tx_witness_ready_gap_count_ctrl;
    wire [31:0]  dac_tx_witness_rd_data_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_phase_epoch_seen_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_phase_epoch_seen_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase_acc_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase_acc_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase_step_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase_step_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase0_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_phase0_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_mode_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_audit_ch0_mode_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   dac_enable_mask_meta = 8'hff;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   dac_enable_mask_sync = 8'hff;
    (* ASYNC_REG = "TRUE" *) logic [127:0] dac_tone_amplitude_vec_meta = {8{16'd2048}};
    (* ASYNC_REG = "TRUE" *) logic [127:0] dac_tone_amplitude_vec_sync = {8{16'd2048}};
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase_step_vec_meta = {8{32'h0080_0000}};
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase_step_vec_sync = {8{32'h0080_0000}};
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase0_vec_meta = 256'd0;
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase0_vec_sync = 256'd0;
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase_inject_vec_meta = 256'd0;
    (* ASYNC_REG = "TRUE" *) logic [255:0] dac_tone_phase_inject_vec_sync = 256'd0;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  dac_tone_mode_vec_meta = 16'd0;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  dac_tone_mode_vec_sync = 16'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  dac_phase_epoch_meta = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  dac_phase_epoch_sync = 32'd0;
    (* ASYNC_REG = "TRUE" *) logic         diag_adc_force_zero_meta = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic         diag_adc_force_zero_sync = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic         diag_adc_force_hold_meta = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic         diag_adc_force_hold_sync = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   diag_adc_channel_mask_meta = 8'hff;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   diag_adc_channel_mask_sync = 8'hff;
    (* ASYNC_REG = "TRUE" *) logic         diag_dac_gate_meta = 1'b0;
    (* ASYNC_REG = "TRUE" *) logic         diag_dac_gate_sync = 1'b0;

    localparam [27:0] PPS_RECENT_TIMEOUT_CYCLES = 28'd122_880_000;
    localparam [23:0] PPS_BLINK_CYCLES          = 24'd6_144_000;

    logic [27:0] heartbeat = 28'd0;
    logic [1:0]  pps_sync = 2'b00;
    logic        pps_d = 1'b0;
    logic        pps_seen_latched = 1'b0;
    logic [27:0] pps_age_cycles = PPS_RECENT_TIMEOUT_CYCLES;
    logic [23:0] pps_blink_cycles = 24'd0;
    logic        tx_activity_latched = 1'b0;
    logic [31:0] tx_word_count = 32'd0;
    logic [31:0] tx_packet_count = 32'd0;
    wire         qsfp0_module_present = !qsfp0_modprsl;
    wire [31:0]  tx_link_status_flags = {
        (&cmac_lt_frame_lock),
        (|cmac_lt_training_fail),
        (|cmac_lt_training),
        (&cmac_lt_signal_detect),
        cmac_an_rs_fec_enable,
        cmac_an_lp_ability_100gbase_cr4,
        cmac_an_lp_autoneg_able,
        cmac_an_lp_ability_valid,
        cmac_an_autoneg_complete,
        cmac_tx_local_fault_detail,
        cmac_rx_internal_local_fault,
        cmac_rx_local_fault,
        cmac_rx_status,
        cmac_rx_aligned,
        cmac_tx_overflow,
        cmac_tx_underflow,
        cmac_gt_rx_reset_done,
        cmac_gt_tx_reset_done,
        cmac_gt_refclk_seen,
        qsfp0_module_present,
        5'd0,
        cmac_remote_fault,
        cmac_local_fault,
        cmac_tx_ready,
        cmac_gt_locked,
        cmac_reset_done,
        1'b0,
        cmac_link_up
    };
    wire         ref_chain_locked = data_rst_n && all_dac_ready;
    wire         pps_recent = pps_seen_latched && (pps_age_cycles < PPS_RECENT_TIMEOUT_CYCLES);

    assign core_s_axi_awaddr_offset = core_s_axi_awaddr_full[17:0];
    assign core_s_axi_araddr_offset = core_s_axi_araddr_full[17:0];
    assign core_axil_awaddr = {14'd0, core_axil_awaddr_offset};
    assign core_axil_araddr = {14'd0, core_axil_araddr_offset};
    assign time_ddr_s_axi_awaddr = {9'd0, time_ddr_core_awaddr};
    assign time_ddr_s_axi_araddr = {9'd0, time_ddr_core_araddr};

    assign clk_main_sel   = 1'b0;
    assign iic_rst_n      = 1'b1;
    assign qsfp0_resetl   = 1'b1;
    assign qsfp0_lpmode   = 1'b0;
    assign qsfp0_modsell  = 1'b0;
    wire [7:0] dac_loopback_enable_mask = diag_dac_gate_sync ? 8'h00 : dac_enable_mask_sync;
    wire [127:0] dac_loopback_amplitude_vec = diag_dac_gate_sync ? 128'd0 : dac_tone_amplitude_vec_sync;

    always_ff @(posedge adc_m_axis_clk or negedge data_rst_n) begin
        if (!data_rst_n) begin
            heartbeat <= 28'd0;
            pps_sync <= 2'b00;
            pps_d <= 1'b0;
            pps_seen_latched <= 1'b0;
            pps_age_cycles <= PPS_RECENT_TIMEOUT_CYCLES;
            pps_blink_cycles <= 24'd0;
            tx_activity_latched <= 1'b0;
            tx_word_count <= 32'd0;
            tx_packet_count <= 32'd0;
        end else begin
            heartbeat <= heartbeat + 28'd1;
            pps_sync <= {pps_sync[0], pps_in};
            pps_d <= pps_sync[1];
            if (pps_sync[1] && !pps_d) begin
                pps_seen_latched <= 1'b1;
                pps_age_cycles <= 28'd0;
                pps_blink_cycles <= PPS_BLINK_CYCLES;
            end else begin
                if (pps_age_cycles != PPS_RECENT_TIMEOUT_CYCLES) begin
                    pps_age_cycles <= pps_age_cycles + 28'd1;
                end
                if (pps_blink_cycles != 24'd0) begin
                    pps_blink_cycles <= pps_blink_cycles - 24'd1;
                end
            end
            if (core_tx_tvalid) begin
                tx_activity_latched <= 1'b1;
                tx_word_count <= tx_word_count + 32'd1;
                if (core_tx_tlast) begin
                    tx_packet_count <= tx_packet_count + 32'd1;
                end
            end
        end
    end

    always_ff @(posedge dac_s_axis_clk or negedge data_rst_n) begin
        if (!data_rst_n) begin
            dac_enable_mask_meta <= 8'hff;
            dac_enable_mask_sync <= 8'hff;
            dac_tone_amplitude_vec_meta <= {8{16'd2048}};
            dac_tone_amplitude_vec_sync <= {8{16'd2048}};
            dac_tone_phase_step_vec_meta <= {8{32'h0080_0000}};
            dac_tone_phase_step_vec_sync <= {8{32'h0080_0000}};
            dac_tone_phase0_vec_meta <= 256'd0;
            dac_tone_phase0_vec_sync <= 256'd0;
            dac_tone_phase_inject_vec_meta <= 256'd0;
            dac_tone_phase_inject_vec_sync <= 256'd0;
            dac_tone_mode_vec_meta <= 16'd0;
            dac_tone_mode_vec_sync <= 16'd0;
            dac_phase_epoch_meta <= 32'd0;
            dac_phase_epoch_sync <= 32'd0;
            diag_dac_gate_meta <= 1'b0;
            diag_dac_gate_sync <= 1'b0;
        end else begin
            dac_enable_mask_meta <= core_dac_enable_mask;
            dac_enable_mask_sync <= dac_enable_mask_meta;
            dac_tone_amplitude_vec_meta <= core_dac_tone_amplitude_vec;
            dac_tone_amplitude_vec_sync <= dac_tone_amplitude_vec_meta;
            dac_tone_phase_step_vec_meta <= core_dac_tone_phase_step_vec;
            dac_tone_phase_step_vec_sync <= dac_tone_phase_step_vec_meta;
            dac_tone_phase0_vec_meta <= core_dac_tone_phase0_vec;
            dac_tone_phase0_vec_sync <= dac_tone_phase0_vec_meta;
            dac_tone_phase_inject_vec_meta <= core_dac_tone_phase_inject_vec;
            dac_tone_phase_inject_vec_sync <= dac_tone_phase_inject_vec_meta;
            dac_tone_mode_vec_meta <= core_dac_tone_mode_vec;
            dac_tone_mode_vec_sync <= dac_tone_mode_vec_meta;
            dac_phase_epoch_meta <= core_dac_phase_epoch;
            dac_phase_epoch_sync <= dac_phase_epoch_meta;
            diag_dac_gate_meta <= core_diag_dac_gate;
            diag_dac_gate_sync <= diag_dac_gate_meta;
        end
    end

    always_ff @(posedge adc_m_axis_clk or negedge data_rst_n) begin
        if (!data_rst_n) begin
            diag_adc_force_zero_meta <= 1'b0;
            diag_adc_force_zero_sync <= 1'b0;
            diag_adc_force_hold_meta <= 1'b0;
            diag_adc_force_hold_sync <= 1'b0;
            diag_adc_channel_mask_meta <= 8'hff;
            diag_adc_channel_mask_sync <= 8'hff;
        end else begin
            diag_adc_force_zero_meta <= core_diag_adc_force_zero;
            diag_adc_force_zero_sync <= diag_adc_force_zero_meta;
            diag_adc_force_hold_meta <= core_diag_adc_force_hold;
            diag_adc_force_hold_sync <= diag_adc_force_hold_meta;
            diag_adc_channel_mask_meta <= core_diag_adc_channel_mask;
            diag_adc_channel_mask_sync <= diag_adc_channel_mask_meta;
        end
    end

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            dac_audit_phase_epoch_seen_meta <= 32'd0;
            dac_audit_phase_epoch_seen_sync <= 32'd0;
            dac_audit_ch0_phase_acc_meta <= 32'd0;
            dac_audit_ch0_phase_acc_sync <= 32'd0;
            dac_audit_ch0_phase_step_meta <= 32'd0;
            dac_audit_ch0_phase_step_sync <= 32'd0;
            dac_audit_ch0_phase0_meta <= 32'd0;
            dac_audit_ch0_phase0_sync <= 32'd0;
            dac_audit_ch0_mode_meta <= 32'd0;
            dac_audit_ch0_mode_sync <= 32'd0;
        end else begin
            dac_audit_phase_epoch_seen_meta <= dac_audit_phase_epoch_seen_raw;
            dac_audit_phase_epoch_seen_sync <= dac_audit_phase_epoch_seen_meta;
            dac_audit_ch0_phase_acc_meta <= dac_audit_ch0_phase_acc_raw;
            dac_audit_ch0_phase_acc_sync <= dac_audit_ch0_phase_acc_meta;
            dac_audit_ch0_phase_step_meta <= dac_audit_ch0_phase_step_raw;
            dac_audit_ch0_phase_step_sync <= dac_audit_ch0_phase_step_meta;
            dac_audit_ch0_phase0_meta <= dac_audit_ch0_phase0_raw;
            dac_audit_ch0_phase0_sync <= dac_audit_ch0_phase0_meta;
            dac_audit_ch0_mode_meta <= dac_audit_ch0_mode_raw;
            dac_audit_ch0_mode_sync <= dac_audit_ch0_mode_meta;
        end
    end

    t510_rfdc_bd_wrapper u_rfdc_bd (
        .adc1_clk_clk_n(adc1_clk_clk_n),
        .adc1_clk_clk_p(adc1_clk_clk_p),
        .adc_m_axis_clk(adc_m_axis_clk),
        .core_s_axi_araddr(core_s_axi_araddr_full),
        .core_s_axi_arburst(core_s_axi_arburst),
        .core_s_axi_arcache(core_s_axi_arcache),
        .core_s_axi_arid(core_s_axi_arid),
        .core_s_axi_arlen(core_s_axi_arlen),
        .core_s_axi_arlock(core_s_axi_arlock),
        .core_s_axi_arprot(core_s_axi_arprot),
        .core_s_axi_arqos(core_s_axi_arqos),
        .core_s_axi_arready(core_s_axi_arready),
        .core_s_axi_arregion(core_s_axi_arregion),
        .core_s_axi_arsize(core_s_axi_arsize),
        .core_s_axi_aruser(core_s_axi_aruser),
        .core_s_axi_arvalid(core_s_axi_arvalid),
        .core_s_axi_awaddr(core_s_axi_awaddr_full),
        .core_s_axi_awburst(core_s_axi_awburst),
        .core_s_axi_awcache(core_s_axi_awcache),
        .core_s_axi_awid(core_s_axi_awid),
        .core_s_axi_awlen(core_s_axi_awlen),
        .core_s_axi_awlock(core_s_axi_awlock),
        .core_s_axi_awprot(core_s_axi_awprot),
        .core_s_axi_awqos(core_s_axi_awqos),
        .core_s_axi_awready(core_s_axi_awready),
        .core_s_axi_awregion(core_s_axi_awregion),
        .core_s_axi_awsize(core_s_axi_awsize),
        .core_s_axi_awuser(core_s_axi_awuser),
        .core_s_axi_awvalid(core_s_axi_awvalid),
        .core_s_axi_bid(core_s_axi_bid),
        .core_s_axi_bready(core_s_axi_bready),
        .core_s_axi_bresp(core_s_axi_bresp),
        .core_s_axi_bvalid(core_s_axi_bvalid),
        .core_s_axi_rdata(core_s_axi_rdata),
        .core_s_axi_rid(core_s_axi_rid),
        .core_s_axi_rlast(core_s_axi_rlast),
        .core_s_axi_rready(core_s_axi_rready),
        .core_s_axi_rresp(core_s_axi_rresp),
        .core_s_axi_rvalid(core_s_axi_rvalid),
        .core_s_axi_wdata(core_s_axi_wdata),
        .core_s_axi_wlast(core_s_axi_wlast),
        .core_s_axi_wready(core_s_axi_wready),
        .core_s_axi_wstrb(core_s_axi_wstrb),
        .core_s_axi_wvalid(core_s_axi_wvalid),
        .time_ddr_s_axi_aclk(cmac_tx_clk),
        .time_ddr_s_axi_araddr(time_ddr_s_axi_araddr),
        .time_ddr_s_axi_arburst(time_ddr_s_axi_arburst),
        .time_ddr_s_axi_arcache(time_ddr_s_axi_arcache),
        .time_ddr_s_axi_arid(time_ddr_s_axi_arid),
        .time_ddr_s_axi_arlen(time_ddr_s_axi_arlen),
        .time_ddr_s_axi_arlock(time_ddr_s_axi_arlock),
        .time_ddr_s_axi_arprot(time_ddr_s_axi_arprot),
        .time_ddr_s_axi_arqos(time_ddr_s_axi_arqos),
        .time_ddr_s_axi_arready(time_ddr_s_axi_arready),
        .time_ddr_s_axi_arsize(time_ddr_s_axi_arsize),
        .time_ddr_s_axi_aruser(1'b0),
        .time_ddr_s_axi_arvalid(time_ddr_s_axi_arvalid),
        .time_ddr_s_axi_awaddr(time_ddr_s_axi_awaddr),
        .time_ddr_s_axi_awburst(time_ddr_s_axi_awburst),
        .time_ddr_s_axi_awcache(time_ddr_s_axi_awcache),
        .time_ddr_s_axi_awid(time_ddr_s_axi_awid),
        .time_ddr_s_axi_awlen(time_ddr_s_axi_awlen),
        .time_ddr_s_axi_awlock(time_ddr_s_axi_awlock),
        .time_ddr_s_axi_awprot(time_ddr_s_axi_awprot),
        .time_ddr_s_axi_awqos(time_ddr_s_axi_awqos),
        .time_ddr_s_axi_awready(time_ddr_s_axi_awready),
        .time_ddr_s_axi_awsize(time_ddr_s_axi_awsize),
        .time_ddr_s_axi_awuser(1'b0),
        .time_ddr_s_axi_awvalid(time_ddr_s_axi_awvalid),
        .time_ddr_s_axi_bid(time_ddr_s_axi_bid),
        .time_ddr_s_axi_bready(time_ddr_s_axi_bready),
        .time_ddr_s_axi_bresp(time_ddr_s_axi_bresp),
        .time_ddr_s_axi_bvalid(time_ddr_s_axi_bvalid),
        .time_ddr_s_axi_rdata(time_ddr_s_axi_rdata),
        .time_ddr_s_axi_rid(time_ddr_s_axi_rid),
        .time_ddr_s_axi_rlast(time_ddr_s_axi_rlast),
        .time_ddr_s_axi_rready(time_ddr_s_axi_rready),
        .time_ddr_s_axi_rresp(time_ddr_s_axi_rresp),
        .time_ddr_s_axi_rvalid(time_ddr_s_axi_rvalid),
        .time_ddr_s_axi_wdata(time_ddr_s_axi_wdata),
        .time_ddr_s_axi_wlast(time_ddr_s_axi_wlast),
        .time_ddr_s_axi_wready(time_ddr_s_axi_wready),
        .time_ddr_s_axi_wstrb(time_ddr_s_axi_wstrb),
        .time_ddr_s_axi_wvalid(time_ddr_s_axi_wvalid),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .dac2_clk_clk_n(dac2_clk_clk_n),
        .dac2_clk_clk_p(dac2_clk_clk_p),
        .dac_s_axis_clk(dac_s_axis_clk),
        .data_rst_n(data_rst_n),
        .emio_tri_io(lmk_sync),
        .iic_scl_io(iic_scl_io),
        .iic_sda_io(iic_sda_io),
        .m00_axis_tdata(m00_axis_tdata),
        .m00_axis_tready(m00_axis_tready),
        .m00_axis_tvalid(m00_axis_tvalid),
        .m01_axis_tdata(m01_axis_tdata),
        .m01_axis_tready(m01_axis_tready),
        .m01_axis_tvalid(m01_axis_tvalid),
        .m02_axis_tdata(m02_axis_tdata),
        .m02_axis_tready(m02_axis_tready),
        .m02_axis_tvalid(m02_axis_tvalid),
        .m03_axis_tdata(m03_axis_tdata),
        .m03_axis_tready(m03_axis_tready),
        .m03_axis_tvalid(m03_axis_tvalid),
        .m10_axis_tdata(m10_axis_tdata),
        .m10_axis_tready(m10_axis_tready),
        .m10_axis_tvalid(m10_axis_tvalid),
        .m11_axis_tdata(m11_axis_tdata),
        .m11_axis_tready(m11_axis_tready),
        .m11_axis_tvalid(m11_axis_tvalid),
        .m12_axis_tdata(m12_axis_tdata),
        .m12_axis_tready(m12_axis_tready),
        .m12_axis_tvalid(m12_axis_tvalid),
        .m13_axis_tdata(m13_axis_tdata),
        .m13_axis_tready(m13_axis_tready),
        .m13_axis_tvalid(m13_axis_tvalid),
        .m20_axis_tdata(m20_axis_tdata),
        .m20_axis_tready(m20_axis_tready),
        .m20_axis_tvalid(m20_axis_tvalid),
        .m21_axis_tdata(m21_axis_tdata),
        .m21_axis_tready(m21_axis_tready),
        .m21_axis_tvalid(m21_axis_tvalid),
        .m22_axis_tdata(m22_axis_tdata),
        .m22_axis_tready(m22_axis_tready),
        .m22_axis_tvalid(m22_axis_tvalid),
        .m23_axis_tdata(m23_axis_tdata),
        .m23_axis_tready(m23_axis_tready),
        .m23_axis_tvalid(m23_axis_tvalid),
        .m30_axis_tdata(m30_axis_tdata),
        .m30_axis_tready(m30_axis_tready),
        .m30_axis_tvalid(m30_axis_tvalid),
        .m31_axis_tdata(m31_axis_tdata),
        .m31_axis_tready(m31_axis_tready),
        .m31_axis_tvalid(m31_axis_tvalid),
        .m32_axis_tdata(m32_axis_tdata),
        .m32_axis_tready(m32_axis_tready),
        .m32_axis_tvalid(m32_axis_tvalid),
        .m33_axis_tdata(m33_axis_tdata),
        .m33_axis_tready(m33_axis_tready),
        .m33_axis_tvalid(m33_axis_tvalid),
        .pl_clk_n(pl_clk_n),
        .pl_clk_p(pl_clk_p),
        .pl_sys_ref_n(pl_sys_ref_n),
        .pl_sys_ref_p(pl_sys_ref_p),
        .s00_axis_tdata(s00_axis_tdata),
        .s00_axis_tready(s00_axis_tready),
        .s00_axis_tvalid(s00_axis_tvalid),
        .s02_axis_tdata(s02_axis_tdata),
        .s02_axis_tready(s02_axis_tready),
        .s02_axis_tvalid(s02_axis_tvalid),
        .s10_axis_tdata(s10_axis_tdata),
        .s10_axis_tready(s10_axis_tready),
        .s10_axis_tvalid(s10_axis_tvalid),
        .s12_axis_tdata(s12_axis_tdata),
        .s12_axis_tready(s12_axis_tready),
        .s12_axis_tvalid(s12_axis_tvalid),
        .s20_axis_tdata(s20_axis_tdata),
        .s20_axis_tready(s20_axis_tready),
        .s20_axis_tvalid(s20_axis_tvalid),
        .s22_axis_tdata(s22_axis_tdata),
        .s22_axis_tready(s22_axis_tready),
        .s22_axis_tvalid(s22_axis_tvalid),
        .s30_axis_tdata(s30_axis_tdata),
        .s30_axis_tready(s30_axis_tready),
        .s30_axis_tvalid(s30_axis_tvalid),
        .s32_axis_tdata(s32_axis_tdata),
        .s32_axis_tready(s32_axis_tready),
        .s32_axis_tvalid(s32_axis_tvalid),
        .sysref_in_diff_n(sysref_in_diff_n),
        .sysref_in_diff_p(sysref_in_diff_p),
        .vin0_01_v_n(vin0_01_v_n),
        .vin0_01_v_p(vin0_01_v_p),
        .vin0_23_v_n(vin0_23_v_n),
        .vin0_23_v_p(vin0_23_v_p),
        .vin1_01_v_n(vin1_01_v_n),
        .vin1_01_v_p(vin1_01_v_p),
        .vin1_23_v_n(vin1_23_v_n),
        .vin1_23_v_p(vin1_23_v_p),
        .vin2_01_v_n(vin2_01_v_n),
        .vin2_01_v_p(vin2_01_v_p),
        .vin2_23_v_n(vin2_23_v_n),
        .vin2_23_v_p(vin2_23_v_p),
        .vin3_01_v_n(vin3_01_v_n),
        .vin3_01_v_p(vin3_01_v_p),
        .vin3_23_v_n(vin3_23_v_n),
        .vin3_23_v_p(vin3_23_v_p),
        .vout00_v_n(vout00_v_n),
        .vout00_v_p(vout00_v_p),
        .vout02_v_n(vout02_v_n),
        .vout02_v_p(vout02_v_p),
        .vout10_v_n(vout10_v_n),
        .vout10_v_p(vout10_v_p),
        .vout12_v_n(vout12_v_n),
        .vout12_v_p(vout12_v_p),
        .vout20_v_n(vout20_v_n),
        .vout20_v_p(vout20_v_p),
        .vout22_v_n(vout22_v_n),
        .vout22_v_p(vout22_v_p),
        .vout30_v_n(vout30_v_n),
        .vout30_v_p(vout30_v_p),
        .vout32_v_n(vout32_v_n),
        .vout32_v_p(vout32_v_p)
    );

    t510_dac_loopback_source u_dac_loopback_source (
        .clk(dac_s_axis_clk),
        .rst_n(data_rst_n),
        .tone_enable_mask(dac_loopback_enable_mask),
        .tone_amplitude_vec(dac_loopback_amplitude_vec),
        .tone_phase_step_vec(dac_tone_phase_step_vec_sync),
        .tone_phase0_vec(dac_tone_phase0_vec_sync),
        .tone_phase_inject_vec(dac_tone_phase_inject_vec_sync),
        .tone_mode_vec(dac_tone_mode_vec_sync),
        .tone_phase_epoch(dac_phase_epoch_sync),
        .s00_axis_tdata(s00_axis_tdata),
        .s00_axis_tready(s00_axis_tready),
        .s00_axis_tvalid(s00_axis_tvalid),
        .s02_axis_tdata(s02_axis_tdata),
        .s02_axis_tready(s02_axis_tready),
        .s02_axis_tvalid(s02_axis_tvalid),
        .s10_axis_tdata(s10_axis_tdata),
        .s10_axis_tready(s10_axis_tready),
        .s10_axis_tvalid(s10_axis_tvalid),
        .s12_axis_tdata(s12_axis_tdata),
        .s12_axis_tready(s12_axis_tready),
        .s12_axis_tvalid(s12_axis_tvalid),
        .s20_axis_tdata(s20_axis_tdata),
        .s20_axis_tready(s20_axis_tready),
        .s20_axis_tvalid(s20_axis_tvalid),
        .s22_axis_tdata(s22_axis_tdata),
        .s22_axis_tready(s22_axis_tready),
        .s22_axis_tvalid(s22_axis_tvalid),
        .s30_axis_tdata(s30_axis_tdata),
        .s30_axis_tready(s30_axis_tready),
        .s30_axis_tvalid(s30_axis_tvalid),
        .s32_axis_tdata(s32_axis_tdata),
        .s32_axis_tready(s32_axis_tready),
        .s32_axis_tvalid(s32_axis_tvalid),
        .all_dac_ready(all_dac_ready),
        .audit_phase_epoch_seen(dac_audit_phase_epoch_seen_raw),
        .audit_ch0_phase_acc(dac_audit_ch0_phase_acc_raw),
        .audit_ch0_phase_step(dac_audit_ch0_phase_step_raw),
        .audit_ch0_phase0(dac_audit_ch0_phase0_raw),
        .audit_ch0_mode(dac_audit_ch0_mode_raw)
    );

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign dac_tx_witness_rd_data_ctrl = 32'd0;
    assign dac_tx_witness_armed_ctrl = 1'b0;
    assign dac_tx_witness_valid_ctrl = 1'b0;
    assign dac_tx_witness_capturing_ctrl = 1'b0;
    assign dac_tx_witness_overflow_ctrl = 1'b0;
    assign dac_tx_witness_tvalid_seen_ctrl = 1'b0;
    assign dac_tx_witness_tready_seen_ctrl = 1'b0;
    assign dac_tx_witness_ready_gap_seen_ctrl = 1'b0;
    assign dac_tx_witness_word_count_ctrl = 9'd0;
    assign dac_tx_witness_phase_epoch_ctrl = 32'd0;
    assign dac_tx_witness_phase_acc_ctrl = 32'd0;
    assign dac_tx_witness_phase_step_ctrl = 32'd0;
    assign dac_tx_witness_phase0_ctrl = 32'd0;
    assign dac_tx_witness_mode_ctrl = 32'd0;
    assign dac_tx_witness_ready_gap_count_ctrl = 32'd0;
`else
    dac_tx_witness_capture #(
        .DATA_W(128),
        .CAPTURE_WORDS(256)
    ) u_dac_tx_witness_capture (
        .clk(dac_s_axis_clk),
        .rst_n(data_rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(core_dac_tx_witness_arm_pulse),
        .clear_pulse_ctrl(core_dac_tx_witness_clear_pulse),
        .capture_words_ctrl(core_dac_tx_witness_capture_words),
        .s_axis_tdata(s00_axis_tdata),
        .s_axis_tvalid(s00_axis_tvalid),
        .s_axis_tready(s00_axis_tready),
        .phase_epoch(dac_audit_phase_epoch_seen_raw),
        .phase_acc(dac_audit_ch0_phase_acc_raw),
        .phase_step(dac_audit_ch0_phase_step_raw),
        .phase0(dac_audit_ch0_phase0_raw),
        .mode(dac_audit_ch0_mode_raw),
        .ctrl_rd_word(core_dac_tx_witness_rd_word),
        .ctrl_rd_data(dac_tx_witness_rd_data_ctrl),
        .ctrl_armed(dac_tx_witness_armed_ctrl),
        .ctrl_valid(dac_tx_witness_valid_ctrl),
        .ctrl_capturing(dac_tx_witness_capturing_ctrl),
        .ctrl_overflow(dac_tx_witness_overflow_ctrl),
        .ctrl_tvalid_seen(dac_tx_witness_tvalid_seen_ctrl),
        .ctrl_tready_seen(dac_tx_witness_tready_seen_ctrl),
        .ctrl_ready_gap_seen(dac_tx_witness_ready_gap_seen_ctrl),
        .ctrl_word_count(dac_tx_witness_word_count_ctrl),
        .ctrl_phase_epoch(dac_tx_witness_phase_epoch_ctrl),
        .ctrl_phase_acc(dac_tx_witness_phase_acc_ctrl),
        .ctrl_phase_step(dac_tx_witness_phase_step_ctrl),
        .ctrl_phase0(dac_tx_witness_phase0_ctrl),
        .ctrl_mode(dac_tx_witness_mode_ctrl),
        .ctrl_ready_gap_count(dac_tx_witness_ready_gap_count_ctrl)
    );
`endif

    rfdc_adc_axis_adapter u_rfdc_adc_axis_adapter (
        .clk(adc_m_axis_clk),
        .rst_n(data_rst_n),
        .m00_axis_tdata(m00_axis_tdata),
        .m00_axis_tready(m00_axis_tready),
        .m00_axis_tvalid(m00_axis_tvalid),
        .m01_axis_tdata(m01_axis_tdata),
        .m01_axis_tready(m01_axis_tready),
        .m01_axis_tvalid(m01_axis_tvalid),
        .m02_axis_tdata(m02_axis_tdata),
        .m02_axis_tready(m02_axis_tready),
        .m02_axis_tvalid(m02_axis_tvalid),
        .m03_axis_tdata(m03_axis_tdata),
        .m03_axis_tready(m03_axis_tready),
        .m03_axis_tvalid(m03_axis_tvalid),
        .m10_axis_tdata(m10_axis_tdata),
        .m10_axis_tready(m10_axis_tready),
        .m10_axis_tvalid(m10_axis_tvalid),
        .m11_axis_tdata(m11_axis_tdata),
        .m11_axis_tready(m11_axis_tready),
        .m11_axis_tvalid(m11_axis_tvalid),
        .m12_axis_tdata(m12_axis_tdata),
        .m12_axis_tready(m12_axis_tready),
        .m12_axis_tvalid(m12_axis_tvalid),
        .m13_axis_tdata(m13_axis_tdata),
        .m13_axis_tready(m13_axis_tready),
        .m13_axis_tvalid(m13_axis_tvalid),
        .m20_axis_tdata(m20_axis_tdata),
        .m20_axis_tready(m20_axis_tready),
        .m20_axis_tvalid(m20_axis_tvalid),
        .m21_axis_tdata(m21_axis_tdata),
        .m21_axis_tready(m21_axis_tready),
        .m21_axis_tvalid(m21_axis_tvalid),
        .m22_axis_tdata(m22_axis_tdata),
        .m22_axis_tready(m22_axis_tready),
        .m22_axis_tvalid(m22_axis_tvalid),
        .m23_axis_tdata(m23_axis_tdata),
        .m23_axis_tready(m23_axis_tready),
        .m23_axis_tvalid(m23_axis_tvalid),
        .m30_axis_tdata(m30_axis_tdata),
        .m30_axis_tready(m30_axis_tready),
        .m30_axis_tvalid(m30_axis_tvalid),
        .m31_axis_tdata(m31_axis_tdata),
        .m31_axis_tready(m31_axis_tready),
        .m31_axis_tvalid(m31_axis_tvalid),
        .m32_axis_tdata(m32_axis_tdata),
        .m32_axis_tready(m32_axis_tready),
        .m32_axis_tvalid(m32_axis_tvalid),
        .m33_axis_tdata(m33_axis_tdata),
        .m33_axis_tready(m33_axis_tready),
        .m33_axis_tvalid(m33_axis_tvalid),
        .active_port_mask(rfdc_active_port_mask),
        .diag_force_zero(diag_adc_force_zero_sync),
        .diag_force_hold(diag_adc_force_hold_sync),
        .diag_channel_mask(diag_adc_channel_mask_sync),
        .m_axis_tdata(adc_axis_tdata),
        .m_axis_tuser(adc_axis_tuser),
        .m_axis_sample0(adc_axis_sample0),
        .m_axis_tvalid(adc_axis_tvalid),
        .m_axis_tlast(adc_axis_tlast),
        .m_axis_tready(adc_axis_tready),
        .m_preview_tdata0(adc_preview_tdata0),
        .m_preview_tdata1(adc_preview_tdata1),
        .m_preview_tdata2(adc_preview_tdata2),
        .m_preview_tdata3(adc_preview_tdata3),
        .m_preview_sample0(adc_preview_sample0),
        .m_preview_tvalid(adc_preview_tvalid),
        .m_raw_preview_tdata0(adc_raw_preview_tdata0),
        .m_raw_preview_tdata1(adc_raw_preview_tdata1),
        .m_raw_preview_tdata2(adc_raw_preview_tdata2),
        .m_raw_preview_tdata3(adc_raw_preview_tdata3),
        .m_raw_preview_sample0(adc_raw_preview_sample0),
        .m_raw_preview_tvalid(adc_raw_preview_tvalid),
        .all_adc_valid(all_adc_valid),
        .current_valid_mask(rfdc_current_valid_mask),
        .seen_valid_mask(rfdc_seen_valid_mask),
        .sample_count(rfdc_sample_count),
        .dropped_count(rfdc_dropped_count)
    );

    axi4_to_axil_bridge #(
        .ADDR_W(18),
        .DATA_W(32),
        .ID_W(16)
    ) u_core_axi_bridge (
        .clk(ctrl_clk),
        .rst_n(ctrl_rst_n),
        .s_axi_awaddr(core_s_axi_awaddr_offset),
        .s_axi_awid(core_s_axi_awid),
        .s_axi_awlen(core_s_axi_awlen),
        .s_axi_awsize(core_s_axi_awsize),
        .s_axi_awburst(core_s_axi_awburst),
        .s_axi_awvalid(core_s_axi_awvalid),
        .s_axi_awready(core_s_axi_awready),
        .s_axi_wdata(core_s_axi_wdata),
        .s_axi_wstrb(core_s_axi_wstrb),
        .s_axi_wlast(core_s_axi_wlast),
        .s_axi_wvalid(core_s_axi_wvalid),
        .s_axi_wready(core_s_axi_wready),
        .s_axi_bid(core_s_axi_bid),
        .s_axi_bresp(core_s_axi_bresp),
        .s_axi_bvalid(core_s_axi_bvalid),
        .s_axi_bready(core_s_axi_bready),
        .s_axi_araddr(core_s_axi_araddr_offset),
        .s_axi_arid(core_s_axi_arid),
        .s_axi_arlen(core_s_axi_arlen),
        .s_axi_arsize(core_s_axi_arsize),
        .s_axi_arburst(core_s_axi_arburst),
        .s_axi_arvalid(core_s_axi_arvalid),
        .s_axi_arready(core_s_axi_arready),
        .s_axi_rid(core_s_axi_rid),
        .s_axi_rdata(core_s_axi_rdata),
        .s_axi_rresp(core_s_axi_rresp),
        .s_axi_rlast(core_s_axi_rlast),
        .s_axi_rvalid(core_s_axi_rvalid),
        .s_axi_rready(core_s_axi_rready),
        .m_axil_awaddr(core_axil_awaddr_offset),
        .m_axil_awvalid(core_axil_awvalid),
        .m_axil_awready(core_axil_awready),
        .m_axil_wdata(core_axil_wdata),
        .m_axil_wstrb(core_axil_wstrb),
        .m_axil_wvalid(core_axil_wvalid),
        .m_axil_wready(core_axil_wready),
        .m_axil_bresp(core_axil_bresp),
        .m_axil_bvalid(core_axil_bvalid),
        .m_axil_bready(core_axil_bready),
        .m_axil_araddr(core_axil_araddr_offset),
        .m_axil_arvalid(core_axil_arvalid),
        .m_axil_arready(core_axil_arready),
        .m_axil_rdata(core_axil_rdata),
        .m_axil_rresp(core_axil_rresp),
        .m_axil_rvalid(core_axil_rvalid),
        .m_axil_rready(core_axil_rready)
    );

    t510_cmac_qsfp0 u_cmac_qsfp0 (
        .init_clk(ctrl_clk),
        .reset_n(ctrl_rst_n),
        .gt_ref_clk_p(qsfp0_mgt_refclk_p),
        .gt_ref_clk_n(qsfp0_mgt_refclk_n),
        .gt_rxp_in(qsfp0_rxp),
        .gt_rxn_in(qsfp0_rxn),
        .gt_txp_out(qsfp0_txp),
        .gt_txn_out(qsfp0_txn),
        .tx_clk(cmac_tx_clk),
        .tx_rst_n(cmac_tx_rst_n),
        .tx_axis_tdata(cmac_tx_axis_tdata),
        .tx_axis_tkeep(cmac_tx_axis_tkeep),
        .tx_axis_tvalid(cmac_tx_axis_tvalid),
        .tx_axis_tlast(cmac_tx_axis_tlast),
        .tx_axis_tready(cmac_tx_axis_tready),
        .gt_refclk_seen(cmac_gt_refclk_seen),
        .gt_powergood(cmac_gt_powergood),
        .gt_tx_reset_done(cmac_gt_tx_reset_done),
        .gt_rx_reset_done(cmac_gt_rx_reset_done),
        .gt_locked(cmac_gt_locked),
        .cmac_reset_done(cmac_reset_done),
        .cmac_tx_ready(cmac_tx_ready),
        .local_fault(cmac_local_fault),
        .remote_fault(cmac_remote_fault),
        .link_up(cmac_link_up),
        .tx_underflow(cmac_tx_underflow),
        .tx_overflow(cmac_tx_overflow),
        .rx_aligned(cmac_rx_aligned),
        .rx_status(cmac_rx_status),
        .rx_local_fault(cmac_rx_local_fault),
        .rx_internal_local_fault(cmac_rx_internal_local_fault),
        .tx_local_fault_detail(cmac_tx_local_fault_detail),
        .an_autoneg_complete(cmac_an_autoneg_complete),
        .an_lp_ability_valid(cmac_an_lp_ability_valid),
        .an_lp_autoneg_able(cmac_an_lp_autoneg_able),
        .an_lp_ability_100gbase_cr4(cmac_an_lp_ability_100gbase_cr4),
        .an_rs_fec_enable(cmac_an_rs_fec_enable),
        .lt_signal_detect(cmac_lt_signal_detect),
        .lt_training(cmac_lt_training),
        .lt_training_fail(cmac_lt_training_fail),
        .lt_frame_lock(cmac_lt_frame_lock)
    );

    t510_fengine_top u_core (
        .clk(adc_m_axis_clk),
        .rst_n(data_rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .pps_in(pps_sync[1]),
        .ref_lock_in(ref_chain_locked),
        .rfdc_ready_in(all_adc_valid),
        .s_axi_awaddr(core_axil_awaddr),
        .s_axi_awvalid(core_axil_awvalid),
        .s_axi_awready(core_axil_awready),
        .s_axi_wdata(core_axil_wdata),
        .s_axi_wstrb(core_axil_wstrb),
        .s_axi_wvalid(core_axil_wvalid),
        .s_axi_wready(core_axil_wready),
        .s_axi_bresp(core_axil_bresp),
        .s_axi_bvalid(core_axil_bvalid),
        .s_axi_bready(core_axil_bready),
        .s_axi_araddr(core_axil_araddr),
        .s_axi_arvalid(core_axil_arvalid),
        .s_axi_arready(core_axil_arready),
        .s_axi_rdata(core_axil_rdata),
        .s_axi_rresp(core_axil_rresp),
        .s_axi_rvalid(core_axil_rvalid),
        .s_axi_rready(core_axil_rready),
        .s_axis_adc_tdata(adc_axis_tdata),
        .s_axis_adc_tuser(adc_axis_tuser),
        .s_axis_adc_sample0(adc_axis_sample0),
        .s_axis_adc_tvalid(adc_axis_tvalid),
        .s_axis_adc_tlast(adc_axis_tlast),
        .s_axis_adc_tready(adc_axis_tready),
        .s_axis_preview_tdata0(adc_preview_tdata0),
        .s_axis_preview_tdata1(adc_preview_tdata1),
        .s_axis_preview_tdata2(adc_preview_tdata2),
        .s_axis_preview_tdata3(adc_preview_tdata3),
        .s_axis_preview_sample0(adc_preview_sample0),
        .s_axis_preview_tvalid(adc_preview_tvalid),
        .s_axis_raw_witness_tdata0(adc_raw_preview_tdata0),
        .s_axis_raw_witness_tdata1(adc_raw_preview_tdata1),
        .s_axis_raw_witness_tdata2(adc_raw_preview_tdata2),
        .s_axis_raw_witness_tdata3(adc_raw_preview_tdata3),
        .s_axis_raw_witness_sample0(adc_raw_preview_sample0),
        .s_axis_raw_witness_tvalid(adc_raw_preview_tvalid),
        .rfdc_status_flags({
            25'd0,
            pps_recent,
            pps_sync[1],
            pps_seen_latched,
            ref_chain_locked,
            all_dac_ready,
            all_adc_valid,
            adc_axis_tready
        }),
        .rfdc_sample_count(rfdc_sample_count),
        .rfdc_dropped_count(rfdc_dropped_count),
        .rfdc_current_valid_mask(rfdc_current_valid_mask),
        .rfdc_seen_valid_mask(rfdc_seen_valid_mask),
        .dac_audit_phase_epoch_seen(dac_audit_phase_epoch_seen_sync),
        .dac_audit_ch0_phase_acc(dac_audit_ch0_phase_acc_sync),
        .dac_audit_ch0_phase_step(dac_audit_ch0_phase_step_sync),
        .dac_audit_ch0_phase0(dac_audit_ch0_phase0_sync),
        .dac_audit_ch0_mode(dac_audit_ch0_mode_sync),
        .dac_tx_witness_armed(dac_tx_witness_armed_ctrl),
        .dac_tx_witness_valid(dac_tx_witness_valid_ctrl),
        .dac_tx_witness_capturing(dac_tx_witness_capturing_ctrl),
        .dac_tx_witness_overflow(dac_tx_witness_overflow_ctrl),
        .dac_tx_witness_tvalid_seen(dac_tx_witness_tvalid_seen_ctrl),
        .dac_tx_witness_tready_seen(dac_tx_witness_tready_seen_ctrl),
        .dac_tx_witness_ready_gap_seen(dac_tx_witness_ready_gap_seen_ctrl),
        .dac_tx_witness_word_count(dac_tx_witness_word_count_ctrl),
        .dac_tx_witness_phase_epoch(dac_tx_witness_phase_epoch_ctrl),
        .dac_tx_witness_phase_acc(dac_tx_witness_phase_acc_ctrl),
        .dac_tx_witness_phase_step(dac_tx_witness_phase_step_ctrl),
        .dac_tx_witness_phase0(dac_tx_witness_phase0_ctrl),
        .dac_tx_witness_mode(dac_tx_witness_mode_ctrl),
        .dac_tx_witness_ready_gap_count(dac_tx_witness_ready_gap_count_ctrl),
        .dac_tx_witness_rd_data(dac_tx_witness_rd_data_ctrl),
        .rfdc_active_port_mask(rfdc_active_port_mask),
        .m_axis_tx_tdata(core_tx_tdata),
        .m_axis_tx_tkeep(core_tx_tkeep),
        .m_axis_tx_tvalid(core_tx_tvalid),
        .m_axis_tx_tlast(core_tx_tlast),
        .m_axis_tx_tready(1'b1),
        .cmac_tx_clk(cmac_tx_clk),
        .cmac_tx_rst_n(cmac_tx_rst_n),
        .cmac_tx_axis_tdata(cmac_tx_axis_tdata),
        .cmac_tx_axis_tkeep(cmac_tx_axis_tkeep),
        .cmac_tx_axis_tvalid(cmac_tx_axis_tvalid),
        .cmac_tx_axis_tlast(cmac_tx_axis_tlast),
        .cmac_tx_axis_tready(cmac_tx_axis_tready),
        .m_axi_ddr_awid(time_ddr_s_axi_awid),
        .m_axi_ddr_awaddr(time_ddr_core_awaddr),
        .m_axi_ddr_awlen(time_ddr_s_axi_awlen),
        .m_axi_ddr_awsize(time_ddr_s_axi_awsize),
        .m_axi_ddr_awburst(time_ddr_s_axi_awburst),
        .m_axi_ddr_awlock(time_ddr_s_axi_awlock),
        .m_axi_ddr_awcache(time_ddr_s_axi_awcache),
        .m_axi_ddr_awprot(time_ddr_s_axi_awprot),
        .m_axi_ddr_awqos(time_ddr_s_axi_awqos),
        .m_axi_ddr_awvalid(time_ddr_s_axi_awvalid),
        .m_axi_ddr_awready(time_ddr_s_axi_awready),
        .m_axi_ddr_wdata(time_ddr_s_axi_wdata),
        .m_axi_ddr_wstrb(time_ddr_s_axi_wstrb),
        .m_axi_ddr_wlast(time_ddr_s_axi_wlast),
        .m_axi_ddr_wvalid(time_ddr_s_axi_wvalid),
        .m_axi_ddr_wready(time_ddr_s_axi_wready),
        .m_axi_ddr_bid(time_ddr_s_axi_bid),
        .m_axi_ddr_bresp(time_ddr_s_axi_bresp),
        .m_axi_ddr_bvalid(time_ddr_s_axi_bvalid),
        .m_axi_ddr_bready(time_ddr_s_axi_bready),
        .m_axi_ddr_arid(time_ddr_s_axi_arid),
        .m_axi_ddr_araddr(time_ddr_core_araddr),
        .m_axi_ddr_arlen(time_ddr_s_axi_arlen),
        .m_axi_ddr_arsize(time_ddr_s_axi_arsize),
        .m_axi_ddr_arburst(time_ddr_s_axi_arburst),
        .m_axi_ddr_arlock(time_ddr_s_axi_arlock),
        .m_axi_ddr_arcache(time_ddr_s_axi_arcache),
        .m_axi_ddr_arprot(time_ddr_s_axi_arprot),
        .m_axi_ddr_arqos(time_ddr_s_axi_arqos),
        .m_axi_ddr_arvalid(time_ddr_s_axi_arvalid),
        .m_axi_ddr_arready(time_ddr_s_axi_arready),
        .m_axi_ddr_rid(time_ddr_s_axi_rid),
        .m_axi_ddr_rdata(time_ddr_s_axi_rdata),
        .m_axi_ddr_rresp(time_ddr_s_axi_rresp),
        .m_axi_ddr_rlast(time_ddr_s_axi_rlast),
        .m_axi_ddr_rvalid(time_ddr_s_axi_rvalid),
        .m_axi_ddr_rready(time_ddr_s_axi_rready),
        .tx_link_status_flags(tx_link_status_flags),
        .tx_dry_run_packet_count(tx_packet_count),
        .tx_dry_run_byte_count(tx_word_count << 3),
        .dac_tone_enable(core_dac_tone_enable),
        .dac_tone_amplitude(core_dac_tone_amplitude),
        .dac_tone_phase_step(core_dac_tone_phase_step),
        .dac_enable_mask(core_dac_enable_mask),
        .dac_tone_amplitude_vec(core_dac_tone_amplitude_vec),
        .dac_tone_phase_step_vec(core_dac_tone_phase_step_vec),
        .dac_tone_phase0_vec(core_dac_tone_phase0_vec),
        .dac_tone_phase_inject_vec(core_dac_tone_phase_inject_vec),
        .dac_tone_mode_vec(core_dac_tone_mode_vec),
        .dac_phase_epoch(core_dac_phase_epoch),
        .diag_adc_force_zero(core_diag_adc_force_zero),
        .diag_adc_force_hold(core_diag_adc_force_hold),
        .diag_adc_channel_mask(core_diag_adc_channel_mask),
        .diag_dac_gate(core_diag_dac_gate),
        .dac_tx_witness_arm_pulse(core_dac_tx_witness_arm_pulse),
        .dac_tx_witness_clear_pulse(core_dac_tx_witness_clear_pulse),
        .dac_tx_witness_capture_words(core_dac_tx_witness_capture_words),
        .dac_tx_witness_rd_word(core_dac_tx_witness_rd_word),
        .irq(core_irq)
    );

    assign pl_led0 = ref_chain_locked;
    assign pl_led1 = (pps_blink_cycles != 24'd0);
    assign pl_led2 = pps_recent;
    assign pl_led3 = core_irq | !ref_chain_locked | !pps_recent;

endmodule

`default_nettype wire
