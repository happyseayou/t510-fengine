module science_stream_decimator #(
    parameter integer DATA_W = 1024,
    parameter integer USER_W = 32,
    parameter integer SAMPLE0_W = 64
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 clear,
    input  wire                 enable,
    input  wire [1:0]           bandwidth_mode,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [USER_W-1:0]    s_axis_tuser,
    input  wire [SAMPLE0_W-1:0] s_axis_sample0,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [USER_W-1:0]    m_axis_tuser,
    output wire [SAMPLE0_W-1:0] m_axis_sample0,
    output wire                 m_axis_tvalid,
    output wire                 m_axis_tlast,
    input  wire                 m_axis_tready,
    output logic [31:0]         selected_beat_count,
    output logic [31:0]         discarded_beat_count,
    output logic [31:0]         dropped_selected_count
);

    localparam [1:0] BW_20MHZ  = 2'd0;
    localparam [1:0] BW_100MHZ = 2'd1;
    localparam [1:0] BW_200MHZ = 2'd2;

    logic [DATA_W-1:0]    out_tdata;
    logic [USER_W-1:0]    out_tuser;
    logic [SAMPLE0_W-1:0] out_sample0;
    logic                 out_tlast;
    logic                 out_valid;
    logic [5:0]           phase;

    assign s_axis_tready = 1'b1;
    assign m_axis_tdata = out_tdata;
    assign m_axis_tuser = out_tuser;
    assign m_axis_sample0 = out_sample0;
    assign m_axis_tlast = out_tlast;
    assign m_axis_tvalid = out_valid;

    function automatic [5:0] decim_last(input [1:0] mode);
        begin
            case (mode)
                BW_20MHZ:  decim_last = 6'd3;   // 20 MHz selector rate / 4.
                BW_100MHZ: decim_last = 6'd31;  // 100 MHz selector rate / 32.
                BW_200MHZ: decim_last = 6'd63;  // 200 MHz selector rate / 64.
                default:   decim_last = 6'd31;
            endcase
        end
    endfunction

    wire input_fire = s_axis_tvalid && s_axis_tready;
    wire output_fire = out_valid && m_axis_tready;
    wire output_can_load = !out_valid || m_axis_tready;
    wire selected_input = enable && (phase == 6'd0);
    wire [5:0] active_decim_last = decim_last(bandwidth_mode);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_tdata <= {DATA_W{1'b0}};
            out_tuser <= {USER_W{1'b0}};
            out_sample0 <= {SAMPLE0_W{1'b0}};
            out_tlast <= 1'b0;
            out_valid <= 1'b0;
            phase <= 6'd0;
            selected_beat_count <= 32'd0;
            discarded_beat_count <= 32'd0;
            dropped_selected_count <= 32'd0;
        end else begin
            if (clear || !enable) begin
                out_valid <= 1'b0;
                phase <= 6'd0;
                if (clear) begin
                    selected_beat_count <= 32'd0;
                    discarded_beat_count <= 32'd0;
                    dropped_selected_count <= 32'd0;
                end
            end else begin
                if (output_fire) begin
                    out_valid <= 1'b0;
                end

                if (input_fire) begin
                    phase <= (phase == active_decim_last) ? 6'd0 : (phase + 6'd1);
                    if (selected_input) begin
                        if (output_can_load) begin
                            out_tdata <= s_axis_tdata;
                            out_tuser <= s_axis_tuser;
                            out_sample0 <= s_axis_sample0;
                            out_tlast <= s_axis_tlast;
                            out_valid <= 1'b1;
                            selected_beat_count <= selected_beat_count + 32'd1;
                        end else begin
                            dropped_selected_count <= dropped_selected_count + 32'd1;
                        end
                    end else begin
                        discarded_beat_count <= discarded_beat_count + 32'd1;
                    end
                end
            end
        end
    end

endmodule
