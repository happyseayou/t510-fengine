module adc_interleave_spur_corrector #(
    parameter integer NINPUT = 8,
    parameter integer SUBSAMPLES = 4,
    parameter integer SAMPLE_W = 32,
    parameter integer USER_W = 32,
    parameter integer SAMPLE0_W = 64,
    parameter integer TRACKER_TIMEOUT_CYCLES = 80_000_000,
    parameter string SINE_MEM_FILE = "adc_interleave_sine_q17_1024.mem"
) (
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              clear,

    input  wire [NINPUT*SUBSAMPLES*SAMPLE_W-1:0] s_axis_tdata,
    input  wire [USER_W-1:0]                 s_axis_tuser,
    input  wire [SAMPLE0_W-1:0]              s_axis_sample0,
    input  wire [SAMPLE0_W-1:0]              s_axis_raw_sample0,
    input  wire                              s_axis_tvalid,
    input  wire                              s_axis_tlast,
    output wire                              s_axis_tready,

    output logic [NINPUT*SUBSAMPLES*SAMPLE_W-1:0] m_axis_tdata,
    output logic [USER_W-1:0]                m_axis_tuser,
    output logic [SAMPLE0_W-1:0]             m_axis_sample0,
    output logic [SAMPLE0_W-1:0]             m_axis_raw_sample0,
    output logic                             m_axis_tvalid,
    output logic                             m_axis_tlast,
    input  wire                              m_axis_tready,

    input  wire                              shadow_enable,
    input  wire                              shadow_in_band,
    input  wire                              shadow_bypass,
    input  wire                              shadow_phase_reload,
    input  wire [1:0]                        shadow_spur_id,
    input  wire [47:0]                       shadow_phase_step,
    input  wire [47:0]                       shadow_phase_seed,
    input  wire [NINPUT*48-1:0]              shadow_coefficients,
    input  wire [31:0]                       shadow_profile_id,
    input  wire [31:0]                       shadow_model_crc32,
    input  wire [31:0]                       shadow_generation,
    input  wire                              shadow_crc_valid,
    input  wire                              commit_pulse,
    input  wire                              tracker_heartbeat_pulse,
    input  wire                              disable_pulse,
    input  wire                              clear_errors_pulse,

    output wire                              correction_active,
    output wire                              correction_uncorrected,
    output logic [31:0]                      status_word,
    output logic [1:0]                       active_spur_id,
    output logic [47:0]                      active_phase_step,
    output logic [31:0]                      active_profile_id,
    output logic [31:0]                      active_model_crc32,
    output logic [31:0]                      active_generation,
    output logic [63:0]                      last_commit_sample0,
    output logic [31:0]                      saturation_count,
    output logic [31:0]                      sample0_discontinuity_count,
    output logic [31:0]                      crc_error_count,
    output logic [31:0]                      tracker_stale_count,
    output logic [31:0]                      commit_count
);

    localparam integer WORDS_PER_BEAT = NINPUT * SUBSAMPLES;
    localparam integer DATA_W = NINPUT * SUBSAMPLES * SAMPLE_W;
    localparam integer TIMEOUT_W = (TRACKER_TIMEOUT_CYCLES < 2) ? 1 : $clog2(TRACKER_TIMEOUT_CYCLES + 1);

    (* rom_style = "distributed" *) logic signed [17:0] sine_rom [0:1023];
    initial begin
        $readmemh(SINE_MEM_FILE, sine_rom);
    end

    function automatic signed [17:0] sine_q17(input logic [47:0] phase);
        begin
            sine_q17 = sine_rom[phase[47:38]];
        end
    endfunction

    function automatic signed [24:0] round_q33(input logic signed [42:0] value);
        logic signed [43:0] magnitude;
        logic signed [43:0] rounded;
        begin
            if (value < 0) begin
                magnitude = -{{1{value[42]}}, value};
                rounded = (magnitude + (44'sd1 <<< 32)) >>> 33;
                round_q33 = -rounded[24:0];
            end else begin
                rounded = ({{1{value[42]}}, value} + (44'sd1 <<< 32)) >>> 33;
                round_q33 = rounded[24:0];
            end
        end
    endfunction

    function automatic signed [15:0] saturate_iq16(input logic signed [25:0] value);
        begin
            if (value > 26'sd32767) begin
                saturate_iq16 = 16'sh7fff;
            end else if (value < -26'sd32768) begin
                saturate_iq16 = 16'sh8000;
            end else begin
                saturate_iq16 = value[15:0];
            end
        end
    endfunction

    function automatic logic would_saturate(input logic signed [25:0] value);
        begin
            would_saturate = (value > 26'sd32767) || (value < -26'sd32768);
        end
    endfunction

    logic active_enable;
    logic active_in_band;
    logic active_bypass;
    logic phase_synchronized;
    logic fault_latched;
    logic tracker_stale_latched;
    logic commit_pending;
    logic [47:0] phase_accumulator;
    logic [NINPUT*48-1:0] active_coefficients;
    logic [TIMEOUT_W-1:0] tracker_age;
    logic raw_sample_seen;
    logic [63:0] last_raw_sample0;

    wire tracker_fresh = !tracker_stale_latched &&
        (tracker_age < TRACKER_TIMEOUT_CYCLES[TIMEOUT_W-1:0]);
    assign correction_active = active_enable && active_in_band && !active_bypass &&
        phase_synchronized && tracker_fresh && !fault_latched;
    assign correction_uncorrected = active_in_band && !correction_active;

    wire pipeline_advance = !m_axis_tvalid || m_axis_tready;
    assign s_axis_tready = pipeline_advance;
    wire input_fire = s_axis_tvalid && s_axis_tready;
    wire raw_sample_contiguous = !raw_sample_seen ||
        (s_axis_raw_sample0 == (last_raw_sample0 + 64'd4));
    wire commit_requested = commit_pending || commit_pulse;
    wire commit_boundary = (s_axis_raw_sample0[12:0] == 13'd0);
    wire commit_now = input_fire && commit_requested && commit_boundary;
    wire commit_allowed = shadow_crc_valid &&
        (!shadow_enable || !shadow_in_band || shadow_phase_reload || phase_synchronized);

    wire effective_enable = commit_now ? shadow_enable : active_enable;
    wire effective_in_band = commit_now ? shadow_in_band : active_in_band;
    wire effective_bypass = commit_now ? shadow_bypass : active_bypass;
    wire effective_phase_sync = commit_now ?
        (shadow_phase_reload || phase_synchronized) : phase_synchronized;
    wire [47:0] effective_step = commit_now ? shadow_phase_step : active_phase_step;
    wire [47:0] phase_for_input = (commit_now && shadow_phase_reload) ?
        shadow_phase_seed : phase_accumulator;
    wire [NINPUT*48-1:0] effective_coefficients = commit_now ?
        shadow_coefficients : active_coefficients;
    wire apply_for_input = effective_enable && effective_in_band && !effective_bypass &&
        effective_phase_sync && tracker_fresh && !fault_latched && raw_sample_contiguous &&
        (!commit_now || commit_allowed);

    logic pipe1_valid;
    logic [DATA_W-1:0] pipe1_raw;
    logic [USER_W-1:0] pipe1_user;
    logic [SAMPLE0_W-1:0] pipe1_sample0;
    logic [SAMPLE0_W-1:0] pipe1_raw_sample0;
    logic pipe1_last;
    logic pipe1_apply;
    (* use_dsp = "yes" *) logic signed [41:0] product_cr_cos [0:WORDS_PER_BEAT-1];
    (* use_dsp = "yes" *) logic signed [41:0] product_ci_sin [0:WORDS_PER_BEAT-1];
    (* use_dsp = "yes" *) logic signed [41:0] product_cr_sin [0:WORDS_PER_BEAT-1];
    (* use_dsp = "yes" *) logic signed [41:0] product_ci_cos [0:WORDS_PER_BEAT-1];

    integer word_idx;
    integer comb_word_idx;
    integer lane_idx;
    integer subsample_idx;
    logic signed [15:0] raw_i;
    logic signed [15:0] raw_q;
    logic signed [24:0] correction_i;
    logic signed [24:0] correction_q;
    logic signed [25:0] corrected_i;
    logic signed [25:0] corrected_q;
    logic any_saturation;
    logic signed [23:0] selected_cr;
    logic signed [23:0] selected_ci;
    logic signed [17:0] selected_sin;
    logic signed [17:0] selected_cos;
    logic [47:0] selected_phase;
    logic [DATA_W-1:0] selected_output_data;

    always_comb begin
        any_saturation = 1'b0;
        selected_output_data = {DATA_W{1'b0}};
        for (comb_word_idx = 0; comb_word_idx < WORDS_PER_BEAT; comb_word_idx = comb_word_idx + 1) begin
            raw_i = $signed(pipe1_raw[comb_word_idx*SAMPLE_W +: 16]);
            raw_q = $signed(pipe1_raw[comb_word_idx*SAMPLE_W + 16 +: 16]);
            correction_i = round_q33($signed({product_cr_cos[comb_word_idx][41], product_cr_cos[comb_word_idx]}) -
                                       $signed({product_ci_sin[comb_word_idx][41], product_ci_sin[comb_word_idx]}));
            correction_q = round_q33($signed({product_cr_sin[comb_word_idx][41], product_cr_sin[comb_word_idx]}) +
                                       $signed({product_ci_cos[comb_word_idx][41], product_ci_cos[comb_word_idx]}));
            corrected_i = $signed({{10{raw_i[15]}}, raw_i}) - $signed({correction_i[24], correction_i});
            corrected_q = $signed({{10{raw_q[15]}}, raw_q}) - $signed({correction_q[24], correction_q});
            if (pipe1_apply) begin
                selected_output_data[comb_word_idx*SAMPLE_W +: 16] = saturate_iq16(corrected_i);
                selected_output_data[comb_word_idx*SAMPLE_W + 16 +: 16] = saturate_iq16(corrected_q);
                any_saturation = any_saturation || would_saturate(corrected_i) || would_saturate(corrected_q);
            end else begin
                selected_output_data[comb_word_idx*SAMPLE_W +: SAMPLE_W] =
                    pipe1_raw[comb_word_idx*SAMPLE_W +: SAMPLE_W];
            end
        end
    end

    always_comb begin
        status_word = {
            16'd0,
            shadow_crc_valid,
            commit_pending,
            tracker_stale_latched,
            fault_latched,
            phase_synchronized,
            active_bypass,
            active_in_band,
            active_enable,
            5'd0,
            correction_uncorrected,
            correction_active
        };
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            m_axis_tdata <= {DATA_W{1'b0}};
            m_axis_tvalid <= 1'b0;
            m_axis_tuser <= {USER_W{1'b0}};
            m_axis_sample0 <= {SAMPLE0_W{1'b0}};
            m_axis_raw_sample0 <= {SAMPLE0_W{1'b0}};
            m_axis_tlast <= 1'b0;
            pipe1_valid <= 1'b0;
            pipe1_raw <= {DATA_W{1'b0}};
            pipe1_user <= {USER_W{1'b0}};
            pipe1_sample0 <= {SAMPLE0_W{1'b0}};
            pipe1_raw_sample0 <= {SAMPLE0_W{1'b0}};
            pipe1_last <= 1'b0;
            pipe1_apply <= 1'b0;
            active_enable <= 1'b0;
            active_in_band <= 1'b0;
            active_bypass <= 1'b1;
            phase_synchronized <= 1'b0;
            fault_latched <= 1'b0;
            tracker_stale_latched <= 1'b0;
            commit_pending <= 1'b0;
            phase_accumulator <= 48'd0;
            active_phase_step <= 48'd0;
            active_coefficients <= {(NINPUT*48){1'b0}};
            active_spur_id <= 2'd0;
            active_profile_id <= 32'd0;
            active_model_crc32 <= 32'd0;
            active_generation <= 32'd0;
            tracker_age <= {TIMEOUT_W{1'b0}};
            raw_sample_seen <= 1'b0;
            last_raw_sample0 <= 64'd0;
            last_commit_sample0 <= 64'd0;
            saturation_count <= 32'd0;
            sample0_discontinuity_count <= 32'd0;
            crc_error_count <= 32'd0;
            tracker_stale_count <= 32'd0;
            commit_count <= 32'd0;
            for (word_idx = 0; word_idx < WORDS_PER_BEAT; word_idx = word_idx + 1) begin
                product_cr_cos[word_idx] <= 42'sd0;
                product_ci_sin[word_idx] <= 42'sd0;
                product_cr_sin[word_idx] <= 42'sd0;
                product_ci_cos[word_idx] <= 42'sd0;
            end
        end else begin
            if (clear_errors_pulse) begin
                fault_latched <= 1'b0;
                tracker_stale_latched <= 1'b0;
                saturation_count <= 32'd0;
                sample0_discontinuity_count <= 32'd0;
                crc_error_count <= 32'd0;
                tracker_stale_count <= 32'd0;
            end

            if (disable_pulse) begin
                active_enable <= 1'b0;
                active_in_band <= 1'b0;
                active_bypass <= 1'b1;
                phase_synchronized <= 1'b0;
                commit_pending <= 1'b0;
                tracker_age <= {TIMEOUT_W{1'b0}};
            end

            if (commit_pulse) begin
                commit_pending <= 1'b1;
            end

            if (tracker_heartbeat_pulse) begin
                tracker_age <= {TIMEOUT_W{1'b0}};
            end else if (active_enable && active_in_band && !active_bypass && !tracker_stale_latched) begin
                if (tracker_age < TRACKER_TIMEOUT_CYCLES[TIMEOUT_W-1:0]) begin
                    tracker_age <= tracker_age + {{(TIMEOUT_W-1){1'b0}}, 1'b1};
                end else begin
                    tracker_stale_latched <= 1'b1;
                    fault_latched <= 1'b1;
                    tracker_stale_count <= tracker_stale_count + 32'd1;
                end
            end

            if (commit_now) begin
                commit_pending <= 1'b0;
                if (commit_allowed) begin
                    active_enable <= shadow_enable;
                    active_in_band <= shadow_in_band;
                    active_bypass <= shadow_bypass;
                    active_spur_id <= shadow_spur_id;
                    active_phase_step <= shadow_phase_step;
                    active_coefficients <= shadow_coefficients;
                    active_profile_id <= shadow_profile_id;
                    active_model_crc32 <= shadow_model_crc32;
                    active_generation <= shadow_generation;
                    last_commit_sample0 <= s_axis_raw_sample0;
                    commit_count <= commit_count + 32'd1;
                    tracker_age <= {TIMEOUT_W{1'b0}};
                    if (shadow_phase_reload) begin
                        phase_synchronized <= 1'b1;
                        phase_accumulator <= shadow_phase_seed + (shadow_phase_step << 2);
                    end
                end else begin
                    active_enable <= 1'b0;
                    active_bypass <= 1'b1;
                    fault_latched <= 1'b1;
                    crc_error_count <= crc_error_count + 32'd1;
                end
            end else if (input_fire && phase_synchronized) begin
                phase_accumulator <= phase_accumulator + (active_phase_step << 2);
            end

            if (input_fire) begin
                if (!raw_sample_contiguous) begin
                    sample0_discontinuity_count <= sample0_discontinuity_count + 32'd1;
                    if (correction_active) begin
                        fault_latched <= 1'b1;
                    end
                end
                raw_sample_seen <= 1'b1;
                last_raw_sample0 <= s_axis_raw_sample0;
            end

            // A science-path clear flushes only buffered validity, even when a
            // downstream stall is holding the output.  If the RFDC beat is
            // accepted in this cycle, the raw continuity checker and NCO still
            // advance above, so START does not create a new local phase epoch.
            if (clear) begin
                m_axis_tvalid <= 1'b0;
                pipe1_valid <= 1'b0;
            end else if (pipeline_advance) begin
                m_axis_tvalid <= pipe1_valid;
                m_axis_tuser <= pipe1_user;
                m_axis_sample0 <= pipe1_sample0;
                m_axis_raw_sample0 <= pipe1_raw_sample0;
                m_axis_tlast <= pipe1_last;
                if (pipe1_valid) begin
                    m_axis_tdata <= selected_output_data;
                end
                if (pipe1_valid && pipe1_apply && any_saturation) begin
                    saturation_count <= saturation_count + 32'd1;
                end

                pipe1_valid <= input_fire;
                if (input_fire) begin
                    pipe1_raw <= s_axis_tdata;
                    pipe1_user <= s_axis_tuser;
                    pipe1_sample0 <= s_axis_sample0;
                    pipe1_raw_sample0 <= s_axis_raw_sample0;
                    pipe1_last <= s_axis_tlast;
                    pipe1_apply <= apply_for_input;
                    for (word_idx = 0; word_idx < WORDS_PER_BEAT; word_idx = word_idx + 1) begin
                        lane_idx = word_idx % NINPUT;
                        subsample_idx = word_idx / NINPUT;
                        selected_phase = phase_for_input + (effective_step * subsample_idx);
                        selected_sin = sine_q17(selected_phase);
                        selected_cos = sine_q17(selected_phase + 48'h4000_0000_0000);
                        selected_cr = $signed(effective_coefficients[lane_idx*48 +: 24]);
                        selected_ci = $signed(effective_coefficients[lane_idx*48 + 24 +: 24]);
                        product_cr_cos[word_idx] <= selected_cr * selected_cos;
                        product_ci_sin[word_idx] <= selected_ci * selected_sin;
                        product_cr_sin[word_idx] <= selected_cr * selected_sin;
                        product_ci_cos[word_idx] <= selected_ci * selected_cos;
                    end
                end
            end
        end
    end

endmodule
