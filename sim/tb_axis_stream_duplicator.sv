`include "tb_common.svh"

module tb_axis_stream_duplicator;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic spec_enable = 1'b0;
    logic time_enable = 1'b0;
    logic snapshot_enable = 1'b0;
    logic monitor_enable = 1'b0;
    logic spec_drop_when_full = 1'b0;
    logic time_drop_when_full = 1'b1;
    logic snapshot_drop_when_full = 1'b1;
    logic monitor_drop_when_full = 1'b1;
    logic [255:0] s_axis_tdata = 256'd0;
    logic [31:0]  s_axis_tuser = 32'd0;
    logic [63:0]  s_axis_sample0 = 64'd0;
    logic         s_axis_tvalid = 1'b0;
    logic         s_axis_tlast = 1'b0;
    wire          s_axis_tready;
    wire [255:0]  m_spec_tdata;
    wire [31:0]   m_spec_tuser;
    wire [63:0]   m_spec_sample0;
    wire          m_spec_tvalid;
    wire          m_spec_tlast;
    logic         m_spec_tready = 1'b0;
    wire [255:0]  m_time_tdata;
    wire [31:0]   m_time_tuser;
    wire [63:0]   m_time_sample0;
    wire          m_time_tvalid;
    wire          m_time_tlast;
    logic         m_time_tready = 1'b0;
    wire [255:0]  m_snapshot_tdata;
    wire [31:0]   m_snapshot_tuser;
    wire [63:0]   m_snapshot_sample0;
    wire          m_snapshot_tvalid;
    wire          m_snapshot_tlast;
    logic         m_snapshot_tready = 1'b0;
    wire [255:0]  m_monitor_tdata;
    wire [31:0]   m_monitor_tuser;
    wire [63:0]   m_monitor_sample0;
    wire          m_monitor_tvalid;
    wire          m_monitor_tlast;
    logic         m_monitor_tready = 1'b0;
    wire [31:0]   dropped_spec_count;
    wire [31:0]   dropped_time_count;
    wire [31:0]   dropped_snapshot_count;
    wire [31:0]   dropped_monitor_count;

    always #5 clk = ~clk;

    axis_stream_duplicator dut (
        .clk(clk),
        .rst_n(rst_n),
        .spec_enable(spec_enable),
        .time_enable(time_enable),
        .snapshot_enable(snapshot_enable),
        .monitor_enable(monitor_enable),
        .spec_drop_when_full(spec_drop_when_full),
        .time_drop_when_full(time_drop_when_full),
        .snapshot_drop_when_full(snapshot_drop_when_full),
        .monitor_drop_when_full(monitor_drop_when_full),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tuser(s_axis_tuser),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(s_axis_tready),
        .m_spec_tdata(m_spec_tdata),
        .m_spec_tuser(m_spec_tuser),
        .m_spec_sample0(m_spec_sample0),
        .m_spec_tvalid(m_spec_tvalid),
        .m_spec_tlast(m_spec_tlast),
        .m_spec_tready(m_spec_tready),
        .m_time_tdata(m_time_tdata),
        .m_time_tuser(m_time_tuser),
        .m_time_sample0(m_time_sample0),
        .m_time_tvalid(m_time_tvalid),
        .m_time_tlast(m_time_tlast),
        .m_time_tready(m_time_tready),
        .m_snapshot_tdata(m_snapshot_tdata),
        .m_snapshot_tuser(m_snapshot_tuser),
        .m_snapshot_sample0(m_snapshot_sample0),
        .m_snapshot_tvalid(m_snapshot_tvalid),
        .m_snapshot_tlast(m_snapshot_tlast),
        .m_snapshot_tready(m_snapshot_tready),
        .m_monitor_tdata(m_monitor_tdata),
        .m_monitor_tuser(m_monitor_tuser),
        .m_monitor_sample0(m_monitor_sample0),
        .m_monitor_tvalid(m_monitor_tvalid),
        .m_monitor_tlast(m_monitor_tlast),
        .m_monitor_tready(m_monitor_tready),
        .dropped_spec_count(dropped_spec_count),
        .dropped_time_count(dropped_time_count),
        .dropped_snapshot_count(dropped_snapshot_count),
        .dropped_monitor_count(dropped_monitor_count)
    );

    initial begin
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        s_axis_tdata = 256'h0123;
        s_axis_tuser = 32'hfeed_cafe;
        s_axis_sample0 = 64'h0000_0001_feed_caf0;
        s_axis_tlast = 1'b1;
        s_axis_tvalid = 1'b1;
        spec_enable = 1'b1;
        time_enable = 1'b1;
        snapshot_enable = 1'b1;
        monitor_enable = 1'b1;
        m_spec_tready = 1'b1;
        m_time_tready = 1'b0;
        m_snapshot_tready = 1'b0;
        m_monitor_tready = 1'b0;
        #1;
        `TB_CHECK(s_axis_tready, "SPEC ready prevents TIME/SNAPSHOT/MONITOR backpressure")
        `TB_CHECK(m_spec_tvalid, "SPEC valid asserted")
        `TB_CHECK(!m_time_tvalid, "TIME drops when full")
        `TB_CHECK_EQ(m_spec_tdata, 256'h0123, "SPEC data passthrough")
        `TB_CHECK_EQ(m_spec_tuser, 32'hfeed_cafe, "SPEC user passthrough")
        `TB_CHECK_EQ(m_spec_sample0, 64'h0000_0001_feed_caf0, "SPEC sample0 passthrough")
        `TB_CHECK(m_spec_tlast, "SPEC last passthrough")
        @(posedge clk);
        s_axis_tvalid = 1'b0;
        @(posedge clk);
        `TB_CHECK_EQ(dropped_time_count, 32'd1, "TIME drop count")
        `TB_CHECK_EQ(dropped_snapshot_count, 32'd1, "SNAPSHOT drop count")
        `TB_CHECK_EQ(dropped_monitor_count, 32'd1, "MONITOR drop count")
        `TB_CHECK_EQ(dropped_spec_count, 32'd0, "SPEC no drop while ready")

        s_axis_tvalid = 1'b1;
        m_spec_tready = 1'b0;
        m_time_tready = 1'b1;
        m_snapshot_tready = 1'b1;
        m_monitor_tready = 1'b1;
        #1;
        `TB_CHECK(!s_axis_tready, "SPEC backpressure blocks input")
        `TB_CHECK(!m_time_tvalid, "TIME does not consume while SPEC backpressures")
        @(posedge clk);
        s_axis_tvalid = 1'b0;
        @(posedge clk);
        `TB_CHECK_EQ(dropped_time_count, 32'd1, "no drop when input not accepted")
        `TB_CHECK_EQ(dropped_spec_count, 32'd0, "SPEC no drop when input not accepted")

        spec_drop_when_full = 1'b1;
        spec_enable = 1'b1;
        time_enable = 1'b1;
        m_spec_tready = 1'b0;
        m_time_tready = 1'b1;
        m_snapshot_tready = 1'b1;
        m_monitor_tready = 1'b1;
        s_axis_tvalid = 1'b1;
        #1;
        `TB_CHECK(s_axis_tready, "dropping SPEC does not backpressure input")
        `TB_CHECK(!m_spec_tvalid, "SPEC valid suppressed while dropping")
        `TB_CHECK(m_time_tvalid, "TIME still valid while SPEC drops")
        @(posedge clk);
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        @(posedge clk);
        `TB_CHECK_EQ(dropped_spec_count, 32'd1, "SPEC drop count")

        spec_enable = 1'b0;
        time_enable = 1'b1;
        time_drop_when_full = 1'b0;
        m_time_tready = 1'b0;
        s_axis_tvalid = 1'b1;
        #1;
        `TB_CHECK(!s_axis_tready, "non-dropping TIME backpressures input")

        `TB_PASS("tb_axis_stream_duplicator")
    end

endmodule
