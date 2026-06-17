module axis_stream_duplicator #(
    parameter integer DATA_W = 256,
    parameter integer USER_W = 32,
    parameter integer SAMPLE0_W = 64
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 spec_enable,
    input  wire                 time_enable,
    input  wire                 snapshot_enable,
    input  wire                 monitor_enable,
    input  wire                 time_drop_when_full,
    input  wire                 snapshot_drop_when_full,
    input  wire                 monitor_drop_when_full,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [USER_W-1:0]    s_axis_tuser,
    input  wire [SAMPLE0_W-1:0] s_axis_sample0,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_spec_tdata,
    output wire [USER_W-1:0]    m_spec_tuser,
    output wire [SAMPLE0_W-1:0] m_spec_sample0,
    output wire                 m_spec_tvalid,
    output wire                 m_spec_tlast,
    input  wire                 m_spec_tready,
    output wire [DATA_W-1:0]    m_time_tdata,
    output wire [USER_W-1:0]    m_time_tuser,
    output wire [SAMPLE0_W-1:0] m_time_sample0,
    output wire                 m_time_tvalid,
    output wire                 m_time_tlast,
    input  wire                 m_time_tready,
    output wire [DATA_W-1:0]    m_snapshot_tdata,
    output wire [USER_W-1:0]    m_snapshot_tuser,
    output wire [SAMPLE0_W-1:0] m_snapshot_sample0,
    output wire                 m_snapshot_tvalid,
    output wire                 m_snapshot_tlast,
    input  wire                 m_snapshot_tready,
    output wire [DATA_W-1:0]    m_monitor_tdata,
    output wire [USER_W-1:0]    m_monitor_tuser,
    output wire [SAMPLE0_W-1:0] m_monitor_sample0,
    output wire                 m_monitor_tvalid,
    output wire                 m_monitor_tlast,
    input  wire                 m_monitor_tready,
    output logic [31:0]         dropped_time_count,
    output logic [31:0]         dropped_snapshot_count,
    output logic [31:0]         dropped_monitor_count
);

    wire time_must_accept     = time_enable && !time_drop_when_full;
    wire snapshot_must_accept = snapshot_enable && !snapshot_drop_when_full;
    wire monitor_must_accept  = monitor_enable && !monitor_drop_when_full;

    assign s_axis_tready =
        (!spec_enable || m_spec_tready) &&
        (!time_must_accept || m_time_tready) &&
        (!snapshot_must_accept || m_snapshot_tready) &&
        (!monitor_must_accept || m_monitor_tready);

    assign m_spec_tdata  = s_axis_tdata;
    assign m_spec_tuser  = s_axis_tuser;
    assign m_spec_sample0 = s_axis_sample0;
    assign m_spec_tlast  = s_axis_tlast;
    assign m_spec_tvalid = s_axis_tvalid && spec_enable;

    assign m_time_tdata  = s_axis_tdata;
    assign m_time_tuser  = s_axis_tuser;
    assign m_time_sample0 = s_axis_sample0;
    assign m_time_tlast  = s_axis_tlast;
    assign m_time_tvalid = s_axis_tvalid && time_enable &&
                           (m_time_tready || !time_drop_when_full);

    assign m_snapshot_tdata  = s_axis_tdata;
    assign m_snapshot_tuser  = s_axis_tuser;
    assign m_snapshot_sample0 = s_axis_sample0;
    assign m_snapshot_tlast  = s_axis_tlast;
    assign m_snapshot_tvalid = s_axis_tvalid && snapshot_enable &&
                               (m_snapshot_tready || !snapshot_drop_when_full);

    assign m_monitor_tdata  = s_axis_tdata;
    assign m_monitor_tuser  = s_axis_tuser;
    assign m_monitor_sample0 = s_axis_sample0;
    assign m_monitor_tlast  = s_axis_tlast;
    assign m_monitor_tvalid = s_axis_tvalid && monitor_enable &&
                              (m_monitor_tready || !monitor_drop_when_full);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dropped_time_count     <= 32'd0;
            dropped_snapshot_count <= 32'd0;
            dropped_monitor_count  <= 32'd0;
        end else if (s_axis_tvalid && s_axis_tready) begin
            if (time_enable && time_drop_when_full && !m_time_tready) begin
                dropped_time_count <= dropped_time_count + 32'd1;
            end
            if (snapshot_enable && snapshot_drop_when_full && !m_snapshot_tready) begin
                dropped_snapshot_count <= dropped_snapshot_count + 32'd1;
            end
            if (monitor_enable && monitor_drop_when_full && !m_monitor_tready) begin
                dropped_monitor_count <= dropped_monitor_count + 32'd1;
            end
        end
    end

endmodule
