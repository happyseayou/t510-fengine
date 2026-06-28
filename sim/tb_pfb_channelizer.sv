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
    logic enable = 1'b1;
    logic clear = 1'b0;
    logic [15:0] cfg_taps = 16'd0;
    logic [15:0] cfg_fft_shift = 16'h5556;
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
            s_axis_tdata <= make_beat(0);
            s_axis_sample0 <= beat_sample0(0);
        end else if (s_axis_tvalid && s_axis_tready) begin
            beat_idx <= beat_idx + 1;
            s_axis_tdata <= make_beat(beat_idx + 1);
            s_axis_sample0 <= beat_sample0(beat_idx + 1);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            out_packet_idx = out_count / BEATS_PER_SPEC_PACKET;
            out_packet_beat = out_count % BEATS_PER_SPEC_PACKET;
            if (out_count < 8) begin
                `TB_CHECK(m_axis_tdata != make_beat(out_count), "PFB/F-engine output is not raw pass-through")
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

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            s_axis_tvalid = 1'b0;
            clear = 1'b0;
            repeat (6) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
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

    initial begin
        reset_dut();
        repeat (4) @(posedge clk);

        `TB_CHECK(status[0], "PFB enabled status bit")
        `TB_CHECK(status[1], "PFB config valid status bit")
        `TB_CHECK(status[5], "FFT-only science-valid gate reflects configured XFFT backend")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[31:8], 24'h555556, "PFB XFFT channel 0 scaling schedule")
        `TB_CHECK_EQ(dut.u_feng_channelizer_4096.xfft_config_tdata[199:176], 24'h555556, "PFB XFFT channel 7 scaling schedule")
        `TB_CHECK_EQ(packet_chan0, 32'd0, "PFB packet chan0")
        `TB_CHECK_EQ(packet_chan_count, 16'd256, "FFT-only packet channel count")
        `TB_CHECK_EQ(packet_time_count, 16'd1, "FFT-only packet time count")

        @(negedge clk);
        s_axis_tvalid = 1'b1;
        wait_for_outputs(OUTPUT_BEATS * OUTPUT_TILES);
        s_axis_tvalid = 1'b0;
        repeat (3) @(posedge clk);

        `TB_CHECK_EQ(frame_count, 32'd2, "FFT-only frame count after two full 4096-bin F-engine tiles")
        `TB_CHECK_EQ(overflow_count, 32'd0, "PFB overflow count")
        `TB_CHECK(peak_chan < 32'd4096, "PFB peak channel stays inside full F-engine band")
        `TB_CHECK(peak_power > 32'd0, "PFB peak power rises")

        @(negedge clk);
        clear = 1'b1;
        @(negedge clk);
        clear = 1'b0;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(frame_count, 32'd0, "PFB clear resets frame count")
        `TB_CHECK_EQ(peak_power, 32'd0, "PFB clear resets peak power")

        cfg_time_count = 16'd3;
        repeat (2) @(posedge clk);
        `TB_CHECK(!status[1], "PFB invalid window clears config_valid")
        `TB_CHECK(!s_axis_tready, "PFB invalid window deasserts ready")

        `TB_PASS("tb_pfb_channelizer")
    end

endmodule
