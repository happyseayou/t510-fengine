`include "tb_common.svh"

module tb_t510_qsfp_test_frame_gen;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b0;
    logic clear = 1'b0;
    wire [511:0] tdata;
    wire [63:0] tkeep;
    wire tvalid;
    wire tlast;
    logic tready = 1'b1;
    wire [31:0] packet_count;
    wire [31:0] byte_count;

    always #5 clk = ~clk;

    function automatic [7:0] byte_at(input [511:0] word, input integer index);
        begin
            byte_at = word[index*8 +: 8];
        end
    endfunction

    task automatic check_byte(input integer index, input [7:0] expected, input string label);
        begin
            `TB_CHECK_EQ(byte_at(tdata, index), expected, label)
        end
    endtask

    t510_qsfp_test_frame_gen dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .interval_cycles(32'd1024),
        .src_mac(48'h0200_0000_0001),
        .src_ip(32'h0a00_0101),
        .dst_mac(48'h08c0_ebd5_95b2),
        .dst_ip(32'h0a00_0110),
        .src_udp_port(16'd4000),
        .dst_udp_port(16'd4300),
        .core_version(32'h0001_001A),
        .board_id(16'h005a),
        .status_flags(32'ha5a5_5a5a),
        .sample_count(64'h0000_0001_1234_5678),
        .m_axis_tdata(tdata),
        .m_axis_tkeep(tkeep),
        .m_axis_tvalid(tvalid),
        .m_axis_tlast(tlast),
        .m_axis_tready(tready),
        .packet_count(packet_count),
        .byte_count(byte_count)
    );

    initial begin
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);
        enable = 1'b1;
        wait (tvalid);
        `TB_CHECK_EQ(tkeep, 64'hffff_ffff_ffff_ffff, "heartbeat keep all bytes")
        `TB_CHECK(tlast, "heartbeat is single beat")

        check_byte(0, 8'h08, "dst MAC byte0");
        check_byte(1, 8'hc0, "dst MAC byte1");
        check_byte(2, 8'heb, "dst MAC byte2");
        check_byte(3, 8'hd5, "dst MAC byte3");
        check_byte(4, 8'h95, "dst MAC byte4");
        check_byte(5, 8'hb2, "dst MAC byte5");
        check_byte(6, 8'h02, "src MAC byte0");
        check_byte(12, 8'h08, "ethertype high");
        check_byte(13, 8'h00, "ethertype low");
        check_byte(14, 8'h45, "IPv4 version/IHL");
        check_byte(16, 8'h00, "IPv4 total length high");
        check_byte(17, 8'h32, "IPv4 total length low");
        check_byte(23, 8'h11, "IPv4 protocol UDP");
        check_byte(26, 8'h0a, "src IP byte0");
        check_byte(29, 8'h01, "src IP byte3");
        check_byte(30, 8'h0a, "dst IP byte0");
        check_byte(33, 8'h10, "dst IP byte3");
        check_byte(34, 8'h0f, "UDP src port high");
        check_byte(35, 8'ha0, "UDP src port low");
        check_byte(36, 8'h10, "UDP dst port high");
        check_byte(37, 8'hcc, "UDP dst port low");
        check_byte(38, 8'h00, "UDP length high");
        check_byte(39, 8'h1e, "UDP length low");
        check_byte(42, 8'h54, "payload magic T");
        check_byte(43, 8'h35, "payload magic 5");
        check_byte(44, 8'h31, "payload magic 1");
        check_byte(45, 8'h30, "payload magic 0");
        check_byte(46, 8'h00, "core version byte0");
        check_byte(47, 8'h01, "core version byte1");
        check_byte(48, 8'h00, "core version byte2");
        check_byte(49, 8'h1a, "core version byte3");
        check_byte(50, 8'h00, "seq byte0");
        check_byte(53, 8'h00, "seq byte3");
        check_byte(54, 8'h12, "sample count byte0");
        check_byte(57, 8'h78, "sample count byte3");
        check_byte(58, 8'ha5, "status flags byte0");
        check_byte(61, 8'h5a, "status flags byte3");
        check_byte(62, 8'h00, "board id high");
        check_byte(63, 8'h5a, "board id low");

        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(packet_count, 32'd1, "packet count after first beat")
        `TB_CHECK_EQ(byte_count, 32'd64, "byte count after first beat")
        repeat (1030) @(posedge clk);
        `TB_CHECK(packet_count >= 32'd2, "second heartbeat emitted after interval")
        $display("[%0t] PASS: tb_t510_qsfp_test_frame_gen", $time);
        $finish;
    end

endmodule
