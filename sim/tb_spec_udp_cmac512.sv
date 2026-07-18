`include "tb_common.svh"

module tb_spec_udp_cmac512;

    localparam integer N_ENDPOINTS = 24;
    localparam integer N_SPEC_ROUTES = 16;
    localparam integer FRAME_BEATS = 131;
    localparam integer CAPTURE_PACKETS = 16;
    localparam integer CAPTURE_BEATS = FRAME_BEATS * CAPTURE_PACKETS;
    localparam logic [63:0] SAMPLE0_BASE = 64'h0000_0020_0000_0000;

    logic s_clk = 1'b0;
    logic m_clk = 1'b0;
    logic s_rst_n = 1'b0;
    logic m_rst_n = 1'b0;
    logic s_clear = 1'b0;
    logic m_clear = 1'b0;
    logic enable = 1'b1;
    logic drop_on_route_miss = 1'b1;

    logic [31:0] spec_chan0 = 32'd0;
    logic [1023:0] s_tdata = 1024'd0;
    logic [63:0] s_sample0 = SAMPLE0_BASE;
    logic s_tvalid = 1'b0;
    wire s_tready;

    wire [511:0] m_tdata;
    wire [63:0] m_tkeep;
    wire m_tvalid;
    wire m_tlast;
    logic m_tready = 1'b1;
    logic random_m_backpressure = 1'b0;
    logic force_m_stall = 1'b0;
    logic [15:0] m_ready_lfsr = 16'h1ace;
    integer m_stall_cycles = 0;

    wire [31:0] packet_count;
    wire [31:0] udp_byte_count;
    wire [31:0] frame_built_count;
    wire [31:0] frame_byte_count;
    wire [31:0] frame_dropped_count;
    wire [31:0] route_miss_count;
    wire [31:0] route_error_count;
    wire [31:0] seq_no_debug;
    wire [63:0] sample0_debug;
    wire [63:0] frame_id_debug;
    wire [31:0] chan0_debug;
    wire [7:0] selected_endpoint_id;
    wire [5:0] selected_route_id;
    wire selected_route_is_time;
    wire [N_SPEC_ROUTES*32-1:0] spec_route_hit_count_vec;
    wire [31:0] fifo_level_words;
    wire [31:0] output_frame_count;
    wire [31:0] backpressure_cycles;
    wire fifo_full;
    wire fifo_empty;

    logic [N_ENDPOINTS-1:0] endpoint_enable = {N_ENDPOINTS{1'b1}};
    logic [N_ENDPOINTS*32-1:0] endpoint_ip_vec = {N_ENDPOINTS{32'h0a00_0110}};
    logic [N_ENDPOINTS*48-1:0] endpoint_mac_vec = {N_ENDPOINTS{48'h08c0_ebd5_95b2}};
    logic [N_ENDPOINTS*16-1:0] endpoint_src_port_vec = {N_ENDPOINTS{16'd4000}};
    logic [N_ENDPOINTS*16-1:0] endpoint_dst_port_vec = {N_ENDPOINTS{16'd4300}};
    logic [N_SPEC_ROUTES-1:0] spec_route_enable = {N_SPEC_ROUTES{1'b1}};
    logic [N_SPEC_ROUTES*32-1:0] spec_route_chan0_vec = {N_SPEC_ROUTES{32'd0}};
    logic [N_SPEC_ROUTES*16-1:0] spec_route_chan_count_vec = {N_SPEC_ROUTES{16'd256}};
    logic [N_SPEC_ROUTES*8-1:0] spec_route_endpoint_vec = {N_SPEC_ROUTES{8'd8}};

    logic [511:0] captured [0:CAPTURE_BEATS-1];
    logic [63:0] captured_keep [0:CAPTURE_BEATS-1];
    logic captured_last [0:CAPTURE_BEATS-1];
    integer out_count = 0;
    integer last_count = 0;
    integer last_index = -1;
    integer input_cycle = 0;
    integer contiguous_accept_count = 0;
    integer restart_out_before = 0;
    integer restart_last_before = 0;
    integer restart_timeout = 0;

    always #5 s_clk = ~s_clk;
    always #3 m_clk = ~m_clk;

    always_ff @(posedge m_clk) begin
        if (!m_rst_n) begin
            m_ready_lfsr <= 16'h1ace;
            m_tready <= 1'b1;
            m_stall_cycles <= 0;
        end else begin
            m_ready_lfsr <= {m_ready_lfsr[14:0], m_ready_lfsr[15] ^ m_ready_lfsr[13] ^ m_ready_lfsr[12] ^ m_ready_lfsr[10]};
            m_tready <= !force_m_stall &&
                (!random_m_backpressure || m_ready_lfsr[0] || m_ready_lfsr[1]);
            if (random_m_backpressure && m_tvalid && !m_tready) begin
                m_stall_cycles <= m_stall_cycles + 1;
            end
        end
    end

    always_ff @(posedge s_clk) begin
        if (!s_rst_n) begin
            input_cycle <= 0;
        end else begin
            input_cycle <= input_cycle + 1;
        end
    end

    function automatic [1023:0] make_payload(input integer packet_idx, input integer beat_idx);
        integer byte_idx;
        integer payload_byte_idx;
        begin
            make_payload = 1024'd0;
            for (byte_idx = 0; byte_idx < 128; byte_idx = byte_idx + 1) begin
                payload_byte_idx = (packet_idx * 8192) + (beat_idx * 128) + byte_idx;
                make_payload[byte_idx*8 +: 8] = payload_byte_idx[7:0];
            end
        end
    endfunction

    function automatic [7:0] frame_byte_at(input integer packet_idx, input integer abs_idx);
        integer beat_idx;
        integer byte_idx;
        begin
            beat_idx = packet_idx * FRAME_BEATS + (abs_idx / 64);
            byte_idx = abs_idx % 64;
            frame_byte_at = captured[beat_idx][byte_idx*8 +: 8];
        end
    endfunction

    task automatic check_frame_byte(input integer packet_idx, input integer abs_idx, input [7:0] expected, input string label);
        begin
            `TB_CHECK_EQ(frame_byte_at(packet_idx, abs_idx), expected, label);
        end
    endtask

    task automatic send_payload_packet(input integer packet_idx);
        integer beat_idx;
        begin
            @(negedge s_clk);
            spec_chan0 = packet_idx * 32'd256;
            for (beat_idx = 0; beat_idx < 64; beat_idx = beat_idx + 1) begin
                s_tdata = make_payload(packet_idx, beat_idx);
                s_sample0 = SAMPLE0_BASE + packet_idx * 64'd16384;
                s_tvalid = 1'b1;
                do begin
                    @(posedge s_clk);
                end while (!s_tready);
                @(negedge s_clk);
            end
            s_tvalid = 1'b0;
        end
    endtask

    task automatic send_payload_packets_contiguous;
        integer packet_idx;
        integer beat_idx;
        integer previous_accept_cycle;
        begin
            previous_accept_cycle = -1;
            contiguous_accept_count = 0;
            @(negedge s_clk);
            spec_chan0 = 32'd0;
            s_tdata = make_payload(0, 0);
            s_sample0 = SAMPLE0_BASE;
            while (!s_tready) begin
                @(negedge s_clk);
            end
            s_tvalid = 1'b1;
            for (packet_idx = 0; packet_idx < CAPTURE_PACKETS; packet_idx = packet_idx + 1) begin
                spec_chan0 = packet_idx * 32'd256;
                for (beat_idx = 0; beat_idx < 64; beat_idx = beat_idx + 1) begin
                    s_tdata = make_payload(packet_idx, beat_idx);
                    s_sample0 = SAMPLE0_BASE + packet_idx * 64'd16384;
                    do begin
                        @(posedge s_clk);
                    end while (!s_tready);
                    if (previous_accept_cycle >= 0) begin
                        `TB_CHECK_EQ(input_cycle, previous_accept_cycle + 1, "SPEC continuous payload accepts every adjacent beat including packet boundaries")
                    end
                    previous_accept_cycle = input_cycle;
                    contiguous_accept_count = contiguous_accept_count + 1;
                    @(negedge s_clk);
                end
            end
            s_tvalid = 1'b0;
        end
    endtask

    spec_udp_cmac512 #(
        .DATA_W(1024),
        .N_ENDPOINTS(N_ENDPOINTS),
        .N_SPEC_ROUTES(N_SPEC_ROUTES),
        .DATA_FIFO_DEPTH(512),
        .DATA_COUNT_W(10),
        .TOKEN_FIFO_DEPTH(64),
        .TOKEN_COUNT_W(7),
        .PRODUCTION_27H(1'b1)
    ) dut (
        .s_clk(s_clk),
        .s_rst_n(s_rst_n),
        .s_clear(s_clear),
        .enable(enable),
        .drop_on_route_miss(drop_on_route_miss),
        .board_id(16'h00bb),
        .global_input0(16'h0000),
        .epoch_mode(16'd1),
        .packet_flags(16'h000a),
        .unix_seconds(64'h1122_3344_5566_7788),
        .pps_count(64'h0000_0000_0000_4567),
        .sync_generation(64'd0),
        .sync_observation_tag(64'd0),
        .sync_metadata(64'd0),
        .sync_status(64'd0),
        .quant_mode(16'd0),
        .scale_mode(16'd2),
        .scale_id(32'h1234_5678),
        .spec_chan0(spec_chan0),
        .spec_chan_count(16'd256),
        .spec_time_count(16'd1),
        .spec_nchan(16'd4096),
        .spec_taps(16'd0),
        .spec_fft_shift(16'h00ff),
        .spec_sample_rate_hz(32'd100_000_000),
        .spec_status_flags(32'h0000_0100),
        .chan_split(32'd2048),
        .src_mac(48'h0200_0000_0001),
        .src_ip(32'h0a00_0101),
        .endpoint_enable(endpoint_enable),
        .endpoint_ip_vec(endpoint_ip_vec),
        .endpoint_mac_vec(endpoint_mac_vec),
        .endpoint_src_port_vec(endpoint_src_port_vec),
        .endpoint_dst_port_vec(endpoint_dst_port_vec),
        .spec_route_enable(spec_route_enable),
        .spec_route_chan0_vec(spec_route_chan0_vec),
        .spec_route_chan_count_vec(spec_route_chan_count_vec),
        .spec_route_endpoint_vec(spec_route_endpoint_vec),
        .s_axis_tdata(s_tdata),
        .s_axis_sample0(s_sample0),
        .s_axis_tvalid(s_tvalid),
        .s_axis_tready(s_tready),
        .m_clk(m_clk),
        .m_rst_n(m_rst_n),
        .m_clear(m_clear),
        .m_axis_tdata(m_tdata),
        .m_axis_tkeep(m_tkeep),
        .m_axis_tvalid(m_tvalid),
        .m_axis_tlast(m_tlast),
        .m_axis_tready(m_tready),
        .packet_count(packet_count),
        .udp_byte_count(udp_byte_count),
        .frame_built_count(frame_built_count),
        .frame_byte_count(frame_byte_count),
        .frame_dropped_count(frame_dropped_count),
        .route_miss_count(route_miss_count),
        .route_error_count(route_error_count),
        .seq_no_debug(seq_no_debug),
        .sample0_debug(sample0_debug),
        .frame_id_debug(frame_id_debug),
        .chan0_debug(chan0_debug),
        .selected_endpoint_id(selected_endpoint_id),
        .selected_route_id(selected_route_id),
        .selected_route_is_time(selected_route_is_time),
        .spec_route_hit_count_vec(spec_route_hit_count_vec),
        .fifo_level_words(fifo_level_words),
        .output_frame_count(output_frame_count),
        .backpressure_cycles(backpressure_cycles),
        .fifo_full(fifo_full),
        .fifo_empty(fifo_empty)
    );

    always_ff @(posedge m_clk) begin
        if (!m_rst_n) begin
            out_count <= 0;
            last_count <= 0;
            last_index <= -1;
        end else if (m_tvalid && m_tready) begin
            if (out_count < CAPTURE_BEATS) begin
                captured[out_count] <= m_tdata;
                captured_keep[out_count] <= m_tkeep;
                captured_last[out_count] <= m_tlast;
            end
            if (m_tlast) begin
                last_count <= last_count + 1;
                last_index <= out_count;
            end
            out_count <= out_count + 1;
        end
    end

    integer idx;
    initial begin
        for (idx = 0; idx < N_ENDPOINTS; idx = idx + 1) begin
            endpoint_ip_vec[idx*32 +: 32] = 32'h0a00_0110;
            endpoint_mac_vec[idx*48 +: 48] = 48'h08c0_ebd5_95b2;
            endpoint_src_port_vec[idx*16 +: 16] = 16'd4000 + idx[15:0];
            endpoint_dst_port_vec[idx*16 +: 16] = 16'd4300 + idx[15:0];
        end
        for (idx = 0; idx < N_SPEC_ROUTES; idx = idx + 1) begin
            spec_route_enable[idx] = (idx < CAPTURE_PACKETS);
            spec_route_chan0_vec[idx*32 +: 32] = (idx < CAPTURE_PACKETS) ? (idx * 32'd256) : 32'd0;
            spec_route_chan_count_vec[idx*16 +: 16] = (idx < CAPTURE_PACKETS) ? 16'd256 : 16'd0;
            spec_route_endpoint_vec[idx*8 +: 8] = 8'd8 + idx[7:0];
        end

        repeat (8) @(posedge s_clk);
        s_rst_n = 1'b1;
        m_rst_n = 1'b1;
        repeat (8) @(posedge s_clk);

        random_m_backpressure = 1'b1;
        send_payload_packets_contiguous();

        while (last_count < CAPTURE_PACKETS) begin
            @(posedge m_clk);
        end

        `TB_CHECK_EQ(out_count, CAPTURE_BEATS, "SPEC CMAC beat count");
        `TB_CHECK_EQ(last_index, CAPTURE_BEATS - 1, "SPEC CMAC last index");
        `TB_CHECK_EQ(captured_keep[FRAME_BEATS-1], 64'h0000_03ff_ffff_ffff, "SPEC tail tkeep");
        `TB_CHECK_EQ(captured_last[FRAME_BEATS-1], 1'b1, "SPEC first frame tlast");

        check_frame_byte(0, 34, 8'h0f, "SPEC packet0 src port high");
        check_frame_byte(0, 35, 8'ha8, "SPEC packet0 src port low");
        check_frame_byte(0, 36, 8'h10, "SPEC packet0 dst port high");
        check_frame_byte(0, 37, 8'hd4, "SPEC packet0 dst port low");
        check_frame_byte(15, 34, 8'h0f, "SPEC packet15 src port high");
        check_frame_byte(15, 35, 8'hb7, "SPEC packet15 src port low");
        check_frame_byte(15, 36, 8'h10, "SPEC packet15 dst port high");
        check_frame_byte(15, 37, 8'he3, "SPEC packet15 dst port low");

        check_frame_byte(0, 42, 8'h80, "SPEC T510 header bytes low");
        check_frame_byte(0, 44, 8'h02, "SPEC T510 version low");
        check_frame_byte(0, 46, 8'h30, "SPEC T510 magic byte0");
        check_frame_byte(0, 49, 8'h54, "SPEC T510 magic byte3");
        check_frame_byte(0, 56, 8'hbb, "SPEC board byte");
        check_frame_byte(0, 98, 8'h00, "SPEC quant low");
        check_frame_byte(0, 100, 8'h08, "SPEC ninput low");
        check_frame_byte(0, 102, 8'h01, "SPEC time_count low");
        check_frame_byte(0, 104, 8'h00, "SPEC chan_count low");
        check_frame_byte(0, 105, 8'h01, "SPEC chan_count high");
        check_frame_byte(0, 106, 8'h00, "SPEC payload bytes byte0");
        check_frame_byte(0, 107, 8'h20, "SPEC payload bytes byte1");
        check_frame_byte(0, 114, 8'h10, "SPEC block_count low");
        check_frame_byte(0, 116, 8'h00, "SPEC block_index low");
        check_frame_byte(0, 118, 8'h00, "SPEC nchan byte0");
        check_frame_byte(0, 119, 8'h10, "SPEC nchan byte1");
        check_frame_byte(0, 120, 8'h01, "SPEC product byte0");
        check_frame_byte(0, 121, 8'hf1, "SPEC product byte1");
        check_frame_byte(0, 122, 8'h00, "SPEC status byte0");
        check_frame_byte(0, 123, 8'h01, "SPEC FFT-only status byte1");
        check_frame_byte(0, 126, 8'hff, "SPEC FFT shift low");
        check_frame_byte(0, 128, 8'h00, "SPEC taps low");
        check_frame_byte(15, 116, 8'h0f, "SPEC final block_index low");

        check_frame_byte(0, 170, 8'h00, "SPEC payload byte0");
        check_frame_byte(0, 170 + 8191, 8'hff, "SPEC payload final byte");

        `TB_CHECK_EQ(packet_count, 32'd16, "SPEC packet_count");
        `TB_CHECK_EQ(udp_byte_count, 32'd133120, "SPEC UDP byte count");
        `TB_CHECK_EQ(frame_built_count, 32'd16, "SPEC frame built count");
        `TB_CHECK_EQ(frame_byte_count, 32'd133792, "SPEC frame byte count");
        `TB_CHECK_EQ(frame_dropped_count, 32'd0, "SPEC no frame drops");
        `TB_CHECK_EQ(route_miss_count, 32'd0, "SPEC no route miss");
        `TB_CHECK_EQ(route_error_count, 32'd0, "SPEC no route error");
        `TB_CHECK_EQ(seq_no_debug, 32'd16, "SPEC seq debug");
        `TB_CHECK_EQ(frame_id_debug, 64'd16, "SPEC frame_id debug");
        `TB_CHECK_EQ(chan0_debug, 32'd3840, "SPEC chan0 debug final block");
        `TB_CHECK_EQ(selected_endpoint_id, 8'd23, "SPEC selected endpoint final");
        `TB_CHECK_EQ(selected_route_id, 6'd15, "SPEC selected route final");
        `TB_CHECK(!selected_route_is_time, "SPEC selected route is spec");
        for (idx = 0; idx < N_SPEC_ROUTES; idx = idx + 1) begin
            `TB_CHECK_EQ(spec_route_hit_count_vec[idx*32 +: 32], (idx < CAPTURE_PACKETS) ? 32'd1 : 32'd0, "SPEC route hit count");
        end
        `TB_CHECK_EQ(output_frame_count, 32'd16, "SPEC output frame count");
        `TB_CHECK_EQ(contiguous_accept_count, CAPTURE_PACKETS * 64, "SPEC contiguous accepted input beat count");
        `TB_CHECK_EQ(backpressure_cycles, 32'd0, "SPEC continuous input has no packet-boundary backpressure");
        `TB_CHECK(m_stall_cycles > 0, "SPEC output exercises randomized downstream backpressure");

        // Clear an actively selected, incomplete SPEC frame and prove that a
        // new frame can cross both domains immediately afterwards.
        random_m_backpressure = 1'b0;
        force_m_stall = 1'b1;
        restart_out_before = out_count;
        restart_last_before = last_count;
        send_payload_packet(0);
        wait (m_tvalid);
        @(negedge m_clk);
        force_m_stall = 1'b0;
        while (out_count < restart_out_before + 4) begin
            @(posedge m_clk);
        end
        @(negedge m_clk);
        force_m_stall = 1'b1;
        `TB_CHECK_EQ(last_count, restart_last_before, "partial SPEC frame has no tlast before clear");

        @(negedge s_clk);
        s_clear = 1'b1;
        m_clear = 1'b1;
        repeat (4) @(posedge s_clk);
        @(negedge s_clk);
        s_clear = 1'b0;
        m_clear = 1'b0;
        repeat (8) @(posedge s_clk);
        force_m_stall = 1'b0;

        send_payload_packet(1);
        restart_timeout = 0;
        while ((last_count < restart_last_before + 1) && (restart_timeout < 30000)) begin
            @(posedge m_clk);
            restart_timeout = restart_timeout + 1;
        end
        `TB_CHECK_EQ(last_count, restart_last_before + 1, "SPEC emits a complete frame after runtime clear");
        `TB_CHECK_EQ(packet_count, 32'd1, "SPEC packet counter restarts after clear");
        `TB_CHECK_EQ(output_frame_count, 32'd1, "SPEC output frame counter restarts after clear");
        `TB_CHECK(!fifo_full, "SPEC FIFO is not left full after clear/restart");

        `TB_PASS("tb_spec_udp_cmac512")
    end

endmodule
