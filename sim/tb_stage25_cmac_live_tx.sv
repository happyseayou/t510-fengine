`include "tb_common.svh"

module tb_stage25_cmac_live_tx;

    logic s_clk = 1'b0;
    logic m_clk = 1'b0;
    logic s_rst_n = 1'b0;
    logic m_rst_n = 1'b0;
    logic s_clear = 1'b0;
    logic mux_clear = 1'b0;
    logic [63:0] s_tdata = 64'd0;
    logic [7:0]  s_tkeep = 8'hff;
    logic        s_tvalid = 1'b0;
    logic        s_tlast = 1'b0;
    wire         s_tready;
    wire [511:0] time_tdata;
    wire [63:0]  time_tkeep;
    wire         time_tvalid;
    wire         time_tlast;
    wire         time_tready;
    wire [31:0] fifo_level_words;
    wire [31:0] input_frame_count;
    wire [31:0] output_frame_count;
    wire [31:0] backpressure_cycles;
    wire fifo_full;
    wire fifo_empty;

    logic select_time_live = 1'b0;
    logic select_spec_live = 1'b0;
    logic [511:0] heartbeat_tdata = 512'h0123;
    logic [63:0]  heartbeat_tkeep = 64'hffff_ffff_ffff_ffff;
    logic         heartbeat_tvalid = 1'b0;
    logic         heartbeat_tlast = 1'b1;
    wire          heartbeat_tready;
    logic [511:0] spec_tdata = 512'hfedc_ba98_7654_3210;
    logic [63:0]  spec_tkeep = 64'h0000_0000_0000_00ff;
    logic         spec_tvalid = 1'b0;
    logic         spec_tlast = 1'b1;
    wire          spec_tready;
    wire [511:0] m_tdata;
    wire [63:0]  m_tkeep;
    wire         m_tvalid;
    wire         m_tlast;
    logic        m_tready = 1'b1;
    wire [31:0] status;

    always #5 s_clk = ~s_clk;
    always #3 m_clk = ~m_clk;

    axis64_to_cmac512_async dut_bridge (
        .s_clk(s_clk),
        .s_rst_n(s_rst_n),
        .s_clear(s_clear),
        .s_axis_tdata(s_tdata),
        .s_axis_tkeep(s_tkeep),
        .s_axis_tvalid(s_tvalid),
        .s_axis_tlast(s_tlast),
        .s_axis_tready(s_tready),
        .m_clk(m_clk),
        .m_rst_n(m_rst_n),
        .m_axis_tdata(time_tdata),
        .m_axis_tkeep(time_tkeep),
        .m_axis_tvalid(time_tvalid),
        .m_axis_tlast(time_tlast),
        .m_axis_tready(time_tready),
        .fifo_level_words(fifo_level_words),
        .input_frame_count(input_frame_count),
        .output_frame_count(output_frame_count),
        .backpressure_cycles(backpressure_cycles),
        .fifo_full(fifo_full),
        .fifo_empty(fifo_empty)
    );

    cmac_tx_source_mux dut_mux (
        .clk(m_clk),
        .rst_n(m_rst_n),
        .clear(mux_clear),
        .select_time_live(select_time_live),
        .select_spec_live(select_spec_live),
        .heartbeat_tdata(heartbeat_tdata),
        .heartbeat_tkeep(heartbeat_tkeep),
        .heartbeat_tvalid(heartbeat_tvalid),
        .heartbeat_tlast(heartbeat_tlast),
        .heartbeat_tready(heartbeat_tready),
        .time_tdata(time_tdata),
        .time_tkeep(time_tkeep),
        .time_tvalid(time_tvalid),
        .time_tlast(time_tlast),
        .time_tready(time_tready),
        .spec_tdata(spec_tdata),
        .spec_tkeep(spec_tkeep),
        .spec_tvalid(spec_tvalid),
        .spec_tlast(spec_tlast),
        .spec_tready(spec_tready),
        .m_axis_tdata(m_tdata),
        .m_axis_tkeep(m_tkeep),
        .m_axis_tvalid(m_tvalid),
        .m_axis_tlast(m_tlast),
        .m_axis_tready(m_tready),
        .status(status)
    );

    task automatic send_word(input [63:0] data, input [7:0] keep, input bit last);
        begin
            while (!s_tready) begin
                @(posedge s_clk);
            end
            @(posedge s_clk);
            s_tdata <= data;
            s_tkeep <= keep;
            s_tlast <= last;
            s_tvalid <= 1'b1;
            @(posedge s_clk);
            while (!s_tready) begin
                @(posedge s_clk);
            end
            s_tvalid <= 1'b0;
            s_tlast <= 1'b0;
            s_tkeep <= 8'hff;
        end
    endtask

    task automatic wait_for_m_axis;
        integer timeout;
        begin
            timeout = 0;
            while (!m_tvalid && timeout < 200) begin
                @(posedge m_clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(m_tvalid, "CMAC mux output valid")
        end
    endtask

    task automatic consume_m_axis_beat;
        begin
            m_tready = 1'b1;
            do begin
                @(posedge m_clk);
            end while (!m_tvalid);
            m_tready = 1'b0;
            @(posedge m_clk);
        end
    endtask

    initial begin
        repeat (8) @(posedge s_clk);
        s_rst_n = 1'b1;
        m_rst_n = 1'b1;
        repeat (8) @(posedge m_clk);

        heartbeat_tvalid = 1'b1;
        wait_for_m_axis();
        `TB_CHECK_EQ(m_tdata, heartbeat_tdata, "heartbeat selected by default")
        `TB_CHECK_EQ(m_tkeep, heartbeat_tkeep, "heartbeat tkeep")
        `TB_CHECK(m_tlast, "heartbeat single-beat tlast")
        @(posedge m_clk);
        heartbeat_tvalid = 1'b0;

        repeat (2) @(posedge m_clk);
        select_spec_live = 1'b1;
        spec_tvalid = 1'b1;
        wait_for_m_axis();
        `TB_CHECK_EQ(m_tdata, spec_tdata, "SPEC selected when live")
        `TB_CHECK_EQ(m_tkeep, spec_tkeep, "SPEC tkeep")
        `TB_CHECK(m_tlast, "SPEC single-beat tlast")
        @(posedge m_clk);
        spec_tvalid = 1'b0;
        select_spec_live = 1'b0;

        m_tready = 1'b0;
        select_time_live = 1'b1;
        repeat (4) @(posedge m_clk);
        send_word(64'h0706_0504_0302_0100, 8'hff, 1'b0);
        send_word(64'h1716_1514_1312_1110, 8'hff, 1'b0);
        send_word(64'h2726_2524_2322_2120, 8'hff, 1'b0);
        send_word(64'h3736_3534_3332_3130, 8'hff, 1'b0);
        send_word(64'h4746_4544_4342_4140, 8'hff, 1'b0);
        send_word(64'h5756_5554_5352_5150, 8'hff, 1'b0);
        send_word(64'h6766_6564_6362_6160, 8'hff, 1'b0);
        send_word(64'h7776_7574_7372_7170, 8'hff, 1'b0);
        repeat (20) @(posedge m_clk);
        `TB_CHECK(!m_tvalid, "TIME bridge waits for complete frame before CMAC output")
        send_word(64'h8786_8584_8382_8180, 8'hff, 1'b0);
        send_word(64'h9796_9594_9392_9190, 8'h3f, 1'b1);

        wait_for_m_axis();
        `TB_CHECK_EQ(m_tdata[63:0], 64'h0706_0504_0302_0100, "TIME lane0 word")
        `TB_CHECK_EQ(m_tdata[511:448], 64'h7776_7574_7372_7170, "TIME lane7 word")
        `TB_CHECK_EQ(m_tkeep, 64'hffff_ffff_ffff_ffff, "TIME first 512b keep")
        `TB_CHECK(!m_tlast, "TIME first 512b beat is not last")

        select_time_live = 1'b0;
        select_spec_live = 1'b1;
        spec_tvalid = 1'b1;
        repeat (4) @(posedge m_clk);
        `TB_CHECK(!spec_tready, "locked TIME frame blocks SPEC before clear")
        mux_clear = 1'b1;
        @(posedge m_clk);
        mux_clear = 1'b0;
        wait_for_m_axis();
        `TB_CHECK_EQ(m_tdata, spec_tdata, "mux clear unlocks stale TIME frame and selects SPEC")
        `TB_CHECK_EQ(m_tkeep, spec_tkeep, "SPEC tkeep after mux clear")
        `TB_CHECK(m_tlast, "SPEC single-beat tlast after mux clear")
        @(posedge m_clk);
        spec_tvalid = 1'b0;
        select_spec_live = 1'b0;

        select_time_live = 1'b1;
        consume_m_axis_beat();

        wait_for_m_axis();
        `TB_CHECK_EQ(m_tdata[63:0], 64'h8786_8584_8382_8180, "TIME tail lane0")
        `TB_CHECK_EQ(m_tdata[127:64], 64'h9796_9594_9392_9190, "TIME tail lane1")
        `TB_CHECK_EQ(m_tkeep, 64'h0000_0000_0000_3fff, "TIME partial keep")
        `TB_CHECK(m_tlast, "TIME tail tlast")
        consume_m_axis_beat();

        `TB_CHECK_EQ(input_frame_count, 32'd1, "bridge input frame count")
        `TB_CHECK(output_frame_count >= 32'd1, "bridge output frame count")
        `TB_CHECK_EQ(backpressure_cycles, 32'd0, "bridge no backpressure")
        `TB_PASS("tb_stage25_cmac_live_tx")
    end

endmodule
