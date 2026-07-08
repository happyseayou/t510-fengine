`include "tb_common.svh"

module tb_science_rate_selector;

    localparam integer NINPUT = 8;
    localparam integer SUBS = 4;
    localparam integer SAMPLE_W = 32;
    localparam integer DATA_W = NINPUT * SUBS * SAMPLE_W;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [1:0] bandwidth_mode = 2'd2;
    logic [DATA_W-1:0] s_axis_tdata = {DATA_W{1'b0}};
    logic [31:0] s_axis_tuser = 32'd0;
    logic [63:0] s_axis_sample0 = 64'd0;
    logic s_axis_tvalid = 1'b0;
    logic s_axis_tlast = 1'b0;
    wire s_axis_tready;
    wire [DATA_W-1:0] m_axis_tdata;
    wire [31:0] m_axis_tuser;
    wire [63:0] m_axis_sample0;
    wire m_axis_tvalid;
    wire m_axis_tlast;
    logic m_axis_tready = 1'b1;
    wire aa100_active;
    wire aa100_primed;
    wire [31:0] aa100_coeff_version;
    wire [31:0] output_beat_count;
    wire [31:0] dropped_beat_count;

    integer in_beat = 0;
    integer out_count = 0;
    integer stalled_in_beat = 0;
    logic [DATA_W-1:0] captured_data [0:15];
    logic [63:0] captured_sample0 [0:15];

    always #5 clk = ~clk;

    function automatic [255:0] make_subsample(input integer beat, input integer sub);
        integer lane;
        logic [255:0] value;
        begin
            value = 256'd0;
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                value[lane*32 +: 32] = 32'h1000_0000 + (beat * 32) + (sub * 8) + lane;
            end
            make_subsample = value;
        end
    endfunction

    function automatic [DATA_W-1:0] make_beat(input integer beat);
        begin
            make_beat = {
                make_subsample(beat, 3),
                make_subsample(beat, 2),
                make_subsample(beat, 1),
                make_subsample(beat, 0)
            };
        end
    endfunction

    function automatic [DATA_W-1:0] expect_decim2(input integer beat0);
        begin
            expect_decim2 = {
                make_subsample(beat0 + 1, 2),
                make_subsample(beat0 + 1, 0),
                make_subsample(beat0, 2),
                make_subsample(beat0, 0)
            };
        end
    endfunction

    function automatic [DATA_W-1:0] expect_decim8(input integer beat0);
        begin
            expect_decim8 = {
                make_subsample(beat0 + 6, 0),
                make_subsample(beat0 + 4, 0),
                make_subsample(beat0 + 2, 0),
                make_subsample(beat0, 0)
            };
        end
    endfunction

    science_rate_selector dut (
        .clk(clk),
        .rst_n(rst_n),
        .bandwidth_mode(bandwidth_mode),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tuser(s_axis_tuser),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tuser(m_axis_tuser),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready),
        .aa100_active(aa100_active),
        .aa100_primed(aa100_primed),
        .aa100_coeff_version(aa100_coeff_version),
        .output_beat_count(output_beat_count),
        .dropped_beat_count(dropped_beat_count)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            in_beat <= 0;
            s_axis_tdata <= make_beat(0);
            s_axis_tuser <= 32'd0;
            s_axis_sample0 <= 64'h1000;
        end else if (s_axis_tvalid && s_axis_tready) begin
            in_beat <= in_beat + 1;
            s_axis_tdata <= make_beat(in_beat + 1);
            s_axis_tuser <= in_beat + 1;
            s_axis_sample0 <= 64'h1000 + ((in_beat + 1) * 4);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_count <= 0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            if (out_count < 16) begin
                captured_data[out_count] <= m_axis_tdata;
                captured_sample0[out_count] <= m_axis_sample0;
            end
            out_count <= out_count + 1;
        end
    end

    task automatic reset_case(input [1:0] mode_value);
        begin
            rst_n = 1'b0;
            bandwidth_mode = mode_value;
            m_axis_tready = 1'b1;
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
            in_beat = 0;
            out_count = 0;
            repeat (5) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic drive_beats(input integer nbeats);
        integer idx;
        begin
            @(negedge clk);
            s_axis_tvalid = 1'b1;
            for (idx = 0; idx < nbeats; idx = idx + 1) begin
                @(posedge clk);
            end
            @(negedge clk);
            s_axis_tvalid = 1'b0;
            repeat (4) @(posedge clk);
        end
    endtask

    initial begin
        reset_case(2'd2);
        drive_beats(4);
        `TB_CHECK_EQ(out_count, 4, "200MHz selector output count")
        `TB_CHECK_EQ(captured_data[0], make_beat(0), "200MHz selector beat0")
        `TB_CHECK_EQ(captured_sample0[0], 64'h1000, "200MHz selector sample0")

        reset_case(2'd1);
        drive_beats(16);
        `TB_CHECK_EQ(out_count, 3, "100MHz selector output count")
        `TB_CHECK_EQ(captured_sample0[0], 64'h1014, "100MHz anti-alias selector first sample0 includes FIR group delay")
        `TB_CHECK_EQ(captured_sample0[1], 64'h101c, "100MHz anti-alias selector second sample0")
        `TB_CHECK_EQ(captured_sample0[2], 64'h1024, "100MHz anti-alias selector third sample0")
        `TB_CHECK_EQ(aa100_active, 1'b1, "100MHz anti-alias active")
        `TB_CHECK_EQ(aa100_primed, 1'b1, "100MHz anti-alias primed")
        `TB_CHECK_EQ(aa100_coeff_version, 32'haa10_0041, "100MHz anti-alias coefficient version")

        reset_case(2'd1);
        @(negedge clk);
        m_axis_tready = 1'b0;
        s_axis_tvalid = 1'b1;
        repeat (24) @(posedge clk);
        #1;
        `TB_CHECK_EQ(s_axis_tready, 1'b0, "100MHz selector backpressures instead of dropping selected output beats")
        `TB_CHECK(in_beat >= 12, "100MHz selector accepts enough input to prime FIR before backpressure")
        `TB_CHECK(dropped_beat_count != 32'd0, "100MHz selector records attempted input during backpressure")
        stalled_in_beat = in_beat;
        repeat (3) @(posedge clk);
        `TB_CHECK_EQ(in_beat, stalled_in_beat, "100MHz selector holds input phase while stalled")
        @(negedge clk);
        m_axis_tready = 1'b1;
        repeat (4) @(posedge clk);
        @(negedge clk);
        s_axis_tvalid = 1'b0;
        repeat (4) @(posedge clk);
        `TB_CHECK_EQ(captured_sample0[0], 64'h1014, "100MHz stalled selector first sample0")
        `TB_CHECK_EQ(captured_sample0[1], 64'h101c, "100MHz stalled selector preserves second sample0 after backpressure")

        reset_case(2'd0);
        m_axis_tready = 1'b1;
        drive_beats(16);
        `TB_CHECK_EQ(out_count, 2, "20MHz selector output count")
        `TB_CHECK_EQ(captured_data[0], expect_decim8(0), "20MHz selector first packed beat")
        `TB_CHECK_EQ(captured_sample0[0], 64'h1000, "20MHz selector sample0")
        `TB_CHECK_EQ(captured_sample0[1], 64'h1020, "20MHz selector second sample0")
        `TB_CHECK_EQ(dropped_beat_count, 32'd0, "selector no drops")

        `TB_PASS("tb_science_rate_selector")
    end

endmodule
