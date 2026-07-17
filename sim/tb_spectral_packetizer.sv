`include "tb_common.svh"

module tb_spectral_packetizer;

    localparam integer WORDS_PER_PACKET = 16 + (256 * 4);
    localparam integer PACKETS = 3;
    localparam integer CAPTURE_WORDS = WORDS_PER_PACKET * PACKETS;
    localparam integer INPUT_BEATS = PACKETS * 256;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b0;
    logic stream_reset = 1'b0;
    logic [255:0] s_axis_tdata = 256'd0;
    logic [63:0]  s_axis_sample0 = 64'd0;
    logic         s_axis_tvalid = 1'b0;
    wire          s_axis_tready;
    wire [63:0]   m_axis_tdata;
    wire [7:0]    m_axis_tkeep;
    wire          m_axis_tvalid;
    wire          m_axis_tlast;
    logic         m_axis_tready = 1'b1;
    wire [31:0]   packet_count;
    wire [31:0]   udp_byte_count;
    wire [31:0]   seq_no_debug;
    wire [63:0]   frame_id_debug;
    wire [31:0]   chan0_debug;

    logic [63:0] captured [0:CAPTURE_WORDS-1];
    integer out_count = 0;
    integer last_count = 0;
    integer last_index = -1;
    integer beat_idx = 0;
    integer accept_count = 0;
    logic [255:0] accepted [0:INPUT_BEATS-1];

    always #5 clk = ~clk;

    function automatic [63:0] sample_word(input integer beat, input integer subword);
        begin
            sample_word = 64'h2000_0000_0000_0000 + ((beat * 4) + subword);
        end
    endfunction

    function automatic [255:0] make_sample(input integer beat);
        begin
            make_sample = {
                sample_word(beat, 3),
                sample_word(beat, 2),
                sample_word(beat, 1),
                sample_word(beat, 0)
            };
        end
    endfunction

    function automatic [63:0] beat_sample0(input integer beat);
        begin
            beat_sample0 = 64'h0000_0002_0000_0000 + (beat * 4);
        end
    endfunction

    spectral_packetizer dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .stream_reset(stream_reset),
        .board_id(16'h00bb),
        .global_input0(16'h0066),
        .epoch_mode(16'd1),
        .packet_flags(16'h000a),
        .unix_seconds(64'h0102_0304_0506_0708),
        .pps_count(64'h0000_0000_0000_0099),
        .sync_generation(64'h11),
        .sync_observation_tag(64'h22),
        .sync_metadata(64'h33),
        .sync_status(64'h44),
        .quant_mode(16'd0),
        .scale_mode(16'd0),
        .scale_id(32'h8765_4321),
        .spec_chan0(32'd3840),
        .spec_time_count(16'd1),
        .spec_chan_count(16'd256),
        .spec_nchan(16'd4096),
        .spec_taps(16'd0),
        .spec_fft_shift(16'd3),
        .spec_sample_rate_hz(32'd100_000_000),
        .spec_status_flags(32'h0000_0100),
        .chan_split(32'd2048),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready),
        .packet_count(packet_count),
        .udp_byte_count(udp_byte_count),
        .seq_no_debug(seq_no_debug),
        .frame_id_debug(frame_id_debug),
        .chan0_debug(chan0_debug)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            beat_idx <= 0;
            accept_count <= 0;
            s_axis_tdata <= make_sample(0);
            s_axis_sample0 <= beat_sample0(0);
        end else begin
            if (s_axis_tvalid && s_axis_tready && accept_count < INPUT_BEATS) begin
                accepted[accept_count] <= s_axis_tdata;
                accept_count <= accept_count + 1;
                beat_idx <= beat_idx + 1;
                s_axis_tdata <= make_sample(beat_idx + 1);
                s_axis_sample0 <= beat_sample0(beat_idx + 1);
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
            last_count <= 0;
            last_index <= -1;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (out_count < CAPTURE_WORDS) begin
                captured[out_count] <= m_axis_tdata;
            end
            if (m_axis_tlast) begin
                last_count <= last_count + 1;
                last_index <= out_count;
            end
            out_count <= out_count + 1;
        end
    end

    task automatic wait_for_packets(input integer expected_packets);
        integer timeout;
        begin
            timeout = 0;
            while ((last_count < expected_packets) && (timeout < 9000)) begin
                @(posedge clk);
                #1;
                timeout = timeout + 1;
            end
            `TB_CHECK(last_count == expected_packets, "SPEC packetizer timeout")
        end
    endtask

    task automatic check_header(
        input integer      base,
        input logic [31:0] seq,
        input logic [63:0] sample0,
        input logic [63:0] frame_id,
        input logic [31:0] chan0,
        input logic        split_flag
    );
        begin
            `TB_CHECK_EQ(captured[base + 0], 64'h5435_3130_0003_0080, "SPEC v3 header word 0")
            `TB_CHECK_EQ(captured[base + 1], 64'h00bb_0000_0001_000a, "SPEC stream identity")
            `TB_CHECK_EQ(captured[base + 2], 64'h0102_0304_0506_0708, "SPEC unix seconds")
            `TB_CHECK_EQ(captured[base + 3], 64'h0000_0000_0000_0099, "SPEC pps count")
            `TB_CHECK_EQ(captured[base + 4], sample0[63:0], "SPEC sample0")
            `TB_CHECK_EQ(captured[base + 5], frame_id[63:0], "SPEC frame_id")
            `TB_CHECK_EQ(captured[base + 6], {seq[31:0], chan0[31:0]}, "SPEC seq/chan0")
            `TB_CHECK_EQ(captured[base + 7], {16'd256, 16'd1, 16'd8, 16'd0}, "SPEC layout")
            `TB_CHECK_EQ(captured[base + 8], 64'h8765_4321_0000_2000, "SPEC scale/payload bytes")
            `TB_CHECK_EQ(captured[base + 9], {16'hf101, 16'd4096, 16'd15, 16'd16}, "SPEC 27h product/block header")
            `TB_CHECK_EQ(captured[base + 10], {16'd0, 16'd3, 32'h0000_0100}, "SPEC 27h taps/shift/status")
            `TB_CHECK_EQ(captured[base + 11], {32'd100_000_000, 16'd0, 15'd0, split_flag}, "SPEC 27h sample rate/split flag")
            `TB_CHECK_EQ(captured[base + 12], 64'h11, "SPEC sync generation")
            `TB_CHECK_EQ(captured[base + 13], 64'h22, "SPEC observation tag")
            `TB_CHECK_EQ(captured[base + 14], 64'h33, "SPEC sync metadata")
            `TB_CHECK_EQ(captured[base + 15], 64'h44, "SPEC sync status")
        end
    endtask

    task automatic check_payload(input integer base, input integer first_beat);
        integer idx;
        integer beat;
        integer subword;
        begin
            for (idx = 0; idx < 256 * 4; idx = idx + 1) begin
                beat = first_beat + (idx / 4);
                subword = idx % 4;
                `TB_CHECK_EQ(captured[base + 16 + idx], accepted[beat][subword*64 +: 64], "SPEC payload word")
            end
        end
    endtask

    initial begin
        rst_n = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        @(negedge clk);
        enable = 1'b1;
        s_axis_tvalid = 1'b1;
        wait_for_packets(PACKETS);
        s_axis_tvalid = 1'b0;
        #1;

        `TB_CHECK_EQ(out_count, CAPTURE_WORDS, "SPEC output word count")
        `TB_CHECK_EQ(last_index, CAPTURE_WORDS - 1, "SPEC tlast index")
        `TB_CHECK_EQ(accept_count, INPUT_BEATS, "SPEC accepted input beat count")
        check_header(0, 0, beat_sample0(0), 0, 3840, 1);
        check_payload(0, 0);
        check_header(WORDS_PER_PACKET, 1, beat_sample0(256), 1, 3840, 1);
        check_payload(WORDS_PER_PACKET, 256);
        check_header(WORDS_PER_PACKET * 2, 2, beat_sample0(512), 2, 3840, 1);
        check_payload(WORDS_PER_PACKET * 2, 512);
        `TB_CHECK_EQ(packet_count, 32'd3, "SPEC packet_count")
        `TB_CHECK_EQ(seq_no_debug, 32'd3, "SPEC seq debug")
        `TB_CHECK_EQ(frame_id_debug, 64'd3, "SPEC frame debug")
        `TB_CHECK_EQ(chan0_debug, 32'd3840, "SPEC chan0 debug from channelizer")
        `TB_CHECK_EQ(udp_byte_count, 32'd24960, "SPEC byte count")
        `TB_CHECK_EQ(m_axis_tkeep, 8'hff, "SPEC tkeep")

        `TB_PASS("tb_spectral_packetizer")
    end

endmodule
