`timescale 1ns/1ps
`include "tb_common.svh"

module tb_cmac_tx_source_mux;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    always #3 clk = ~clk;

    logic select_time = 1'b0;
    logic select_spec = 1'b0;
    logic [511:0] heartbeat_tdata = 512'h11;
    logic [63:0] heartbeat_tkeep = 64'hffff_ffff_ffff_ffff;
    logic heartbeat_tvalid = 1'b0;
    logic heartbeat_tlast = 1'b1;
    wire heartbeat_tready;
    logic [511:0] time_tdata = 512'h22;
    logic [63:0] time_tkeep = 64'hffff_ffff_ffff_ffff;
    logic time_tvalid = 1'b0;
    logic time_tlast = 1'b1;
    wire time_tready;
    logic [511:0] spec_tdata = 512'h33;
    logic [63:0] spec_tkeep = 64'hffff_ffff_ffff_ffff;
    logic spec_tvalid = 1'b0;
    logic spec_tlast = 1'b0;
    wire spec_tready;
    wire [511:0] m_tdata;
    wire [63:0] m_tkeep;
    wire m_tvalid;
    wire m_tlast;
    logic m_tready = 1'b1;
    wire [31:0] status;

    cmac_tx_source_mux dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
        .select_time_live(select_time),
        .select_spec_live(select_spec),
        .heartbeat_tdata(heartbeat_tdata),
        .heartbeat_tkeep(heartbeat_tkeep),
        .heartbeat_tvalid(heartbeat_tvalid),
        .heartbeat_tlast(heartbeat_tlast),
        .heartbeat_tready(heartbeat_tready),
        .time_tdata(time_tdata),
        .time_tkeep(time_tkeep),
        .time_tvalid(time_tvalid),
        .time_tlast(time_tlast),
        .time_tready(time_tready),
        .spec_tdata(spec_tdata),
        .spec_tkeep(spec_tkeep),
        .spec_tvalid(spec_tvalid),
        .spec_tlast(spec_tlast),
        .spec_tready(spec_tready),
        .m_axis_tdata(m_tdata),
        .m_axis_tkeep(m_tkeep),
        .m_axis_tvalid(m_tvalid),
        .m_axis_tlast(m_tlast),
        .m_axis_tready(m_tready),
        .status(status)
    );

    initial begin
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        // Start a SPEC frame and deliberately remove valid before TLAST.  The
        // frame arbiter must remain locked, matching a STOP in mid-frame.
        @(negedge clk);
        select_spec = 1'b1;
        spec_tvalid = 1'b1;
        spec_tlast = 1'b0;
        @(posedge clk);
        @(negedge clk);
        spec_tvalid = 1'b0;
        select_time = 1'b1;
        time_tvalid = 1'b1;
        repeat (3) @(posedge clk);
        `TB_CHECK_EQ(status[4], 1'b1, "CMAC mux locks incomplete SPEC frame")
        `TB_CHECK_EQ(status[1:0], 2'd2, "CMAC mux remains selected on SPEC")
        `TB_CHECK_EQ(time_tready, 1'b0, "locked SPEC frame blocks TIME")

        // The unified cross-domain pipeline flush is connected to this clear.
        // It must discard the partial frame and allow TIME immediately.
        @(negedge clk);
        clear = 1'b1;
        @(posedge clk);
        @(negedge clk);
        clear = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK(time_tready, "pipeline flush releases TIME arbitration")
        `TB_CHECK(m_tvalid, "TIME valid reaches CMAC after flush")
        `TB_CHECK_EQ(m_tdata, time_tdata, "post-flush CMAC data comes from TIME")
        `TB_CHECK(m_tlast, "post-flush TIME frame terminates")

        @(negedge clk);
        time_tvalid = 1'b0;
        select_time = 1'b0;
        select_spec = 1'b0;
        `TB_PASS("tb_cmac_tx_source_mux")
    end
endmodule
