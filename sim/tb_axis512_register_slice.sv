`include "tb_common.svh"

module tb_axis512_register_slice;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;

    logic [511:0] s_tdata = 512'd0;
    logic [63:0]  s_tkeep = 64'hffff_ffff_ffff_ffff;
    logic         s_tvalid = 1'b0;
    logic         s_tlast = 1'b0;
    wire          s_tready;

    wire [511:0] m_tdata;
    wire [63:0]  m_tkeep;
    wire         m_tvalid;
    wire         m_tlast;
    logic        m_tready = 1'b0;

    integer sent_count = 0;
    integer recv_count = 0;
    integer timeout = 0;
    logic [31:0] expected [0:3];

    always #3 clk = ~clk;

    axis512_register_slice dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
        .s_axis_tdata(s_tdata),
        .s_axis_tkeep(s_tkeep),
        .s_axis_tvalid(s_tvalid),
        .s_axis_tlast(s_tlast),
        .s_axis_tready(s_tready),
        .m_axis_tdata(m_tdata),
        .m_axis_tkeep(m_tkeep),
        .m_axis_tvalid(m_tvalid),
        .m_axis_tlast(m_tlast),
        .m_axis_tready(m_tready)
    );

    task automatic drive_word(input integer idx, input bit last);
        begin
            @(negedge clk);
            s_tdata = {480'd0, idx[31:0]};
            s_tkeep = last ? 64'h0000_0000_0000_00ff : 64'hffff_ffff_ffff_ffff;
            s_tlast = last;
            s_tvalid = 1'b1;
            do begin
                @(posedge clk);
            end while (!(s_tvalid && s_tready));
            sent_count = sent_count + 1;
            @(negedge clk);
            s_tvalid = 1'b0;
            s_tlast = 1'b0;
            s_tkeep = 64'hffff_ffff_ffff_ffff;
        end
    endtask

    initial begin
        expected[0] = 32'd0;
        expected[1] = 32'd1;
        expected[2] = 32'd2;
        expected[3] = 32'd3;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);
        m_tready = 1'b0;

        drive_word(0, 1'b0);
        drive_word(1, 1'b0);
        @(posedge clk);
        `TB_CHECK(!s_tready, "slice backpressures when both skid slots are full")

        @(negedge clk);
        m_tready = 1'b1;
        drive_word(2, 1'b0);
        drive_word(3, 1'b1);

        repeat (4) @(posedge clk);

        timeout = 0;
        while ((recv_count < 4) && (timeout < 200)) begin
            @(posedge clk);
            timeout = timeout + 1;
        end
        `TB_CHECK_EQ(sent_count, 4, "all words accepted")
        `TB_CHECK_EQ(recv_count, 4, "all words received")
        `TB_PASS("tb_axis512_register_slice")
    end

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            recv_count <= 0;
        end else if (m_tvalid && m_tready) begin
            `TB_CHECK(recv_count < 4, "no extra output beats")
            `TB_CHECK_EQ(m_tdata[31:0], expected[recv_count], "output order")
            if (recv_count == 3) begin
                `TB_CHECK(m_tlast, "last beat marked")
                `TB_CHECK_EQ(m_tkeep, 64'h0000_0000_0000_00ff, "last keep preserved")
            end else begin
                `TB_CHECK(!m_tlast, "non-last beat")
                `TB_CHECK_EQ(m_tkeep, 64'hffff_ffff_ffff_ffff, "full keep preserved")
            end
            recv_count <= recv_count + 1;
        end
    end

endmodule
