`include "tb_common.svh"

module tb_feng_ctrl_axi;

    logic clk = 1'b0;
    logic rst_n = 1'b0;

    always #5 clk = ~clk;

    logic [31:0] s_axi_awaddr = 32'd0;
    logic        s_axi_awvalid = 1'b0;
    wire         s_axi_awready;
    logic [31:0] s_axi_wdata = 32'd0;
    logic [3:0]  s_axi_wstrb = 4'hf;
    logic        s_axi_wvalid = 1'b0;
    wire         s_axi_wready;
    wire [1:0]   s_axi_bresp;
    wire         s_axi_bvalid;
    logic        s_axi_bready = 1'b0;
    logic [31:0] s_axi_araddr = 32'd0;
    logic        s_axi_arvalid = 1'b0;
    wire         s_axi_arready;
    wire [31:0] s_axi_rdata;
    wire [1:0]  s_axi_rresp;
    wire        s_axi_rvalid;
    logic       s_axi_rready = 1'b0;

    logic [3:0]   fsm_state = 4'd0;
    logic         streaming = 1'b0;
    logic         armed = 1'b0;
    logic [1:0]   active_sync_mode = 2'd0;
    logic         waiting_for_epoch = 1'b0;
    logic         pps_seen = 1'b0;
    logic [63:0]  pps_count = 64'h0000_0001_0000_0002;
    logic         ref_locked = 1'b0;
    logic [31:0]  error_flags = 32'd0;
    logic [31:0]  monitor_sample_count = 32'd0;
    logic [255:0] clip_counts = 256'd0;
    logic [255:0] mean_mags = 256'd0;
    logic [31:0]  spec_packet_count = 32'd0;
    logic [31:0]  spec_udp_byte_count = 32'd0;
    logic [31:0]  time_packet_count = 32'd0;
    logic [31:0]  time_udp_byte_count = 32'd0;
    logic [31:0]  time_dropped_count = 32'd0;
    logic [31:0]  spec_seq_no = 32'd0;
    logic [31:0]  time_seq_no = 32'd0;
    logic [63:0]  time_sample0 = 64'd0;
    logic [63:0]  time_frame_id = 64'd0;
    logic [63:0]  spec_frame_id = 64'd0;
    logic [31:0]  spec_chan0 = 32'd0;
    logic [31:0]  rfdc_status_flags = 32'd0;
    logic [63:0]  rfdc_sample_count = 64'd0;
    logic [31:0]  rfdc_dropped_count = 32'd0;
    logic [15:0]  rfdc_current_valid_mask = 16'd0;
    logic [15:0]  rfdc_seen_valid_mask = 16'd0;
    logic [31:0]  tx_fifo_level_words = 32'd0;
    logic [31:0]  tx_fifo_high_water_words = 32'd0;
    logic [31:0]  tx_fifo_backpressure_cycles = 32'd0;
    logic [31:0]  tx_preflight_status_flags = 32'h0000_0682;
    logic [31:0]  tx_frame_built_count = 32'd9;
    logic [31:0]  tx_frame_dropped_count = 32'd1;
    logic [31:0]  tx_frame_byte_count = 32'd8192;
    logic [31:0]  tx_route_miss_count = 32'd2;
    logic [31:0]  tx_route_error_count = 32'd3;
    logic [2:0]   tx_selected_endpoint_id = 3'd1;
    logic [2:0]   tx_selected_route_id = 3'd1;
    logic         tx_selected_route_is_time = 1'b0;
    logic         tx_header_capture_armed = 1'b0;
    logic         tx_header_capture_valid = 1'b0;
    logic [4:0]   tx_header_capture_word_count = 5'd0;
    logic         tx_frame_capture_armed = 1'b0;
    logic         tx_frame_capture_valid = 1'b0;
    logic [4:0]   tx_frame_capture_word_count = 5'd0;
    logic         tx_payload_witness_armed = 1'b1;
    logic         tx_payload_witness_valid = 1'b1;
    logic         tx_payload_witness_capturing = 1'b0;
    logic [10:0]  tx_payload_witness_word_count = 11'd1040;
    logic [15:0]  tx_payload_witness_stream_type = 16'd0;
    logic [63:0]  tx_payload_witness_sample0 = 64'h0000_0001_0000_0100;
    logic [63:0]  tx_payload_witness_frame_id = 64'h0000_0000_0000_0042;
    logic [31:0]  tx_payload_witness_seq_no = 32'h0000_0011;
    logic [31:0]  tx_payload_witness_chan0 = 32'd64;
    logic [63:0]  tx_payload_witness_layout_word = 64'h0040_0004_0008_0000;
    logic [31:0]  tx_payload_witness_payload_bytes = 32'd8192;
    logic [31:0]  tx_payload_witness_route_meta = 32'h0000_0020;
    logic [31:0]  tx_payload_witness_rfdc_flags = 32'h0000_000f;
    logic [63:0]  tx_payload_witness_rfdc_sample_count = 64'h0000_0001_0000_0100;
    logic [31:0]  tx_payload_witness_dac_phase_epoch = 32'd17;
    logic         tx_payload_witness_overflow = 1'b0;
    logic         tx_payload_witness_filter_mismatch = 1'b0;
    logic         dac_tx_witness_armed = 1'b1;
    logic         dac_tx_witness_valid = 1'b1;
    logic         dac_tx_witness_capturing = 1'b0;
    logic         dac_tx_witness_overflow = 1'b0;
    logic         dac_tx_witness_tvalid_seen = 1'b1;
    logic         dac_tx_witness_tready_seen = 1'b1;
    logic         dac_tx_witness_ready_gap_seen = 1'b0;
    logic [8:0]   dac_tx_witness_word_count = 9'd256;
    logic [31:0]  dac_tx_witness_phase_epoch = 32'd17;
    logic [31:0]  dac_tx_witness_phase_acc = 32'h1234_5678;
    logic [31:0]  dac_tx_witness_phase_step = 32'h0102_0304;
    logic [31:0]  dac_tx_witness_phase0 = 32'h4000_0000;
    logic [31:0]  dac_tx_witness_mode = 32'd1;
    logic [31:0]  dac_tx_witness_ready_gap_count = 32'd0;
    logic         rfdc_axis_raw_witness_armed = 1'b0;
    logic         rfdc_axis_raw_witness_valid = 1'b1;
    logic         rfdc_axis_raw_witness_capturing = 1'b0;
    logic         rfdc_axis_raw_witness_overflow = 1'b0;
    logic         rfdc_axis_raw_witness_tvalid_seen = 1'b1;
    logic [8:0]   rfdc_axis_raw_witness_beat_count = 9'd4;
    logic [2:0]   rfdc_axis_raw_witness_channel_select = 3'd3;
    logic [63:0]  rfdc_axis_raw_witness_sample0 = 64'h0000_0001_0000_0200;
    logic [31:0]  rfdc_axis_raw_witness_rfdc_flags = 32'h0000_001f;
    logic [15:0]  rfdc_axis_raw_witness_valid_mask = 16'h00ff;
    logic [31:0]  pfb_status = 32'h0000_0003;
    logic [31:0]  pfb_frame_count = 32'd0;
    logic [31:0]  pfb_overflow_count = 32'd0;
    logic [31:0]  pfb_peak_chan = 32'd0;
    logic [31:0]  pfb_peak_power = 32'd0;

    wire [15:0] board_id;
    wire [1:0]  mode;
    wire        arm_latched;
    wire        soft_epoch_pulse;
    wire        stop_pulse;
    wire        soft_reset_pulse;
    wire [1:0]  sync_mode;
    wire [1:0]  clock_ref;
    wire [31:0] sample_rate_hz;
    wire [15:0] quant_mode;
    wire [15:0] scale_mode;
    wire [31:0] scale_id;
    wire [15:0] time_payload_nsamp;
    wire [15:0] spec_time_count;
    wire [15:0] spec_chan_count;
    wire        pfb_enable;
    wire        pfb_clear_pulse;
    wire [15:0] pfb_taps;
    wire [15:0] pfb_fft_shift;
    wire [31:0] pfb_chan0;
    wire [15:0] pfb_chan_count;
    wire [15:0] pfb_time_count;
    wire [31:0] chan_split;
    wire [31:0] src_ip;
    wire [31:0] dgx_a_ip;
    wire [31:0] dgx_b_ip;
    wire [31:0] time_dst_ip;
    wire [47:0] src_mac;
    wire [47:0] dgx_a_mac;
    wire [47:0] dgx_b_mac;
    wire [15:0] src_udp_port;
    wire [15:0] dgx_a_udp_port;
    wire [15:0] dgx_b_udp_port;
    wire [15:0] time_udp_port;
    wire [15:0] rfdc_active_mask;
    wire [63:0] unix_seconds;
    wire        tx_header_capture_arm_pulse;
    wire [4:0]  tx_header_capture_rd_word;
    wire [31:0] tx_header_capture_rd_data;
    wire [31:0] tx_control;
    wire        tx_clear_pulse;
    wire [7:0]  tx_endpoint_enable;
    wire [255:0] tx_endpoint_ip_vec;
    wire [383:0] tx_endpoint_mac_vec;
    wire [127:0] tx_endpoint_src_port_vec;
    wire [127:0] tx_endpoint_dst_port_vec;
    wire [7:0]  tx_spec_route_enable;
    wire [255:0] tx_spec_route_chan0_vec;
    wire [127:0] tx_spec_route_chan_count_vec;
    wire [23:0] tx_spec_route_endpoint_vec;
    wire [7:0]  tx_time_route_enable;
    wire [127:0] tx_time_route_input_mask_vec;
    wire [23:0] tx_time_route_endpoint_vec;
    wire        tx_frame_capture_arm_pulse;
    wire [4:0]  tx_frame_capture_rd_word;
    wire [31:0] tx_frame_capture_rd_data;
    wire        tx_payload_witness_arm_pulse;
    wire        tx_payload_witness_clear_pulse;
    wire [1:0]  tx_payload_witness_stream_filter;
    wire [10:0] tx_payload_witness_capture_words;
    wire [11:0] tx_payload_witness_rd_word;
    wire [31:0] tx_payload_witness_rd_data;
    wire        dac_tx_witness_arm_pulse;
    wire        dac_tx_witness_clear_pulse;
    wire [8:0]  dac_tx_witness_capture_words;
    wire [9:0]  dac_tx_witness_rd_word;
    wire [31:0] dac_tx_witness_rd_data;
    wire        rfdc_axis_raw_witness_arm_pulse;
    wire        rfdc_axis_raw_witness_clear_pulse;
    wire [2:0]  rfdc_axis_raw_witness_channel_select_ctrl;
    wire [8:0]  rfdc_axis_raw_witness_capture_beats;
    wire [9:0]  rfdc_axis_raw_witness_rd_word;
    wire [31:0] rfdc_axis_raw_witness_rd_data;
    wire [31:0] dac_phase_epoch;
    wire [1:0]  science_bandwidth_mode_cfg;
    wire [2:0]  science_output_mode_cfg;
    wire        preview_audit_clear_pulse;
    wire [1:0]  preview_audit_source_select;
    wire        preview_audit_event_enable;
    wire        preview_audit_freeze_on_event;
    wire [15:0] preview_audit_event_threshold;
    wire [7:0]  preview_event_rd_addr;

    assign tx_header_capture_rd_data = 32'hca00_0000 | {27'd0, tx_header_capture_rd_word};
    assign tx_frame_capture_rd_data = 32'hfb00_0000 | {27'd0, tx_frame_capture_rd_word};
    assign tx_payload_witness_rd_data = 32'hd000_0000 | {20'd0, tx_payload_witness_rd_word};
    assign dac_tx_witness_rd_data = 32'hdc00_0000 | {22'd0, dac_tx_witness_rd_word};
    assign rfdc_axis_raw_witness_rd_data = 32'he800_0000 | {22'd0, rfdc_axis_raw_witness_rd_word};

    feng_ctrl_axi dut (
        .s_axi_aclk(clk),
        .s_axi_aresetn(rst_n),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .fsm_state(fsm_state),
        .streaming(streaming),
        .armed(armed),
        .active_sync_mode(active_sync_mode),
        .waiting_for_epoch(waiting_for_epoch),
        .pps_seen(pps_seen),
        .pps_count(pps_count),
        .ref_locked(ref_locked),
        .error_flags(error_flags),
        .monitor_sample_count(monitor_sample_count),
        .clip_counts(clip_counts),
        .mean_mags(mean_mags),
        .spec_packet_count(spec_packet_count),
        .spec_udp_byte_count(spec_udp_byte_count),
        .time_packet_count(time_packet_count),
        .time_udp_byte_count(time_udp_byte_count),
        .time_dropped_count(time_dropped_count),
        .spec_seq_no(spec_seq_no),
        .time_seq_no(time_seq_no),
        .time_sample0(time_sample0),
        .time_frame_id(time_frame_id),
        .spec_frame_id(spec_frame_id),
        .spec_chan0(spec_chan0),
        .rfdc_status_flags(rfdc_status_flags),
        .rfdc_sample_count(rfdc_sample_count),
        .rfdc_dropped_count(rfdc_dropped_count),
        .rfdc_current_valid_mask(rfdc_current_valid_mask),
        .rfdc_seen_valid_mask(rfdc_seen_valid_mask),
        .tx_link_status_flags(32'h0000_0002),
        .tx_dry_run_packet_count(32'd5),
        .tx_dry_run_byte_count(32'd4096),
        .tx_fifo_level_words(tx_fifo_level_words),
        .tx_fifo_high_water_words(tx_fifo_high_water_words),
        .tx_fifo_backpressure_cycles(tx_fifo_backpressure_cycles),
        .tx_preflight_status_flags(tx_preflight_status_flags),
        .tx_frame_built_count(tx_frame_built_count),
        .tx_frame_sent_count(32'd6),
        .tx_frame_dropped_count(tx_frame_dropped_count),
        .tx_frame_byte_count(tx_frame_byte_count),
        .tx_route_miss_count(tx_route_miss_count),
        .tx_route_error_count(tx_route_error_count),
        .tx_selected_endpoint_id(tx_selected_endpoint_id),
        .tx_selected_route_id(tx_selected_route_id),
        .tx_selected_route_is_time(tx_selected_route_is_time),
        .tx_header_capture_armed(tx_header_capture_armed),
        .tx_header_capture_valid(tx_header_capture_valid),
        .tx_header_capture_word_count(tx_header_capture_word_count),
        .tx_header_capture_rd_data(tx_header_capture_rd_data),
        .tx_frame_capture_armed(tx_frame_capture_armed),
        .tx_frame_capture_valid(tx_frame_capture_valid),
        .tx_frame_capture_word_count(tx_frame_capture_word_count),
        .tx_frame_capture_rd_data(tx_frame_capture_rd_data),
        .tx_payload_witness_armed(tx_payload_witness_armed),
        .tx_payload_witness_valid(tx_payload_witness_valid),
        .tx_payload_witness_capturing(tx_payload_witness_capturing),
        .tx_payload_witness_word_count(tx_payload_witness_word_count),
        .tx_payload_witness_stream_type(tx_payload_witness_stream_type),
        .tx_payload_witness_sample0(tx_payload_witness_sample0),
        .tx_payload_witness_frame_id(tx_payload_witness_frame_id),
        .tx_payload_witness_seq_no(tx_payload_witness_seq_no),
        .tx_payload_witness_chan0(tx_payload_witness_chan0),
        .tx_payload_witness_layout_word(tx_payload_witness_layout_word),
        .tx_payload_witness_payload_bytes(tx_payload_witness_payload_bytes),
        .tx_payload_witness_route_meta(tx_payload_witness_route_meta),
        .tx_payload_witness_rfdc_flags(tx_payload_witness_rfdc_flags),
        .tx_payload_witness_rfdc_sample_count(tx_payload_witness_rfdc_sample_count),
        .tx_payload_witness_dac_phase_epoch(tx_payload_witness_dac_phase_epoch),
        .tx_payload_witness_overflow(tx_payload_witness_overflow),
        .tx_payload_witness_filter_mismatch(tx_payload_witness_filter_mismatch),
        .tx_payload_witness_rd_data(tx_payload_witness_rd_data),
        .dac_tx_witness_armed(dac_tx_witness_armed),
        .dac_tx_witness_valid(dac_tx_witness_valid),
        .dac_tx_witness_capturing(dac_tx_witness_capturing),
        .dac_tx_witness_overflow(dac_tx_witness_overflow),
        .dac_tx_witness_tvalid_seen(dac_tx_witness_tvalid_seen),
        .dac_tx_witness_tready_seen(dac_tx_witness_tready_seen),
        .dac_tx_witness_ready_gap_seen(dac_tx_witness_ready_gap_seen),
        .dac_tx_witness_word_count(dac_tx_witness_word_count),
        .dac_tx_witness_phase_epoch(dac_tx_witness_phase_epoch),
        .dac_tx_witness_phase_acc(dac_tx_witness_phase_acc),
        .dac_tx_witness_phase_step(dac_tx_witness_phase_step),
        .dac_tx_witness_phase0(dac_tx_witness_phase0),
        .dac_tx_witness_mode(dac_tx_witness_mode),
        .dac_tx_witness_ready_gap_count(dac_tx_witness_ready_gap_count),
        .dac_tx_witness_rd_data(dac_tx_witness_rd_data),
        .rfdc_axis_raw_witness_armed(rfdc_axis_raw_witness_armed),
        .rfdc_axis_raw_witness_valid(rfdc_axis_raw_witness_valid),
        .rfdc_axis_raw_witness_capturing(rfdc_axis_raw_witness_capturing),
        .rfdc_axis_raw_witness_overflow(rfdc_axis_raw_witness_overflow),
        .rfdc_axis_raw_witness_tvalid_seen(rfdc_axis_raw_witness_tvalid_seen),
        .rfdc_axis_raw_witness_beat_count(rfdc_axis_raw_witness_beat_count),
        .rfdc_axis_raw_witness_channel_select(rfdc_axis_raw_witness_channel_select),
        .rfdc_axis_raw_witness_sample0(rfdc_axis_raw_witness_sample0),
        .rfdc_axis_raw_witness_rfdc_flags(rfdc_axis_raw_witness_rfdc_flags),
        .rfdc_axis_raw_witness_valid_mask(rfdc_axis_raw_witness_valid_mask),
        .rfdc_axis_raw_witness_rd_data(rfdc_axis_raw_witness_rd_data),
        .tx_spec_route_hit_counts({32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd22, 32'd11}),
        .tx_time_route_hit_counts({32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd33}),
        .pfb_status(pfb_status),
        .pfb_frame_count(pfb_frame_count),
        .pfb_overflow_count(pfb_overflow_count),
        .pfb_peak_chan(pfb_peak_chan),
        .pfb_peak_power(pfb_peak_power),
        .debug_busy(1'b0),
        .debug_done(1'b1),
        .debug_error(1'b0),
        .debug_capture_count(32'd1024),
        .debug_peak_bin(32'd7),
        .debug_peak_power(32'h0001_2345),
        .debug_time_rd_data(32'h1234_5678),
        .debug_fft_rd_data(32'h8765_4321),
        .preview_busy(1'b0),
        .preview_done(1'b1),
        .preview_error(1'b0),
        .preview_capture_count(32'd1024),
        .preview_sample0(64'h0000_0001_0000_0200),
        .preview_rd_data(32'hfeed_cafe),
        .preview_event_rd_data(32'hea00_0000 | {24'd0, preview_event_rd_addr}),
        .preview_audit_status(32'h0000_0101),
        .preview_audit_start_count(32'd3),
        .preview_audit_first_count(32'd3),
        .preview_audit_done_count(32'd2),
        .preview_audit_start_sample0(64'h0000_0001_0000_1000),
        .preview_audit_first_sample0(64'h0000_0001_0000_1010),
        .preview_audit_done_sample0(64'h0000_0001_0000_140c),
        .preview_audit_start_to_first_latency(32'd9),
        .preview_audit_capture_beats(32'd256),
        .preview_audit_valid_gap_count(32'd4),
        .preview_audit_sample0_error_count(32'd5),
        .preview_event_sample0(64'h0000_0001_0000_2004),
        .preview_event_max_code(32'd32000),
        .preview_event_info(32'h0000_1200),
        .preview_event_rfdc_flags(32'h0000_000f),
        .preview_event_dac_phase_epoch(32'd17),
        .dac_audit_phase_epoch_seen(32'd17),
        .dac_audit_ch0_phase_acc(32'h1234_5678),
        .dac_audit_ch0_phase_step(32'h0102_0304),
        .dac_audit_ch0_phase0(32'h4000_0000),
        .dac_audit_ch0_mode(32'd1),
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
        .pfb_enable(pfb_enable),
        .pfb_clear_pulse(pfb_clear_pulse),
        .pfb_taps(pfb_taps),
        .pfb_fft_shift(pfb_fft_shift),
        .pfb_chan0(pfb_chan0),
        .pfb_chan_count(pfb_chan_count),
        .pfb_time_count(pfb_time_count),
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
        .tx_control(tx_control),
        .tx_clear_pulse(tx_clear_pulse),
        .tx_endpoint_enable(tx_endpoint_enable),
        .tx_endpoint_ip_vec(tx_endpoint_ip_vec),
        .tx_endpoint_mac_vec(tx_endpoint_mac_vec),
        .tx_endpoint_src_port_vec(tx_endpoint_src_port_vec),
        .tx_endpoint_dst_port_vec(tx_endpoint_dst_port_vec),
        .tx_spec_route_enable(tx_spec_route_enable),
        .tx_spec_route_chan0_vec(tx_spec_route_chan0_vec),
        .tx_spec_route_chan_count_vec(tx_spec_route_chan_count_vec),
        .tx_spec_route_endpoint_vec(tx_spec_route_endpoint_vec),
        .tx_time_route_enable(tx_time_route_enable),
        .tx_time_route_input_mask_vec(tx_time_route_input_mask_vec),
        .tx_time_route_endpoint_vec(tx_time_route_endpoint_vec),
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
        .dac_phase_epoch(dac_phase_epoch),
        .preview_capture_start_pulse(),
        .preview_capture_clear_pulse(),
        .preview_input_mask(),
        .preview_rd_input(),
        .preview_rd_addr(),
        .preview_audit_clear_pulse(preview_audit_clear_pulse),
        .preview_audit_source_select(preview_audit_source_select),
        .preview_audit_event_enable(preview_audit_event_enable),
        .preview_audit_freeze_on_event(preview_audit_freeze_on_event),
        .preview_audit_event_threshold(preview_audit_event_threshold),
        .preview_event_rd_addr(preview_event_rd_addr),
        .tx_header_capture_arm_pulse(tx_header_capture_arm_pulse),
        .tx_header_capture_rd_word(tx_header_capture_rd_word),
        .tx_frame_capture_arm_pulse(tx_frame_capture_arm_pulse),
        .tx_frame_capture_rd_word(tx_frame_capture_rd_word),
        .tx_payload_witness_arm_pulse(tx_payload_witness_arm_pulse),
        .tx_payload_witness_clear_pulse(tx_payload_witness_clear_pulse),
        .tx_payload_witness_stream_filter(tx_payload_witness_stream_filter),
        .tx_payload_witness_capture_words(tx_payload_witness_capture_words),
        .tx_payload_witness_rd_word(tx_payload_witness_rd_word),
        .dac_tx_witness_arm_pulse(dac_tx_witness_arm_pulse),
        .dac_tx_witness_clear_pulse(dac_tx_witness_clear_pulse),
        .dac_tx_witness_capture_words(dac_tx_witness_capture_words),
        .dac_tx_witness_rd_word(dac_tx_witness_rd_word),
        .rfdc_axis_raw_witness_arm_pulse(rfdc_axis_raw_witness_arm_pulse),
        .rfdc_axis_raw_witness_clear_pulse(rfdc_axis_raw_witness_clear_pulse),
        .rfdc_axis_raw_witness_channel_select_ctrl(rfdc_axis_raw_witness_channel_select_ctrl),
        .rfdc_axis_raw_witness_capture_beats(rfdc_axis_raw_witness_capture_beats),
        .rfdc_axis_raw_witness_rd_word(rfdc_axis_raw_witness_rd_word),
        .unix_seconds(unix_seconds),
        .science_bandwidth_mode_cfg(science_bandwidth_mode_cfg),
        .science_output_mode_cfg(science_output_mode_cfg)
    );

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            s_axi_awvalid = 1'b0;
            s_axi_wvalid = 1'b0;
            s_axi_bready = 1'b0;
            s_axi_arvalid = 1'b0;
            s_axi_rready = 1'b0;
            repeat (5) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic axi_write(input [31:0] addr, input [31:0] data);
        begin
            @(posedge clk);
            s_axi_awaddr <= addr;
            s_axi_awvalid <= 1'b1;
            s_axi_wdata <= data;
            s_axi_wstrb <= 4'hf;
            s_axi_wvalid <= 1'b1;
            s_axi_bready <= 1'b1;
            @(posedge clk);
            s_axi_awvalid <= 1'b0;
            while (!s_axi_bvalid) begin
                @(posedge clk);
            end
            `TB_CHECK_EQ(s_axi_bresp, 2'b00, "AXI write response")
            @(posedge clk);
            s_axi_wvalid <= 1'b0;
            s_axi_bready <= 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic axi_read(input [31:0] addr, output [31:0] data);
        begin
            @(posedge clk);
            s_axi_araddr <= addr;
            s_axi_arvalid <= 1'b1;
            s_axi_rready <= 1'b1;
            @(posedge clk);
            s_axi_arvalid <= 1'b0;
            while (!s_axi_rvalid) begin
                @(posedge clk);
            end
            data = s_axi_rdata;
            `TB_CHECK_EQ(s_axi_rresp, 2'b00, "AXI read response")
            @(posedge clk);
            s_axi_rready <= 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic axi_write_split(input [31:0] addr, input [31:0] data);
        begin
            @(posedge clk);
            s_axi_awaddr <= addr;
            s_axi_awvalid <= 1'b1;
            s_axi_bready <= 1'b1;
            @(posedge clk);
            s_axi_awvalid <= 1'b0;
            repeat (3) @(posedge clk);
            s_axi_wdata <= data;
            s_axi_wstrb <= 4'hf;
            s_axi_wvalid <= 1'b1;
            while (!s_axi_bvalid) begin
                @(posedge clk);
            end
            `TB_CHECK_EQ(s_axi_bresp, 2'b00, "AXI split write response")
            @(posedge clk);
            s_axi_wvalid <= 1'b0;
            s_axi_bready <= 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic expect_pulse_on_control(input [31:0] control_word, input integer pulse_kind);
        integer idx;
        bit seen;
        begin
            seen = 1'b0;
            fork
                begin
                    axi_write(16'h000c, control_word);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if ((pulse_kind == 0) && stop_pulse) begin
                            seen = 1'b1;
                        end
                        if ((pulse_kind == 1) && soft_reset_pulse) begin
                            seen = 1'b1;
                        end
                        if ((pulse_kind == 2) && soft_epoch_pulse) begin
                            seen = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen, "CONTROL pulse was not observed")
        end
    endtask

    task automatic expect_header_capture_arm_pulse;
        integer idx;
        bit seen;
        begin
            seen = 1'b0;
            fork
                begin
                    axi_write(16'h0378, 32'h0000_0001);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (tx_header_capture_arm_pulse) begin
                            seen = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen, "TX header capture arm pulse was not observed")
        end
    endtask

    task automatic expect_frame_capture_arm_pulse;
        integer idx;
        bit seen;
        begin
            seen = 1'b0;
            fork
                begin
                    axi_write(16'hb030, 32'h0000_0001);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (tx_frame_capture_arm_pulse) begin
                            seen = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen, "TX frame capture arm pulse was not observed")
        end
    endtask

    task automatic expect_payload_witness_pulses;
        integer idx;
        bit seen_arm;
        bit seen_clear;
        begin
            seen_arm = 1'b0;
            seen_clear = 1'b0;
            fork
                begin
                    axi_write(16'h0790, 32'h0000_0003);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (tx_payload_witness_arm_pulse) begin
                            seen_arm = 1'b1;
                        end
                        if (tx_payload_witness_clear_pulse) begin
                            seen_clear = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen_arm, "TX payload witness arm pulse was not observed")
            `TB_CHECK(seen_clear, "TX payload witness clear pulse was not observed")
        end
    endtask

    task automatic expect_dac_tx_witness_pulses;
        integer idx;
        bit seen_arm;
        bit seen_clear;
        begin
            seen_arm = 1'b0;
            seen_clear = 1'b0;
            fork
                begin
                    axi_write(16'hb600, 32'h0000_0003);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (dac_tx_witness_arm_pulse) begin
                            seen_arm = 1'b1;
                        end
                        if (dac_tx_witness_clear_pulse) begin
                            seen_clear = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen_arm, "DAC TX witness arm pulse was not observed")
            `TB_CHECK(seen_clear, "DAC TX witness clear pulse was not observed")
        end
    endtask

    task automatic expect_rfdc_axis_raw_witness_pulses;
        integer idx;
        bit seen_arm;
        bit seen_clear;
        begin
            seen_arm = 1'b0;
            seen_clear = 1'b0;
            fork
                begin
                    axi_write(16'he200, 32'h0000_0003);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (rfdc_axis_raw_witness_arm_pulse) begin
                            seen_arm = 1'b1;
                        end
                        if (rfdc_axis_raw_witness_clear_pulse) begin
                            seen_clear = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen_arm, "RFDC AXIS raw witness arm pulse was not observed")
            `TB_CHECK(seen_clear, "RFDC AXIS raw witness clear pulse was not observed")
        end
    endtask

    task automatic expect_tx_clear_pulse;
        integer idx;
        bit seen;
        begin
            seen = 1'b0;
            fork
                begin
                    axi_write(16'hb000, 32'h0000_002d);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (tx_clear_pulse) begin
                            seen = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen, "TX clear pulse was not observed")
        end
    endtask

    task automatic expect_pfb_clear_pulse;
        integer idx;
        bit seen;
        begin
            seen = 1'b0;
            fork
                begin
                    axi_write(16'h0900, 32'h0000_0002);
                end
                begin
                    for (idx = 0; idx < 12; idx = idx + 1) begin
                        @(posedge clk);
                        if (pfb_clear_pulse) begin
                            seen = 1'b1;
                        end
                    end
                end
            join
            `TB_CHECK(seen, "PFB clear pulse was not observed")
        end
    endtask

    initial begin
        reg [31:0] rd;
        integer mode_idx;

        reset_dut();

        axi_read(16'h0000, rd);
        `TB_CHECK_EQ(rd, 32'h0001_001A, "CORE_VERSION")
        axi_read(16'h0008, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default MODE")
        axi_read(16'h0114, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default TIME payload count")
        axi_read(16'h011c, rd);
        `TB_CHECK_EQ(rd, 32'd64, "default SPEC channel count")
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default PFB enable")
        axi_read(16'h0908, rd);
        `TB_CHECK_EQ(rd, 32'd4096, "default PFB nchan")
        axi_read(16'h090c, rd);
        `TB_CHECK_EQ(rd, 32'd4, "default PFB taps")
        axi_read(16'h0918, rd);
        `TB_CHECK_EQ(rd, 32'd64, "default PFB channel count")
        axi_read(16'h091c, rd);
        `TB_CHECK_EQ(rd, 32'd4, "default PFB time count")
        axi_read(16'h0200, rd);
        `TB_CHECK_EQ(rd, 32'h0a00_0101, "default source IP")
        axi_read(16'h0020, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default SYNC_CONFIG")
        axi_read(16'h0350, rd);
        `TB_CHECK_EQ(rd, 32'h0000_ffff, "default RFDC active mask")
        axi_read(16'hb000, rd);
        `TB_CHECK_EQ(rd, 32'h0000_000d, "default TX control")
        axi_read(16'hd000, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "default science control forces dry-run")
        axi_read(16'hd004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0100, "default science status is 100MHz/OFF")
        axi_read(16'hd008, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default science bandwidth is 100MHz")
        `TB_CHECK_EQ(science_bandwidth_mode_cfg, 2'd1, "default science bandwidth output")
        axi_read(16'hd00c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default science mode is OFF")
        `TB_CHECK_EQ(science_output_mode_cfg, 3'd0, "default science mode output")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd122_880_000, "default science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd2, "default science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0048, "default science block reasons keep dry-run/wide-science blockers only")
        `TB_CHECK_EQ(rd[4], 1'b0, "RFDC science bus truncation block is cleared")
        axi_read(16'hd020, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0307, "science capability word")
        axi_read(16'hb100, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default endpoint0 enabled")
        axi_read(16'hb104, rd);
        `TB_CHECK_EQ(rd, 32'h0a00_010a, "default endpoint0 IP")
        axi_read(16'hb110, rd);
        `TB_CHECK_EQ(rd, 32'd4100, "default endpoint0 dst port")
        axi_read(16'hb300, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "default SPEC route0 control")
        axi_read(16'hb304, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default SPEC route0 chan0")
        axi_read(16'hb308, rd);
        `TB_CHECK_EQ(rd, 32'd2048, "default SPEC route0 count")
        axi_read(16'hb320, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0101, "default SPEC route1 control")
        axi_read(16'hb500, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0201, "default TIME route0 control")
        axi_read(16'hb504, rd);
        `TB_CHECK_EQ(rd, 32'h0000_00ff, "default TIME route0 mask")
        axi_read(16'h0794, rd);
        `TB_CHECK_EQ(rd, 32'h0004_1003, "TX payload witness status")
        axi_read(16'h079c, rd);
        `TB_CHECK_EQ(rd, 32'd1040, "default TX payload witness capture words")
        axi_read(16'h07a0, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0100, "TX payload witness sample0 low")
        axi_read(16'h07a4, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "TX payload witness sample0 high")
        axi_read(16'h07b8, rd);
        `TB_CHECK_EQ(rd, 32'h0008_0000, "TX payload witness layout low")
        axi_read(16'h07bc, rd);
        `TB_CHECK_EQ(rd, 32'h0040_0004, "TX payload witness layout high")
        axi_read(16'h07d0, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0100, "TX payload witness RFDC sample count low")
        axi_read(16'h07d8, rd);
        `TB_CHECK_EQ(rd, 32'h0004_1003, "paired coherence status")
        axi_read(16'h07dc, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0400, "paired source sample0 low")
        axi_read(16'h07e0, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0004, "paired source sample0 high")
        axi_read(16'h07e4, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0200, "paired preview sample0 low")
        axi_read(16'h07e8, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "paired preview sample0 high")
        axi_read(16'h07ec, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0100, "paired header sample0 low")
        axi_read(16'h07f0, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "paired header sample0 high")
        axi_read(16'h07f4, rd);
        `TB_CHECK_EQ(rd, 32'hffff_ff00, "paired sample0 delta low")
        axi_read(16'h07f8, rd);
        `TB_CHECK_EQ(rd, 32'hffff_ffff, "paired sample0 delta high")
        axi_read(32'h0001_0000, rd);
        `TB_CHECK_EQ(rd, 32'hd000_0000, "TX payload witness buffer read")
        axi_write(16'h0798, 32'd1);
        `TB_CHECK_EQ(tx_payload_witness_stream_filter, 2'd1, "TX payload witness stream filter output")
        axi_write(16'h079c, 32'd64);
        `TB_CHECK_EQ(tx_payload_witness_capture_words, 11'd64, "TX payload witness capture words output")
        expect_payload_witness_pulses();
        axi_read(16'hb604, rd);
        `TB_CHECK_EQ(rd, 32'h0001_0033, "DAC TX witness status")
        axi_read(16'hb608, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default DAC TX witness capture words")
        axi_read(16'hb60c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "DAC TX witness buffer words")
        axi_read(16'hb610, rd);
        `TB_CHECK_EQ(rd, 32'd17, "DAC TX witness phase epoch")
        axi_read(16'hb614, rd);
        `TB_CHECK_EQ(rd, 32'h1234_5678, "DAC TX witness phase accumulator")
        axi_read(16'hb618, rd);
        `TB_CHECK_EQ(rd, 32'h0102_0304, "DAC TX witness phase step")
        axi_read(16'hb61c, rd);
        `TB_CHECK_EQ(rd, 32'h4000_0000, "DAC TX witness phase0")
        axi_read(16'hb620, rd);
        `TB_CHECK_EQ(rd, 32'd1, "DAC TX witness mode")
        axi_read(16'hc000, rd);
        `TB_CHECK_EQ(rd, 32'hdc00_0000, "DAC TX witness buffer read")
        axi_write(16'hb608, 32'd64);
        `TB_CHECK_EQ(dac_tx_witness_capture_words, 9'd64, "DAC TX witness capture words output")
        expect_dac_tx_witness_pulses();
        axi_read(16'he204, rd);
        `TB_CHECK_EQ(rd, 32'h0300_0412, "RFDC AXIS raw witness status")
        axi_read(16'he20c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default RFDC AXIS raw witness capture beats")
        axi_read(16'he210, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0200, "RFDC AXIS raw witness sample0 low")
        axi_read(16'he214, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "RFDC AXIS raw witness sample0 high")
        axi_read(16'he218, rd);
        `TB_CHECK_EQ(rd, 32'h0000_001f, "RFDC AXIS raw witness flags")
        axi_read(16'he21c, rd);
        `TB_CHECK_EQ(rd, 32'd16, "RFDC AXIS raw witness word count")
        axi_read(16'he220, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "RFDC AXIS raw witness buffer words")
        axi_read(16'he224, rd);
        `TB_CHECK_EQ(rd, 32'h0000_00ff, "RFDC AXIS raw witness valid mask")
        axi_read(16'he800, rd);
        `TB_CHECK_EQ(rd, 32'he800_0000, "RFDC AXIS raw witness buffer read")
        axi_write(16'he208, 32'd5);
        `TB_CHECK_EQ(rfdc_axis_raw_witness_channel_select_ctrl, 3'd5, "RFDC AXIS raw witness channel output")
        axi_write(16'he20c, 32'd32);
        `TB_CHECK_EQ(rfdc_axis_raw_witness_capture_beats, 9'd32, "RFDC AXIS raw witness capture beats output")
        expect_rfdc_axis_raw_witness_pulses();

        axi_write(16'hd008, 32'd0);
        axi_write(16'hd00c, 32'd3);
        axi_read(16'hd004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_6003, "20MHz TIME_SPEC enables time and spec")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd30_720_000, "20MHz science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd8, "20MHz science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_004a, "20MHz TIME_SPEC blocks dry-run/wide-science/SPEC-scaffold")
        `TB_CHECK_EQ(science_bandwidth_mode_cfg, 2'd0, "20MHz science bandwidth output")
        `TB_CHECK_EQ(science_output_mode_cfg, 3'd3, "TIME_SPEC science mode output")

        axi_write(16'hd008, 32'd2);
        axi_read(16'hd004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_6207, "200MHz TIME_SPEC is explicitly rejected")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd245_760_000, "200MHz science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd1, "200MHz science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_004b, "200MHz TIME_SPEC block reasons")
        `TB_CHECK_EQ(rd[0], 1'b1, "200MHz TIME_SPEC rejection bit set")
        `TB_CHECK_EQ(rd[4], 1'b0, "RFDC bus truncation remains cleared at 200MHz")

        for (mode_idx = 0; mode_idx < 4; mode_idx = mode_idx + 1) begin
            axi_write(16'h0008, mode_idx[31:0]);
            `TB_CHECK_EQ(mode, mode_idx[1:0], "MODE output")
            axi_read(16'h0008, rd);
            `TB_CHECK_EQ(rd, mode_idx[31:0], "MODE readback")
        end

        axi_write(16'h0004, 32'h0000_005a);
        `TB_CHECK_EQ(board_id, 16'h005a, "board_id output")
        axi_write(16'h000c, 32'h0000_0001);
        `TB_CHECK(arm_latched, "arm_latched set")
        axi_read(16'h000c, rd);
        `TB_CHECK_EQ(rd[0], 1'b1, "CONTROL arm readback")
        expect_pulse_on_control(32'h0000_0002, 2);
        expect_pulse_on_control(32'h0000_0004, 0);
        `TB_CHECK(!arm_latched, "arm_latched cleared by stop")
        axi_write(16'h000c, 32'h0000_0001);
        expect_pulse_on_control(32'h0000_0008, 1);
        `TB_CHECK(!arm_latched, "arm_latched cleared by soft reset")

        axi_write(16'h0020, 32'h0001_0002);
        `TB_CHECK_EQ(sync_mode, 2'd2, "free-run sync mode output")
        `TB_CHECK_EQ(clock_ref, 2'd1, "TCXO clock ref output")
        axi_read(16'h0020, rd);
        `TB_CHECK_EQ(rd, 32'h0001_0002, "SYNC_CONFIG readback")
        armed = 1'b1;
        streaming = 1'b0;
        axi_write(16'h0020, 32'h0002_0001);
        axi_read(16'h0020, rd);
        `TB_CHECK_EQ(rd, 32'h0001_0002, "SYNC_CONFIG write ignored while armed")
        armed = 1'b0;
        axi_write(16'h0020, 32'h0002_0001);
        axi_read(16'h0020, rd);
        `TB_CHECK_EQ(rd, 32'h0002_0001, "SYNC_CONFIG write accepted while idle")
        axi_write(16'h0350, 32'h0000_0003);
        `TB_CHECK_EQ(rfdc_active_mask, 16'h0003, "RFDC active mask output")
        axi_read(16'h0350, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0003, "RFDC active mask readback")
        axi_write(16'h0350, 32'h0000_0000);
        axi_read(16'h0350, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0003, "RFDC active mask ignores zero")
        armed = 1'b1;
        axi_write(16'h0350, 32'h0000_0001);
        axi_read(16'h0350, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0003, "RFDC active mask write ignored while armed")
        armed = 1'b0;

        axi_write(16'h0200, 32'hc0a8_0102);
        axi_write(16'h0210, 32'h1122_3344);
        axi_write(16'h0214, 32'h0000_aabb);
        axi_write(16'h0228, 32'd5000);
        axi_write(16'h0238, 32'd1024);
        axi_write(16'h0240, 32'h1234_5678);
        axi_write(16'h0244, 32'h5566_7788);
        axi_write(16'h0248, 32'h1122_3344);
        axi_write(16'hb164, 32'h0a00_0112);
        axi_write(16'hb168, 32'h5566_7788);
        axi_write(16'hb16c, 32'h0000_1122);
        axi_write(16'hb170, 32'd4400);
        axi_write(16'hb174, 32'd4001);
        axi_write(16'hb160, 32'd1);
        axi_write(16'hb340, 32'h0000_0301);
        axi_write(16'hb344, 32'd1024);
        axi_write(16'hb348, 32'd64);
        axi_write(16'hb540, 32'h0000_0301);
        axi_write(16'hb544, 32'h0000_000f);
        axi_write(16'h0914, 32'd128);
        axi_write(16'h0918, 32'd32);
        axi_write(16'h091c, 32'd8);
        axi_write(16'h0910, 32'h0000_0aaa);
        axi_read(16'h0200, rd);
        `TB_CHECK_EQ(rd, 32'hc0a8_0102, "source IP readback")
        `TB_CHECK_EQ(src_mac, 48'haabb_1122_3344, "source MAC output")
        axi_read(16'h0228, rd);
        `TB_CHECK_EQ(rd, 32'd5000, "source UDP port readback")
        `TB_CHECK_EQ(chan_split, 32'd1024, "chan_split output")
        `TB_CHECK_EQ(scale_id, 32'h1234_5678, "scale_id output")
        `TB_CHECK_EQ(unix_seconds, 64'h1122_3344_5566_7788, "unix_seconds output")
        `TB_CHECK_EQ(pfb_chan0, 32'd128, "PFB chan0 output")
        `TB_CHECK_EQ(pfb_chan_count, 16'd32, "PFB channel count output")
        `TB_CHECK_EQ(pfb_time_count, 16'd8, "PFB time count output")
        `TB_CHECK_EQ(spec_chan_count, 16'd32, "legacy SPEC channel count mirrors PFB")
        `TB_CHECK_EQ(spec_time_count, 16'd8, "legacy SPEC time count mirrors PFB")
        axi_read(16'h0914, rd);
        `TB_CHECK_EQ(rd, 32'd128, "PFB chan0 readback")
        axi_read(16'h0918, rd);
        `TB_CHECK_EQ(rd, 32'd32, "PFB channel count readback")
        axi_read(16'h091c, rd);
        `TB_CHECK_EQ(rd, 32'd8, "PFB time count readback")
        axi_read(16'h0910, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0aaa, "PFB FFT shift readback")
        axi_read(16'hb164, rd);
        `TB_CHECK_EQ(rd, 32'h0a00_0112, "endpoint3 IP readback")
        axi_read(16'hb16c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_1122, "endpoint3 MAC high readback")
        axi_read(16'hb170, rd);
        `TB_CHECK_EQ(rd, 32'd4400, "endpoint3 dst port readback")
        axi_read(16'hb174, rd);
        `TB_CHECK_EQ(rd, 32'd4001, "endpoint3 src port readback")
        axi_read(16'hb340, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0301, "SPEC route2 control readback")
        axi_read(16'hb344, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "SPEC route2 chan0 readback")
        axi_read(16'hb348, rd);
        `TB_CHECK_EQ(rd, 32'd64, "SPEC route2 count readback")
        axi_read(16'hb540, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0301, "TIME route2 control readback")
        axi_read(16'hb544, rd);
        `TB_CHECK_EQ(rd, 32'h0000_000f, "TIME route2 mask readback")

        fsm_state = 4'd6;
        streaming = 1'b1;
        armed = 1'b1;
        active_sync_mode = 2'd2;
        waiting_for_epoch = 1'b1;
        pps_seen = 1'b1;
        ref_locked = 1'b1;
        error_flags = 32'hdead_beef;
        monitor_sample_count = 32'd99;
        spec_packet_count = 32'd7;
        time_dropped_count = 32'd3;
        spec_seq_no = 32'd11;
        spec_frame_id = 64'h0102_0304_0506_0708;
        spec_chan0 = 32'd2048;
        tx_fifo_level_words = 32'd123;
        tx_fifo_high_water_words = 32'd456;
        tx_fifo_backpressure_cycles = 32'd789;
        tx_header_capture_armed = 1'b1;
        tx_header_capture_valid = 1'b0;
        tx_header_capture_word_count = 5'd7;
        pfb_status = 32'h0000_0013;
        pfb_frame_count = 32'd17;
        pfb_overflow_count = 32'd2;
        pfb_peak_chan = 32'd129;
        pfb_peak_power = 32'd123456;
        rfdc_current_valid_mask = 16'h0003;
        rfdc_seen_valid_mask = 16'h00ff;
        clip_counts[0 +: 32] = 32'd12;
        mean_mags[32 +: 32] = 32'd34;
        @(posedge clk);

        axi_read(16'h0010, rd);
        `TB_CHECK_EQ(rd, 32'h0000_061b, "FSM status readback")
        axi_read(16'h0014, rd);
        `TB_CHECK_EQ(rd, 32'd7, "sync status readback")
        axi_read(16'h001c, rd);
        `TB_CHECK_EQ(rd, 32'hdead_beef, "error flags readback")
        axi_read(16'h0024, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0002, "PPS count low readback")
        axi_read(16'h0028, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "PPS count high readback")
        axi_read(16'h0300, rd);
        `TB_CHECK_EQ(rd, 32'd99, "monitor sample count readback")
        axi_read(16'h0304, rd);
        `TB_CHECK_EQ(rd, 32'd7, "SPEC packet count readback")
        axi_read(16'h0314, rd);
        `TB_CHECK_EQ(rd, 32'd3, "TIME dropped count readback")
        axi_read(16'h0318, rd);
        `TB_CHECK_EQ(rd, 32'd11, "SPEC seq readback")
        axi_read(16'h0330, rd);
        `TB_CHECK_EQ(rd, 32'h0506_0708, "SPEC frame low readback")
        axi_read(16'h0334, rd);
        `TB_CHECK_EQ(rd, 32'h0102_0304, "SPEC frame high readback")
        axi_read(16'h0338, rd);
        `TB_CHECK_EQ(rd, 32'd2048, "SPEC chan0 readback")
        axi_read(16'h0354, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0003, "RFDC current valid mask readback")
        axi_read(16'h0358, rd);
        `TB_CHECK_EQ(rd, 32'h0000_00ff, "RFDC seen valid mask readback")
        axi_read(16'h0360, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0002, "TX link dry-run flags readback")
        axi_read(16'h0364, rd);
        `TB_CHECK_EQ(rd, 32'd5, "TX dry-run packet count readback")
        axi_read(16'h0368, rd);
        `TB_CHECK_EQ(rd, 32'd4096, "TX dry-run byte count readback")
        axi_read(16'h036c, rd);
        `TB_CHECK_EQ(rd, 32'd123, "TX FIFO level readback")
        axi_read(16'h0370, rd);
        `TB_CHECK_EQ(rd, 32'd456, "TX FIFO high-water readback")
        axi_read(16'h0374, rd);
        `TB_CHECK_EQ(rd, 32'd789, "TX FIFO backpressure readback")
        axi_read(16'h037c, rd);
        `TB_CHECK_EQ(rd, 32'h0007_0001, "TX header capture armed status")
        axi_read(16'hb004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0682, "TX preflight status readback")
        axi_read(16'hb008, rd);
        `TB_CHECK_EQ(rd, 32'd9, "TX frame built count readback")
        axi_read(16'hb00c, rd);
        `TB_CHECK_EQ(rd, 32'd6, "TX frame sent count readback")
        axi_read(16'hb010, rd);
        `TB_CHECK_EQ(rd, 32'd1, "TX frame dropped count readback")
        axi_read(16'hb014, rd);
        `TB_CHECK_EQ(rd, 32'd8192, "TX frame byte count readback")
        axi_read(16'hb018, rd);
        `TB_CHECK_EQ(rd, 32'd2, "TX route miss count readback")
        axi_read(16'hb01c, rd);
        `TB_CHECK_EQ(rd, 32'd3, "TX route error count readback")
        axi_read(16'hb028, rd);
        `TB_CHECK_EQ(rd, 32'd1, "TX selected endpoint readback")
        axi_read(16'hb02c, rd);
        `TB_CHECK_EQ(rd, 32'd1, "TX selected SPEC route readback")
        axi_read(16'hb30c, rd);
        `TB_CHECK_EQ(rd, 32'd11, "TX SPEC route0 hit readback")
        axi_read(16'hb32c, rd);
        `TB_CHECK_EQ(rd, 32'd22, "TX SPEC route1 hit readback")
        axi_read(16'hb50c, rd);
        `TB_CHECK_EQ(rd, 32'd33, "TX TIME route0 hit readback")
        axi_read(16'h0904, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0013, "PFB status readback")
        axi_read(16'h0920, rd);
        `TB_CHECK_EQ(rd, 32'd17, "PFB frame count readback")
        axi_read(16'h0924, rd);
        `TB_CHECK_EQ(rd, 32'd2, "PFB overflow count readback")
        axi_read(16'h0928, rd);
        `TB_CHECK_EQ(rd, 32'd129, "PFB peak channel readback")
        axi_read(16'h092c, rd);
        `TB_CHECK_EQ(rd, 32'd123456, "PFB peak power readback")
        expect_pfb_clear_pulse();
        axi_write(16'h0900, 32'h0000_0000);
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd0, "PFB disable readback")
        axi_write(16'h0900, 32'h0000_0001);
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd1, "PFB enable readback")
        expect_header_capture_arm_pulse();
        expect_frame_capture_arm_pulse();
        expect_tx_clear_pulse();
        tx_header_capture_armed = 1'b0;
        tx_header_capture_valid = 1'b1;
        tx_header_capture_word_count = 5'd16;
        tx_frame_capture_armed = 1'b0;
        tx_frame_capture_valid = 1'b1;
        tx_frame_capture_word_count = 5'd16;
        axi_read(16'h037c, rd);
        `TB_CHECK_EQ(rd, 32'h0010_0002, "TX header capture valid status")
        axi_read(16'hb034, rd);
        `TB_CHECK_EQ(rd, 32'h0010_0002, "TX frame capture valid status")
        axi_read(16'h0380, rd);
        `TB_CHECK_EQ(rd, 32'hca00_0000, "TX header capture buffer word 0")
        `TB_CHECK_EQ(tx_header_capture_rd_word, 5'd0, "TX header capture read word 0")
        axi_read(16'h0384, rd);
        `TB_CHECK_EQ(rd, 32'hca00_0001, "TX header capture buffer word 1")
        `TB_CHECK_EQ(tx_header_capture_rd_word, 5'd1, "TX header capture read word 1")
        axi_read(16'hb040, rd);
        `TB_CHECK_EQ(rd, 32'hfb00_0000, "TX frame capture buffer word 0")
        `TB_CHECK_EQ(tx_frame_capture_rd_word, 5'd0, "TX frame capture read word 0")
        axi_read(16'hb044, rd);
        `TB_CHECK_EQ(rd, 32'hfb00_0001, "TX frame capture buffer word 1")
        `TB_CHECK_EQ(tx_frame_capture_rd_word, 5'd1, "TX frame capture read word 1")
        axi_read(16'h0500, rd);
        `TB_CHECK_EQ(rd, 32'd12, "clip lane0 readback")
        axi_read(16'h0524, rd);
        `TB_CHECK_EQ(rd, 32'd34, "mean lane1 readback")
        axi_read(16'h0404, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0004, "debug done status readback")
        axi_read(16'h0408, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "debug NFFT readback")
        axi_read(16'h0410, rd);
        `TB_CHECK_EQ(rd, 32'd7, "debug peak bin readback")
        axi_read(16'h0414, rd);
        `TB_CHECK_EQ(rd, 32'h0001_2345, "debug peak power readback")
        axi_read(16'h0800, rd);
        `TB_CHECK_EQ(rd, 32'h1234_5678, "debug time buffer readback")
        axi_read(16'h1800, rd);
        `TB_CHECK_EQ(rd, 32'h8765_4321, "debug FFT buffer readback")
        axi_read(16'h0600, rd);
        `TB_CHECK_EQ(rd, 32'h0000_00ff, "default DAC enable mask")
        axi_write(16'h0600, 32'h0000_0055);
        axi_read(16'h0600, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0055, "DAC enable mask readback")
        axi_write(16'h0638, 32'h0102_0304);
        axi_write(16'h063c, 32'd4096);
        axi_write(16'h0644, 32'h1122_3344);
        axi_read(16'h0638, rd);
        `TB_CHECK_EQ(rd, 32'h0102_0304, "DAC ch1 phase step readback")
        axi_read(16'h063c, rd);
        `TB_CHECK_EQ(rd, 32'd4096, "DAC ch1 amplitude readback")
        axi_read(16'h0644, rd);
        `TB_CHECK_EQ(rd, 32'h1122_3344, "DAC ch1 phase inject readback")
        axi_read(16'h060c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "DAC phase epoch reset value")
        axi_write(16'h060c, 32'd1);
        axi_read(16'h060c, rd);
        `TB_CHECK_EQ(rd, 32'd1, "DAC phase epoch increments")
        `TB_CHECK_EQ(dac_phase_epoch, 32'd1, "DAC phase epoch output")
        axi_write(16'h0708, 32'h0000_000f);
        axi_read(16'h0704, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0004, "preview done status readback")
        axi_read(16'h0708, rd);
        `TB_CHECK_EQ(rd, 32'h0000_000f, "preview input mask readback")
        axi_read(16'h070c, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "preview capture count readback")
        axi_read(16'h0710, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0200, "preview sample0 low readback")
        axi_read(16'h0714, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "preview sample0 high readback")
        axi_read(16'h0718, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "preview nsamp readback")
        axi_read(16'h071c, rd);
        `TB_CHECK_EQ(rd, 32'd245_760_000, "preview sample rate readback")
        axi_read(16'h0720, rd);
        `TB_CHECK_EQ(rd, 32'd61_440_000, "preview axis beat rate readback")
        axi_read(16'h0724, rd);
        `TB_CHECK_EQ(rd, 32'd1, "preview mode readback")
        axi_write(16'h0730, 32'h0000_0207);
        axi_read(16'h0730, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0206, "preview audit control readback")
        `TB_CHECK_EQ(preview_audit_source_select, 2'd2, "preview audit source output")
        `TB_CHECK(preview_audit_event_enable, "preview audit event enable output")
        `TB_CHECK(preview_audit_freeze_on_event, "preview audit freeze output")
        axi_read(16'h0734, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0101, "preview audit status readback")
        axi_read(16'h0738, rd);
        `TB_CHECK_EQ(rd, 32'd3, "preview audit start count")
        axi_read(16'h074c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_1010, "preview audit first sample0 low")
        axi_read(16'h0750, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "preview audit first sample0 high")
        axi_read(16'h075c, rd);
        `TB_CHECK_EQ(rd, 32'd9, "preview audit latency")
        axi_read(16'h0760, rd);
        `TB_CHECK_EQ(rd, 32'd256, "preview audit capture beats")
        axi_read(16'h0764, rd);
        `TB_CHECK_EQ(rd, 32'd4, "preview audit valid gaps")
        axi_read(16'h0768, rd);
        `TB_CHECK_EQ(rd, 32'd5, "preview audit sample0 errors")
        axi_write(16'h0770, 32'd28000);
        `TB_CHECK_EQ(preview_audit_event_threshold, 16'd28000, "preview audit threshold output")
        axi_read(16'h0770, rd);
        `TB_CHECK_EQ(rd, 32'd28000, "preview audit threshold readback")
        axi_read(16'h0774, rd);
        `TB_CHECK_EQ(rd, 32'h0000_2004, "preview event sample0 low")
        axi_read(16'h077c, rd);
        `TB_CHECK_EQ(rd, 32'd32000, "preview event max code")
        axi_read(16'h0784, rd);
        `TB_CHECK_EQ(rd, 32'h0000_000f, "preview event RFDC flags")
        axi_read(16'h0788, rd);
        `TB_CHECK_EQ(rd, 32'd17, "preview event DAC epoch")
        axi_read(16'h078c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "preview event buffer words")
        axi_read(16'ha808, rd);
        `TB_CHECK_EQ(rd, 32'hea00_0002, "preview event buffer readback")
        axi_read(16'h06e0, rd);
        `TB_CHECK_EQ(rd, 32'd17, "DAC audit epoch seen")
        axi_read(16'h06e4, rd);
        `TB_CHECK_EQ(rd, 32'h1234_5678, "DAC audit phase accumulator")
        axi_read(16'h06e8, rd);
        `TB_CHECK_EQ(rd, 32'h0102_0304, "DAC audit phase step")
        axi_read(16'h06ec, rd);
        `TB_CHECK_EQ(rd, 32'h4000_0000, "DAC audit phase0")
        axi_read(16'h06f0, rd);
        `TB_CHECK_EQ(rd, 32'd1, "DAC audit mode")
        axi_read(16'h2800, rd);
        `TB_CHECK_EQ(rd, 32'hfeed_cafe, "preview buffer readback")

        axi_read(32'h8004_0008, rd);
        `TB_CHECK_EQ(rd, 32'd3, "absolute MODE readback")
        axi_write_split(32'h8004_0004, 32'h0000_0510);
        axi_read(32'h8004_0004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0510, "split AW/W absolute BOARD_ID write")
        axi_read(32'h8004_00f0, rd);
        `TB_CHECK_EQ(rd, 32'h8004_00f0, "debug last AR address")
        axi_read(32'h8004_00f4, rd);
        `TB_CHECK_EQ(rd, 32'h8004_0004, "debug last AW address")

        `TB_PASS("tb_feng_ctrl_axi")
    end

endmodule
