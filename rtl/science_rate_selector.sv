module science_rate_selector #(
    parameter integer NINPUT = 8,
    parameter integer SUBSAMPLES_PER_BEAT = 4,
    parameter integer SAMPLE_W = 32,
    parameter integer USER_W = 32,
    parameter integer SAMPLE0_W = 64
) (
    input  wire                                         clk,
    input  wire                                         rst_n,
    input  wire [1:0]                                   bandwidth_mode,
    input  wire [NINPUT*SUBSAMPLES_PER_BEAT*SAMPLE_W-1:0] s_axis_tdata,
    input  wire [USER_W-1:0]                            s_axis_tuser,
    input  wire [SAMPLE0_W-1:0]                         s_axis_sample0,
    input  wire                                         s_axis_tvalid,
    input  wire                                         s_axis_tlast,
    output wire                                         s_axis_tready,
    output wire [NINPUT*SUBSAMPLES_PER_BEAT*SAMPLE_W-1:0] m_axis_tdata,
    output wire [USER_W-1:0]                            m_axis_tuser,
    output wire [SAMPLE0_W-1:0]                         m_axis_sample0,
    output wire                                         m_axis_tvalid,
    output wire                                         m_axis_tlast,
    input  wire                                         m_axis_tready,
    output logic [31:0]                                  output_beat_count,
    output logic [31:0]                                  dropped_beat_count
);

    localparam integer SUB_W = NINPUT * SAMPLE_W;
    localparam integer DATA_W = NINPUT * SUBSAMPLES_PER_BEAT * SAMPLE_W;

    localparam [1:0] BW_20MHZ  = 2'd0;
    localparam [1:0] BW_100MHZ = 2'd1;
    localparam [1:0] BW_200MHZ = 2'd2;

    logic [DATA_W-1:0] pending_tdata;
    logic [USER_W-1:0] pending_tuser;
    logic [SAMPLE0_W-1:0] pending_sample0;
    logic pending_tlast;
    logic pending_valid;

    logic [0:0] decim2_phase;
    logic [2:0] decim8_phase;
    logic [SUB_W-1:0] decim2_sub0;
    logic [SUB_W-1:0] decim2_sub2;
    logic [USER_W-1:0] decim2_tuser;
    logic [SAMPLE0_W-1:0] decim2_sample0;
    logic decim2_tlast;
    logic [SUB_W-1:0] decim8_sub [0:3];
    logic [USER_W-1:0] decim8_tuser;
    logic [SAMPLE0_W-1:0] decim8_sample0;
    logic decim8_tlast;

    logic [DATA_W-1:0] candidate_tdata;
    logic [USER_W-1:0] candidate_tuser;
    logic [SAMPLE0_W-1:0] candidate_sample0;
    logic candidate_tlast;
    logic candidate_valid;

    wire input_fire = s_axis_tvalid && s_axis_tready;

    assign s_axis_tready = !pending_valid || m_axis_tready;
    assign m_axis_tdata = pending_tdata;
    assign m_axis_tuser = pending_tuser;
    assign m_axis_sample0 = pending_sample0;
    assign m_axis_tlast = pending_tlast;
    assign m_axis_tvalid = pending_valid;

    function automatic [SUB_W-1:0] sub_sample(
        input logic [DATA_W-1:0] data,
        input integer idx
    );
        begin
            sub_sample = data[idx*SUB_W +: SUB_W];
        end
    endfunction

    always_comb begin
        candidate_tdata = {DATA_W{1'b0}};
        candidate_tuser = s_axis_tuser;
        candidate_sample0 = s_axis_sample0;
        candidate_tlast = s_axis_tlast;
        candidate_valid = 1'b0;

        if (input_fire) begin
            case (bandwidth_mode)
                BW_200MHZ: begin
                    candidate_tdata = s_axis_tdata;
                    candidate_valid = 1'b1;
                end
                BW_100MHZ: begin
                    if (decim2_phase == 1'b1) begin
                        candidate_tdata = {
                            sub_sample(s_axis_tdata, 2),
                            sub_sample(s_axis_tdata, 0),
                            decim2_sub2,
                            decim2_sub0
                        };
                        candidate_tuser = decim2_tuser;
                        candidate_sample0 = decim2_sample0;
                        candidate_tlast = decim2_tlast || s_axis_tlast;
                        candidate_valid = 1'b1;
                    end
                end
                BW_20MHZ: begin
                    if (decim8_phase == 3'd6) begin
                        candidate_tdata = {
                            sub_sample(s_axis_tdata, 0),
                            decim8_sub[2],
                            decim8_sub[1],
                            decim8_sub[0]
                        };
                        candidate_tuser = decim8_tuser;
                        candidate_sample0 = decim8_sample0;
                        candidate_tlast = decim8_tlast || s_axis_tlast;
                        candidate_valid = 1'b1;
                    end
                end
                default: begin
                    candidate_tdata = s_axis_tdata;
                    candidate_valid = 1'b1;
                end
            endcase
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_tdata <= {DATA_W{1'b0}};
            pending_tuser <= {USER_W{1'b0}};
            pending_sample0 <= {SAMPLE0_W{1'b0}};
            pending_tlast <= 1'b0;
            pending_valid <= 1'b0;
            decim2_phase <= 1'b0;
            decim2_sub0 <= {SUB_W{1'b0}};
            decim2_sub2 <= {SUB_W{1'b0}};
            decim2_tuser <= {USER_W{1'b0}};
            decim2_sample0 <= {SAMPLE0_W{1'b0}};
            decim2_tlast <= 1'b0;
            decim8_phase <= 3'd0;
            decim8_sub[0] <= {SUB_W{1'b0}};
            decim8_sub[1] <= {SUB_W{1'b0}};
            decim8_sub[2] <= {SUB_W{1'b0}};
            decim8_sub[3] <= {SUB_W{1'b0}};
            decim8_tuser <= {USER_W{1'b0}};
            decim8_sample0 <= {SAMPLE0_W{1'b0}};
            decim8_tlast <= 1'b0;
            output_beat_count <= 32'd0;
            dropped_beat_count <= 32'd0;
        end else begin
            if (pending_valid && m_axis_tready) begin
                pending_valid <= 1'b0;
            end

            if (input_fire) begin
                case (bandwidth_mode)
                    BW_100MHZ: begin
                        decim2_phase <= ~decim2_phase;
                        if (decim2_phase == 1'b0) begin
                            decim2_sub0 <= sub_sample(s_axis_tdata, 0);
                            decim2_sub2 <= sub_sample(s_axis_tdata, 2);
                            decim2_tuser <= s_axis_tuser;
                            decim2_sample0 <= s_axis_sample0;
                            decim2_tlast <= s_axis_tlast;
                        end
                    end
                    BW_20MHZ: begin
                        decim8_phase <= decim8_phase + 3'd1;
                        case (decim8_phase)
                            3'd0: begin
                                decim8_sub[0] <= sub_sample(s_axis_tdata, 0);
                                decim8_tuser <= s_axis_tuser;
                                decim8_sample0 <= s_axis_sample0;
                                decim8_tlast <= s_axis_tlast;
                            end
                            3'd2: begin
                                decim8_sub[1] <= sub_sample(s_axis_tdata, 0);
                                decim8_tlast <= decim8_tlast || s_axis_tlast;
                            end
                            3'd4: begin
                                decim8_sub[2] <= sub_sample(s_axis_tdata, 0);
                                decim8_tlast <= decim8_tlast || s_axis_tlast;
                            end
                            3'd6: begin
                                decim8_sub[3] <= sub_sample(s_axis_tdata, 0);
                                decim8_tlast <= 1'b0;
                            end
                            default: begin
                                decim8_tlast <= decim8_tlast || s_axis_tlast;
                            end
                        endcase
                    end
                    default: begin
                        decim2_phase <= 1'b0;
                        decim8_phase <= 3'd0;
                    end
                endcase
            end

            if (s_axis_tvalid && !s_axis_tready) begin
                dropped_beat_count <= dropped_beat_count + 32'd1;
            end

            if (candidate_valid) begin
                pending_tdata <= candidate_tdata;
                pending_tuser <= candidate_tuser;
                pending_sample0 <= candidate_sample0;
                pending_tlast <= candidate_tlast;
                pending_valid <= 1'b1;
                output_beat_count <= output_beat_count + 32'd1;
            end
        end
    end

endmodule
