`include "tb_common.svh"

module tb_feng_ctrl_axi;

    logic clk = 1'b0;
    logic rst_n = 1'b0;

    always #5 clk = ~clk;

    localparam integer TB_TX_ENDPOINTS = 24;
    localparam integer TB_SPEC_ROUTES = 16;

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
    logic [31:0]  spec_dropped_count = 32'd0;
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
    logic [31:0]  science_dropped_beat_count = 32'd0;
    logic [31:0]  tx_fifo_level_words = 32'd0;
    logic [31:0]  tx_fifo_high_water_words = 32'd0;
    logic [31:0]  tx_fifo_backpressure_cycles = 32'd0;
    logic [31:0]  tx_preflight_status_flags = 32'h0000_0682;
    logic [31:0]  tx_frame_built_count = 32'd9;
    logic [31:0]  tx_frame_dropped_count = 32'd1;
    logic [31:0]  tx_frame_byte_count = 32'd8192;
    logic [31:0]  tx_route_miss_count = 32'd2;
    logic [31:0]  tx_route_error_count = 32'd3;
    logic [31:0]  tx_cmac_source_status = 32'h0000_01d3;
    logic [7:0]   tx_selected_endpoint_id = 8'd9;
    logic [5:0]   tx_selected_route_id = 6'd1;
    logic         tx_selected_route_is_time = 1'b0;
    logic [31:0]  pfb_status = 32'h0000_0003;
    logic [31:0]  pfb_frame_count = 32'd0;
    logic [31:0]  pfb_overflow_count = 32'd0;
    logic [31:0]  pfb_data_halt_count = 32'd0;
    logic [31:0]  pfb_xfft_event_count = 32'd0;
    logic [31:0]  pfb_tile_overflow_count = 32'd0;
    logic [31:0]  pfb_xfft_tlast_unexpected_count = 32'd0;
    logic [31:0]  pfb_xfft_tlast_missing_count = 32'd0;
    logic [31:0]  pfb_xfft_fft_overflow_count = 32'd0;
    logic [31:0]  pfb_xfft_data_out_halt_count = 32'd0;
    logic [31:0]  pfb_xfft_status_halt_count = 32'd0;
    logic [31:0]  pfb_capture_backpressure_count = 32'd0;
    logic [31:0]  pfb_frame_sample0_overflow_count = 32'd0;
    logic [31:0]  pfb_input_fifo_level = 32'd0;
    logic [31:0]  pfb_peak_chan = 32'd0;
    logic [31:0]  pfb_peak_power = 32'd0;
    logic [31:0]  pfb_coeff_status = 32'h0000_0801;
    logic [31:0]  pfb_coeff_loaded_count = 32'd32768;
    logic [31:0]  pfb_coeff_active_id = 32'h34a8_0001;
    logic [31:0]  pfb_coeff_active_checksum = 32'hb9ba_227c;
    logic [31:0]  pfb_coeff_error_count = 32'd0;
    logic [31:0]  time_ddr_ring_status = 32'd0;
    logic [31:0]  time_ddr_ring_occupancy = 32'd0;
    logic [31:0]  time_ddr_ring_write_count = 32'd0;
    logic [31:0]  time_ddr_ring_read_count = 32'd0;
    logic [31:0]  time_ddr_ring_drop_count = 32'd0;
    logic [31:0]  time_ddr_ring_error_count = 32'd0;

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
    wire        pfb_coeff_load_start_pulse;
    wire        pfb_coeff_commit_pulse;
    wire        pfb_coeff_abort_pulse;
    wire        pfb_coeff_write_pulse;
    wire [3:0]  pfb_coeff_requested_taps;
    wire [14:0] pfb_coeff_index;
    wire signed [17:0] pfb_coeff_data;
    wire [31:0] pfb_coeff_id;
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
    wire [31:0] tx_control;
    wire        tx_clear_pulse;
    wire [TB_TX_ENDPOINTS-1:0] tx_endpoint_enable;
    wire [TB_TX_ENDPOINTS*32-1:0] tx_endpoint_ip_vec;
    wire [TB_TX_ENDPOINTS*48-1:0] tx_endpoint_mac_vec;
    wire [TB_TX_ENDPOINTS*16-1:0] tx_endpoint_src_port_vec;
    wire [TB_TX_ENDPOINTS*16-1:0] tx_endpoint_dst_port_vec;
    wire [TB_SPEC_ROUTES-1:0] tx_spec_route_enable;
    wire [TB_SPEC_ROUTES*32-1:0] tx_spec_route_chan0_vec;
    wire [TB_SPEC_ROUTES*16-1:0] tx_spec_route_chan_count_vec;
    wire [TB_SPEC_ROUTES*8-1:0] tx_spec_route_endpoint_vec;
    wire [7:0]  tx_time_route_enable;
    wire [127:0] tx_time_route_input_mask_vec;
    wire [64-1:0] tx_time_route_endpoint_vec;
    wire [31:0] dac_phase_epoch;
    wire [1:0]  science_sample_rate_mode_cfg;
    wire [2:0]  science_output_mode_cfg;
    wire        science_aa100_active_tb = (science_sample_rate_mode_cfg == 2'd1);
    wire        science_aa100_primed_tb = (science_sample_rate_mode_cfg == 2'd1);
    wire [31:0] time_live_interval_beats;
    wire        time_ddr_ring_enable;
    wire        time_ddr_ring_clear_pulse;
    wire [63:0] time_ddr_ring_base_addr;
    wire [15:0] time_ddr_ring_slots;
    wire        time_multiflow_enable;
    wire [2:0]  time_multiflow_base_endpoint;
    wire [3:0]  time_multiflow_count;


    localparam integer TB_SPEC_HIT_PAD = TB_SPEC_ROUTES - 2;
    wire [TB_SPEC_ROUTES*32-1:0] tx_spec_route_hit_counts_tb =
        {{TB_SPEC_HIT_PAD{32'd0}}, 32'd22, 32'd11};

    feng_ctrl_axi #(
        .N_TX_ENDPOINTS(TB_TX_ENDPOINTS),
        .N_SPEC_ROUTES(TB_SPEC_ROUTES)
    ) dut (
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
        .sysref_capture_levels(3'b101),
        .sysref_pl_edge_count(32'd101),
        .sysref_adc_edge_count(32'd100),
        .sysref_dac_edge_count(32'd99),
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
        .spec_dropped_count(spec_dropped_count),
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
        .science_dropped_beat_count(science_dropped_beat_count),
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
        .tx_cmac_source_status(tx_cmac_source_status),
        .tx_selected_endpoint_id(tx_selected_endpoint_id),
        .tx_selected_route_id(tx_selected_route_id),
        .tx_selected_route_is_time(tx_selected_route_is_time),
        .tx_spec_route_hit_counts(tx_spec_route_hit_counts_tb),
        .tx_time_route_hit_counts({32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd33}),
        .time_ddr_ring_status(time_ddr_ring_status),
        .time_ddr_ring_occupancy(time_ddr_ring_occupancy),
        .time_ddr_ring_write_count(time_ddr_ring_write_count),
        .time_ddr_ring_read_count(time_ddr_ring_read_count),
        .time_ddr_ring_drop_count(time_ddr_ring_drop_count),
        .time_ddr_ring_error_count(time_ddr_ring_error_count),
        .pfb_status(pfb_status),
        .pfb_frame_count(pfb_frame_count),
        .pfb_overflow_count(pfb_overflow_count),
        .pfb_data_halt_count(pfb_data_halt_count),
        .pfb_xfft_event_count(pfb_xfft_event_count),
        .pfb_tile_overflow_count(pfb_tile_overflow_count),
        .pfb_xfft_tlast_unexpected_count(pfb_xfft_tlast_unexpected_count),
        .pfb_xfft_tlast_missing_count(pfb_xfft_tlast_missing_count),
        .pfb_xfft_fft_overflow_count(pfb_xfft_fft_overflow_count),
        .pfb_xfft_data_out_halt_count(pfb_xfft_data_out_halt_count),
        .pfb_xfft_status_halt_count(pfb_xfft_status_halt_count),
        .pfb_capture_backpressure_count(pfb_capture_backpressure_count),
        .pfb_frame_sample0_overflow_count(pfb_frame_sample0_overflow_count),
        .pfb_input_fifo_level(pfb_input_fifo_level),
        .pfb_peak_chan(pfb_peak_chan),
        .pfb_peak_power(pfb_peak_power),
        .pfb_coeff_status(pfb_coeff_status),
        .pfb_coeff_loaded_count(pfb_coeff_loaded_count),
        .pfb_coeff_active_id(pfb_coeff_active_id),
        .pfb_coeff_active_checksum(pfb_coeff_active_checksum),
        .pfb_coeff_error_count(pfb_coeff_error_count),
        .science_aa100_active(science_aa100_active_tb),
        .science_aa100_primed(science_aa100_primed_tb),
        .science_aa100_coeff_version(32'hAA16_0055),
        .preview_busy(1'b0),
        .preview_done(1'b1),
        .preview_error(1'b0),
        .preview_capture_count(32'd1024),
        .preview_sample0(64'h0000_0001_0000_0200),
        .preview_rd_data(32'hfeed_cafe),
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
        .pfb_coeff_load_start_pulse(pfb_coeff_load_start_pulse),
        .pfb_coeff_commit_pulse(pfb_coeff_commit_pulse),
        .pfb_coeff_abort_pulse(pfb_coeff_abort_pulse),
        .pfb_coeff_write_pulse(pfb_coeff_write_pulse),
        .pfb_coeff_requested_taps(pfb_coeff_requested_taps),
        .pfb_coeff_index(pfb_coeff_index),
        .pfb_coeff_data(pfb_coeff_data),
        .pfb_coeff_id(pfb_coeff_id),
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
        .unix_seconds(unix_seconds),
        .time_live_interval_beats(time_live_interval_beats),
        .time_ddr_ring_enable(time_ddr_ring_enable),
        .time_ddr_ring_clear_pulse(time_ddr_ring_clear_pulse),
        .time_ddr_ring_base_addr(time_ddr_ring_base_addr),
        .time_ddr_ring_slots(time_ddr_ring_slots),
        .time_multiflow_enable(time_multiflow_enable),
        .time_multiflow_base_endpoint(time_multiflow_base_endpoint),
        .time_multiflow_count(time_multiflow_count),
        .science_sample_rate_mode_cfg(science_sample_rate_mode_cfg),
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
        `TB_CHECK_EQ(rd, 32'h0001_0035, "CORE_VERSION Stage 34c-2R")
        axi_read(32'h0000_002c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0005, "SYSREF capture levels")
        axi_read(32'h0000_0030, rd);
        `TB_CHECK_EQ(rd, 32'd101, "PL SYSREF edge count")
        axi_read(32'h0000_0034, rd);
        `TB_CHECK_EQ(rd, 32'd100, "ADC SYSREF edge count")
        axi_read(32'h0000_0038, rd);
        `TB_CHECK_EQ(rd, 32'd99, "DAC SYSREF edge count")
        axi_read(16'h0008, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default MODE")
        axi_read(16'h0114, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default TIME payload count")
        axi_read(16'h011c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default SPEC channel count")
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default PFB enable")
        axi_read(16'h0908, rd);
        `TB_CHECK_EQ(rd, 32'd4096, "default PFB nchan")
        axi_read(16'h090c, rd);
        `TB_CHECK_EQ(rd, 32'd8, "current PFB uses eight taps")
        axi_write(16'h090c, 32'd0);
        axi_read(16'h090c, rd);
        `TB_CHECK_EQ(rd, 32'd8, "PFB tap count is fixed")
        axi_read(16'h0960, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0080, "default PFB coefficient control")
        axi_write(16'h0968, 32'h0000_5234);
        axi_read(16'h0968, rd);
        `TB_CHECK_EQ(rd, 32'h0000_5234, "PFB 15-bit coefficient index readback")
        axi_write(16'h096c, 32'h0001_ffff);
        axi_read(16'h096c, rd);
        `TB_CHECK_EQ(rd, 32'h0001_ffff, "PFB coefficient data readback")
        axi_write(16'h0960, 32'h0000_0088);
        axi_write(16'h0968, 32'h0000_5234);
        axi_write(16'h096c, 32'h0000_1111);
        `TB_CHECK_EQ(pfb_coeff_index, 15'h5234, "coefficient payload index")
        `TB_CHECK_EQ(pfb_coeff_data, 18'h01111, "coefficient payload data")
        axi_read(16'h0968, rd);
        `TB_CHECK_EQ(rd, 32'h0000_5235, "coefficient index auto-increments")
        axi_write(16'h096c, 32'h0000_2222);
        `TB_CHECK_EQ(pfb_coeff_index, 15'h5235, "next coefficient payload index")
        `TB_CHECK_EQ(pfb_coeff_data, 18'h02222, "next coefficient payload data")
        axi_read(16'h0968, rd);
        `TB_CHECK_EQ(rd, 32'h0000_5236, "coefficient index remains monotonic")
        axi_read(16'h0974, rd);
        `TB_CHECK_EQ(rd, pfb_coeff_active_id, "active coefficient id status")
        axi_read(16'h0918, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default PFB channel count")
        axi_read(16'h091c, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default PFB time count")
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
        `TB_CHECK_EQ(rd, 32'h0000_0d10, "default current status is 160MS/s/OFF with half-band active")
        axi_read(16'hd008, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default science rate tier is narrow")
        `TB_CHECK_EQ(science_sample_rate_mode_cfg, 2'd1, "default science bandwidth output")
        axi_read(16'hd00c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default science mode is OFF")
        `TB_CHECK_EQ(science_output_mode_cfg, 3'd0, "default science mode output")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd160_000_000, "default current science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd2, "default science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0040, "default science block reasons keep dry-run blocker only")
        `TB_CHECK_EQ(rd[4], 1'b0, "RFDC science bus truncation block is cleared")
        `TB_CHECK_EQ(rd[11], 1'b0, "science rate drop block is clear by default")
        axi_read(16'hd020, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0707, "current science capability word")
        axi_read(16'hd024, rd);
        `TB_CHECK_EQ(rd, 32'd7680, "default TIME live interval beats")
        `TB_CHECK_EQ(time_live_interval_beats, 32'd7680, "default TIME live interval output")
        axi_read(16'hd028, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0000, "default TIME DDR ring control")
        axi_read(16'hd02c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0000, "default TIME DDR ring base low")
        axi_read(16'hd030, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0008, "default TIME DDR ring base high")
        axi_read(16'hd034, rd);
        `TB_CHECK_EQ(rd, 32'd64, "default TIME DDR ring slots")
        axi_read(16'hd038, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0000, "default TIME DDR ring status")
        axi_read(16'hd03c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default TIME DDR ring occupancy")
        axi_read(16'hd040, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default TIME DDR ring write count")
        axi_read(16'hd044, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default TIME DDR ring read count")
        axi_read(16'hd048, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default TIME DDR ring drop count")
        axi_read(16'hd04c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default TIME DDR ring error count")
        axi_read(16'hd050, rd);
        `TB_CHECK_EQ(rd, 32'h0001_0000, "default TIME multiflow disabled count one")
        `TB_CHECK_EQ(time_multiflow_enable, 1'b0, "default TIME multiflow enable output")
        `TB_CHECK_EQ(time_multiflow_base_endpoint, 3'd0, "default TIME multiflow base endpoint")
        `TB_CHECK_EQ(time_multiflow_count, 4'd1, "default TIME multiflow count")
        axi_read(16'hd054, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0337, "current half-band status active primed 55 taps")
        axi_read(16'hd058, rd);
        `TB_CHECK_EQ(rd, 32'haa16_0055, "current half-band coefficient version")
        axi_read(16'hd060, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired diagnostic register is reserved")
        axi_write(16'hd060, 32'h0001_0103);
        axi_read(16'hd060, rd);
        `TB_CHECK_EQ(rd, 32'd0, "reserved diagnostic register ignores writes")
        axi_write(16'hd050, 32'h0008_0001);
        axi_read(16'hd050, rd);
        `TB_CHECK_EQ(rd, 32'h0008_0001, "TIME multiflow 8-flow readback")
        `TB_CHECK(time_multiflow_enable, "TIME multiflow enable output")
        `TB_CHECK_EQ(time_multiflow_count, 4'd8, "TIME multiflow count output")
        axi_write(16'hd050, 32'h0004_0201);
        axi_read(16'hd050, rd);
        `TB_CHECK_EQ(rd, 32'h0004_0201, "TIME multiflow base endpoint readback")
        `TB_CHECK_EQ(time_multiflow_base_endpoint, 3'd2, "TIME multiflow base endpoint output")
        axi_write(16'hd024, 32'd1);
        axi_read(16'hd024, rd);
        `TB_CHECK_EQ(rd, 32'd16, "TIME live interval clamps low nonzero")
        axi_write(16'hd024, 32'd0);
        axi_read(16'hd024, rd);
        `TB_CHECK_EQ(rd, 32'd0, "TIME live interval allows continuous mode")
        axi_write(16'hd024, 32'd12345);
        axi_read(16'hd024, rd);
        `TB_CHECK_EQ(rd, 32'd12345, "TIME live interval readback")
        `TB_CHECK_EQ(time_live_interval_beats, 32'd12345, "TIME live interval output")
        axi_write(16'hb100, 32'd0);
        axi_read(16'hb104, rd);
        `TB_CHECK_EQ(rd, 32'd1, "default endpoint0 enabled")
        axi_read(16'hb108, rd);
        `TB_CHECK_EQ(rd, 32'h0a00_0110, "default endpoint0 IP")
        axi_read(16'hb114, rd);
        `TB_CHECK_EQ(rd, 32'd4300, "default endpoint0 dst port")
        axi_write(16'hb100, 32'd23);
        axi_read(16'hb100, rd);
        `TB_CHECK_EQ(rd, 32'd23, "endpoint indirect index accepts endpoint23")
        axi_write(16'hb108, 32'h0a00_0123);
        axi_write(16'hb10c, 32'h89ab_cdef);
        axi_write(16'hb110, 32'h0000_4567);
        axi_write(16'hb114, 32'd4323);
        axi_write(16'hb118, 32'd4023);
        axi_write(16'hb104, 32'd1);
        axi_read(16'hb108, rd);
        `TB_CHECK_EQ(rd, 32'h0a00_0123, "endpoint23 indirect IP readback")
        axi_read(16'hb10c, rd);
        `TB_CHECK_EQ(rd, 32'h89ab_cdef, "endpoint23 indirect MAC low readback")
        axi_read(16'hb110, rd);
        `TB_CHECK_EQ(rd, 32'h0000_4567, "endpoint23 indirect MAC high readback")
        axi_read(16'hb114, rd);
        `TB_CHECK_EQ(rd, 32'd4323, "endpoint23 indirect dst port")
        axi_read(16'hb118, rd);
        `TB_CHECK_EQ(rd, 32'd4023, "endpoint23 indirect src port")
        axi_write(16'hb130, 32'd0);
        axi_read(16'hb134, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0801, "default SPEC route0 control")
        axi_read(16'hb138, rd);
        `TB_CHECK_EQ(rd, 32'd0, "default SPEC route0 chan0")
        axi_read(16'hb13c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "default SPEC route0 count")
        axi_write(16'hb130, 32'd15);
        axi_read(16'hb130, rd);
        `TB_CHECK_EQ(rd, 32'd15, "SPEC route indirect index accepts route15")
        axi_write(16'hb134, 32'h0000_1701);
        axi_write(16'hb138, 32'd3840);
        axi_write(16'hb13c, 32'd256);
        axi_read(16'hb134, rd);
        `TB_CHECK_EQ(rd, 32'h0000_1701, "SPEC route15 indirect control")
        axi_read(16'hb138, rd);
        `TB_CHECK_EQ(rd, 32'd3840, "SPEC route15 indirect chan0")
        axi_read(16'hb13c, rd);
        `TB_CHECK_EQ(rd, 32'd256, "SPEC route15 indirect count")
        axi_write(16'hb150, 32'd0);
        axi_read(16'hb154, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0001, "default TIME route0 control")
        axi_read(16'hb158, rd);
        `TB_CHECK_EQ(rd, 32'h0000_00ff, "default TIME route0 mask")
        axi_write(16'hb150, 32'd7);
        axi_read(16'hb150, rd);
        `TB_CHECK_EQ(rd, 32'd7, "TIME route indirect index accepts route7")
        axi_write(16'hb154, 32'h0000_0701);
        axi_write(16'hb158, 32'h0000_0080);
        axi_read(16'hb154, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0701, "TIME route7 indirect control")
        axi_read(16'hb158, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0080, "TIME route7 indirect mask")
        axi_read(16'h0794, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired payload window is reserved")
        axi_write(16'h0798, 32'd1);
        axi_read(16'h0798, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired payload control ignores writes")
        axi_read(16'hb604, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired DAC witness window is reserved")
        axi_write(16'hb608, 32'd64);
        axi_read(16'hb608, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired DAC witness control ignores writes")
        axi_read(16'he204, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired RFDC witness window is reserved")
        axi_write(16'he208, 32'd5);
        axi_read(16'he208, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired RFDC witness control ignores writes")
        axi_read(32'h0001_0000, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired payload buffer is reserved")
        axi_read(16'hc000, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired DAC witness buffer is reserved")
        axi_read(16'he800, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired RFDC witness buffer is reserved")

        axi_write(16'hd008, 32'd0);
        axi_write(16'hd00c, 32'd3);
        axi_read(16'hd004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_6d13, "unsupported tier zero falls back to 160MS/s TIME_SPEC")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd160_000_000, "fallback narrow science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd2, "fallback narrow science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0140, "20MHz TIME_SPEC blocks dry-run and missing F-engine backend")
        `TB_CHECK_EQ(science_sample_rate_mode_cfg, 2'd1, "invalid current tier falls back to narrow")
        `TB_CHECK_EQ(science_output_mode_cfg, 3'd3, "TIME_SPEC science mode output")

        axi_write(16'hd008, 32'd2);
        axi_read(16'hd004, rd);
        `TB_CHECK_EQ(rd, 32'h0000_6217, "200MHz TIME_SPEC is explicitly rejected")
        axi_read(16'hd010, rd);
        `TB_CHECK_EQ(rd, 32'd320_000_000, "320MS/s science sample rate")
        axi_read(16'hd014, rd);
        `TB_CHECK_EQ(rd, 32'd1, "200MHz science decim factor")
        axi_read(16'hd01c, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0141, "200MHz TIME_SPEC block reasons")
        `TB_CHECK_EQ(rd[0], 1'b1, "200MHz TIME_SPEC rejection bit set")
        `TB_CHECK_EQ(rd[4], 1'b0, "RFDC bus truncation remains cleared at 200MHz")
        `TB_CHECK_EQ(rd[11], 1'b0, "science rate drop block remains clear at 200MHz")

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
        axi_write(32'h0001_3060, 32'd1);
        axi_write(32'h0001_3064, 32'h0a00_0112);
        axi_write(32'h0001_3068, 32'h5566_7788);
        axi_write(32'h0001_306c, 32'h0000_1122);
        axi_write(32'h0001_3070, 32'd4400);
        axi_write(32'h0001_3074, 32'd4001);
        axi_write(32'h0001_4040, 32'h0000_0301);
        axi_write(32'h0001_4044, 32'd1024);
        axi_write(32'h0001_4048, 32'd64);
        axi_write(32'h0001_4840, 32'h0000_0301);
        axi_write(32'h0001_4844, 32'h0000_000f);
        axi_write(16'h0914, 32'd128);
        axi_write(16'h0918, 32'd32);
        axi_write(16'h091c, 32'd8);
        axi_write(16'h0910, 32'h0000_0aaa);
        axi_write(16'h0910, 32'h0000_5556);
        axi_read(16'h0200, rd);
        `TB_CHECK_EQ(rd, 32'hc0a8_0102, "source IP readback")
        `TB_CHECK_EQ(src_mac, 48'haabb_1122_3344, "source MAC output")
        axi_read(16'h0228, rd);
        `TB_CHECK_EQ(rd, 32'd5000, "source UDP port readback")
        `TB_CHECK_EQ(chan_split, 32'd1024, "chan_split output")
        `TB_CHECK_EQ(scale_id, 32'h1234_5678, "scale_id output")
        `TB_CHECK_EQ(unix_seconds, 64'h1122_3344_5566_7788, "unix_seconds output")
        `TB_CHECK_EQ(pfb_chan0, 32'd0, "PFB channel origin is fixed")
        `TB_CHECK_EQ(pfb_chan_count, 16'd256, "PFB channel count is fixed")
        `TB_CHECK_EQ(pfb_time_count, 16'd1, "PFB time count is fixed")
        `TB_CHECK_EQ(spec_chan_count, 16'd256, "SPEC channel count stays 256")
        `TB_CHECK_EQ(spec_time_count, 16'd1, "SPEC time count stays one")
        axi_read(16'h0914, rd);
        `TB_CHECK_EQ(rd, 32'd0, "PFB channel origin readback")
        axi_read(16'h0918, rd);
        `TB_CHECK_EQ(rd, 32'd256, "PFB channel count readback")
        axi_read(16'h091c, rd);
        `TB_CHECK_EQ(rd, 32'd1, "PFB time count readback")
        axi_read(16'h0910, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0556, "12-bit XFFT scale schedule readback")
        axi_read(32'h0001_3064, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired endpoint bulk window is reserved")
        axi_read(32'h0001_4040, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired SPEC route bulk window is reserved")
        axi_read(32'h0001_4840, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TIME route bulk window is reserved")

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
        pfb_status = 32'h0000_0013;
        pfb_frame_count = 32'd17;
        pfb_overflow_count = 32'd2;
        pfb_data_halt_count = 32'd3;
        pfb_xfft_event_count = 32'd4;
        pfb_tile_overflow_count = 32'd5;
        pfb_xfft_tlast_unexpected_count = 32'd6;
        pfb_xfft_tlast_missing_count = 32'd7;
        pfb_xfft_fft_overflow_count = 32'd8;
        pfb_xfft_data_out_halt_count = 32'd9;
        pfb_xfft_status_halt_count = 32'd10;
        pfb_capture_backpressure_count = 32'd11;
        pfb_frame_sample0_overflow_count = 32'd12;
        pfb_input_fifo_level = 32'd1024;
        pfb_peak_chan = 32'd129;
        pfb_peak_power = 32'd123456;
        rfdc_current_valid_mask = 16'h0003;
        rfdc_seen_valid_mask = 16'h00ff;
        science_dropped_beat_count = 32'd7;
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
        axi_read(16'h035c, rd);
        `TB_CHECK_EQ(rd, 32'd7, "science dropped beat count readback")
        axi_read(16'h0360, rd);
        `TB_CHECK_EQ(rd, 32'h0000_0002, "TX link dry-run flags readback")
        axi_read(16'h0364, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX dry-run packet count is reserved")
        axi_read(16'h0368, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX dry-run byte count is reserved")
        axi_read(16'h036c, rd);
        `TB_CHECK_EQ(rd, 32'd123, "TX FIFO level readback")
        axi_read(16'h0370, rd);
        `TB_CHECK_EQ(rd, 32'd456, "TX FIFO high-water readback")
        axi_read(16'h0374, rd);
        `TB_CHECK_EQ(rd, 32'd789, "TX FIFO backpressure readback")
        axi_read(16'h037c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX header status is reserved")
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
        `TB_CHECK_EQ(rd, 32'd9, "TX selected endpoint readback")
        axi_read(16'hb02c, rd);
        `TB_CHECK_EQ(rd, 32'd1, "TX selected SPEC route readback")
        axi_read(16'hb704, rd);
        `TB_CHECK_EQ(rd, 32'h0000_01d3, "TX CMAC source status readback")
        axi_read(32'h0001_400c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired SPEC route0 bulk hit is reserved")
        axi_read(32'h0001_402c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired SPEC route1 bulk hit is reserved")
        axi_read(32'h0001_480c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TIME route0 bulk hit is reserved")
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
        axi_read(16'h0930, rd);
        `TB_CHECK_EQ(rd, 32'd3, "PFB data halt count readback")
        axi_read(16'h0934, rd);
        `TB_CHECK_EQ(rd, 32'd4, "PFB XFFT event count readback")
        axi_read(16'h0938, rd);
        `TB_CHECK_EQ(rd, 32'd5, "PFB tile overflow count readback")
        axi_read(16'h093c, rd);
        `TB_CHECK_EQ(rd, 32'd1024, "PFB input FIFO level readback")
        axi_read(16'h0940, rd);
        `TB_CHECK_EQ(rd, 32'd6, "PFB XFFT TLAST unexpected count readback")
        axi_read(16'h0944, rd);
        `TB_CHECK_EQ(rd, 32'd7, "PFB XFFT TLAST missing count readback")
        axi_read(16'h0948, rd);
        `TB_CHECK_EQ(rd, 32'd8, "PFB XFFT FFT overflow count readback")
        axi_read(16'h094c, rd);
        `TB_CHECK_EQ(rd, 32'd9, "PFB XFFT data output halt count readback")
        axi_read(16'h0950, rd);
        `TB_CHECK_EQ(rd, 32'd10, "PFB XFFT status halt count readback")
        axi_read(16'h0954, rd);
        `TB_CHECK_EQ(rd, 32'd11, "PFB capture backpressure count readback")
        axi_read(16'h0958, rd);
        `TB_CHECK_EQ(rd, 32'd12, "PFB frame sample0 overflow count readback")
        expect_pfb_clear_pulse();
        axi_write(16'h0900, 32'h0000_0000);
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd0, "PFB disable readback")
        axi_write(16'h0900, 32'h0000_0001);
        axi_read(16'h0900, rd);
        `TB_CHECK_EQ(rd, 32'd1, "PFB enable readback")
        expect_tx_clear_pulse();
        axi_read(16'h037c, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX header status is reserved")
        axi_read(16'hb034, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX frame status is reserved")
        axi_read(16'h0380, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX header buffer is reserved")
        axi_read(16'hb040, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired TX frame buffer is reserved")
        axi_read(16'h0500, rd);
        `TB_CHECK_EQ(rd, 32'd12, "clip lane0 readback")
        axi_read(16'h0524, rd);
        `TB_CHECK_EQ(rd, 32'd34, "mean lane1 readback")
        axi_read(16'h0404, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired debug status is reserved")
        axi_read(16'h0800, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired debug time buffer is reserved")
        axi_read(16'h1800, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired debug FFT buffer is reserved")
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
        `TB_CHECK_EQ(rd, 32'd320_000_000, "current preview sample rate readback")
        axi_read(16'h0720, rd);
        `TB_CHECK_EQ(rd, 32'd80_000_000, "current preview AXIS beat rate readback")
        axi_read(16'h0724, rd);
        `TB_CHECK_EQ(rd, 32'd1, "preview mode readback")
        axi_write(16'h0730, 32'h0000_0207);
        axi_read(16'h0730, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired preview diagnostic control is reserved")
        axi_write(16'h0770, 32'd28000);
        axi_read(16'h0770, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired preview event threshold is reserved")
        axi_read(16'ha808, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired preview event buffer is reserved")
        axi_read(16'h06e0, rd);
        `TB_CHECK_EQ(rd, 32'd0, "retired DAC audit window is reserved")
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
