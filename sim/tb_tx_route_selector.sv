`include "tb_common.svh"

module tb_tx_route_selector;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b1;
    logic clear = 1'b0;
    logic drop_on_route_miss = 1'b1;
    logic [15:0] time_input_mask = 16'h00ff;

    logic [7:0] endpoint_enable = 8'h07;
    logic [255:0] endpoint_ip_vec = {
        32'd0, 32'd0, 32'd0, 32'd0, 32'd0,
        32'h0a00_0110, 32'h0a00_010b, 32'h0a00_010a
    };
    logic [383:0] endpoint_mac_vec = {
        48'd0, 48'd0, 48'd0, 48'd0, 48'd0,
        48'h0200_0000_0010, 48'h0200_0000_000b, 48'h0200_0000_000a
    };
    logic [127:0] endpoint_src_port_vec = {8{16'd4000}};
    logic [127:0] endpoint_dst_port_vec = {
        16'd0, 16'd0, 16'd0, 16'd0, 16'd0,
        16'd4300, 16'd4200, 16'd4100
    };

    logic [7:0] spec_route_enable = 8'h03;
    logic [255:0] spec_route_chan0_vec = {
        32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd2048, 32'd0
    };
    logic [127:0] spec_route_chan_count_vec = {
        16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd2048, 16'd2048
    };
    logic [23:0] spec_route_endpoint_vec = {
        3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd1, 3'd0
    };
    logic [7:0] time_route_enable = 8'h01;
    logic [127:0] time_route_input_mask_vec = {
        16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'h00ff
    };
    logic [23:0] time_route_endpoint_vec = {
        3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd2
    };

    logic [63:0] s_axis_tdata = 64'd0;
    logic [7:0]  s_axis_tkeep = 8'hff;
    logic        s_axis_tvalid = 1'b0;
    logic        s_axis_tlast = 1'b0;
    wire         s_axis_tready;
    wire [63:0] m_axis_tdata;
    wire [7:0]  m_axis_tkeep;
    wire        m_axis_tvalid;
    wire        m_axis_tlast;
    logic       m_axis_tready = 1'b1;
    wire [47:0] m_dst_mac;
    wire [31:0] m_dst_ip;
    wire [15:0] m_src_udp_port;
    wire [15:0] m_dst_udp_port;
    wire [31:0] m_t510_payload_bytes;
    wire [15:0] m_stream_type;
    wire [2:0]  m_endpoint_id;
    wire [2:0]  m_route_id;
    wire        m_route_is_time;
    wire [31:0] frame_forwarded_count;
    wire [31:0] frame_dropped_count;
    wire [31:0] route_miss_count;
    wire [31:0] route_error_count;
    wire [2:0] selected_endpoint_id;
    wire [2:0] selected_route_id;
    wire selected_route_is_time;
    wire [255:0] spec_route_hit_count_vec;
    wire [255:0] time_route_hit_count_vec;

    integer out_count = 0;
    integer last_count = 0;
    logic [63:0] captured [0:63];

    always #5 clk = ~clk;

    tx_route_selector dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .drop_on_route_miss(drop_on_route_miss),
        .time_input_mask(time_input_mask),
        .endpoint_enable(endpoint_enable),
        .endpoint_ip_vec(endpoint_ip_vec),
        .endpoint_mac_vec(endpoint_mac_vec),
        .endpoint_src_port_vec(endpoint_src_port_vec),
        .endpoint_dst_port_vec(endpoint_dst_port_vec),
        .spec_route_enable(spec_route_enable),
        .spec_route_chan0_vec(spec_route_chan0_vec),
        .spec_route_chan_count_vec(spec_route_chan_count_vec),
        .spec_route_endpoint_vec(spec_route_endpoint_vec),
        .time_route_enable(time_route_enable),
        .time_route_input_mask_vec(time_route_input_mask_vec),
        .time_route_endpoint_vec(time_route_endpoint_vec),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready),
        .m_dst_mac(m_dst_mac),
        .m_dst_ip(m_dst_ip),
        .m_src_udp_port(m_src_udp_port),
        .m_dst_udp_port(m_dst_udp_port),
        .m_t510_payload_bytes(m_t510_payload_bytes),
        .m_stream_type(m_stream_type),
        .m_endpoint_id(m_endpoint_id),
        .m_route_id(m_route_id),
        .m_route_is_time(m_route_is_time),
        .frame_forwarded_count(frame_forwarded_count),
        .frame_dropped_count(frame_dropped_count),
        .route_miss_count(route_miss_count),
        .route_error_count(route_error_count),
        .selected_endpoint_id(selected_endpoint_id),
        .selected_route_id(selected_route_id),
        .selected_route_is_time(selected_route_is_time),
        .spec_route_hit_count_vec(spec_route_hit_count_vec),
        .time_route_hit_count_vec(time_route_hit_count_vec)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
            last_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (out_count < 64) begin
                captured[out_count] <= m_axis_tdata;
            end
            if (m_axis_tlast) begin
                last_count <= last_count + 1;
            end
            out_count <= out_count + 1;
        end
    end

    task automatic send_word(input [63:0] data, input logic last);
        begin
            @(posedge clk);
            s_axis_tdata <= data;
            s_axis_tkeep <= 8'hff;
            s_axis_tlast <= last;
            s_axis_tvalid <= 1'b1;
            do begin
                @(posedge clk);
            end while (!s_axis_tready);
            s_axis_tvalid <= 1'b0;
            s_axis_tlast <= 1'b0;
        end
    endtask

    function automatic [63:0] header_word(
        input integer idx,
        input [15:0] stream_type,
        input [31:0] chan0,
        input [15:0] chan_count
    );
        begin
            case (idx)
                0: header_word = 64'h5435_3130_0002_0080;
                1: header_word = {16'h00bb, stream_type, 16'd1, 16'h000a};
                6: header_word = {32'h0000_0001, chan0};
                7: header_word = {chan_count, 16'd4, 16'd8, 16'd0};
                8: header_word = 64'h0000_0000_0000_2000;
                default: header_word = 64'h1000_0000_0000_0000 + idx;
            endcase
        end
    endfunction

    task automatic send_packet(
        input [15:0] stream_type,
        input [31:0] chan0,
        input [15:0] chan_count,
        input logic expect_output
    );
        integer idx;
        integer before_out;
        integer timeout;
        begin
            before_out = out_count;
            for (idx = 0; idx < 16; idx = idx + 1) begin
                send_word(header_word(idx, stream_type, chan0, chan_count), 1'b0);
            end
            send_word(64'hdeed_0000_0000_0001, 1'b0);
            send_word(64'hdeed_0000_0000_0002, 1'b1);
            timeout = 0;
            while ((out_count < before_out + (expect_output ? 18 : 0)) && (timeout < 200)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            repeat (4) @(posedge clk);
        end
    endtask

    initial begin
        rst_n = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        send_packet(16'd0, 32'd0, 16'd64, 1'b1);
        `TB_CHECK_EQ(selected_endpoint_id, 3'd0, "SPEC low route endpoint")
        `TB_CHECK_EQ(selected_route_id, 3'd0, "SPEC low route id")
        `TB_CHECK_EQ(m_dst_ip, 32'h0a00_010a, "SPEC low dst IP")

        send_packet(16'd0, 32'd2048, 16'd64, 1'b1);
        `TB_CHECK_EQ(selected_endpoint_id, 3'd1, "SPEC high route endpoint")
        `TB_CHECK_EQ(selected_route_id, 3'd1, "SPEC high route id")
        `TB_CHECK_EQ(m_dst_udp_port, 16'd4200, "SPEC high dst port")

        send_packet(16'd1, 32'd0, 16'd0, 1'b1);
        `TB_CHECK_EQ(selected_endpoint_id, 3'd2, "TIME route endpoint")
        `TB_CHECK_EQ(selected_route_is_time, 1'b1, "TIME route flag")

        send_packet(16'd0, 32'd2000, 16'd128, 1'b0);
        `TB_CHECK_EQ(route_miss_count, 32'd1, "Cross-window route miss")
        `TB_CHECK_EQ(frame_dropped_count, 32'd1, "Cross-window packet dropped")

        `TB_CHECK_EQ(frame_forwarded_count, 32'd3, "Forwarded packet count")
        `TB_CHECK_EQ(spec_route_hit_count_vec[0*32 +: 32], 32'd1, "SPEC route0 hit count")
        `TB_CHECK_EQ(spec_route_hit_count_vec[1*32 +: 32], 32'd1, "SPEC route1 hit count")
        `TB_CHECK_EQ(time_route_hit_count_vec[0*32 +: 32], 32'd1, "TIME route0 hit count")
        `TB_CHECK_EQ(captured[0], 64'h5435_3130_0002_0080, "Header replay word0")

        `TB_PASS("tb_tx_route_selector")
    end

endmodule
