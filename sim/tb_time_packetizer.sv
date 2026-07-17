`include "tb_common.svh"

module tb_time_packetizer;

    localparam integer WORDS_PER_PACKET = 16 + (256 * 4);
    localparam integer PACKETS = 2;
    localparam integer CAPTURE_WORDS = WORDS_PER_PACKET * PACKETS;
    localparam integer INPUT_BEATS = PACKETS * 256;
    localparam integer INTERVAL_INPUT_BEATS = 4096;
    localparam integer LOW_RATE_INTERVAL_BEATS = 2048;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b0;
    logic stream_reset = 1'b0;
    logic [31:0] packet_interval_beats = 32'd0;
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
    wire [31:0]   dropped_count;
    wire [31:0]   udp_byte_count;
    wire [31:0]   seq_no_debug;
    wire [63:0]   sample0_debug;
    wire [63:0]   frame_id_debug;

    logic [63:0] captured [0:CAPTURE_WORDS-1];
    integer out_count = 0;
    integer last_count = 0;
    integer last_index = -1;
    integer beat_idx = 0;
    integer accept_count = 0;
    logic [255:0] accepted [0:INTERVAL_INPUT_BEATS-1];

    always #5 clk = ~clk;

    function automatic [63:0] sample_word(input integer beat, input integer subword);
        begin
            sample_word = 64'h1000_0000_0000_0000 + ((beat * 4) + subword);
        end
    endfunction

    function automatic [63:0] beat_sample0(input integer beat);
        begin
            beat_sample0 = 64'h0000_0001_0000_0000 + (beat * 4);
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

    time_packetizer dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .stream_reset(stream_reset),
        .board_id(16'h00aa),
        .global_input0(16'h0055),
        .epoch_mode(16'd1),
        .packet_flags(16'h000a),
        .unix_seconds(64'h1122_3344_5566_7788),
        .pps_count(64'h0000_0000_0000_0123),
        .sync_generation(64'h1),
        .sync_observation_tag(64'h2),
        .sync_metadata(64'h3),
        .sync_status(64'h4),
        .quant_mode(16'd0),
        .scale_mode(16'd0),
        .scale_id(32'h1234_5678),
        .time_payload_nsamp(16'd256),
        .packet_interval_beats(packet_interval_beats),
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
        .dropped_count(dropped_count),
        .udp_byte_count(udp_byte_count),
        .seq_no_debug(seq_no_debug),
        .sample0_debug(sample0_debug),
        .frame_id_debug(frame_id_debug)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            beat_idx <= 0;
            accept_count <= 0;
            s_axis_tdata <= make_sample(0);
            s_axis_sample0 <= beat_sample0(0);
        end else begin
            if (s_axis_tvalid && s_axis_tready && accept_count < INTERVAL_INPUT_BEATS) begin
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
            while ((last_count < expected_packets) && (timeout < 6000)) begin
                @(posedge clk);
                #1;
                timeout = timeout + 1;
            end
            `TB_CHECK(last_count == expected_packets, "TIME packetizer timeout")
        end
    endtask

    task automatic check_header(
        input integer      base,
        input logic [31:0] seq,
        input logic [63:0] sample0,
        input logic [63:0] frame_id
    );
        begin
            `TB_CHECK_EQ(captured[base + 0], 64'h5435_3130_0003_0080, "TIME v3 header word 0")
            `TB_CHECK_EQ(captured[base + 1], 64'h00aa_0001_0001_000a, "TIME stream identity")
            `TB_CHECK_EQ(captured[base + 2], 64'h1122_3344_5566_7788, "TIME unix seconds")
            `TB_CHECK_EQ(captured[base + 3], 64'h0000_0000_0000_0123, "TIME pps count")
            `TB_CHECK_EQ(captured[base + 4], sample0[63:0], "TIME sample0")
            `TB_CHECK_EQ(captured[base + 5], frame_id[63:0], "TIME frame_id")
            `TB_CHECK_EQ(captured[base + 6], {seq[31:0], 16'd0, 16'h0055}, "TIME seq/input0")
            `TB_CHECK_EQ(captured[base + 7], 64'h0000_0100_0008_0000, "TIME layout")
            `TB_CHECK_EQ(captured[base + 8], 64'h1234_5678_0000_2000, "TIME scale/payload bytes")
            `TB_CHECK_EQ(captured[base + 12], 64'h1, "TIME sync generation")
            `TB_CHECK_EQ(captured[base + 13], 64'h2, "TIME observation tag")
            `TB_CHECK_EQ(captured[base + 14], 64'h3, "TIME sync metadata")
            `TB_CHECK_EQ(captured[base + 15], 64'h4, "TIME sync status")
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
                `TB_CHECK_EQ(captured[base + 16 + idx], accepted[beat][subword*64 +: 64], "TIME payload word")
            end
        end
    endtask

    initial begin
        rst_n = 1'b0;
        packet_interval_beats = 32'd0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        @(negedge clk);
        enable = 1'b1;
        s_axis_tvalid = 1'b1;
        wait_for_packets(PACKETS);
        s_axis_tvalid = 1'b0;
        #1;

        `TB_CHECK_EQ(out_count, CAPTURE_WORDS, "TIME output word count")
        `TB_CHECK_EQ(last_index, CAPTURE_WORDS - 1, "TIME tlast index")
        `TB_CHECK_EQ(accept_count, INPUT_BEATS, "TIME accepted input beat count")
        `TB_CHECK_EQ(m_axis_tkeep, 8'hff, "TIME tkeep")
        check_header(0, 0, beat_sample0(0), 0);
        check_payload(0, 0);
        check_header(WORDS_PER_PACKET, 1, beat_sample0(256), 1);
        check_payload(WORDS_PER_PACKET, 256);
        `TB_CHECK_EQ(packet_count, 32'd2, "TIME packet_count")
        `TB_CHECK_EQ(seq_no_debug, 32'd2, "TIME seq debug")
        `TB_CHECK_EQ(sample0_debug, beat_sample0(256), "TIME sample0 debug")
        `TB_CHECK_EQ(frame_id_debug, 64'd2, "TIME frame debug")
        `TB_CHECK_EQ(udp_byte_count, 32'd16640, "TIME byte count")
        `TB_CHECK_EQ(dropped_count, 32'd0, "TIME dropped count")

        rst_n = 1'b0;
        enable = 1'b0;
        s_axis_tvalid = 1'b0;
        packet_interval_beats = LOW_RATE_INTERVAL_BEATS[31:0];
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);
        @(negedge clk);
        enable = 1'b1;
        s_axis_tvalid = 1'b1;
        wait_for_packets(PACKETS);
        s_axis_tvalid = 1'b0;
        #1;

        check_header(0, 0, beat_sample0(0), 0);
        check_header(WORDS_PER_PACKET, 1, beat_sample0(LOW_RATE_INTERVAL_BEATS), 1);
        check_payload(WORDS_PER_PACKET, LOW_RATE_INTERVAL_BEATS);
        `TB_CHECK(accept_count > LOW_RATE_INTERVAL_BEATS + 256, "TIME interval consumed skipped input beats")
        `TB_CHECK(dropped_count > 32'd0, "TIME interval counted skipped input beats")

        `TB_PASS("tb_time_packetizer")
    end

endmodule
