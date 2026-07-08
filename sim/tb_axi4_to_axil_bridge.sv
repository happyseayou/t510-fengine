`include "tb_common.svh"

module tb_axi4_to_axil_bridge;
    logic clk = 1'b0;
    logic rst_n = 1'b0;

    always #5 clk = ~clk;

    logic [31:0] s_awaddr = 32'd0;
    logic [15:0] s_awid = 16'd0;
    logic [7:0]  s_awlen = 8'd0;
    logic [2:0]  s_awsize = 3'd2;
    logic [1:0]  s_awburst = 2'b01;
    logic        s_awvalid = 1'b0;
    logic        s_awready;
    logic [31:0] s_wdata = 32'd0;
    logic [3:0]  s_wstrb = 4'hf;
    logic        s_wlast = 1'b0;
    logic        s_wvalid = 1'b0;
    logic        s_wready;
    logic [15:0] s_bid;
    logic [1:0]  s_bresp;
    logic        s_bvalid;
    logic        s_bready = 1'b0;
    logic [31:0] s_araddr = 32'd0;
    logic [15:0] s_arid = 16'd0;
    logic [7:0]  s_arlen = 8'd0;
    logic [2:0]  s_arsize = 3'd2;
    logic [1:0]  s_arburst = 2'b01;
    logic        s_arvalid = 1'b0;
    logic        s_arready;
    logic [15:0] s_rid;
    logic [31:0] s_rdata;
    logic [1:0]  s_rresp;
    logic        s_rlast;
    logic        s_rvalid;
    logic        s_rready = 1'b0;

    logic [31:0] m_awaddr;
    logic        m_awvalid;
    logic        m_awready;
    logic [31:0] m_wdata;
    logic [3:0]  m_wstrb;
    logic        m_wvalid;
    logic        m_wready;
    logic [1:0]  m_bresp;
    logic        m_bvalid;
    logic        m_bready;
    logic [31:0] m_araddr;
    logic        m_arvalid;
    logic        m_arready;
    logic [31:0] m_rdata;
    logic [1:0]  m_rresp;
    logic        m_rvalid;
    logic        m_rready;

    logic [15:0] board_id;
    logic [1:0]  mode;
    logic        arm_latched;
    logic        soft_epoch_pulse;
    logic        stop_pulse;
    logic        soft_reset_pulse;
    logic [1:0]  sync_mode;
    logic [1:0]  clock_ref;
    logic [31:0] sample_rate_hz;
    logic [15:0] quant_mode;
    logic [15:0] scale_mode;
    logic [31:0] scale_id;
    logic [15:0] time_payload_nsamp;
    logic [15:0] spec_time_count;
    logic [15:0] spec_chan_count;
    logic [31:0] chan_split;
    logic [31:0] src_ip;
    logic [31:0] dgx_a_ip;
    logic [31:0] dgx_b_ip;
    logic [31:0] time_dst_ip;
    logic [47:0] src_mac;
    logic [47:0] dgx_a_mac;
    logic [47:0] dgx_b_mac;
    logic [15:0] src_udp_port;
    logic [15:0] dgx_a_udp_port;
    logic [15:0] dgx_b_udp_port;
    logic [15:0] time_udp_port;
    logic [15:0] rfdc_active_mask;
    logic [63:0] unix_seconds;
    wire [4:0] tx_header_capture_rd_word;
    wire [31:0] tx_header_capture_rd_data;

    assign tx_header_capture_rd_data = 32'hdb00_0000 | {27'd0, tx_header_capture_rd_word};

    axi4_to_axil_bridge dut_bridge (
        .clk(clk),
        .rst_n(rst_n),
        .s_axi_awaddr(s_awaddr),
        .s_axi_awid(s_awid),
        .s_axi_awlen(s_awlen),
        .s_axi_awsize(s_awsize),
        .s_axi_awburst(s_awburst),
        .s_axi_awvalid(s_awvalid),
        .s_axi_awready(s_awready),
        .s_axi_wdata(s_wdata),
        .s_axi_wstrb(s_wstrb),
        .s_axi_wlast(s_wlast),
        .s_axi_wvalid(s_wvalid),
        .s_axi_wready(s_wready),
        .s_axi_bid(s_bid),
        .s_axi_bresp(s_bresp),
        .s_axi_bvalid(s_bvalid),
        .s_axi_bready(s_bready),
        .s_axi_araddr(s_araddr),
        .s_axi_arid(s_arid),
        .s_axi_arlen(s_arlen),
        .s_axi_arsize(s_arsize),
        .s_axi_arburst(s_arburst),
        .s_axi_arvalid(s_arvalid),
        .s_axi_arready(s_arready),
        .s_axi_rid(s_rid),
        .s_axi_rdata(s_rdata),
        .s_axi_rresp(s_rresp),
        .s_axi_rlast(s_rlast),
        .s_axi_rvalid(s_rvalid),
        .s_axi_rready(s_rready),
        .m_axil_awaddr(m_awaddr),
        .m_axil_awvalid(m_awvalid),
        .m_axil_awready(m_awready),
        .m_axil_wdata(m_wdata),
        .m_axil_wstrb(m_wstrb),
        .m_axil_wvalid(m_wvalid),
        .m_axil_wready(m_wready),
        .m_axil_bresp(m_bresp),
        .m_axil_bvalid(m_bvalid),
        .m_axil_bready(m_bready),
        .m_axil_araddr(m_araddr),
        .m_axil_arvalid(m_arvalid),
        .m_axil_arready(m_arready),
        .m_axil_rdata(m_rdata),
        .m_axil_rresp(m_rresp),
        .m_axil_rvalid(m_rvalid),
        .m_axil_rready(m_rready)
    );

    feng_ctrl_axi dut_ctrl (
        .s_axi_aclk(clk),
        .s_axi_aresetn(rst_n),
        .s_axi_awaddr(m_awaddr),
        .s_axi_awvalid(m_awvalid),
        .s_axi_awready(m_awready),
        .s_axi_wdata(m_wdata),
        .s_axi_wstrb(m_wstrb),
        .s_axi_wvalid(m_wvalid),
        .s_axi_wready(m_wready),
        .s_axi_bresp(m_bresp),
        .s_axi_bvalid(m_bvalid),
        .s_axi_bready(m_bready),
        .s_axi_araddr(m_araddr),
        .s_axi_arvalid(m_arvalid),
        .s_axi_arready(m_arready),
        .s_axi_rdata(m_rdata),
        .s_axi_rresp(m_rresp),
        .s_axi_rvalid(m_rvalid),
        .s_axi_rready(m_rready),
        .fsm_state(4'd0),
        .streaming(1'b0),
        .armed(1'b0),
        .active_sync_mode(2'd0),
        .waiting_for_epoch(1'b0),
        .pps_seen(1'b0),
        .pps_count(64'd0),
        .ref_locked(1'b1),
        .error_flags(32'd0),
        .monitor_sample_count(32'h1234_5678),
        .clip_counts(256'd0),
        .mean_mags(256'd0),
        .spec_packet_count(32'd0),
        .spec_udp_byte_count(32'd0),
        .time_packet_count(32'd0),
        .time_udp_byte_count(32'd0),
        .time_dropped_count(32'd0),
        .spec_dropped_count(32'd0),
        .spec_seq_no(32'd0),
        .time_seq_no(32'd0),
        .time_sample0(64'd0),
        .time_frame_id(64'd0),
        .spec_frame_id(64'd0),
        .spec_chan0(32'd0),
        .rfdc_status_flags(32'h0000_0015),
        .rfdc_sample_count(64'h0000_0000_0000_0055),
        .rfdc_dropped_count(32'd0),
        .rfdc_current_valid_mask(16'h0003),
        .rfdc_seen_valid_mask(16'h00ff),
        .science_dropped_beat_count(32'd0),
        .tx_link_status_flags(32'h0000_0002),
        .tx_dry_run_packet_count(32'd0),
        .tx_dry_run_byte_count(32'd0),
        .tx_fifo_level_words(32'd0),
        .tx_fifo_high_water_words(32'd0),
        .tx_fifo_backpressure_cycles(32'd0),
        .tx_preflight_status_flags(32'd0),
        .tx_frame_built_count(32'd0),
        .tx_frame_sent_count(32'd0),
        .tx_frame_dropped_count(32'd0),
        .tx_frame_byte_count(32'd0),
        .tx_route_miss_count(32'd0),
        .tx_route_error_count(32'd0),
        .tx_cmac_source_status(32'd0),
        .tx_selected_endpoint_id(8'd0),
        .tx_selected_route_id(6'd0),
        .tx_selected_route_is_time(1'b0),
        .tx_header_capture_armed(1'b0),
        .tx_header_capture_valid(1'b0),
        .tx_header_capture_word_count(5'd0),
        .tx_header_capture_rd_data(tx_header_capture_rd_data),
        .tx_frame_capture_armed(1'b0),
        .tx_frame_capture_valid(1'b0),
        .tx_frame_capture_word_count(5'd0),
        .tx_frame_capture_rd_data(32'd0),
        .tx_payload_witness_armed(1'b0),
        .tx_payload_witness_valid(1'b0),
        .tx_payload_witness_capturing(1'b0),
        .tx_payload_witness_word_count(11'd0),
        .tx_payload_witness_stream_type(16'd0),
        .tx_payload_witness_sample0(64'd0),
        .tx_payload_witness_frame_id(64'd0),
        .tx_payload_witness_seq_no(32'd0),
        .tx_payload_witness_chan0(32'd0),
        .tx_payload_witness_layout_word(64'd0),
        .tx_payload_witness_payload_bytes(32'd0),
        .tx_payload_witness_route_meta(32'd0),
        .tx_payload_witness_rfdc_flags(32'd0),
        .tx_payload_witness_rfdc_sample_count(64'd0),
        .tx_payload_witness_dac_phase_epoch(32'd0),
        .tx_payload_witness_overflow(1'b0),
        .tx_payload_witness_filter_mismatch(1'b0),
        .tx_payload_witness_rd_data(32'd0),
        .dac_tx_witness_armed(1'b0),
        .dac_tx_witness_valid(1'b0),
        .dac_tx_witness_capturing(1'b0),
        .dac_tx_witness_overflow(1'b0),
        .dac_tx_witness_tvalid_seen(1'b0),
        .dac_tx_witness_tready_seen(1'b0),
        .dac_tx_witness_ready_gap_seen(1'b0),
        .dac_tx_witness_word_count(9'd0),
        .dac_tx_witness_phase_epoch(32'd0),
        .dac_tx_witness_phase_acc(32'd0),
        .dac_tx_witness_phase_step(32'd0),
        .dac_tx_witness_phase0(32'd0),
        .dac_tx_witness_mode(32'd0),
        .dac_tx_witness_ready_gap_count(32'd0),
        .dac_tx_witness_rd_data(32'd0),
        .rfdc_axis_raw_witness_armed(1'b0),
        .rfdc_axis_raw_witness_valid(1'b0),
        .rfdc_axis_raw_witness_capturing(1'b0),
        .rfdc_axis_raw_witness_overflow(1'b0),
        .rfdc_axis_raw_witness_tvalid_seen(1'b0),
        .rfdc_axis_raw_witness_beat_count(9'd0),
        .rfdc_axis_raw_witness_channel_select(3'd0),
        .rfdc_axis_raw_witness_sample0(64'd0),
        .rfdc_axis_raw_witness_rfdc_flags(32'd0),
        .rfdc_axis_raw_witness_valid_mask(16'd0),
        .rfdc_axis_raw_witness_rd_data(32'd0),
        .tx_spec_route_hit_counts({64{32'd0}}),
        .tx_time_route_hit_counts({8{32'd0}}),
        .time_ddr_ring_status(32'd0),
        .time_ddr_ring_occupancy(32'd0),
        .time_ddr_ring_write_count(32'd0),
        .time_ddr_ring_read_count(32'd0),
        .time_ddr_ring_drop_count(32'd0),
        .time_ddr_ring_error_count(32'd0),
        .pfb_status(32'h0000_0003),
        .pfb_frame_count(32'd0),
        .pfb_overflow_count(32'd0),
        .pfb_data_halt_count(32'd0),
        .pfb_xfft_event_count(32'd0),
        .pfb_tile_overflow_count(32'd0),
        .pfb_xfft_tlast_unexpected_count(32'd0),
        .pfb_xfft_tlast_missing_count(32'd0),
        .pfb_xfft_fft_overflow_count(32'd0),
        .pfb_xfft_data_out_halt_count(32'd0),
        .pfb_xfft_status_halt_count(32'd0),
        .pfb_capture_backpressure_count(32'd0),
        .pfb_frame_sample0_overflow_count(32'd0),
        .pfb_input_fifo_level(32'd0),
        .pfb_peak_chan(32'd0),
        .pfb_peak_power(32'd0),
        .science_aa100_active(1'b0),
        .science_aa100_primed(1'b0),
        .science_aa100_coeff_version(32'hAA10_0041),
        .debug_busy(1'b0),
        .debug_done(1'b0),
        .debug_error(1'b0),
        .debug_capture_count(32'd0),
        .debug_peak_bin(32'd0),
        .debug_peak_power(32'd0),
        .debug_time_rd_data(32'd0),
        .debug_fft_rd_data(32'd0),
        .preview_busy(1'b0),
        .preview_done(1'b0),
        .preview_error(1'b0),
        .preview_capture_count(32'd0),
        .preview_sample0(64'd0),
        .preview_rd_data(32'd0),
        .preview_event_rd_data(32'd0),
        .preview_audit_status(32'd0),
        .preview_audit_start_count(32'd0),
        .preview_audit_first_count(32'd0),
        .preview_audit_done_count(32'd0),
        .preview_audit_start_sample0(64'd0),
        .preview_audit_first_sample0(64'd0),
        .preview_audit_done_sample0(64'd0),
        .preview_audit_start_to_first_latency(32'd0),
        .preview_audit_capture_beats(32'd0),
        .preview_audit_valid_gap_count(32'd0),
        .preview_audit_sample0_error_count(32'd0),
        .preview_event_sample0(64'd0),
        .preview_event_max_code(32'd0),
        .preview_event_info(32'd0),
        .preview_event_rfdc_flags(32'd0),
        .preview_event_dac_phase_epoch(32'd0),
        .dac_audit_phase_epoch_seen(32'd0),
        .dac_audit_ch0_phase_acc(32'd0),
        .dac_audit_ch0_phase_step(32'd0),
        .dac_audit_ch0_phase0(32'd0),
        .dac_audit_ch0_mode(32'd0),
        .board_id(board_id),
        .mode(mode),
        .arm_latched(arm_latched),
        .soft_epoch_pulse(soft_epoch_pulse),
        .stop_pulse(stop_pulse),
        .soft_reset_pulse(soft_reset_pulse),
        .sync_mode(sync_mode),
        .clock_ref(clock_ref),
        .sample_rate_hz(sample_rate_hz),
        .quant_mode(quant_mode),
        .scale_mode(scale_mode),
        .scale_id(scale_id),
        .time_payload_nsamp(time_payload_nsamp),
        .spec_time_count(spec_time_count),
        .spec_chan_count(spec_chan_count),
        .pfb_enable(),
        .pfb_clear_pulse(),
        .pfb_taps(),
        .pfb_fft_shift(),
        .pfb_chan0(),
        .pfb_chan_count(),
        .pfb_time_count(),
        .chan_split(chan_split),
        .src_ip(src_ip),
        .dgx_a_ip(dgx_a_ip),
        .dgx_b_ip(dgx_b_ip),
        .time_dst_ip(time_dst_ip),
        .src_mac(src_mac),
        .dgx_a_mac(dgx_a_mac),
        .dgx_b_mac(dgx_b_mac),
        .src_udp_port(src_udp_port),
        .dgx_a_udp_port(dgx_a_udp_port),
        .dgx_b_udp_port(dgx_b_udp_port),
        .time_udp_port(time_udp_port),
        .tx_control(),
        .tx_clear_pulse(),
        .tx_endpoint_enable(),
        .tx_endpoint_ip_vec(),
        .tx_endpoint_mac_vec(),
        .tx_endpoint_src_port_vec(),
        .tx_endpoint_dst_port_vec(),
        .qsfp_test_interval_cycles(),
        .tx_spec_route_enable(),
        .tx_spec_route_chan0_vec(),
        .tx_spec_route_chan_count_vec(),
        .tx_spec_route_endpoint_vec(),
        .tx_time_route_enable(),
        .tx_time_route_input_mask_vec(),
        .tx_time_route_endpoint_vec(),
        .rfdc_active_mask(rfdc_active_mask),
        .debug_capture_start_pulse(),
        .debug_capture_clear_pulse(),
        .debug_time_rd_addr(),
        .debug_fft_rd_addr(),
        .dac_tone_enable(),
        .dac_tone_amplitude(),
        .dac_tone_phase_step(),
        .dac_enable_mask(),
        .dac_tone_amplitude_vec(),
        .dac_tone_phase_step_vec(),
        .dac_tone_phase0_vec(),
        .dac_tone_phase_inject_vec(),
        .dac_tone_mode_vec(),
        .dac_phase_epoch(),
        .preview_capture_start_pulse(),
        .preview_capture_clear_pulse(),
        .preview_input_mask(),
        .preview_rd_input(),
        .preview_rd_addr(),
        .preview_audit_clear_pulse(),
        .preview_audit_source_select(),
        .preview_audit_event_enable(),
        .preview_audit_freeze_on_event(),
        .preview_audit_event_threshold(),
        .preview_event_rd_addr(),
        .tx_header_capture_arm_pulse(),
        .tx_header_capture_rd_word(tx_header_capture_rd_word),
        .tx_frame_capture_arm_pulse(),
        .tx_frame_capture_rd_word(),
        .tx_payload_witness_arm_pulse(),
        .tx_payload_witness_clear_pulse(),
        .tx_payload_witness_stream_filter(),
        .tx_payload_witness_capture_words(),
        .tx_payload_witness_rd_word(),
        .dac_tx_witness_arm_pulse(),
        .dac_tx_witness_clear_pulse(),
        .dac_tx_witness_capture_words(),
        .dac_tx_witness_rd_word(),
        .rfdc_axis_raw_witness_arm_pulse(),
        .rfdc_axis_raw_witness_clear_pulse(),
        .rfdc_axis_raw_witness_channel_select_ctrl(),
        .rfdc_axis_raw_witness_capture_beats(),
        .rfdc_axis_raw_witness_rd_word(),
        .unix_seconds(unix_seconds)
    );

    task automatic axi4_write_single(input [31:0] addr, input [31:0] data);
        begin
            @(posedge clk);
            s_awaddr  <= addr;
            s_awid    <= 16'h45;
            s_awlen   <= 8'd0;
            s_awsize  <= 3'd2;
            s_awburst <= 2'b01;
            s_awvalid <= 1'b1;
            wait (s_awready);
            @(posedge clk);
            s_awvalid <= 1'b0;

            s_wdata   <= data;
            s_wstrb   <= 4'hf;
            s_wlast   <= 1'b1;
            s_wvalid  <= 1'b1;
            wait (s_wready);
            @(posedge clk);
            s_wvalid <= 1'b0;
            s_wlast  <= 1'b0;

            s_bready <= 1'b1;
            wait (s_bvalid);
            `TB_CHECK_EQ(s_bresp, 2'b00, "AXI4 write response OKAY")
            `TB_CHECK_EQ(s_bid, 16'h45, "AXI4 write ID")
            @(posedge clk);
            s_bready <= 1'b0;
        end
    endtask

    task automatic axi4_read_single(input [31:0] addr, output [31:0] data);
        begin
            @(posedge clk);
            s_araddr  <= addr;
            s_arid    <= 16'h23;
            s_arlen   <= 8'd0;
            s_arsize  <= 3'd2;
            s_arburst <= 2'b01;
            s_arvalid <= 1'b1;
            wait (s_arready);
            @(posedge clk);
            s_arvalid <= 1'b0;

            s_rready <= 1'b1;
            do @(posedge clk); while (!s_rvalid);
            data = s_rdata;
            `TB_CHECK_EQ(s_rresp, 2'b00, "AXI4 read response OKAY")
            `TB_CHECK_EQ(s_rid, 16'h23, "AXI4 read ID")
            `TB_CHECK(s_rlast, "single-beat read has RLAST")
            s_rready <= 1'b0;
        end
    endtask

    task automatic axi4_read_burst4(input [31:0] addr, output [31:0] d0, output [31:0] d1, output [31:0] d2, output [31:0] d3);
        integer beat;
        begin
            @(posedge clk);
            s_araddr  <= addr;
            s_arid    <= 16'h67;
            s_arlen   <= 8'd3;
            s_arsize  <= 3'd2;
            s_arburst <= 2'b01;
            s_arvalid <= 1'b1;
            wait (s_arready);
            @(posedge clk);
            s_arvalid <= 1'b0;

            s_rready <= 1'b1;
            for (beat = 0; beat < 4; beat = beat + 1) begin
                do @(posedge clk); while (!s_rvalid);
                case (beat)
                    0: d0 = s_rdata;
                    1: d1 = s_rdata;
                    2: d2 = s_rdata;
                    default: d3 = s_rdata;
                endcase
                `TB_CHECK_EQ(s_rresp, 2'b00, "AXI4 burst read response OKAY")
                `TB_CHECK_EQ(s_rid, 16'h67, "AXI4 burst read ID")
                if (beat == 3) begin
                    `TB_CHECK(s_rlast, "final burst beat has RLAST")
                end else begin
                    `TB_CHECK(!s_rlast, "non-final burst beat does not have RLAST")
                end
            end
            s_rready <= 1'b0;
        end
    endtask

    initial begin
        logic [31:0] rd;
        logic [31:0] b0;
        logic [31:0] b1;
        logic [31:0] b2;
        logic [31:0] b3;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        axi4_read_single(32'h8004_0000, rd);
`ifdef T510_STAGE27I_ANTI_ALIAS
        `TB_CHECK_EQ(rd, 32'h0001_002b, "version via AXI4 bridge anti-alias candidate")
`else
        `TB_CHECK_EQ(rd, 32'h0001_0029, "version via AXI4 bridge")
`endif

        axi4_write_single(32'h8004_0004, 32'h0000_0510);
        axi4_read_single(32'h8004_0004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0510, "board_id via AXI4 bridge")

        axi4_write_single(32'h8004_0008, 32'h0000_0001);
        axi4_read_single(32'h8004_0008, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "mode via AXI4 bridge")

        axi4_read_single(32'h8004_00f0, rd);
        `TB_CHECK_EQ(rd, 32'h8004_00f0, "debug AR via AXI4 bridge")

        axi4_read_burst4(32'h8004_0000, b0, b1, b2, b3);
`ifdef T510_STAGE27I_ANTI_ALIAS
        `TB_CHECK_EQ(b0, 32'h0001_002b, "burst beat 0 version anti-alias candidate")
`else
        `TB_CHECK_EQ(b0, 32'h0001_0029, "burst beat 0 version")
`endif
        `TB_CHECK_EQ(b1, 32'h0000_0510, "burst beat 1 board_id")
        `TB_CHECK_EQ(b2, 32'h0000_0001, "burst beat 2 mode")
        `TB_CHECK_EQ(b3, 32'h0000_0000, "burst beat 3 control")

        `TB_PASS("tb_axi4_to_axil_bridge")
    end

endmodule
