`include "tb_common.svh"

module tb_udp_frame_builder;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b1;
    logic clear = 1'b0;
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
    wire [31:0] frame_built_count;
    wire [31:0] frame_byte_count;

    logic [63:0] captured [0:15];
    logic [7:0]  captured_keep [0:15];
    integer out_count = 0;
    integer last_count = 0;

    always #5 clk = ~clk;

    udp_frame_builder dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .src_mac(48'h0200_0000_0001),
        .src_ip(32'h0a00_0101),
        .s_dst_mac(48'h0200_0000_000a),
        .s_dst_ip(32'h0a00_010a),
        .s_src_udp_port(16'd4000),
        .s_dst_udp_port(16'd4100),
        .s_t510_payload_bytes(32'd16),
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
        .frame_built_count(frame_built_count),
        .frame_byte_count(frame_byte_count)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
            last_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (out_count < 16) begin
                captured[out_count] <= m_axis_tdata;
                captured_keep[out_count] <= m_axis_tkeep;
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

    initial begin
        rst_n = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        send_word(64'h5435_3130_0002_0080, 1'b0);
        send_word(64'h1122_3344_5566_7788, 1'b1);

        while ((last_count < 1) && (out_count < 32)) begin
            @(posedge clk);
        end
        #1;

        `TB_CHECK_EQ(last_count, 1, "UDP frame emits one tlast")
        `TB_CHECK_EQ(captured[0], 64'h0002_0a00_0000_0002, "Ethernet word0 dst/src MAC")
        `TB_CHECK_EQ(captured[1], 64'h0045_0008_0100_0000, "Ethernet word1 src/type/IP")
        `TB_CHECK_EQ(captured[2], 64'h1140_0040_0000_ac00, "IPv4 total length/id/flags")
        `TB_CHECK_EQ(captured[3], 64'h000a_0101_000a_3724, "IPv4 checksum/src/dst")
        `TB_CHECK_EQ(captured[4], 64'h9800_0410_a00f_0a01, "IPv4 dst/UDP ports/length")
        `TB_CHECK_EQ(captured[5], 64'h3130_0002_0080_0000, "UDP checksum and T510 payload start")
        `TB_CHECK_EQ(captured[6], 64'h3344_5566_7788_5435, "Payload byte-shift word")
        `TB_CHECK_EQ(captured[7][15:0], 16'h1122, "Payload tail carry")
        `TB_CHECK_EQ(captured_keep[7], 8'h03, "Final keep covers carry bytes")
        `TB_CHECK_EQ(frame_built_count, 32'd1, "Frame built count")
        `TB_CHECK_EQ(frame_byte_count, 32'd186, "Frame byte count")

        `TB_PASS("tb_udp_frame_builder")
    end

endmodule
