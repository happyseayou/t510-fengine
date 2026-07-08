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
    localparam integer TAPS = 41;
    localparam integer DELAY = 20;
    localparam integer HIST_DEPTH = 44;
    localparam integer COEFF_FRAC = 17;
    localparam signed [17:0] CENTER_COEFF = 18'sd65552;
    localparam signed [47:0] ROUND_TERM = 48'sd65536;
    localparam [31:0] COEFF_VERSION = 32'hAA10_0041;
    localparam [SAMPLE0_W-1:0] DELAY_SAMPLE0 = DELAY;

    logic [SUB_W-1:0] history [0:HIST_DEPTH-1];
    logic [7:0] valid_samples;

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

    wire input_fire = enable && s_axis_tvalid && s_axis_tready;
    wire output_ready = !pending_valid || m_axis_tready;
    wire [7:0] valid_samples_next = (valid_samples >= HIST_DEPTH[7:0]) ? valid_samples : (valid_samples + 8'd4);
    wire filtered_half_valid = input_fire && (valid_samples_next >= HIST_DEPTH[7:0]);
    wire [SAMPLE0_W-1:0] filtered_half_sample0 =
        (s_axis_sample0 >= DELAY_SAMPLE0) ? (s_axis_sample0 - DELAY_SAMPLE0) : {SAMPLE0_W{1'b0}};

    assign s_axis_tready = enable && output_ready;
    assign m_axis_tdata = pending_tdata;
    assign m_axis_tuser = pending_tuser;
    assign m_axis_sample0 = pending_sample0;
    assign m_axis_tlast = pending_tlast;
    assign m_axis_tvalid = pending_valid;
    assign aa_active = enable;
    assign aa_primed = enable && (valid_samples >= HIST_DEPTH[7:0]);
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

    function automatic signed [17:0] coeff_for_odd_offset(input integer offset_abs);
        begin
            case (offset_abs)
                1:  coeff_for_odd_offset = 18'sd41466;
                3:  coeff_for_odd_offset = -18'sd13128;
                5:  coeff_for_odd_offset = 18'sd7096;
                7:  coeff_for_odd_offset = -18'sd4317;
                9:  coeff_for_odd_offset = 18'sd2690;
                11: coeff_for_odd_offset = -18'sd1645;
                13: coeff_for_odd_offset = 18'sd958;
                15: coeff_for_odd_offset = -18'sd513;
                17: coeff_for_odd_offset = 18'sd240;
                19: coeff_for_odd_offset = -18'sd87;
                default: coeff_for_odd_offset = 18'sd0;
            endcase
        end
    endfunction

    function automatic signed [15:0] round_sat_q17(input signed [47:0] acc);
        logic signed [47:0] rounded;
        logic signed [47:0] scaled;
        begin
            rounded = (acc >= 0) ? (acc + ROUND_TERM) : (acc - ROUND_TERM);
            scaled = rounded >>> COEFF_FRAC;
            if (scaled > 48'sd32767) begin
                round_sat_q17 = 16'sd32767;
            end else if (scaled < -48'sd32768) begin
                round_sat_q17 = -16'sd32768;
            end else begin
                round_sat_q17 = scaled[15:0];
            end
        end
    endfunction

    function automatic [SUB_W-1:0] fir_subsample(input integer center_pos);
        integer lane;
        integer odd;
        logic signed [47:0] acc_i;
        logic signed [47:0] acc_q;
        logic signed [17:0] coeff;
        logic signed [16:0] pair_i;
        logic signed [16:0] pair_q;
        logic signed [15:0] i_pos;
        logic signed [15:0] i_neg;
        logic signed [15:0] q_pos;
        logic signed [15:0] q_neg;
        logic signed [15:0] i_out;
        logic signed [15:0] q_out;
        logic [SUB_W-1:0] out;
        begin
            out = {SUB_W{1'b0}};
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                acc_i = $signed(get_comp(hist_after_push(center_pos), lane, 0)) * CENTER_COEFF;
                acc_q = $signed(get_comp(hist_after_push(center_pos), lane, 1)) * CENTER_COEFF;
                for (odd = 1; odd <= 19; odd = odd + 2) begin
                    coeff = coeff_for_odd_offset(odd);
                    i_pos = get_comp(hist_after_push(center_pos - odd), lane, 0);
                    i_neg = get_comp(hist_after_push(center_pos + odd), lane, 0);
                    q_pos = get_comp(hist_after_push(center_pos - odd), lane, 1);
                    q_neg = get_comp(hist_after_push(center_pos + odd), lane, 1);
                    pair_i = $signed({i_pos[15], i_pos}) + $signed({i_neg[15], i_neg});
                    pair_q = $signed({q_pos[15], q_pos}) + $signed({q_neg[15], q_neg});
                    acc_i = acc_i + ($signed(pair_i) * coeff);
                    acc_q = acc_q + ($signed(pair_q) * coeff);
                end
                i_out = round_sat_q17(acc_i);
                q_out = round_sat_q17(acc_q);
                out[lane*SAMPLE_W +: SAMPLE_W] = {q_out, i_out};
            end
            fir_subsample = out;
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        integer idx;
        if (!rst_n) begin
            for (idx = 0; idx < HIST_DEPTH; idx = idx + 1) begin
                history[idx] <= {SUB_W{1'b0}};
            end
            valid_samples <= 8'd0;
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
        end else begin
            if (!enable) begin
                valid_samples <= 8'd0;
                half_valid <= 1'b0;
                pending_valid <= 1'b0;
            end else begin
                if (pending_valid && m_axis_tready) begin
                    pending_valid <= 1'b0;
                end

                if (s_axis_tvalid && !s_axis_tready) begin
                    dropped_beat_count <= dropped_beat_count + 32'd1;
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

                    if (filtered_half_valid) begin
                        if (!half_valid) begin
                            half_sub0 <= fir_subsample(23);
                            half_sub1 <= fir_subsample(21);
                            half_tuser <= s_axis_tuser;
                            half_sample0 <= filtered_half_sample0;
                            half_tlast <= s_axis_tlast;
                            half_valid <= 1'b1;
                        end else begin
                            pending_tdata <= {
                                fir_subsample(21),
                                fir_subsample(23),
                                half_sub1,
                                half_sub0
                            };
                            pending_tuser <= half_tuser;
                            pending_sample0 <= half_sample0;
                            pending_tlast <= half_tlast || s_axis_tlast;
                            pending_valid <= 1'b1;
                            output_beat_count <= output_beat_count + 32'd1;
                            half_valid <= 1'b0;
                        end
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
