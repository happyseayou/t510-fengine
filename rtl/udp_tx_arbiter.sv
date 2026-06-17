module udp_tx_arbiter #(
    parameter integer DATA_W = 64
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                clear,
    input  wire [DATA_W-1:0]   s_spec_tdata,
    input  wire [DATA_W/8-1:0] s_spec_tkeep,
    input  wire                s_spec_tvalid,
    input  wire                s_spec_tlast,
    output logic               s_spec_tready,
    input  wire [DATA_W-1:0]   s_time_tdata,
    input  wire [DATA_W/8-1:0] s_time_tkeep,
    input  wire                s_time_tvalid,
    input  wire                s_time_tlast,
    output logic               s_time_tready,
    input  wire [DATA_W-1:0]   s_snapshot_tdata,
    input  wire [DATA_W/8-1:0] s_snapshot_tkeep,
    input  wire                s_snapshot_tvalid,
    input  wire                s_snapshot_tlast,
    output logic               s_snapshot_tready,
    input  wire [DATA_W-1:0]   s_monitor_tdata,
    input  wire [DATA_W/8-1:0] s_monitor_tkeep,
    input  wire                s_monitor_tvalid,
    input  wire                s_monitor_tlast,
    output logic               s_monitor_tready,
    output logic [DATA_W-1:0]  m_axis_tdata,
    output logic [DATA_W/8-1:0] m_axis_tkeep,
    output logic               m_axis_tvalid,
    output logic               m_axis_tlast,
    input  wire                m_axis_tready
);

    localparam [1:0] SEL_SPEC     = 2'd0;
    localparam [1:0] SEL_TIME     = 2'd1;
    localparam [1:0] SEL_SNAPSHOT = 2'd2;
    localparam [1:0] SEL_MONITOR  = 2'd3;

    logic       locked;
    logic [1:0] active_sel;
    logic [1:0] next_sel;
    logic       next_valid;
    logic       active_last;

    always_comb begin
        next_sel   = SEL_SPEC;
        next_valid = 1'b0;

        if (s_spec_tvalid) begin
            next_sel   = SEL_SPEC;
            next_valid = 1'b1;
        end else if (s_time_tvalid) begin
            next_sel   = SEL_TIME;
            next_valid = 1'b1;
        end else if (s_snapshot_tvalid) begin
            next_sel   = SEL_SNAPSHOT;
            next_valid = 1'b1;
        end else if (s_monitor_tvalid) begin
            next_sel   = SEL_MONITOR;
            next_valid = 1'b1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            locked     <= 1'b0;
            active_sel <= SEL_SPEC;
        end else if (clear) begin
            locked     <= 1'b0;
            active_sel <= SEL_SPEC;
        end else begin
            if (m_axis_tvalid && m_axis_tready) begin
                if (locked) begin
                    if (active_last) begin
                        locked <= 1'b0;
                    end
                end else begin
                    active_sel <= next_sel;
                    locked     <= !active_last;
                end
            end
        end
    end

    always_comb begin
        s_spec_tready     = 1'b0;
        s_time_tready     = 1'b0;
        s_snapshot_tready = 1'b0;
        s_monitor_tready  = 1'b0;
        m_axis_tdata      = {DATA_W{1'b0}};
        m_axis_tkeep      = {DATA_W/8{1'b0}};
        m_axis_tvalid     = 1'b0;
        m_axis_tlast      = 1'b0;
        active_last       = 1'b0;

        if (!clear) begin
            case (locked ? active_sel : next_sel)
                SEL_SPEC: begin
                    m_axis_tdata  = s_spec_tdata;
                    m_axis_tkeep  = s_spec_tkeep;
                    m_axis_tvalid = s_spec_tvalid && (locked || next_valid);
                    m_axis_tlast  = s_spec_tlast;
                    active_last   = s_spec_tlast;
                    s_spec_tready = m_axis_tready;
                end
                SEL_TIME: begin
                    m_axis_tdata  = s_time_tdata;
                    m_axis_tkeep  = s_time_tkeep;
                    m_axis_tvalid = s_time_tvalid && (locked || next_valid);
                    m_axis_tlast  = s_time_tlast;
                    active_last   = s_time_tlast;
                    s_time_tready = m_axis_tready;
                end
                SEL_SNAPSHOT: begin
                    m_axis_tdata      = s_snapshot_tdata;
                    m_axis_tkeep      = s_snapshot_tkeep;
                    m_axis_tvalid     = s_snapshot_tvalid && (locked || next_valid);
                    m_axis_tlast      = s_snapshot_tlast;
                    active_last       = s_snapshot_tlast;
                    s_snapshot_tready = m_axis_tready;
                end
                default: begin
                    m_axis_tdata     = s_monitor_tdata;
                    m_axis_tkeep     = s_monitor_tkeep;
                    m_axis_tvalid    = s_monitor_tvalid && (locked || next_valid);
                    m_axis_tlast     = s_monitor_tlast;
                    active_last      = s_monitor_tlast;
                    s_monitor_tready = m_axis_tready;
                end
            endcase
        end
    end

endmodule
