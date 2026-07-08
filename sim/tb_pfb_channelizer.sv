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
    logic [15:0] cfg_taps = 16'd0;
    logic [15:0] cfg_fft_shift = 16'h0556;
    logic [31:0] cfg_chan0 = 32'd0;
    logic [15:0] cfg_chan_count = 16'd256;
    logic [15:0] cfg_time_count = 16'd1;
    logic [DATA_W-1:0] s_axis_tdata = {DATA_W{1'b0}};
    logic [63:0]  s_axis_sample0 = 64'd0;
    logic         s_axis_tvalid = 1'b0;
    wire          s_axis_tready;
    wire [DATA_W-1:0]  m_axis_tdata;
    wire [63:0]   m_axis_sample0;
    wire          m_axis_tvalid;
    logic         m_axis_tready = 1'b1;
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
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    logic [12:0] xfft_frame_cell_count = 13'd0;
    logic        xfft_frame_active = 1'b0;
    integer      xfft_frame_gap_count = 0;
`endif

    always #5 clk = ~clk;

    function automatic [31:0] lane_word(input integer sample_idx, input integer lane);
        logic [15:0] i_word;
        logic [15:0] q_word;
        begin
            i_word = sample_idx + lane;
            q_word = sample_idx + lane + 16;
            lane_word = {q_word, i_word};
        end
    endfunction

    function automatic [255:0] make_cell(input integer sample_idx);
        integer lane;
        logic [255:0] value;
        begin
            value = 256'd0;
            for (lane = 0; lane < 8; lane = lane + 1) begin
                value[lane*32 +: 32] = lane_word(sample_idx, lane);
            end
            make_cell = value;
        end
    endfunction

    function automatic [DATA_W-1:0] make_beat(input integer beat);
        integer cell_idx;
        logic [DATA_W-1:0] value;
        begin
            value = {DATA_W{1'b0}};
            for (cell_idx = 0; cell_idx < CELLS_PER_BEAT; cell_idx = cell_idx + 1) begin
                value[cell_idx*256 +: 256] = make_cell((beat * CELLS_PER_BEAT) + cell_idx);
            end
            make_beat = value;
        end
    endfunction

    function automatic [63:0] beat_sample0(input integer beat);
        begin
            beat_sample0 = 64'h0000_0003_0000_0000 + (beat * 4);
        end
    endfunction

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
        .s_axis_tdata(s_axis_tdata),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .status(status),
        .frame_count(frame_count),
        .overflow_count(overflow_count),
        .peak_chan(peak_chan),
        .peak_power(peak_power),
        .packet_chan0(packet_chan0),
        .packet_chan_count(packet_chan_count),
        .packet_time_count(packet_time_count)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            beat_idx <= 0;
            accepted_input_beats <= 0;
            s_axis_tdata <= zero_input_mode ? {DATA_W{1'b0}} : make_beat(0);
            s_axis_sample0 <= beat_sample0(0);
        end else if (s_axis_tvalid && s_axis_tready) begin
            beat_idx <= beat_idx + 1;
            accepted_input_beats <= accepted_input_beats + 1;
            s_axis_tdata <= zero_input_mode ? {DATA_W{1'b0}} : make_beat(beat_idx + 1);
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
            end else begin
                if (out_count < 8) begin
                    `TB_CHECK(m_axis_tdata != make_beat(out_count), "PFB/F-engine output is not raw pass-through")
                end
            end
            `TB_CHECK_EQ(
                m_axis_sample0,
                beat_sample0((out_packet_idx / SPEC_BLOCKS) * INPUT_BEATS_PER_FFT_FRAME),
                "PFB packet sample0 is first FFT frame sample"
            )
            if (out_packet_beat == 0) begin
                `TB_CHECK_EQ(packet_chan0, (out_packet_idx % SPEC_BLOCKS) * 256, "FFT-only packet chan0 block sweep")
                `TB_CHECK_EQ(packet_chan_count, 16'd256, "FFT-only packet channel count during sweep")
                `TB_CHECK_EQ(packet_time_count, 16'd1, "FFT-only packet time count during sweep")
            end
            out_count <= out_count + 1;
        end
    end

`ifdef T510_STAGE27H_PRODUCTION_ONLY
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
`endif

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            s_axis_tvalid = 1'b0;
            clear = 1'b0;
            repeat (6) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
            s_axis_tdata = zero_input_mode ? {DATA_W{1'b0}} : make_beat(0);
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
`ifdef T510_STAGE27H_PRODUCTION_ONLY
            `TB_CHECK(timeout <= (expected * (CELLS_PER_BEAT + 1)) + 64, "FFT-only production input frame buffer keeps up with 1024b input beats")
`endif
        end
    endtask

    initial begin
        reset_dut();
        repeat (4) @(posedge clk);

        `TB_CHECK(!status[0], "PFB enabled status bit stays low before streaming enable")
        `TB_CHECK(status[1], "PFB config valid status bit")
        `TB_CHECK(status[8], "FFT-only status bit")
        `TB_CHECK(status[9], "XFFT config completes while stream enable is low")
        `TB_CHECK_EQ(status[23:16], 8'hff, "XFFT lane config done mask")
        `TB_CHECK(status[5], "FFT-only science-valid gate reflects configured XFFT backend")
`ifdef T510_STAGE27H_PRODUCTION_ONLY
`ifndef T510_SIM_FFT_MODEL
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[0].lane_config_tdata[0], 1'b1, "lane0 XFFT forward config")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[0].lane_config_tdata[12:1], cfg_fft_shift[11:0], "lane0 XFFT scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[7].lane_config_tdata[0], 1'b1, "lane7 XFFT forward config")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.u_fengine_xfft_4096.gen_lane_xfft[7].lane_config_tdata[12:1], cfg_fft_shift[11:0], "lane7 XFFT scaling schedule")
`else
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[19:8], 12'h556, "PFB XFFT channel 0 12-bit scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[103:92], 12'h556, "PFB XFFT channel 7 12-bit scaling schedule")
`endif
`else
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[31:8], 24'h550556, "PFB XFFT channel 0 legacy scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[199:176], 24'h550556, "PFB XFFT channel 7 legacy scaling schedule")
`endif
        `TB_CHECK_EQ(packet_chan0, 32'd0, "PFB packet chan0")
        `TB_CHECK_EQ(packet_chan_count, 16'd256, "FFT-only packet channel count")
        `TB_CHECK_EQ(packet_time_count, 16'd1, "FFT-only packet time count")

        @(negedge clk);
        enable = 1'b1;
        repeat (2) @(posedge clk);
        `TB_CHECK(status[0], "PFB enabled status bit after streaming enable")

        @(negedge clk);
        s_axis_tvalid = 1'b1;
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME * OUTPUT_TILES);
`endif
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        wait_for_outputs(OUTPUT_BEATS * OUTPUT_TILES);
        repeat (3) @(posedge clk);

        `TB_CHECK_EQ(frame_count, 32'd2, "FFT-only frame count after two full 4096-bin F-engine tiles")
        `TB_CHECK_EQ(overflow_count, 32'd0, "PFB overflow count")
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        `TB_CHECK_EQ(xfft_frame_gap_count, 0, "FFT-only XFFT input frame has zero internal gaps")
`endif
        `TB_CHECK(peak_chan < 32'd4096, "PFB peak channel stays inside full F-engine band")
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        `TB_CHECK_EQ(peak_power, 32'd0, "production FFT-only removes high-speed peak scan")
`else
        `TB_CHECK(peak_power > 32'd0, "PFB peak power rises")
`endif

        @(negedge clk);
        clear = 1'b1;
        @(negedge clk);
        clear = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(frame_count, 32'd0, "PFB clear resets frame count")
        `TB_CHECK_EQ(peak_power, 32'd0, "PFB clear resets peak power")

        test_case = 1;
        zero_input_mode = 1'b1;
        reset_dut();
        repeat (4) @(posedge clk);
        @(negedge clk);
        enable = 1'b1;
        repeat (2) @(posedge clk);
        @(negedge clk);
        s_axis_tvalid = 1'b1;
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        wait_for_accepted_inputs(INPUT_BEATS_PER_FFT_FRAME);
`endif
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        wait_for_outputs(OUTPUT_BEATS);
        repeat (3) @(posedge clk);
        `TB_CHECK_EQ(frame_count, 32'd1, "FFT-only zero input frame count")
        `TB_CHECK_EQ(overflow_count, 32'd0, "FFT-only zero input no overflow")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_event_count, 32'd0, "FFT-only zero input no XFFT event")
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        `TB_CHECK_EQ(xfft_frame_gap_count, 0, "FFT-only zero input XFFT frame has zero internal gaps")
`endif

        cfg_time_count = 16'd3;
        repeat (2) @(posedge clk);
        `TB_CHECK(!status[1], "PFB invalid window clears config_valid")
        `TB_CHECK(!s_axis_tready, "PFB invalid window deasserts ready")

        `TB_PASS("tb_pfb_channelizer")
    end

endmodule
