`include "tb_common.svh"

module tb_adc_interleave_spur_corrector;

    localparam integer NINPUT = 8;
    localparam integer SUBSAMPLES = 4;
    localparam integer SAMPLE_W = 32;
    localparam integer DATA_W = NINPUT * SUBSAMPLES * SAMPLE_W;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic [DATA_W-1:0] s_axis_tdata = '0;
    logic [31:0] s_axis_tuser = '0;
    logic [63:0] s_axis_sample0 = '0;
    logic [63:0] s_axis_raw_sample0 = '0;
    logic s_axis_tvalid = 1'b0;
    logic s_axis_tlast = 1'b0;
    wire s_axis_tready;
    wire [DATA_W-1:0] m_axis_tdata;
    wire [31:0] m_axis_tuser;
    wire [63:0] m_axis_sample0;
    wire [63:0] m_axis_raw_sample0;
    wire m_axis_tvalid;
    wire m_axis_tlast;
    logic m_axis_tready = 1'b1;

    logic shadow_enable = 1'b0;
    logic shadow_in_band = 1'b0;
    logic shadow_bypass = 1'b1;
    logic shadow_phase_reload = 1'b0;
    logic [1:0] shadow_spur_id = 2'd0;
    logic [47:0] shadow_phase_step = 48'd0;
    logic [47:0] shadow_phase_seed = 48'd0;
    logic [NINPUT*48-1:0] shadow_coefficients = '0;
    logic [31:0] shadow_profile_id = 32'd0;
    logic [31:0] shadow_model_crc32 = 32'd0;
    logic [31:0] shadow_generation = 32'd0;
    logic shadow_crc_valid = 1'b0;
    logic commit_pulse = 1'b0;
    logic tracker_heartbeat_pulse = 1'b0;
    logic disable_pulse = 1'b0;
    logic clear_errors_pulse = 1'b0;

    wire correction_active;
    wire correction_uncorrected;
    wire [31:0] status_word;
    wire [1:0] active_spur_id;
    wire [47:0] active_phase_step;
    wire [31:0] active_profile_id;
    wire [31:0] active_model_crc32;
    wire [31:0] active_generation;
    wire [63:0] last_commit_sample0;
    wire [31:0] saturation_count;
    wire [31:0] sample0_discontinuity_count;
    wire [31:0] crc_error_count;
    wire [31:0] tracker_stale_count;
    wire [31:0] commit_count;

    integer lane;
    integer sub;
    logic [DATA_W-1:0] held_data;
    logic [31:0] held_user;
    logic [63:0] held_sample0;
    integer capture_count = 0;
    logic [DATA_W-1:0] captured_data [0:7];
    logic [31:0] captured_user [0:7];

    always #5 clk = ~clk;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            capture_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (capture_count < 8) begin
                captured_data[capture_count] <= m_axis_tdata;
                captured_user[capture_count] <= m_axis_tuser;
            end
            capture_count <= capture_count + 1;
        end
    end

    function automatic [DATA_W-1:0] make_beat(input integer i_value, input integer q_value);
        integer word_index;
        logic [DATA_W-1:0] value;
        begin
            value = '0;
            for (word_index = 0; word_index < NINPUT*SUBSAMPLES; word_index = word_index + 1) begin
                value[word_index*32 +: 16] = i_value[15:0];
                value[word_index*32 + 16 +: 16] = q_value[15:0];
            end
            make_beat = value;
        end
    endfunction

    function automatic [DATA_W-1:0] quarter_step_saturated_expected(input integer i_value, input integer q_value);
        integer word_index;
        integer sample_index;
        integer temp_i;
        integer temp_q;
        logic [DATA_W-1:0] value;
        begin
            value = '0;
            for (word_index = 0; word_index < NINPUT*SUBSAMPLES; word_index = word_index + 1) begin
                sample_index = word_index / NINPUT;
                temp_i = i_value;
                temp_q = q_value;
                case (sample_index)
                    0: temp_i = temp_i - 1;
                    1: temp_q = temp_q - 1;
                    2: temp_i = temp_i + 1;
                    default: temp_q = temp_q + 1;
                endcase
                if (temp_i > 32767) temp_i = 32767;
                if (temp_i < -32768) temp_i = -32768;
                if (temp_q > 32767) temp_q = 32767;
                if (temp_q < -32768) temp_q = -32768;
                value[word_index*32 +: 16] = temp_i[15:0];
                value[word_index*32 + 16 +: 16] = temp_q[15:0];
            end
            quarter_step_saturated_expected = value;
        end
    endfunction

    function automatic [DATA_W-1:0] quarter_step_expected(input integer i_value, input integer q_value);
        integer word_index;
        integer sample_index;
        logic signed [15:0] out_i;
        logic signed [15:0] out_q;
        logic [DATA_W-1:0] value;
        begin
            value = '0;
            for (word_index = 0; word_index < NINPUT*SUBSAMPLES; word_index = word_index + 1) begin
                sample_index = word_index / NINPUT;
                case (sample_index)
                    0: begin out_i = i_value - 1; out_q = q_value; end
                    1: begin out_i = i_value; out_q = q_value - 1; end
                    2: begin out_i = i_value + 1; out_q = q_value; end
                    default: begin out_i = i_value; out_q = q_value + 1; end
                endcase
                value[word_index*32 +: 16] = out_i;
                value[word_index*32 + 16 +: 16] = out_q;
            end
            quarter_step_expected = value;
        end
    endfunction

    function automatic [DATA_W-1:0] quarter_tone_beat(input integer amplitude);
        integer word_index;
        integer sample_index;
        logic signed [15:0] tone_i;
        logic signed [15:0] tone_q;
        logic [DATA_W-1:0] value;
        begin
            value = '0;
            for (word_index = 0; word_index < NINPUT*SUBSAMPLES; word_index = word_index + 1) begin
                sample_index = word_index / NINPUT;
                case (sample_index)
                    0: begin tone_i = amplitude; tone_q = 0; end
                    1: begin tone_i = 0; tone_q = amplitude; end
                    2: begin tone_i = -amplitude; tone_q = 0; end
                    default: begin tone_i = 0; tone_q = -amplitude; end
                endcase
                value[word_index*32 +: 16] = tone_i;
                value[word_index*32 + 16 +: 16] = tone_q;
            end
            quarter_tone_beat = value;
        end
    endfunction

    function automatic [DATA_W-1:0] negative_quarter_step_expected(input integer i_value, input integer q_value);
        integer word_index;
        integer sample_index;
        logic signed [15:0] out_i;
        logic signed [15:0] out_q;
        logic [DATA_W-1:0] value;
        begin
            value = '0;
            for (word_index = 0; word_index < NINPUT*SUBSAMPLES; word_index = word_index + 1) begin
                sample_index = word_index / NINPUT;
                case (sample_index)
                    0: begin out_i = i_value - 1; out_q = q_value; end
                    1: begin out_i = i_value; out_q = q_value + 1; end
                    2: begin out_i = i_value + 1; out_q = q_value; end
                    default: begin out_i = i_value; out_q = q_value - 1; end
                endcase
                value[word_index*32 +: 16] = out_i;
                value[word_index*32 + 16 +: 16] = out_q;
            end
            negative_quarter_step_expected = value;
        end
    endfunction

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            clear = 1'b0;
            s_axis_tvalid = 1'b0;
            m_axis_tready = 1'b1;
            shadow_enable = 1'b0;
            shadow_in_band = 1'b0;
            shadow_bypass = 1'b1;
            shadow_phase_reload = 1'b0;
            shadow_spur_id = 2'd0;
            shadow_phase_step = 48'd0;
            shadow_phase_seed = 48'd0;
            shadow_coefficients = '0;
            shadow_profile_id = 32'd0;
            shadow_model_crc32 = 32'd0;
            shadow_generation = 32'd0;
            shadow_crc_valid = 1'b0;
            commit_pulse = 1'b0;
            tracker_heartbeat_pulse = 1'b0;
            disable_pulse = 1'b0;
            clear_errors_pulse = 1'b0;
            repeat (5) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic pulse_commit_and_heartbeat;
        begin
            @(negedge clk);
            commit_pulse = 1'b1;
            tracker_heartbeat_pulse = 1'b1;
            @(negedge clk);
            commit_pulse = 1'b0;
            tracker_heartbeat_pulse = 1'b0;
        end
    endtask

    task automatic send_beat(
        input [DATA_W-1:0] data,
        input [63:0] raw_sample0,
        input [31:0] user_value,
        input logic last_value
    );
        begin
            @(negedge clk);
            while (!s_axis_tready) @(negedge clk);
            s_axis_tdata = data;
            s_axis_tuser = user_value;
            s_axis_sample0 = raw_sample0 + 64'h1000_0000;
            s_axis_raw_sample0 = raw_sample0;
            s_axis_tlast = last_value;
            s_axis_tvalid = 1'b1;
            @(negedge clk);
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
        end
    endtask

    task automatic expect_output(
        input [DATA_W-1:0] data,
        input [63:0] raw_sample0,
        input [31:0] user_value,
        input logic last_value
    );
        begin
            while (!m_axis_tvalid) @(negedge clk);
            `TB_CHECK_EQ(m_axis_tdata, data, "corrector output data")
            `TB_CHECK_EQ(m_axis_tuser, user_value, "corrector tuser alignment")
            `TB_CHECK_EQ(m_axis_sample0, raw_sample0 + 64'h1000_0000, "corrector sample0 alignment")
            `TB_CHECK_EQ(m_axis_raw_sample0, raw_sample0, "corrector raw sample0 alignment")
            `TB_CHECK_EQ(m_axis_tlast, last_value, "corrector tlast alignment")
            @(negedge clk);
        end
    endtask

    adc_interleave_spur_corrector #(
        .TRACKER_TIMEOUT_CYCLES(50),
        .SINE_MEM_FILE("adc_interleave_sine_q17_1024.mem")
    ) dut (.*);

    initial begin
        reset_dut();

        // Bypass has exactly the same latency/hold behavior and data bits as
        // the corrected path, including while downstream is stalled.
        send_beat(make_beat(1234, -567), 64'd40, 32'ha5a5_1234, 1'b1);
        while (!m_axis_tvalid) @(negedge clk);
        held_data = m_axis_tdata;
        held_user = m_axis_tuser;
        held_sample0 = m_axis_sample0;
        m_axis_tready = 1'b0;
        repeat (3) begin
            @(negedge clk);
            `TB_CHECK_EQ(m_axis_tdata, held_data, "backpressure holds data")
            `TB_CHECK_EQ(m_axis_tuser, held_user, "backpressure holds user")
            `TB_CHECK_EQ(m_axis_sample0, held_sample0, "backpressure holds sample0")
            `TB_CHECK_EQ(m_axis_tvalid, 1'b1, "backpressure holds valid")
        end
        `TB_CHECK_EQ(held_data, make_beat(1234, -567), "bit-exact bypass")
        clear = 1'b1;
        @(negedge clk);
        `TB_CHECK_EQ(m_axis_tvalid, 1'b0, "clear flushes a backpressured output")
        clear = 1'b0;
        m_axis_tready = 1'b1;
        @(negedge clk);

        reset_dut();
        // Continuous full-rate beats must not pair the previous valid/sideband
        // with the next beat's data.
        @(negedge clk);
        s_axis_tvalid = 1'b1;
        for (lane = 0; lane < 4; lane = lane + 1) begin
            s_axis_tdata = make_beat(200 + lane, -100 - lane);
            s_axis_tuser = 32'h2000 + lane;
            s_axis_sample0 = 64'h2000 + lane * 4;
            s_axis_raw_sample0 = 64'd1000 + lane * 4;
            @(negedge clk);
        end
        s_axis_tvalid = 1'b0;
        while (capture_count < 4) @(negedge clk);
        for (lane = 0; lane < 4; lane = lane + 1) begin
            `TB_CHECK_EQ(captured_data[lane], make_beat(200 + lane, -100 - lane), "continuous bypass data alignment")
            `TB_CHECK_EQ(captured_user[lane], 32'h2000 + lane, "continuous bypass sideband alignment")
        end

        // A science clear and an incoming raw beat may occur together.  The
        // cleared beat must not leak out, but it must still advance the raw
        // sample continuity epoch so the following beat remains contiguous.
        reset_dut();
        @(negedge clk);
        clear = 1'b1;
        s_axis_tvalid = 1'b1;
        s_axis_tdata = make_beat(777, -333);
        s_axis_tuser = 32'hdead_0001;
        s_axis_sample0 = 64'h1000_0000 + 64'd2000;
        s_axis_raw_sample0 = 64'd2000;
        @(negedge clk);
        clear = 1'b0;
        s_axis_tdata = make_beat(778, -334);
        s_axis_tuser = 32'hdead_0002;
        s_axis_sample0 = 64'h1000_0000 + 64'd2004;
        s_axis_raw_sample0 = 64'd2004;
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        expect_output(make_beat(778, -334), 64'd2004, 32'hdead_0002, 1'b0);
        `TB_CHECK_EQ(sample0_discontinuity_count, 32'd0, "clear preserves raw sample continuity")

        reset_dut();
        shadow_enable = 1'b1;
        shadow_in_band = 1'b1;
        shadow_bypass = 1'b0;
        shadow_phase_reload = 1'b1;
        shadow_spur_id = 2'd2;
        shadow_phase_step = 48'h4000_0000_0000;
        shadow_phase_seed = 48'd0;
        shadow_profile_id = 32'h36e8_0001;
        shadow_model_crc32 = 32'h1234_5678;
        shadow_generation = 32'd17;
        shadow_crc_valid = 1'b1;
        for (lane = 0; lane < NINPUT; lane = lane + 1) begin
            shadow_coefficients[lane*48 +: 24] = 24'sd65536;
            shadow_coefficients[lane*48 + 24 +: 24] = 24'sd0;
        end
        pulse_commit_and_heartbeat();
        // Pending commit must not apply away from sample0 mod 8192 == 0.
        send_beat(make_beat(100, 50), 64'd8188, 32'd1, 1'b0);
        expect_output(make_beat(100, 50), 64'd8188, 32'd1, 1'b0);
        `TB_CHECK_EQ(commit_count, 32'd0, "commit waits for atomic boundary")
        send_beat(make_beat(100, 50), 64'd8192, 32'd2, 1'b0);
        expect_output(quarter_step_expected(100, 50), 64'd8192, 32'd2, 1'b0);
        `TB_CHECK_EQ(commit_count, 32'd1, "atomic commit count")
        `TB_CHECK_EQ(last_commit_sample0, 64'd8192, "atomic commit sample0")
        `TB_CHECK_EQ(active_spur_id, 2'd2, "active spur identity")
        `TB_CHECK_EQ(active_phase_step, 48'h4000_0000_0000, "signed/positive phase step bits")
        `TB_CHECK_EQ(active_profile_id, 32'h36e8_0001, "active profile identity")
        `TB_CHECK_EQ(active_model_crc32, 32'h1234_5678, "active model identity")
        `TB_CHECK_EQ(active_generation, 32'd17, "active transaction generation")
        `TB_CHECK_EQ(correction_active, 1'b1, "correction active after commit")

        // A later real signal at exactly the same frequency is not learned or
        // notched.  Subtracting the calibrated one-ADU vector leaves the new
        // ten-ADU tone with its amplitude and phase intact.
        send_beat(quarter_tone_beat(11), 64'd8196, 32'd3, 1'b0);
        expect_output(quarter_tone_beat(10), 64'd8196, 32'd3, 1'b0);

        // One cell with any I/Q saturation increments the cell counter once.
        send_beat(make_beat(-32768, 0), 64'd8200, 32'd4, 1'b0);
        expect_output(quarter_step_saturated_expected(-32768, 0), 64'd8200, 32'd4, 1'b0);
        `TB_CHECK_EQ(saturation_count, 32'd1, "saturation is counted per cell")

        // A discontinuity never applies a phase-misaligned subtraction and
        // permanently latches the session fault.
        send_beat(make_beat(100, 50), 64'd9000, 32'd5, 1'b0);
        expect_output(make_beat(100, 50), 64'd9000, 32'd5, 1'b0);
        `TB_CHECK_EQ(sample0_discontinuity_count, 32'd1, "sample0 discontinuity count")
        `TB_CHECK_EQ(status_word[11], 1'b1, "sample0 fault latched")
        `TB_CHECK_EQ(correction_active, 1'b0, "fault forces bypass")

        reset_dut();
        shadow_enable = 1'b1;
        shadow_in_band = 1'b1;
        shadow_bypass = 1'b0;
        shadow_phase_reload = 1'b1;
        shadow_crc_valid = 1'b0;
        pulse_commit_and_heartbeat();
        send_beat(make_beat(7, 8), 64'd8192, 32'd5, 1'b0);
        expect_output(make_beat(7, 8), 64'd8192, 32'd5, 1'b0);
        `TB_CHECK_EQ(crc_error_count, 32'd1, "bad CRC commit rejected")
        `TB_CHECK_EQ(status_word[11], 1'b1, "CRC failure latched")

        reset_dut();
        shadow_enable = 1'b1;
        shadow_in_band = 1'b1;
        shadow_bypass = 1'b0;
        shadow_phase_reload = 1'b1;
        shadow_crc_valid = 1'b1;
        pulse_commit_and_heartbeat();
        send_beat(make_beat(1, 2), 64'd8192, 32'd6, 1'b0);
        expect_output(make_beat(1, 2), 64'd8192, 32'd6, 1'b0);
        repeat (55) @(posedge clk);
        #1;
        `TB_CHECK_EQ(tracker_stale_count, 32'd1, "tracker timeout count")
        `TB_CHECK_EQ(status_word[12], 1'b1, "tracker stale latched")
        `TB_CHECK_EQ(status_word[11], 1'b1, "tracker timeout faults session")
        `TB_CHECK_EQ(correction_active, 1'b0, "tracker timeout forces bypass")
        @(negedge clk);
        tracker_heartbeat_pulse = 1'b1;
        @(negedge clk);
        tracker_heartbeat_pulse = 1'b0;
        `TB_CHECK_EQ(correction_active, 1'b0, "late heartbeat cannot silently resume")

        // A two's-complement negative phase step reverses the four-subsample
        // rotation without changing lane/subsample ordering.
        reset_dut();
        shadow_enable = 1'b1;
        shadow_in_band = 1'b1;
        shadow_bypass = 1'b0;
        shadow_phase_reload = 1'b1;
        shadow_phase_step = 48'hc000_0000_0000;
        shadow_phase_seed = 48'd0;
        shadow_crc_valid = 1'b1;
        for (lane = 0; lane < NINPUT; lane = lane + 1) begin
            shadow_coefficients[lane*48 +: 24] = 24'sd65536;
            shadow_coefficients[lane*48 + 24 +: 24] = 24'sd0;
        end
        pulse_commit_and_heartbeat();
        send_beat(make_beat(100, 50), 64'd8192, 32'd7, 1'b0);
        expect_output(negative_quarter_step_expected(100, 50), 64'd8192, 32'd7, 1'b0);
        `TB_CHECK_EQ(active_phase_step, 48'hc000_0000_0000, "signed/negative phase step bits")

        `TB_PASS("tb_adc_interleave_spur_corrector")
    end

endmodule
