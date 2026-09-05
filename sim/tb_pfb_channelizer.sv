`include "tb_common.svh"

module tb_pfb_channelizer;

    localparam integer DATA_W = 1024;
    localparam integer CELLS_PER_BEAT = 4;
    localparam integer INPUT_BEATS_PER_FFT_FRAME = 4096 / CELLS_PER_BEAT;
    localparam integer BEATS_PER_SPEC_PACKET = 64;
    localparam integer SPEC_BLOCKS = 16;
    localparam integer OUTPUT_BEATS = BEATS_PER_SPEC_PACKET * SPEC_BLOCKS;
    localparam integer OUTPUT_TILES = 2;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b0;
    logic clear = 1'b0;
    logic [15:0] cfg_taps = 16'd8;
    logic [15:0] cfg_fft_shift = 16'h0556;
    logic [31:0] cfg_chan0 = 32'd0;
    logic [15:0] cfg_chan_count = 16'd256;
    logic [15:0] cfg_time_count = 16'd1;
    logic        coeff_load_start = 1'b0;
    logic        coeff_commit = 1'b0;
    logic        coeff_abort = 1'b0;
    logic        coeff_write = 1'b0;
    logic [3:0]  coeff_requested_taps = 4'd8;
    logic [14:0] coeff_index = 15'd0;
    logic signed [17:0] coeff_data = 18'sd0;
    logic [31:0] coeff_id = 32'h34a8_0001;
    wire [31:0] coeff_status;
    wire [31:0] coeff_loaded_count;
    wire [31:0] coeff_active_id;
    wire [31:0] coeff_active_checksum;
    wire [31:0] coeff_error_count;
    logic [DATA_W-1:0] s_axis_tdata = {DATA_W{1'b0}};
    logic [63:0]  s_axis_sample0 = 64'd0;
    logic         s_axis_tvalid = 1'b0;
    wire          s_axis_tready;
    wire [DATA_W-1:0]  m_axis_tdata;
    wire [63:0]   m_axis_sample0;
    wire          m_axis_tvalid;
    logic         m_axis_tready = 1'b1;
    logic         random_output_backpressure = 1'b0;
    logic [15:0]  output_ready_lfsr = 16'h1ace;
    integer       output_capacity_stall_cycles = 0;
    logic [31:0]  output_fifo_level = 32'd0;
    wire [31:0]   status;
    wire [31:0]   frame_count;
    wire [31:0]   overflow_count;
    wire [31:0]   peak_chan;
    wire [31:0]   peak_power;
    wire [31:0]   packet_chan0;
    wire [15:0]   packet_chan_count;
    wire [15:0]   packet_time_count;

    integer beat_idx = 0;
    integer out_count = 0;
    integer out_packet_idx = 0;
    integer out_packet_beat = 0;
    integer accepted_input_beats = 0;
    integer test_case = 0;
    logic zero_input_mode = 1'b0;
    logic saturation_input_mode = 1'b0;
    integer pfb_input_cell_count = 0;
    integer pfb_elastic_pop_push_count = 0;
    integer input_cycle = 0;
    integer last_accept_cycle = 0;
    integer max_nonboundary_accept_gap = 0;
    logic [12:0] xfft_frame_cell_count = 13'd0;
    logic        xfft_frame_active = 1'b0;
    logic        first_active_bank = 1'b0;
    integer      xfft_frame_gap_count = 0;
    integer signed production_coeff [0:32767];
    integer rejection_tap;
    integer rejection_phase;

    always #5 clk = ~clk;

    function automatic [255:0] make_frame_cell(
        input integer phase,
        input integer frame_idx
    );
        integer lane;
        logic signed [15:0] i_value;
        logic signed [15:0] q_value;
        logic [255:0] value;
        begin
            value = 256'd0;
            for (lane = 0; lane < 8; lane = lane + 1) begin
                i_value = phase + lane + frame_idx * 128;
                q_value = phase + lane + 16 + frame_idx * 128;
                value[lane*32 +: 16] = i_value;
                value[lane*32 + 16 +: 16] = q_value;
            end
            make_frame_cell = value;
        end
    endfunction

    function automatic [DATA_W-1:0] make_beat(input integer beat);
        integer cell_idx;
        integer frame_idx;
        integer phase;
        logic [DATA_W-1:0] value;
        begin
            value = {DATA_W{1'b0}};
            frame_idx = beat / INPUT_BEATS_PER_FFT_FRAME;
            for (cell_idx = 0; cell_idx < CELLS_PER_BEAT; cell_idx = cell_idx + 1) begin
                phase = ((beat * CELLS_PER_BEAT) + cell_idx) % 4096;
                value[cell_idx*256 +: 256] = make_frame_cell(phase, frame_idx);
            end
            make_beat = value;
        end
    endfunction

    function automatic [255:0] golden_pfb_cell(
        input integer phase,
        input integer first_frame
    );
        integer comp;
        integer tap;
        longint signed acc;
        longint signed magnitude;
        longint signed rounded;
        logic signed [15:0] sample_value;
        logic signed [15:0] output_value;
        logic [255:0] frame_cell;
        logic [255:0] value;
        begin
            value = 256'd0;
            for (comp = 0; comp < 16; comp = comp + 1) begin
                acc = 0;
                for (tap = 0; tap < 8; tap = tap + 1) begin
                    frame_cell = make_frame_cell(phase, first_frame + tap);
                    sample_value = $signed(frame_cell[comp*16 +: 16]);
                    acc = acc + sample_value * production_coeff[tap*4096 + phase];
                end
                magnitude = (acc < 0) ? -acc : acc;
                rounded = (magnitude + 32768) >>> 16;
                if (acc < 0) begin
                    output_value = (rounded >= 32768) ? -16'sd32768 : -rounded;
                end else begin
                    output_value = (rounded > 32767) ? 16'sd32767 : rounded;
                end
                value[comp*16 +: 16] = output_value;
            end
            golden_pfb_cell = value;
        end
    endfunction

    function automatic [DATA_W-1:0] make_saturation_beat(input integer beat);
        integer cell_idx;
        integer lane;
        integer tap;
        integer phase;
        logic signed [15:0] sample_value;
        logic [DATA_W-1:0] value;
        begin
            value = {DATA_W{1'b0}};
            tap = (beat / INPUT_BEATS_PER_FFT_FRAME) % 8;
            for (cell_idx = 0; cell_idx < CELLS_PER_BEAT; cell_idx = cell_idx + 1) begin
                phase = (beat * CELLS_PER_BEAT + cell_idx) % 4096;
                sample_value = production_coeff[tap*4096 + phase] < 0
                    ? -16'sd32768 : 16'sd32767;
                for (lane = 0; lane < 8; lane = lane + 1) begin
                    value[cell_idx*256 + lane*32 +: 16] = sample_value;
                    value[cell_idx*256 + lane*32 + 16 +: 16] = sample_value;
                end
            end
            make_saturation_beat = value;
        end
    endfunction

    function automatic [63:0] beat_sample0(input integer beat);
        begin
            beat_sample0 = 64'h0000_0003_0000_0000 + (beat * 4);
        end
    endfunction

    task automatic generate_production_pfb_coefficients;
        integer tap;
        integer phase;
        integer sample;
        integer delta;
        integer strongest_tap;
        integer quantized [0:7];
        real values [0:7];
        real x;
        real sinc_value;
        real window_value;
        real phase_sum;
        real scaled;
        real strongest_abs;
        begin
            for (phase = 0; phase < 4096; phase = phase + 1) begin
                phase_sum = 0.0;
                strongest_tap = 0;
                strongest_abs = 0.0;
                for (tap = 0; tap < 8; tap = tap + 1) begin
                    sample = tap * 4096 + phase;
                    x = (sample - 16383.5) / 4096.0;
                    sinc_value = (((x < 0.0) ? -x : x) < 1.0e-15)
                        ? 1.0 : $sin(3.14159265358979323846 * x) /
                                (3.14159265358979323846 * x);
                    window_value = 0.54 - 0.46 * $cos(
                        (2.0 * 3.14159265358979323846 * sample) / 32767.0
                    );
                    values[tap] = sinc_value * window_value;
                    phase_sum = phase_sum + values[tap];
                end
                delta = 131072;
                for (tap = 0; tap < 8; tap = tap + 1) begin
                    scaled = values[tap] / phase_sum * 131072.0;
                    quantized[tap] = (scaled >= 0.0)
                        ? $rtoi(scaled + 0.5) : $rtoi(scaled - 0.5);
                    if (quantized[tap] > 131071) quantized[tap] = 131071;
                    if (quantized[tap] < -131072) quantized[tap] = -131072;
                    delta = delta - quantized[tap];
                end
                strongest_tap = -1;
                strongest_abs = -1.0;
                for (tap = 0; tap < 8; tap = tap + 1) begin
                    if (((delta > 0 && quantized[tap] < 131071) ||
                         (delta < 0 && quantized[tap] > -131072) || delta == 0) &&
                        ((values[tap] < 0.0 ? -values[tap] : values[tap]) > strongest_abs)) begin
                        strongest_abs = values[tap] < 0.0 ? -values[tap] : values[tap];
                        strongest_tap = tap;
                    end
                end
                quantized[strongest_tap] = quantized[strongest_tap] + delta;
                for (tap = 0; tap < 8; tap = tap + 1) begin
                    production_coeff[tap*4096 + phase] = quantized[tap];
                end
            end
        end
    endtask

    pfb_channelizer #(
        .DATA_W(DATA_W),
        .NINPUT(8),
        .NCHAN(4096)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .cfg_taps(cfg_taps),
        .cfg_fft_shift(cfg_fft_shift),
        .cfg_chan0(cfg_chan0),
        .cfg_chan_count(cfg_chan_count),
        .cfg_time_count(cfg_time_count),
        .coeff_load_start(coeff_load_start),
        .coeff_commit(coeff_commit),
        .coeff_abort(coeff_abort),
        .coeff_write(coeff_write),
        .coeff_requested_taps(coeff_requested_taps),
        .coeff_index(coeff_index),
        .coeff_data(coeff_data),
        .coeff_id(coeff_id),
        .coeff_status(coeff_status),
        .coeff_loaded_count(coeff_loaded_count),
        .coeff_active_id(coeff_active_id),
        .coeff_active_checksum(coeff_active_checksum),
        .coeff_error_count(coeff_error_count),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .output_fifo_level(output_fifo_level),
        .status(status),
        .frame_count(frame_count),
        .overflow_count(overflow_count),
        .peak_chan(peak_chan),
        .peak_power(peak_power),
        .packet_chan0(packet_chan0),
        .packet_chan_count(packet_chan_count),
        .packet_time_count(packet_time_count)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            output_ready_lfsr <= 16'h1ace;
            output_capacity_stall_cycles <= 0;
        end else begin
            output_ready_lfsr <= {
                output_ready_lfsr[14:0],
                output_ready_lfsr[15] ^ output_ready_lfsr[13] ^
                output_ready_lfsr[12] ^ output_ready_lfsr[10]
            };
            if (random_output_backpressure) begin
                // The realtime XFFT itself cannot be throttled once a frame
                // starts.  Downstream pressure is represented by the real
                // output-FIFO occupancy feedback, which gates the next full
                // frame reservation without introducing an internal gap.
                output_fifo_level <= (output_ready_lfsr[2:0] == 3'b000)
                    ? 32'd3500 : 32'd0;
                if ((dut.u_feng_channelizer_4096.valid_frame_count == 4'd8) &&
                    !dut.u_feng_channelizer_4096.feed_active &&
                    !dut.u_feng_channelizer_4096.output_capacity_available) begin
                    output_capacity_stall_cycles <= output_capacity_stall_cycles + 1;
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            beat_idx <= 0;
            accepted_input_beats <= 0;
            s_axis_tdata <= zero_input_mode ? {DATA_W{1'b0}} :
                            saturation_input_mode ? make_saturation_beat(0) : make_beat(0);
            s_axis_sample0 <= beat_sample0(0);
        end else if (s_axis_tvalid && s_axis_tready) begin
            beat_idx <= beat_idx + 1;
            accepted_input_beats <= accepted_input_beats + 1;
            s_axis_tdata <= zero_input_mode ? {DATA_W{1'b0}} :
                            saturation_input_mode ? make_saturation_beat(beat_idx + 1) :
                                                    make_beat(beat_idx + 1);
            s_axis_sample0 <= beat_sample0(beat_idx + 1);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            out_packet_idx = out_count / BEATS_PER_SPEC_PACKET;
            out_packet_beat = out_count % BEATS_PER_SPEC_PACKET;
            if (test_case == 1) begin
                `TB_CHECK_EQ(m_axis_tdata, {DATA_W{1'b0}}, "FFT-only zero input produces zero SPEC output word")
            end else if (test_case == 0) begin
                if (out_count < 8) begin
                    `TB_CHECK(m_axis_tdata != make_beat(out_count), "PFB/F-engine output is not raw pass-through")
                end
            end
            `TB_CHECK_EQ(
                m_axis_sample0,
                beat_sample0((out_packet_idx / SPEC_BLOCKS) * INPUT_BEATS_PER_FFT_FRAME),
                "PFB packet sample0 is first contributing frame sample"
            )
            if (out_packet_beat == 0) begin
                `TB_CHECK_EQ(packet_chan0, (out_packet_idx % SPEC_BLOCKS) * 256, "FFT-only packet chan0 block sweep")
                `TB_CHECK_EQ(packet_chan_count, 16'd256, "FFT-only packet channel count during sweep")
                `TB_CHECK_EQ(packet_time_count, 16'd1, "FFT-only packet time count during sweep")
            end
            out_count <= out_count + 1;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n || clear || !enable) begin
            xfft_frame_cell_count <= 13'd0;
            xfft_frame_active <= 1'b0;
            xfft_frame_gap_count <= 0;
        end else begin
            if (xfft_frame_active &&
                dut.u_feng_channelizer_4096.xfft_s_axis_tready &&
                !dut.u_feng_channelizer_4096.xfft_s_axis_tvalid) begin
                xfft_frame_gap_count <= xfft_frame_gap_count + 1;
                `TB_CHECK(1'b0, "FFT-only XFFT input frame has no tvalid gap while tready is high")
            end

            if (dut.u_feng_channelizer_4096.xfft_input_fire) begin
                if (!xfft_frame_active) begin
                    `TB_CHECK_EQ(
                        dut.u_feng_channelizer_4096.xfft_data_idx,
                        12'd0,
                        "FFT-only XFFT input frame starts at bin 0"
                    )
                    xfft_frame_active <= 1'b1;
                    xfft_frame_cell_count <= 13'd1;
                end else begin
                    `TB_CHECK_EQ(
                        dut.u_feng_channelizer_4096.xfft_data_idx,
                        xfft_frame_cell_count[11:0],
                        "FFT-only XFFT input bin increments without gaps"
                    )
                    if (dut.u_feng_channelizer_4096.xfft_data_idx == 12'd4095) begin
                        xfft_frame_active <= 1'b0;
                        xfft_frame_cell_count <= 13'd0;
                    end else begin
                        xfft_frame_cell_count <= xfft_frame_cell_count + 13'd1;
                    end
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n || clear || !enable) begin
            pfb_input_cell_count <= 0;
            pfb_elastic_pop_push_count <= 0;
            input_cycle <= 0;
            last_accept_cycle <= 0;
            max_nonboundary_accept_gap <= 0;
        end else if (dut.u_feng_channelizer_4096.xfft_input_fire) begin
            `TB_CHECK_EQ(
                dut.u_feng_channelizer_4096.xfft_data_idx,
                pfb_input_cell_count % 4096,
                "current PFB XFFT input index remains ordered across backpressure"
            )
            if (!zero_input_mode && !saturation_input_mode) begin
                `TB_CHECK_EQ(
                    dut.u_feng_channelizer_4096.xfft_data,
                    golden_pfb_cell(
                        pfb_input_cell_count % 4096,
                        pfb_input_cell_count / 4096
                    ),
                    "fixed 8-tap PFB output is bit-exact across frame history and backpressure"
                )
            end
            pfb_input_cell_count <= pfb_input_cell_count + 1;
        end
        if (rst_n && enable) begin
            input_cycle <= input_cycle + 1;
            if (s_axis_tvalid && s_axis_tready) begin
                // A frame contains 1024 input words.  A boundary pause is
                // permitted while ownership of the eight PFB frame buffers
                // rotates; every other accepted word must be at most four
                // PFB clocks after the previous word.
                if ((accepted_input_beats != 0) &&
                    ((accepted_input_beats % INPUT_BEATS_PER_FFT_FRAME) != 0) &&
                    ((input_cycle - last_accept_cycle) >
                     max_nonboundary_accept_gap)) begin
                    max_nonboundary_accept_gap <=
                        input_cycle - last_accept_cycle;
                end
                last_accept_cycle <= input_cycle;
            end
        end
        if (rst_n && enable &&
            dut.u_feng_channelizer_4096.output_fire &&
            dut.u_feng_channelizer_4096.xfft_output_fire) begin
            pfb_elastic_pop_push_count <= pfb_elastic_pop_push_count + 1;
        end
        if (rst_n && enable && m_axis_tready &&
            dut.u_feng_channelizer_4096.output_valid &&
            dut.u_feng_channelizer_4096.xfft_m_axis_tvalid) begin
            `TB_CHECK(
                dut.u_feng_channelizer_4096.xfft_m_axis_tready,
                "current PFB accepts an XFFT cell while downstream consumes the previous packed beat"
            )
        end
    end

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            s_axis_tvalid = 1'b0;
            clear = 1'b0;
            enable = 1'b0;
            coeff_load_start = 1'b0;
            coeff_commit = 1'b0;
            coeff_abort = 1'b0;
            coeff_write = 1'b0;
            coeff_requested_taps = 4'd8;
            coeff_index = 15'd0;
            coeff_data = 18'sd0;
            coeff_id = 32'h34a8_0001;
            output_fifo_level = 32'd0;
            repeat (6) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
            s_axis_tdata = zero_input_mode ? {DATA_W{1'b0}} :
                           saturation_input_mode ? make_saturation_beat(0) : make_beat(0);
        end
    endtask

    task automatic load_production_pfb_coefficients;
        integer tap;
        integer phase;
        begin
            @(negedge clk);
            coeff_requested_taps = 4'd8;
            coeff_id = 32'h34a8_0001;
            coeff_load_start = 1'b1;
            @(negedge clk);
            coeff_load_start = 1'b0;
            for (tap = 0; tap < 8; tap = tap + 1) begin
                for (phase = 0; phase < 4096; phase = phase + 1) begin
                    coeff_index = {tap[2:0], phase[11:0]};
                    coeff_data = production_coeff[tap*4096 + phase];
                    coeff_write = 1'b1;
                    @(negedge clk);
                    coeff_write = 1'b0;
                end
            end
            repeat (2) @(posedge clk);
            `TB_CHECK_EQ(coeff_loaded_count, 32'd32768, "fixed 8-tap PFB coefficient load count")
            `TB_CHECK(coeff_status[2], "current PFB shadow coefficient bank full")
            @(negedge clk);
            coeff_commit = 1'b1;
            @(negedge clk);
            coeff_commit = 1'b0;
            repeat (4) @(posedge clk);
            `TB_CHECK(coeff_status[0], "current PFB active coefficient bank valid")
            `TB_CHECK_EQ(coeff_status[11:8], 4'd8, "fixed PFB active taps")
            `TB_CHECK_EQ(coeff_active_id, 32'h34a8_0001, "fixed PFB active coefficient profile id")
            `TB_CHECK_EQ(coeff_active_checksum, 32'hb9ba_227c, "fixed PFB production coefficient CRC32")
            `TB_CHECK_EQ(coeff_error_count, 32'd0, "current PFB coefficient command error count")
        end
    endtask

    task automatic wait_for_outputs(input integer expected);
        integer timeout;
        begin
            timeout = 0;
            while ((out_count < expected) && (timeout < 90000)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK_EQ(out_count, expected, "PFB F-engine output count")
        end
    endtask

    task automatic wait_for_accepted_inputs(input integer expected);
        integer timeout;
        begin
            timeout = 0;
            while ((accepted_input_beats < expected) && (timeout < 90000)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK_EQ(accepted_input_beats, expected, "FFT-only accepted input beat count")
            `TB_CHECK(timeout <= (expected * (CELLS_PER_BEAT + 1)) + 4096, "current PFB production input frame buffer keeps up with priming")
        end
    endtask

    initial begin
        generate_production_pfb_coefficients();
        `TB_CHECK_EQ($signed(dut.u_feng_channelizer_4096.round_sat_q16_39(39'sd32767)), 16'sd0, "PFB positive sub-half-LSB rounds to zero")
        `TB_CHECK_EQ($signed(dut.u_feng_channelizer_4096.round_sat_q16_39(-39'sd32767)), 16'sd0, "PFB negative sub-half-LSB rounds to zero")
        `TB_CHECK_EQ($signed(dut.u_feng_channelizer_4096.round_sat_q16_39(39'sd32768)), 16'sd1, "PFB positive half-LSB rounds away from zero")
        `TB_CHECK_EQ($signed(dut.u_feng_channelizer_4096.round_sat_q16_39(-39'sd32768)), -16'sd1, "PFB negative half-LSB rounds away from zero")
        reset_dut();

        @(negedge clk);
        coeff_requested_taps = 4'd4;
        coeff_load_start = 1'b1;
        @(negedge clk);
        coeff_load_start = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(coeff_loaded_count, 32'd0, "legacy 4-tap load is rejected")
        `TB_CHECK_EQ(coeff_error_count, 32'd1, "legacy 4-tap rejection increments command errors")

        reset_dut();
        @(negedge clk);
        coeff_requested_taps = 4'd8;
        coeff_load_start = 1'b1;
        @(negedge clk);
        coeff_load_start = 1'b0;
        coeff_index = 15'd1;
        coeff_data = 18'sd7;
        coeff_write = 1'b1;
        @(negedge clk);
        coeff_write = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(coeff_loaded_count, 32'd0, "out-of-order coefficient write is not accepted")
        `TB_CHECK_EQ(coeff_error_count, 32'd1, "out-of-order coefficient write increments errors")
        @(negedge clk);
        for (rejection_tap = 0; rejection_tap < 8; rejection_tap = rejection_tap + 1) begin
            for (rejection_phase = 0; rejection_phase < 4096; rejection_phase = rejection_phase + 1) begin
                coeff_index = {rejection_tap[2:0], rejection_phase[11:0]};
                coeff_data = production_coeff[rejection_tap*4096 + rejection_phase];
                coeff_write = 1'b1;
                @(negedge clk);
                coeff_write = 1'b0;
            end
        end
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(coeff_loaded_count, 32'd32768, "poisoned load may count corrected writes")
        `TB_CHECK(!coeff_status[2], "one out-of-order write permanently prevents shadow-full for that load")
        @(negedge clk);
        coeff_commit = 1'b1;
        @(negedge clk);
        coeff_commit = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK(!coeff_status[0], "poisoned coefficient sequence cannot commit")
        `TB_CHECK_EQ(coeff_error_count, 32'd2, "poisoned commit increments command errors")

        reset_dut();
        load_production_pfb_coefficients();
        first_active_bank = dut.u_feng_channelizer_4096.active_bank;
        load_production_pfb_coefficients();
        `TB_CHECK(
            dut.u_feng_channelizer_4096.active_bank != first_active_bank,
            "fixed 8-tap active/shadow commit atomically switches banks while idle"
        )
        // The XFFT aresetn stays low for 15 clocks after reset/epoch clear.
        // current deliberately waits for SPEC enable before configuring its
        // realtime lanes, matching the scheduled first-sample release path.
        repeat (24) @(posedge clk);

        `TB_CHECK(!status[0], "PFB enabled status bit stays low before streaming enable")
        `TB_CHECK(status[1], "PFB config valid status bit")
        `TB_CHECK(!status[8], "current PFB clears FFT-only status bit")
        `TB_CHECK(!status[9], "current defers realtime XFFT config until SPEC enable")
        `TB_CHECK(!status[5], "current science-valid waits for enabled XFFT config")
        `TB_CHECK(
            !dut.u_feng_channelizer_4096.xfft_aresetn,
            "current holds realtime XFFT reset while SPEC is disabled"
        )
`ifndef T510_SIM_FFT_MODEL
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[0].lane_config_tdata[0], 1'b1, "lane0 XFFT forward config")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[0].lane_config_tdata[12:1], cfg_fft_shift[11:0], "lane0 XFFT scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[7].lane_config_tdata[0], 1'b1, "lane7 XFFT forward config")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[7].lane_config_tdata[12:1], cfg_fft_shift[11:0], "lane7 XFFT scaling schedule")
`else
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[19:8], 12'h556, "PFB XFFT channel 0 12-bit scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[103:92], 12'h556, "PFB XFFT channel 7 12-bit scaling schedule")
`endif
        `TB_CHECK_EQ(packet_chan0, 32'd0, "PFB packet chan0")
        `TB_CHECK_EQ(packet_chan_count, 16'd256, "FFT-only packet channel count")
        `TB_CHECK_EQ(packet_time_count, 16'd1, "FFT-only packet time count")

        @(negedge clk);
        enable = 1'b1;
        repeat (24) @(posedge clk);
        `TB_CHECK(status[9], "current XFFT config completes after SPEC enable")
        `TB_CHECK_EQ(status[23:16], 8'hff, "current XFFT lane config done mask")
        `TB_CHECK(status[5], "current science-valid rises after enabled XFFT config")
        `TB_CHECK(
            dut.u_feng_channelizer_4096.xfft_aresetn,
            "current releases realtime XFFT reset after SPEC enable"
        )
        `TB_CHECK(status[0], "PFB enabled status bit after streaming enable")

        @(negedge clk);
        s_axis_tvalid = 1'b1;
        output_fifo_level = 32'd3500;
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME * 8);
        repeat (16) @(posedge clk);
        `TB_CHECK_EQ(pfb_input_cell_count, 0, "current realtime XFFT feed waits for one-frame output FIFO reservation")
        `TB_CHECK(
            max_nonboundary_accept_gap <= CELLS_PER_BEAT,
            "current PFB accepts one 1024-bit word per four clocks without the former fifth-cycle gap"
        )
        output_fifo_level = 32'd0;
        random_output_backpressure = 1'b1;
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME * (OUTPUT_TILES + 7));
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        wait_for_outputs(OUTPUT_BEATS * OUTPUT_TILES);
        repeat (3) @(posedge clk);

        `TB_CHECK_EQ(frame_count, 32'd2, "FFT-only frame count after two full 4096-bin F-engine tiles")
        `TB_CHECK_EQ(overflow_count, 32'd0, "PFB overflow count")
        `TB_CHECK_EQ(xfft_frame_gap_count, 0, "FFT-only XFFT input frame has zero internal gaps")
        `TB_CHECK(output_capacity_stall_cycles > 0, "fixed 8-tap PFB exercises randomized downstream FIFO backpressure")
        `TB_CHECK(pfb_elastic_pop_push_count > 0, "current PFB exercises elastic output pop/push")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_data_out_halt_count, 32'd0, "current PFB sustained-ready XFFT output halt count")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.capture_backpressure_count, 32'd0, "current PFB sustained-ready capture backpressure count")
        `TB_CHECK(peak_chan < 32'd4096, "PFB peak channel stays inside full F-engine band")
        `TB_CHECK_EQ(peak_power, 32'd0, "production FFT-only removes high-speed peak scan")

        @(negedge clk);
        clear = 1'b1;
        @(negedge clk);
        clear = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(frame_count, 32'd0, "PFB clear resets frame count")
        `TB_CHECK_EQ(peak_power, 32'd0, "PFB clear resets peak power")

        test_case = 1;
        zero_input_mode = 1'b1;
        random_output_backpressure = 1'b0;
        reset_dut();
        load_production_pfb_coefficients();
        repeat (4) @(posedge clk);
        @(negedge clk);
        enable = 1'b1;
        repeat (2) @(posedge clk);
        @(negedge clk);
        s_axis_tvalid = 1'b1;
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME * 8);
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        wait_for_outputs(OUTPUT_BEATS);
        repeat (3) @(posedge clk);
        `TB_CHECK_EQ(frame_count, 32'd1, "FFT-only zero input frame count")
        `TB_CHECK_EQ(overflow_count, 32'd0, "FFT-only zero input no overflow")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_event_count, 32'd0, "PFB zero input no XFFT event")
        `TB_CHECK_EQ(xfft_frame_gap_count, 0, "FFT-only zero input XFFT frame has zero internal gaps")

        test_case = 2;
        zero_input_mode = 1'b0;
        saturation_input_mode = 1'b1;
        reset_dut();
        load_production_pfb_coefficients();
        @(negedge clk);
        enable = 1'b1;
        repeat (24) @(posedge clk);
        @(negedge clk);
        s_axis_tvalid = 1'b1;
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME * 8);
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        wait_for_outputs(OUTPUT_BEATS);
        repeat (3) @(posedge clk);
        `TB_CHECK(
            dut.u_feng_channelizer_4096.tile_overflow_count > 32'd0,
            "fixed 8-tap PFB counts cells containing FIR saturation"
        )

        cfg_time_count = 16'd3;
        repeat (2) @(posedge clk);
        `TB_CHECK(!status[1], "PFB invalid window clears config_valid")
        `TB_CHECK(!s_axis_tready, "PFB invalid window deasserts ready")

        `TB_PASS("tb_pfb_channelizer")
    end

endmodule
