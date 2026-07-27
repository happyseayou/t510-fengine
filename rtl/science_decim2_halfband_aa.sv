`default_nettype none

module science_decim2_halfband_aa #(
    parameter integer NINPUT = 8,
    parameter integer SUBSAMPLES_PER_BEAT = 4,
    parameter integer SAMPLE_W = 32,
    parameter integer USER_W = 32,
    parameter integer SAMPLE0_W = 64
) (
    input  wire                                           clk,
    input  wire                                           rst_n,
    input  wire                                           clear,
    input  wire                                           enable,
    input  wire [NINPUT*SUBSAMPLES_PER_BEAT*SAMPLE_W-1:0] s_axis_tdata,
    input  wire [USER_W-1:0]                              s_axis_tuser,
    input  wire [SAMPLE0_W-1:0]                           s_axis_sample0,
    input  wire                                           s_axis_tvalid,
    input  wire                                           s_axis_tlast,
    output wire                                           s_axis_tready,
    output wire [NINPUT*SUBSAMPLES_PER_BEAT*SAMPLE_W-1:0] m_axis_tdata,
    output wire [USER_W-1:0]                              m_axis_tuser,
    output wire [SAMPLE0_W-1:0]                           m_axis_sample0,
    output wire                                           m_axis_tvalid,
    output wire                                           m_axis_tlast,
    input  wire                                           m_axis_tready,
    output wire                                           aa_active,
    output wire                                           aa_primed,
    output wire [31:0]                                    aa_coeff_version,
    output logic [31:0]                                   output_beat_count,
    output logic [31:0]                                   dropped_beat_count
);

    localparam integer SUB_W = NINPUT * SAMPLE_W;
    localparam integer DATA_W = NINPUT * SUBSAMPLES_PER_BEAT * SAMPLE_W;
    localparam integer TAPS = 55;
    localparam integer GROUP_DELAY = 27;
    localparam integer TERMS = 15;
    localparam integer HIST_DEPTH = 58;
    // Prime to the next narrow-path beat residue after all 55 taps are real.
    // This preserves the established sample0 % 8 == 4 release contract.
    localparam integer PRIME_SAMPLES = 61;
    localparam integer COEFF_FRAC = 17;
    localparam integer PROD_W = 40;
    localparam integer ACC_W = 48;
    localparam integer PIPE_STAGES = 4;
    localparam signed [17:0] CENTER_COEFF = 18'sd65536;
    localparam [31:0] COEFF_VERSION = 32'hAA16_0055;

    logic [SUB_W-1:0] history [0:HIST_DEPTH-1];
    logic [7:0] valid_samples;

    // Two filtered samples are produced from every accepted four-sample
    // input beat.  Each component has one center product and fourteen
    // symmetric-pair products.
    logic signed [PROD_W-1:0] product_pipe [0:1][0:NINPUT-1][0:1][0:TERMS-1];
    logic signed [ACC_W-1:0] sum_l1 [0:1][0:NINPUT-1][0:1][0:7];
    logic signed [ACC_W-1:0] sum_l2 [0:1][0:NINPUT-1][0:1][0:3];
    logic signed [ACC_W-1:0] sum_l3 [0:1][0:NINPUT-1][0:1][0:1];
    logic signed [ACC_W-1:0] sum_l4 [0:1][0:NINPUT-1][0:1];

    logic [PIPE_STAGES:0] pipe_valid;
    logic [USER_W-1:0] pipe_tuser [0:PIPE_STAGES];
    logic [SAMPLE0_W-1:0] pipe_sample0 [0:PIPE_STAGES];
    logic pipe_tlast [0:PIPE_STAGES];

    logic [SUB_W-1:0] half_sub0;
    logic [SUB_W-1:0] half_sub1;
    logic [USER_W-1:0] half_tuser;
    logic [SAMPLE0_W-1:0] half_sample0;
    logic half_tlast;
    logic half_valid;

    logic [DATA_W-1:0] pending_tdata;
    logic [USER_W-1:0] pending_tuser;
    logic [SAMPLE0_W-1:0] pending_sample0;
    logic pending_tlast;
    logic pending_valid;

    wire pipeline_ce = !pending_valid || m_axis_tready;
    wire input_fire = enable && s_axis_tvalid && s_axis_tready;
    wire [7:0] valid_samples_next =
        (valid_samples >= PRIME_SAMPLES[7:0]) ?
            valid_samples :
            (valid_samples + 8'd4);
    wire filtered_input_valid =
        input_fire && (valid_samples_next >= PRIME_SAMPLES[7:0]);

    assign s_axis_tready = enable && pipeline_ce;
    assign m_axis_tdata = pending_tdata;
    assign m_axis_tuser = pending_tuser;
    assign m_axis_sample0 = pending_sample0;
    assign m_axis_tlast = pending_tlast;
    assign m_axis_tvalid = pending_valid;
    assign aa_active = enable;
    assign aa_primed = enable && (valid_samples >= PRIME_SAMPLES[7:0]);
    assign aa_coeff_version = COEFF_VERSION;

    function automatic [SUB_W-1:0] sub_sample(
        input logic [DATA_W-1:0] data,
        input integer idx
    );
        begin
            sub_sample = data[idx*SUB_W +: SUB_W];
        end
    endfunction

    function automatic [SUB_W-1:0] hist_after_push(input integer idx);
        begin
            if (idx < 4) begin
                hist_after_push = sub_sample(s_axis_tdata, 3 - idx);
            end else begin
                hist_after_push = history[idx - 4];
            end
        end
    endfunction

    function automatic signed [15:0] get_comp(
        input logic [SUB_W-1:0] sub,
        input integer lane,
        input integer comp
    );
        begin
            get_comp = sub[lane*SAMPLE_W + comp*16 +: 16];
        end
    endfunction

    function automatic signed [16:0] symmetric_pair(
        input integer center_pos,
        input integer offset,
        input integer lane,
        input integer comp
    );
        logic signed [15:0] positive;
        logic signed [15:0] negative;
        begin
            positive = get_comp(
                hist_after_push(center_pos - offset), lane, comp
            );
            negative = get_comp(
                hist_after_push(center_pos + offset), lane, comp
            );
            symmetric_pair =
                $signed({positive[15], positive}) +
                $signed({negative[15], negative});
        end
    endfunction

    function automatic signed [17:0] coeff_for_odd_offset(
        input integer offset_abs
    );
        begin
            case (offset_abs)
                1:  coeff_for_odd_offset =  18'sd41510;
                3:  coeff_for_odd_offset = -18'sd13284;
                5:  coeff_for_odd_offset =  18'sd7343;
                7:  coeff_for_odd_offset = -18'sd4631;
                9:  coeff_for_odd_offset =  18'sd3043;
                11: coeff_for_odd_offset = -18'sd2006;
                13: coeff_for_odd_offset =  18'sd1301;
                15: coeff_for_odd_offset = -18'sd817;
                17: coeff_for_odd_offset =  18'sd490;
                19: coeff_for_odd_offset = -18'sd277;
                21: coeff_for_odd_offset =  18'sd144;
                23: coeff_for_odd_offset = -18'sd67;
                25: coeff_for_odd_offset =  18'sd27;
                27: coeff_for_odd_offset = -18'sd8;
                default: coeff_for_odd_offset = 18'sd0;
            endcase
        end
    endfunction

    function automatic signed [15:0] round_sat_q17(
        input signed [ACC_W-1:0] acc
    );
        logic signed [ACC_W:0] extended;
        logic signed [ACC_W:0] scaled;
        begin
            extended = {acc[ACC_W-1], acc};
            if (extended < 0) begin
                scaled = -(((-extended) + 49'sd65536) >>> COEFF_FRAC);
            end else begin
                scaled = (extended + 49'sd65536) >>> COEFF_FRAC;
            end
            if (scaled > 49'sd32767) begin
                round_sat_q17 = 16'sd32767;
            end else if (scaled < -49'sd32768) begin
                round_sat_q17 = -16'sd32768;
            end else begin
                round_sat_q17 = scaled[15:0];
            end
        end
    endfunction

    function automatic [SUB_W-1:0] filtered_subsample(input integer pos);
        integer lane;
        logic signed [15:0] i_out;
        logic signed [15:0] q_out;
        logic [SUB_W-1:0] result;
        begin
            result = {SUB_W{1'b0}};
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                i_out = round_sat_q17(sum_l4[pos][lane][0]);
                q_out = round_sat_q17(sum_l4[pos][lane][1]);
                result[lane*SAMPLE_W +: SAMPLE_W] = {q_out, i_out};
            end
            filtered_subsample = result;
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        integer idx;
        integer pos;
        integer lane;
        integer comp;
        integer term;
        integer group;
        integer stage;
        integer center_pos;
        if (!rst_n) begin
            for (idx = 0; idx < HIST_DEPTH; idx = idx + 1) begin
                history[idx] <= {SUB_W{1'b0}};
            end
            valid_samples <= 8'd0;
            pipe_valid <= {(PIPE_STAGES+1){1'b0}};
            for (stage = 0; stage <= PIPE_STAGES; stage = stage + 1) begin
                pipe_tuser[stage] <= {USER_W{1'b0}};
                pipe_sample0[stage] <= {SAMPLE0_W{1'b0}};
                pipe_tlast[stage] <= 1'b0;
            end
            half_sub0 <= {SUB_W{1'b0}};
            half_sub1 <= {SUB_W{1'b0}};
            half_tuser <= {USER_W{1'b0}};
            half_sample0 <= {SAMPLE0_W{1'b0}};
            half_tlast <= 1'b0;
            half_valid <= 1'b0;
            pending_tdata <= {DATA_W{1'b0}};
            pending_tuser <= {USER_W{1'b0}};
            pending_sample0 <= {SAMPLE0_W{1'b0}};
            pending_tlast <= 1'b0;
            pending_valid <= 1'b0;
            output_beat_count <= 32'd0;
            dropped_beat_count <= 32'd0;
        end else if (clear || !enable) begin
            valid_samples <= 8'd0;
            pipe_valid <= {(PIPE_STAGES+1){1'b0}};
            half_valid <= 1'b0;
            pending_valid <= 1'b0;
            output_beat_count <= 32'd0;
            dropped_beat_count <= 32'd0;
        end else begin
            if (s_axis_tvalid && !s_axis_tready) begin
                dropped_beat_count <= dropped_beat_count + 32'd1;
            end

            if (pipeline_ce) begin
                if (pending_valid && m_axis_tready) begin
                    pending_valid <= 1'b0;
                end

                pipe_valid[0] <= filtered_input_valid;
                pipe_tuser[0] <= s_axis_tuser;
                // sample0 denotes the signal sample represented by the FIR
                // output.  GROUP_DELAY is filter delay, not extra RTL latency.
                pipe_sample0[0] <= s_axis_sample0;
                pipe_tlast[0] <= s_axis_tlast;
                for (stage = 1; stage <= PIPE_STAGES; stage = stage + 1) begin
                    pipe_valid[stage] <= pipe_valid[stage-1];
                    pipe_tuser[stage] <= pipe_tuser[stage-1];
                    pipe_sample0[stage] <= pipe_sample0[stage-1];
                    pipe_tlast[stage] <= pipe_tlast[stage-1];
                end

                if (input_fire) begin
                    history[0] <= sub_sample(s_axis_tdata, 3);
                    history[1] <= sub_sample(s_axis_tdata, 2);
                    history[2] <= sub_sample(s_axis_tdata, 1);
                    history[3] <= sub_sample(s_axis_tdata, 0);
                    for (idx = 4; idx < HIST_DEPTH; idx = idx + 1) begin
                        history[idx] <= history[idx - 4];
                    end
                    valid_samples <= valid_samples_next;

                    for (pos = 0; pos < 2; pos = pos + 1) begin
                        center_pos = (GROUP_DELAY + 3) - (2 * pos);
                        for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                            for (comp = 0; comp < 2; comp = comp + 1) begin
                                product_pipe[pos][lane][comp][0] <=
                                    $signed(get_comp(
                                        hist_after_push(center_pos), lane, comp
                                    )) * CENTER_COEFF;
                                for (term = 1; term < TERMS; term = term + 1) begin
                                    product_pipe[pos][lane][comp][term] <=
                                        $signed(symmetric_pair(
                                            center_pos,
                                            (2 * term) - 1,
                                            lane,
                                            comp
                                        )) *
                                        coeff_for_odd_offset((2 * term) - 1);
                                end
                            end
                        end
                    end
                end

                for (pos = 0; pos < 2; pos = pos + 1) begin
                    for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                        for (comp = 0; comp < 2; comp = comp + 1) begin
                            for (group = 0; group < 8; group = group + 1) begin
                                if ((2 * group + 1) < TERMS) begin
                                    sum_l1[pos][lane][comp][group] <=
                                        $signed(product_pipe[pos][lane][comp][2*group]) +
                                        $signed(product_pipe[pos][lane][comp][2*group+1]);
                                end else begin
                                    sum_l1[pos][lane][comp][group] <=
                                        $signed(product_pipe[pos][lane][comp][2*group]);
                                end
                            end
                            for (group = 0; group < 4; group = group + 1) begin
                                sum_l2[pos][lane][comp][group] <=
                                    $signed(sum_l1[pos][lane][comp][2*group]) +
                                    $signed(sum_l1[pos][lane][comp][2*group+1]);
                            end
                            for (group = 0; group < 2; group = group + 1) begin
                                sum_l3[pos][lane][comp][group] <=
                                    $signed(sum_l2[pos][lane][comp][2*group]) +
                                    $signed(sum_l2[pos][lane][comp][2*group+1]);
                            end
                            sum_l4[pos][lane][comp] <=
                                $signed(sum_l3[pos][lane][comp][0]) +
                                $signed(sum_l3[pos][lane][comp][1]);
                        end
                    end
                end

                if (pipe_valid[PIPE_STAGES]) begin
                    if (!half_valid) begin
                        half_sub0 <= filtered_subsample(0);
                        half_sub1 <= filtered_subsample(1);
                        half_tuser <= pipe_tuser[PIPE_STAGES];
                        half_sample0 <= pipe_sample0[PIPE_STAGES];
                        half_tlast <= pipe_tlast[PIPE_STAGES];
                        half_valid <= 1'b1;
                    end else begin
                        pending_tdata <= {
                            filtered_subsample(1),
                            filtered_subsample(0),
                            half_sub1,
                            half_sub0
                        };
                        pending_tuser <= half_tuser;
                        pending_sample0 <= half_sample0;
                        pending_tlast <=
                            half_tlast || pipe_tlast[PIPE_STAGES];
                        pending_valid <= 1'b1;
                        output_beat_count <= output_beat_count + 32'd1;
                        half_valid <= 1'b0;
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
