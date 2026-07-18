`include "tb_common.svh"

module tb_time_udp_cmac512;

    localparam integer FRAME_BEATS = 131;
    localparam integer PACKETS_PER_CASE = 8;
    localparam integer PACKETS = PACKETS_PER_CASE * 4;
    localparam integer CAPTURE_BEATS = FRAME_BEATS * PACKETS;
    localparam logic [63:0] SAMPLE0_BASE = 64'h0000_0010_0000_0000;
    localparam logic [63:0] SAMPLE0_SECOND = SAMPLE0_BASE + 64'd256;

    logic s_clk = 1'b0;
    logic m_clk = 1'b0;
    logic s_rst_n = 1'b0;
    logic m_rst_n = 1'b0;
    logic s_clear = 1'b0;
    logic m_clear = 1'b0;
    logic enable = 1'b0;
    logic drop_on_route_miss = 1'b1;

    logic [1023:0] s_tdata = 1024'd0;
    logic [63:0]   s_sample0 = 64'd0;
    logic          s_tvalid = 1'b0;
    wire           s_tready;

    wire [511:0] m_tdata;
    wire [63:0]  m_tkeep;
    wire         m_tvalid;
    wire         m_tlast;
    logic        m_tready = 1'b1;

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
    wire [7:0]  selected_endpoint_id;
    wire [5:0]  selected_route_id;
    wire        selected_route_is_time;
    wire [255:0] time_route_hit_count_vec;
    wire [31:0] fifo_level_words;
    wire [31:0] output_frame_count;
    wire [31:0] backpressure_cycles;
    wire fifo_full;
    wire fifo_empty;

    logic [15:0] endpoint_enable = 16'hffff;
    logic [511:0] endpoint_ip_vec = 512'd0;
    logic [767:0] endpoint_mac_vec = 768'd0;
    logic [255:0] endpoint_src_port_vec = 256'd0;
    logic [255:0] endpoint_dst_port_vec = 256'd0;
    logic [7:0] time_route_enable = 8'b0000_0001;
    logic [127:0] time_route_input_mask_vec = 128'd0;
    logic [63:0] time_route_endpoint_vec = 64'd0;
    logic time_multiflow_enable = 1'b1;
    logic [2:0] time_multiflow_base_endpoint = 3'd0;
    logic [3:0] time_multiflow_count = 4'd8;

    logic [511:0] captured [0:CAPTURE_BEATS-1];
    logic [63:0]  captured_keep [0:CAPTURE_BEATS-1];
    logic         captured_last [0:CAPTURE_BEATS-1];
    integer out_count = 0;
    integer last_count = 0;
    integer last_index = -1;
    integer restart_out_before = 0;
    integer restart_last_before = 0;
    integer restart_timeout = 0;

    always #5 s_clk = ~s_clk;
    always #3 m_clk = ~m_clk;

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
            `TB_CHECK_EQ(frame_byte_at(packet_idx, abs_idx), expected, label)
        end
    endtask

    function automatic integer expected_flow_id(input integer packet_idx, input integer flow_count_cfg);
        integer mask;
        begin
            if (flow_count_cfg <= 1) begin
                mask = 0;
            end else if (flow_count_cfg <= 2) begin
                mask = 1;
            end else if (flow_count_cfg <= 4) begin
                mask = 3;
            end else begin
                mask = 7;
            end
            expected_flow_id = packet_idx & mask;
        end
    endfunction

    task automatic check_multiflow_ports(input integer first_packet, input integer flow_count_cfg, input string label);
        integer local_packet;
        integer packet_abs;
        integer expected_flow;
        begin
            for (local_packet = 0; local_packet < PACKETS_PER_CASE; local_packet = local_packet + 1) begin
                packet_abs = first_packet + local_packet;
                expected_flow = expected_flow_id(packet_abs, flow_count_cfg);
                check_frame_byte(packet_abs, 34, (16'd4000 + expected_flow[15:0]) >> 8, {label, " src port high"});
                check_frame_byte(packet_abs, 35, (16'd4000 + expected_flow[15:0]) & 8'hff, {label, " src port low"});
                check_frame_byte(packet_abs, 36, (16'd4300 + expected_flow[15:0]) >> 8, {label, " dst port high"});
                check_frame_byte(packet_abs, 37, (16'd4300 + expected_flow[15:0]) & 8'hff, {label, " dst port low"});
            end
        end
    endtask

    task automatic send_payload_beat(input integer packet_idx, input integer beat_idx);
        begin
            @(negedge s_clk);
            s_tdata = make_payload(packet_idx, beat_idx);
            s_sample0 = SAMPLE0_BASE + packet_idx * 64'd256 + beat_idx * 64'd4;
            s_tvalid = 1'b1;
            do begin
                @(posedge s_clk);
            end while (!s_tready);
        end
    endtask

    task automatic run_multiflow_case(input integer flow_count_cfg, input integer first_packet);
        integer local_packet;
        integer local_beat;
        integer timeout_local;
        begin
            @(negedge s_clk);
            time_multiflow_count = flow_count_cfg[3:0];
            repeat (2) @(posedge s_clk);
            for (local_packet = 0; local_packet < PACKETS_PER_CASE; local_packet = local_packet + 1) begin
                for (local_beat = 0; local_beat < 64; local_beat = local_beat + 1) begin
                    send_payload_beat(first_packet + local_packet, local_beat);
                end
            end
            @(negedge s_clk);
            s_tvalid = 1'b0;

            timeout_local = 0;
            while ((last_count < first_packet + PACKETS_PER_CASE) && (timeout_local < 30000)) begin
                @(posedge m_clk);
                timeout_local = timeout_local + 1;
            end
            `TB_CHECK_EQ(last_count, first_packet + PACKETS_PER_CASE, "wide TIME output frame count per multiflow case")
        end
    endtask

    time_udp_cmac512 dut (
        .s_clk(s_clk),
        .s_rst_n(s_rst_n),
        .s_clear(s_clear),
        .enable(enable),
        .drop_on_route_miss(drop_on_route_miss),
        .board_id(16'h00aa),
        .global_input0(16'h0055),
        .epoch_mode(16'd1),
        .packet_flags(16'h000a),
        .unix_seconds(64'h1122_3344_5566_7788),
        .pps_count(64'h0000_0000_0000_0123),
        .sync_generation(64'd0),
        .sync_observation_tag(64'd0),
        .sync_metadata(64'd0),
        .sync_status(64'd0),
        .quant_mode(16'd0),
        .scale_id(32'h1234_5678),
        .src_mac(48'h0200_0000_0001),
        .src_ip(32'h0a00_0101),
        .time_input_mask(16'h00ff),
        .endpoint_enable(endpoint_enable),
        .endpoint_ip_vec(endpoint_ip_vec),
        .endpoint_mac_vec(endpoint_mac_vec),
        .endpoint_src_port_vec(endpoint_src_port_vec),
        .endpoint_dst_port_vec(endpoint_dst_port_vec),
        .time_route_enable(time_route_enable),
        .time_route_input_mask_vec(time_route_input_mask_vec),
        .time_route_endpoint_vec(time_route_endpoint_vec),
        .time_multiflow_enable(time_multiflow_enable),
        .time_multiflow_base_endpoint(time_multiflow_base_endpoint),
        .time_multiflow_count(time_multiflow_count),
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
        .selected_endpoint_id(selected_endpoint_id),
        .selected_route_id(selected_route_id),
        .selected_route_is_time(selected_route_is_time),
        .time_route_hit_count_vec(time_route_hit_count_vec),
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

    integer flow_idx;
    initial begin
        for (flow_idx = 0; flow_idx < 8; flow_idx = flow_idx + 1) begin
            endpoint_ip_vec[flow_idx*32 +: 32] = 32'h0a00_0110;
            endpoint_mac_vec[flow_idx*48 +: 48] = 48'h08c0_ebd5_95b2;
            endpoint_src_port_vec[flow_idx*16 +: 16] = 16'd4000 + flow_idx[15:0];
            endpoint_dst_port_vec[flow_idx*16 +: 16] = 16'd4300 + flow_idx[15:0];
        end
        time_route_input_mask_vec[0 +: 16] = 16'h00ff;
        time_route_endpoint_vec[0 +: 8] = 8'd0;

        repeat (10) @(posedge s_clk);
        s_rst_n = 1'b1;
        m_rst_n = 1'b1;
        enable = 1'b1;
        repeat (10) @(posedge s_clk);

        run_multiflow_case(1, 0);
        run_multiflow_case(2, PACKETS_PER_CASE);
        run_multiflow_case(4, PACKETS_PER_CASE * 2);
        run_multiflow_case(8, PACKETS_PER_CASE * 3);

        `TB_CHECK_EQ(last_count, PACKETS, "wide TIME output frame count")
        `TB_CHECK_EQ(out_count, CAPTURE_BEATS, "wide TIME CMAC beat count")
        `TB_CHECK_EQ(last_index, CAPTURE_BEATS - 1, "wide TIME last index")
        `TB_CHECK_EQ(captured_keep[FRAME_BEATS-1], 64'h0000_03ff_ffff_ffff, "wide TIME tail tkeep")
        `TB_CHECK_EQ(captured_last[FRAME_BEATS-1], 1'b1, "wide TIME first frame tlast")
        `TB_CHECK_EQ(captured_last[FRAME_BEATS*2-1], 1'b1, "wide TIME second frame tlast")

        check_frame_byte(0, 0, 8'h08, "dst mac byte0");
        check_frame_byte(0, 5, 8'hb2, "dst mac byte5");
        check_frame_byte(0, 6, 8'h02, "src mac byte0");
        check_frame_byte(0, 11, 8'h01, "src mac byte5");
        check_frame_byte(0, 12, 8'h08, "ethertype ipv4 high");
        check_frame_byte(0, 13, 8'h00, "ethertype ipv4 low");
        check_frame_byte(0, 14, 8'h45, "ipv4 version ihl");
        check_frame_byte(0, 16, 8'h20, "ipv4 total length high");
        check_frame_byte(0, 17, 8'h9c, "ipv4 total length low");
        check_frame_byte(0, 34, 8'h0f, "udp src port high");
        check_frame_byte(0, 35, 8'ha0, "udp src port low");
        check_frame_byte(0, 36, 8'h10, "udp dst port high");
        check_frame_byte(0, 37, 8'hcc, "udp dst port low");
        check_frame_byte(0, 38, 8'h20, "udp length high");
        check_frame_byte(0, 39, 8'h88, "udp length low");

        check_frame_byte(0, 42, 8'h80, "T510 word0 header_bytes lo");
        check_frame_byte(0, 44, 8'h02, "T510 word0 version lo");
        check_frame_byte(0, 46, 8'h30, "T510 word0 magic byte0");
        check_frame_byte(0, 49, 8'h54, "T510 word0 magic byte3");
        check_frame_byte(0, 50, 8'h0a, "T510 flags low byte");
        check_frame_byte(0, 56, 8'haa, "T510 board byte");
        check_frame_byte(0, 74, SAMPLE0_BASE[7:0], "T510 sample0 low byte");
        check_frame_byte(0, 98, 8'h00, "T510 word7 format low");
        check_frame_byte(0, 100, 8'h08, "T510 ninput low");
        check_frame_byte(0, 102, 8'h40, "T510 time_count low");
        check_frame_byte(0, 106, 8'h00, "T510 payload bytes byte0");
        check_frame_byte(0, 107, 8'h20, "T510 payload bytes byte1");

        check_frame_byte(0, 170, 8'h00, "payload byte0");
        check_frame_byte(0, 171, 8'h01, "payload byte1");
        check_frame_byte(0, 177, 8'h07, "payload byte7");
        check_frame_byte(0, 170 + 127, 8'h7f, "payload byte127");
        check_frame_byte(0, 170 + 130, 8'h82, "payload crosses 1024-bit beat");
        check_frame_byte(0, 170 + 8191, 8'hff, "payload final byte");

        check_multiflow_ports(0, 1, "multiflow count1");
        check_multiflow_ports(PACKETS_PER_CASE, 2, "multiflow count2");
        check_multiflow_ports(PACKETS_PER_CASE * 2, 4, "multiflow count4");
        check_multiflow_ports(PACKETS_PER_CASE * 3, 8, "multiflow count8");

        check_frame_byte(1, 74, SAMPLE0_SECOND[7:0], "second frame sample0 low byte");
        check_frame_byte(1, 82, 8'h01, "second frame frame_id low byte");
        check_frame_byte(1, 94, 8'h01, "second frame seq low byte");

        `TB_CHECK_EQ(packet_count, 32'd32, "wide TIME packet_count")
        `TB_CHECK_EQ(udp_byte_count, 32'd266240, "wide TIME UDP byte count")
        `TB_CHECK_EQ(frame_built_count, 32'd32, "wide TIME frame built count")
        `TB_CHECK_EQ(frame_byte_count, 32'd267584, "wide TIME frame byte count")
        `TB_CHECK_EQ(frame_dropped_count, 32'd0, "wide TIME no frame drops")
        `TB_CHECK_EQ(route_miss_count, 32'd0, "wide TIME no route miss")
        `TB_CHECK_EQ(route_error_count, 32'd0, "wide TIME no route error")
        `TB_CHECK_EQ(seq_no_debug, 32'd32, "wide TIME seq debug")
        `TB_CHECK_EQ(sample0_debug, SAMPLE0_BASE + 64'd7936, "wide TIME sample0 debug")
        `TB_CHECK_EQ(frame_id_debug, 64'd32, "wide TIME frame_id debug")
        `TB_CHECK_EQ(selected_endpoint_id, 4'd7, "wide TIME selected endpoint")
        `TB_CHECK_EQ(selected_route_id, 3'd0, "wide TIME selected route")
        `TB_CHECK(selected_route_is_time, "wide TIME selected route is time")
        `TB_CHECK_EQ(time_route_hit_count_vec[0 +: 32], 32'd32, "wide TIME route hit count")
        `TB_CHECK_EQ(output_frame_count, 32'd32, "wide TIME output frame counter")

        // Reproduce STOP/ABORT while CMAC owns an incomplete frame.  Both
        // clock-domain clears must discard it and allow the very next packet
        // to terminate normally without a full bitstream reload.
        @(negedge m_clk);
        m_tready = 1'b0;
        restart_out_before = out_count;
        restart_last_before = last_count;
        for (flow_idx = 0; flow_idx < 64; flow_idx = flow_idx + 1) begin
            send_payload_beat(PACKETS, flow_idx);
        end
        @(negedge s_clk);
        s_tvalid = 1'b0;
        wait (m_tvalid);
        @(negedge m_clk);
        m_tready = 1'b1;
        while (out_count < restart_out_before + 4) begin
            @(posedge m_clk);
        end
        @(negedge m_clk);
        m_tready = 1'b0;
        `TB_CHECK_EQ(last_count, restart_last_before, "partial TIME frame has no tlast before clear")

        @(negedge s_clk);
        s_clear = 1'b1;
        m_clear = 1'b1;
        repeat (4) @(posedge s_clk);
        @(negedge s_clk);
        s_clear = 1'b0;
        m_clear = 1'b0;
        repeat (8) @(posedge s_clk);
        @(negedge m_clk);
        m_tready = 1'b1;

        for (flow_idx = 0; flow_idx < 64; flow_idx = flow_idx + 1) begin
            send_payload_beat(PACKETS + 1, flow_idx);
        end
        @(negedge s_clk);
        s_tvalid = 1'b0;
        restart_timeout = 0;
        while ((last_count < restart_last_before + 1) && (restart_timeout < 30000)) begin
            @(posedge m_clk);
            restart_timeout = restart_timeout + 1;
        end
        `TB_CHECK_EQ(last_count, restart_last_before + 1, "TIME emits a complete frame after runtime clear")
        `TB_CHECK_EQ(packet_count, 32'd1, "TIME packet counter restarts after clear")
        `TB_CHECK_EQ(output_frame_count, 32'd1, "TIME output frame counter restarts after clear")
        `TB_CHECK(!fifo_full, "TIME FIFO is not left full after clear/restart")

        `TB_PASS("tb_time_udp_cmac512")
    end

endmodule
