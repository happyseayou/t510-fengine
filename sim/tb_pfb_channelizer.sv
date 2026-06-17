`include "tb_common.svh"

module tb_pfb_channelizer;

    localparam integer BEATS = 256;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b1;
    logic clear = 1'b0;
    logic [15:0] cfg_taps = 16'd4;
    logic [15:0] cfg_fft_shift = 16'd0;
    logic [31:0] cfg_chan0 = 32'd128;
    logic [15:0] cfg_chan_count = 16'd64;
    logic [15:0] cfg_time_count = 16'd4;
    logic [255:0] s_axis_tdata = 256'd0;
    logic [63:0]  s_axis_sample0 = 64'd0;
    logic         s_axis_tvalid = 1'b0;
    wire          s_axis_tready;
    wire [255:0]  m_axis_tdata;
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

    always #5 clk = ~clk;

    function automatic [31:0] lane_word(input integer beat, input integer lane);
        logic [15:0] i_word;
        logic [15:0] q_word;
        begin
            i_word = beat + lane;
            q_word = beat + lane + 16;
            lane_word = {q_word, i_word};
        end
    endfunction

    function automatic [255:0] make_beat(input integer beat);
        integer lane;
        logic [255:0] value;
        begin
            value = 256'd0;
            for (lane = 0; lane < 8; lane = lane + 1) begin
                value[lane*32 +: 32] = lane_word(beat, lane);
            end
            make_beat = value;
        end
    endfunction

    function automatic [63:0] beat_sample0(input integer beat);
        begin
            beat_sample0 = 64'h0000_0003_0000_0000 + (beat * 4);
        end
    endfunction

    pfb_channelizer dut (
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
            `TB_CHECK_EQ(m_axis_tdata, make_beat(out_count), "PFB dry-run output order")
            `TB_CHECK_EQ(m_axis_sample0, beat_sample0(out_count), "PFB dry-run sample0 order")
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
            while ((out_count < expected) && (timeout < 1200)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK_EQ(out_count, expected, "PFB dry-run output count")
        end
    endtask

    initial begin
        reset_dut();

        `TB_CHECK(status[0], "PFB enabled status bit")
        `TB_CHECK(status[1], "PFB config valid status bit")
        `TB_CHECK_EQ(packet_chan0, 32'd128, "PFB packet chan0")
        `TB_CHECK_EQ(packet_chan_count, 16'd64, "PFB packet channel count")
        `TB_CHECK_EQ(packet_time_count, 16'd4, "PFB packet time count")

        @(negedge clk);
        s_axis_tvalid = 1'b1;
        wait_for_outputs(BEATS);
        s_axis_tvalid = 1'b0;
        repeat (3) @(posedge clk);

        `TB_CHECK_EQ(frame_count, 32'd1, "PFB frame count after one 64x4 window")
        `TB_CHECK_EQ(overflow_count, 32'd0, "PFB overflow count")
        `TB_CHECK((peak_chan >= 32'd128) && (peak_chan < 32'd192), "PFB peak channel stays inside configured window")
        `TB_CHECK(peak_power > 32'd0, "PFB peak power rises")

        clear = 1'b1;
        @(posedge clk);
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
