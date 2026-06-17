`include "tb_common.svh"

module tb_udp_tx_arbiter;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic [63:0] s_spec_tdata = 64'd0;
    logic [7:0]  s_spec_tkeep = 8'hff;
    logic        s_spec_tvalid = 1'b0;
    logic        s_spec_tlast = 1'b0;
    wire         s_spec_tready;
    logic [63:0] s_time_tdata = 64'd0;
    logic [7:0]  s_time_tkeep = 8'hff;
    logic        s_time_tvalid = 1'b0;
    logic        s_time_tlast = 1'b0;
    wire         s_time_tready;
    logic [63:0] s_snapshot_tdata = 64'd0;
    logic [7:0]  s_snapshot_tkeep = 8'hff;
    logic        s_snapshot_tvalid = 1'b0;
    logic        s_snapshot_tlast = 1'b0;
    wire         s_snapshot_tready;
    logic [63:0] s_monitor_tdata = 64'd0;
    logic [7:0]  s_monitor_tkeep = 8'hff;
    logic        s_monitor_tvalid = 1'b0;
    logic        s_monitor_tlast = 1'b0;
    wire         s_monitor_tready;
    wire [63:0]  m_axis_tdata;
    wire [7:0]   m_axis_tkeep;
    wire         m_axis_tvalid;
    wire         m_axis_tlast;
    logic        m_axis_tready = 1'b1;

    always #5 clk = ~clk;

    udp_tx_arbiter dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
        .s_spec_tdata(s_spec_tdata),
        .s_spec_tkeep(s_spec_tkeep),
        .s_spec_tvalid(s_spec_tvalid),
        .s_spec_tlast(s_spec_tlast),
        .s_spec_tready(s_spec_tready),
        .s_time_tdata(s_time_tdata),
        .s_time_tkeep(s_time_tkeep),
        .s_time_tvalid(s_time_tvalid),
        .s_time_tlast(s_time_tlast),
        .s_time_tready(s_time_tready),
        .s_snapshot_tdata(s_snapshot_tdata),
        .s_snapshot_tkeep(s_snapshot_tkeep),
        .s_snapshot_tvalid(s_snapshot_tvalid),
        .s_snapshot_tlast(s_snapshot_tlast),
        .s_snapshot_tready(s_snapshot_tready),
        .s_monitor_tdata(s_monitor_tdata),
        .s_monitor_tkeep(s_monitor_tkeep),
        .s_monitor_tvalid(s_monitor_tvalid),
        .s_monitor_tlast(s_monitor_tlast),
        .s_monitor_tready(s_monitor_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready)
    );

    initial begin
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        s_spec_tdata = 64'haaaa;
        s_time_tdata = 64'hbbbb;
        s_snapshot_tdata = 64'hcccc;
        s_monitor_tdata = 64'hdddd;
        s_spec_tvalid = 1'b1;
        s_time_tvalid = 1'b1;
        s_snapshot_tvalid = 1'b1;
        s_monitor_tvalid = 1'b1;
        s_spec_tlast = 1'b1;
        s_time_tlast = 1'b1;
        s_snapshot_tlast = 1'b1;
        s_monitor_tlast = 1'b1;
        #1;
        `TB_CHECK(m_axis_tvalid, "arbiter output valid")
        `TB_CHECK_EQ(m_axis_tdata, 64'haaaa, "SPEC priority")
        `TB_CHECK(s_spec_tready, "SPEC ready under priority")
        `TB_CHECK(!s_time_tready && !s_snapshot_tready && !s_monitor_tready, "lower priorities not ready")
        @(posedge clk);

        s_spec_tvalid = 1'b0;
        s_time_tvalid = 1'b1;
        s_time_tdata = 64'h1000;
        s_time_tlast = 1'b0;
        s_snapshot_tvalid = 1'b0;
        s_monitor_tvalid = 1'b0;
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h1000, "TIME starts packet")
        @(posedge clk);

        s_spec_tvalid = 1'b1;
        s_spec_tdata = 64'h2000;
        s_spec_tlast = 1'b1;
        s_time_tdata = 64'h1001;
        s_time_tlast = 1'b1;
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h1001, "packet lock holds TIME despite SPEC arrival")
        `TB_CHECK(s_time_tready, "TIME ready while locked")
        `TB_CHECK(!s_spec_tready, "SPEC waits until TIME packet ends")
        @(posedge clk);

        s_time_tvalid = 1'b0;
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h2000, "SPEC selected after TIME tlast")
        `TB_CHECK(s_spec_tready, "SPEC ready after re-arbitration")
        @(posedge clk);

        s_spec_tvalid = 1'b0;
        s_snapshot_tvalid = 1'b1;
        s_monitor_tvalid = 1'b1;
        s_snapshot_tdata = 64'h3000;
        s_monitor_tdata = 64'h4000;
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h3000, "SNAPSHOT priority over MONITOR")
        @(posedge clk);

        s_snapshot_tvalid = 1'b0;
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h4000, "MONITOR selected last")
        @(posedge clk);

        s_monitor_tvalid = 1'b0;
        s_time_tvalid = 1'b1;
        s_time_tdata = 64'h5000;
        s_time_tlast = 1'b0;
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h5000, "TIME selected before clear")
        `TB_CHECK(s_time_tready, "TIME ready before clear")

        s_time_tvalid = 1'b0;
        s_spec_tvalid = 1'b1;
        s_spec_tdata = 64'h6000;
        s_spec_tlast = 1'b1;
        clear = 1'b1;
        @(posedge clk);
        #1;
        `TB_CHECK(!m_axis_tvalid, "clear suppresses stale arbiter output")
        `TB_CHECK(!s_spec_tready && !s_time_tready, "clear suppresses input ready")

        clear = 1'b0;
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(m_axis_tdata, 64'h6000, "SPEC selected after clear releases stale TIME lock")
        `TB_CHECK(s_spec_tready, "SPEC ready after clear")

        `TB_PASS("tb_udp_tx_arbiter")
    end

endmodule
