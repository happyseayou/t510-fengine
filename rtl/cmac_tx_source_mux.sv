`default_nettype none

module cmac_tx_source_mux (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         clear,
    input  wire         select_time_live,
    input  wire         select_spec_live,
    input  wire [511:0] heartbeat_tdata,
    input  wire [63:0]  heartbeat_tkeep,
    input  wire         heartbeat_tvalid,
    input  wire         heartbeat_tlast,
    output logic        heartbeat_tready,
    input  wire [511:0] time_tdata,
    input  wire [63:0]  time_tkeep,
    input  wire         time_tvalid,
    input  wire         time_tlast,
    output logic        time_tready,
    input  wire [511:0] spec_tdata,
    input  wire [63:0]  spec_tkeep,
    input  wire         spec_tvalid,
    input  wire         spec_tlast,
    output logic        spec_tready,
    output logic [511:0] m_axis_tdata,
    output logic [63:0]  m_axis_tkeep,
    output logic         m_axis_tvalid,
    output logic         m_axis_tlast,
    input  wire          m_axis_tready,
    output wire [31:0]   status
);

    localparam logic [1:0] SRC_HEARTBEAT = 2'd0;
    localparam logic [1:0] SRC_TIME      = 2'd1;
    localparam logic [1:0] SRC_SPEC      = 2'd2;

    logic locked;
    logic [1:0] active_src;
    logic [1:0] rr_next_src;
    logic [1:0] candidate_src;
    logic       candidate_valid;
    logic selected_last;
    (* ASYNC_REG = "TRUE" *) logic [2:0] rst_sync;
    wire reset;
    wire live_time_valid = select_time_live && time_tvalid;
    wire live_spec_valid = select_spec_live && spec_tvalid;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_sync <= 3'b111;
        end else begin
            rst_sync <= {rst_sync[1:0], 1'b0};
        end
    end

    assign reset = rst_sync[2] || clear;

    function automatic [1:0] src_after(input [1:0] src);
        begin
            case (src)
                SRC_HEARTBEAT: src_after = SRC_TIME;
                SRC_TIME:      src_after = SRC_SPEC;
                default:       src_after = SRC_HEARTBEAT;
            endcase
        end
    endfunction

    function automatic logic src_valid(input [1:0] src);
        begin
            case (src)
                SRC_HEARTBEAT: src_valid = heartbeat_tvalid;
                SRC_TIME:      src_valid = live_time_valid;
                SRC_SPEC:      src_valid = live_spec_valid;
                default:       src_valid = 1'b0;
            endcase
        end
    endfunction

    always_comb begin
        case (rr_next_src)
            SRC_HEARTBEAT: begin
                if (heartbeat_tvalid) begin
                    candidate_src = SRC_HEARTBEAT;
                end else if (live_time_valid) begin
                    candidate_src = SRC_TIME;
                end else begin
                    candidate_src = SRC_SPEC;
                end
            end
            SRC_TIME: begin
                if (live_time_valid) begin
                    candidate_src = SRC_TIME;
                end else if (live_spec_valid) begin
                    candidate_src = SRC_SPEC;
                end else begin
                    candidate_src = SRC_HEARTBEAT;
                end
            end
            default: begin
                if (live_spec_valid) begin
                    candidate_src = SRC_SPEC;
                end else if (heartbeat_tvalid) begin
                    candidate_src = SRC_HEARTBEAT;
                end else begin
                    candidate_src = SRC_TIME;
                end
            end
        endcase
        candidate_valid = src_valid(candidate_src);
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            locked <= 1'b0;
            active_src <= SRC_HEARTBEAT;
            rr_next_src <= SRC_HEARTBEAT;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (locked) begin
                if (selected_last) begin
                    locked <= 1'b0;
                    rr_next_src <= src_after(active_src);
                end
            end else if (candidate_valid) begin
                active_src <= candidate_src;
                locked <= !selected_last;
                rr_next_src <= src_after(candidate_src);
            end
        end
    end

    always_comb begin
        heartbeat_tready = 1'b0;
        time_tready = 1'b0;
        spec_tready = 1'b0;
        m_axis_tdata = 512'd0;
        m_axis_tkeep = 64'd0;
        m_axis_tvalid = 1'b0;
        m_axis_tlast = 1'b0;
        selected_last = 1'b0;

        case (locked ? active_src : candidate_src)
            SRC_TIME: begin
                m_axis_tdata = time_tdata;
                m_axis_tkeep = time_tkeep;
                m_axis_tvalid = live_time_valid;
                m_axis_tlast = time_tlast;
                selected_last = time_tlast;
                time_tready = m_axis_tready;
            end
            SRC_SPEC: begin
                m_axis_tdata = spec_tdata;
                m_axis_tkeep = spec_tkeep;
                m_axis_tvalid = live_spec_valid;
                m_axis_tlast = spec_tlast;
                selected_last = spec_tlast;
                spec_tready = m_axis_tready;
            end
            default: begin
                m_axis_tdata = heartbeat_tdata;
                m_axis_tkeep = heartbeat_tkeep;
                m_axis_tvalid = heartbeat_tvalid;
                m_axis_tlast = heartbeat_tlast;
                selected_last = heartbeat_tlast;
                heartbeat_tready = m_axis_tready;
            end
        endcase
    end

    assign status = {
        16'd0,
        select_spec_live,
        select_time_live,
        spec_tready,
        time_tready,
        heartbeat_tready,
        live_spec_valid,
        live_time_valid,
        heartbeat_tvalid,
        locked,
        rr_next_src,
        (locked ? active_src : candidate_src)
    };

endmodule

`default_nettype wire
