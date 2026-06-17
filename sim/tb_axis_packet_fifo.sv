`include "tb_common.svh"

module tb_axis_packet_fifo;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic [63:0] s_axis_tdata = 64'd0;
    logic [7:0]  s_axis_tkeep = 8'hff;
    logic        s_axis_tvalid = 1'b0;
    logic        s_axis_tlast = 1'b0;
    wire         s_axis_tready;
    wire [63:0]  m_axis_tdata;
    wire [7:0]   m_axis_tkeep;
    wire         m_axis_tvalid;
    wire         m_axis_tlast;
    logic        m_axis_tready = 1'b0;
    wire [31:0]  level_words;
    wire [31:0]  high_water_words;
    wire [31:0]  backpressure_cycles;

    always #5 clk = ~clk;

    axis_packet_fifo #(
        .DATA_W(64),
        .DEPTH(16),
        .COUNT_W(5)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
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
        .level_words(level_words),
        .high_water_words(high_water_words),
        .backpressure_cycles(backpressure_cycles)
    );

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            clear = 1'b0;
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
            s_axis_tdata = 64'd0;
            m_axis_tready = 1'b0;
            repeat (10) @(posedge clk);
            rst_n = 1'b1;
            repeat (10) @(posedge clk);
        end
    endtask

    task automatic send_word(input [63:0] data, input logic last);
        begin
            @(posedge clk);
            s_axis_tdata <= data;
            s_axis_tkeep <= 8'hff;
            s_axis_tlast <= last;
            s_axis_tvalid <= 1'b1;
            while (!s_axis_tready) begin
                @(posedge clk);
            end
            @(posedge clk);
            s_axis_tvalid <= 1'b0;
            s_axis_tlast <= 1'b0;
        end
    endtask

    task automatic expect_word(input [63:0] data, input logic last);
        integer timeout;
        begin
            timeout = 0;
            while (!m_axis_tvalid && timeout < 80) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(m_axis_tvalid, "FIFO output valid")
            `TB_CHECK_EQ(m_axis_tdata, data, "FIFO output data order")
            `TB_CHECK_EQ(m_axis_tkeep, 8'hff, "FIFO output keep")
            `TB_CHECK_EQ(m_axis_tlast, last, "FIFO output tlast")
            @(posedge clk);
            #1;
        end
    endtask

    task automatic pulse_clear;
        begin
            @(posedge clk);
            clear <= 1'b1;
            @(posedge clk);
            clear <= 1'b0;
            repeat (8) @(posedge clk);
        end
    endtask

    initial begin
        integer idx;

        reset_dut();

        m_axis_tready = 1'b0;
        send_word(64'h1111_0000_0000_0000, 1'b0);
        send_word(64'h2222_0000_0000_0001, 1'b0);
        send_word(64'h3333_0000_0000_0002, 1'b0);
        send_word(64'h4444_0000_0000_0003, 1'b1);
        repeat (8) @(posedge clk);
        `TB_CHECK(high_water_words >= 32'd3, "FIFO high-water rises while output stalled")

        m_axis_tready = 1'b1;
        expect_word(64'h1111_0000_0000_0000, 1'b0);
        expect_word(64'h2222_0000_0000_0001, 1'b0);
        expect_word(64'h3333_0000_0000_0002, 1'b0);
        expect_word(64'h4444_0000_0000_0003, 1'b1);

        m_axis_tready = 1'b0;
        s_axis_tvalid = 1'b1;
        s_axis_tkeep = 8'hff;
        s_axis_tlast = 1'b0;
        for (idx = 0; idx < 48; idx = idx + 1) begin
            s_axis_tdata = 64'h5555_0000_0000_0000 + idx;
            @(posedge clk);
        end
        s_axis_tvalid = 1'b0;
        repeat (4) @(posedge clk);
        `TB_CHECK(backpressure_cycles > 32'd0, "FIFO backpressure counter increments")

        pulse_clear();
        `TB_CHECK_EQ(high_water_words, 32'd0, "FIFO high-water clear")
        `TB_CHECK_EQ(backpressure_cycles, 32'd0, "FIFO backpressure clear")

        `TB_PASS("tb_axis_packet_fifo")
    end

endmodule
