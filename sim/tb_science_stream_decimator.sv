`include "tb_common.svh"

module tb_science_stream_decimator;

    localparam integer DATA_W = 64;
    localparam integer USER_W = 8;
    localparam integer SAMPLE0_W = 16;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic enable = 1'b1;
    logic [1:0] bandwidth_mode = 2'd1;
    logic [DATA_W-1:0] s_axis_tdata = {DATA_W{1'b0}};
    logic [USER_W-1:0] s_axis_tuser = {USER_W{1'b0}};
    logic [SAMPLE0_W-1:0] s_axis_sample0 = {SAMPLE0_W{1'b0}};
    logic s_axis_tvalid = 1'b0;
    logic s_axis_tlast = 1'b0;
    wire s_axis_tready;
    wire [DATA_W-1:0] m_axis_tdata;
    wire [USER_W-1:0] m_axis_tuser;
    wire [SAMPLE0_W-1:0] m_axis_sample0;
    wire m_axis_tvalid;
    wire m_axis_tlast;
    logic m_axis_tready = 1'b1;
    wire [31:0] selected_beat_count;
    wire [31:0] discarded_beat_count;
    wire [31:0] dropped_selected_count;

    integer output_count = 0;
    integer last_output = -1;

    always #5 clk = ~clk;

    science_stream_decimator #(
        .DATA_W(DATA_W),
        .USER_W(USER_W),
        .SAMPLE0_W(SAMPLE0_W)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
        .enable(enable),
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
        .selected_beat_count(selected_beat_count),
        .discarded_beat_count(discarded_beat_count),
        .dropped_selected_count(dropped_selected_count)
    );

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            output_count <= 0;
            last_output <= -1;
        end else if (m_axis_tvalid && m_axis_tready) begin
            output_count <= output_count + 1;
            last_output <= m_axis_tdata[31:0];
        end
    end

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            clear = 1'b0;
            enable = 1'b1;
            s_axis_tvalid = 1'b0;
            m_axis_tready = 1'b1;
            output_count = 0;
            last_output = -1;
            repeat (5) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic clear_counters;
        begin
            @(negedge clk);
            clear = 1'b1;
            @(negedge clk);
            clear = 1'b0;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic send_beats(input integer count);
        integer idx;
        begin
            for (idx = 0; idx < count; idx = idx + 1) begin
                @(negedge clk);
                s_axis_tdata = {{(DATA_W-32){1'b0}}, idx[31:0]};
                s_axis_tuser = idx[USER_W-1:0];
                s_axis_sample0 = idx[SAMPLE0_W-1:0];
                s_axis_tlast = (idx == count - 1);
                s_axis_tvalid = 1'b1;
                #1;
                `TB_CHECK(s_axis_tready, "decimator never backpressures input")
                @(posedge clk);
            end
            @(negedge clk);
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
            repeat (3) @(posedge clk);
        end
    endtask

    initial begin
        reset_dut();

        bandwidth_mode = 2'd1;
        send_beats(64);
        `TB_CHECK_EQ(selected_beat_count, 32'd2, "100MHz selected beat count")
        `TB_CHECK_EQ(discarded_beat_count, 32'd62, "100MHz discarded beat count")
        `TB_CHECK_EQ(dropped_selected_count, 32'd0, "100MHz no selected drop")
        `TB_CHECK_EQ(output_count, 2, "100MHz output count")
        `TB_CHECK_EQ(last_output, 32, "100MHz selected cadence")

        clear_counters();
        bandwidth_mode = 2'd0;
        send_beats(16);
        `TB_CHECK_EQ(selected_beat_count, 32'd4, "20MHz selected beat count")
        `TB_CHECK_EQ(discarded_beat_count, 32'd12, "20MHz discarded beat count")
        `TB_CHECK_EQ(output_count, 4, "20MHz output count")
        `TB_CHECK_EQ(last_output, 12, "20MHz selected cadence")

        clear_counters();
        bandwidth_mode = 2'd2;
        send_beats(128);
        `TB_CHECK_EQ(selected_beat_count, 32'd2, "200MHz selected beat count")
        `TB_CHECK_EQ(discarded_beat_count, 32'd126, "200MHz discarded beat count")
        `TB_CHECK_EQ(output_count, 2, "200MHz output count")
        `TB_CHECK_EQ(last_output, 64, "200MHz selected cadence")

        clear_counters();
        bandwidth_mode = 2'd1;
        m_axis_tready = 1'b0;
        send_beats(33);
        `TB_CHECK_EQ(selected_beat_count, 32'd1, "first selected beat captured before backpressure")
        `TB_CHECK_EQ(dropped_selected_count, 32'd1, "second selected beat drops under backpressure")
        `TB_CHECK(m_axis_tvalid, "first selected beat held while downstream blocks")
        @(negedge clk);
        m_axis_tready = 1'b1;
        repeat (2) @(posedge clk);
        `TB_CHECK_EQ(output_count, 1, "held selected beat drains after ready")

        `TB_PASS("tb_science_stream_decimator")
    end

endmodule
