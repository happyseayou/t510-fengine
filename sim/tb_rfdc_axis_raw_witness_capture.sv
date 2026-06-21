`include "tb_common.svh"

module tb_rfdc_axis_raw_witness_capture;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic arm_pulse = 1'b0;
    logic clear_pulse = 1'b0;
    logic [2:0] channel_select = 3'd3;
    logic [8:0] capture_beats = 9'd4;
    logic [255:0] tdata0 = 256'd0;
    logic [255:0] tdata1 = 256'd0;
    logic [255:0] tdata2 = 256'd0;
    logic [255:0] tdata3 = 256'd0;
    logic [63:0] sample0 = 64'h0000_0001_0000_0200;
    logic tvalid = 1'b0;
    logic [31:0] rfdc_flags = 32'h0000_001f;
    logic [15:0] valid_mask = 16'h00ff;
    logic [9:0] rd_word = 10'd0;

    wire [31:0] rd_data;
    wire armed;
    wire valid;
    wire capturing;
    wire overflow;
    wire tvalid_seen;
    wire [8:0] beat_count;
    wire [2:0] captured_channel;
    wire [63:0] captured_sample0;
    wire [31:0] captured_rfdc_flags;
    wire [15:0] captured_valid_mask;

    always #5 clk = ~clk;

    rfdc_axis_raw_witness_capture #(
        .CAPTURE_BEATS(256)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(clk),
        .ctrl_rst_n(rst_n),
        .arm_pulse_ctrl(arm_pulse),
        .clear_pulse_ctrl(clear_pulse),
        .channel_select_ctrl(channel_select),
        .capture_beats_ctrl(capture_beats),
        .s_axis_adc_tdata0(tdata0),
        .s_axis_adc_tdata1(tdata1),
        .s_axis_adc_tdata2(tdata2),
        .s_axis_adc_tdata3(tdata3),
        .s_axis_adc_sample0(sample0),
        .s_axis_adc_tvalid(tvalid),
        .rfdc_status_flags(rfdc_flags),
        .rfdc_current_valid_mask(valid_mask),
        .ctrl_rd_word(rd_word),
        .ctrl_rd_data(rd_data),
        .ctrl_armed(armed),
        .ctrl_valid(valid),
        .ctrl_capturing(capturing),
        .ctrl_overflow(overflow),
        .ctrl_tvalid_seen(tvalid_seen),
        .ctrl_beat_count(beat_count),
        .ctrl_channel_select(captured_channel),
        .ctrl_sample0(captured_sample0),
        .ctrl_rfdc_flags(captured_rfdc_flags),
        .ctrl_valid_mask(captured_valid_mask)
    );

    function automatic [31:0] complex_word(input integer beat, input integer lane, input integer ch);
        reg [15:0] i_sample;
        reg [15:0] q_sample;
        begin
            i_sample = 16'h1000 + beat[15:0] * 16'h0100 + lane[15:0] * 16'h0010 + ch[15:0];
            q_sample = 16'h5000 + beat[15:0] * 16'h0100 + lane[15:0] * 16'h0010 + ch[15:0];
            complex_word = {q_sample, i_sample};
        end
    endfunction

    function automatic [255:0] make_lane_bus(input integer beat, input integer lane);
        begin
            make_lane_bus = {
                complex_word(beat, lane, 7),
                complex_word(beat, lane, 6),
                complex_word(beat, lane, 5),
                complex_word(beat, lane, 4),
                complex_word(beat, lane, 3),
                complex_word(beat, lane, 2),
                complex_word(beat, lane, 1),
                complex_word(beat, lane, 0)
            };
        end
    endfunction

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            arm_pulse = 1'b0;
            clear_pulse = 1'b0;
            tvalid = 1'b0;
            repeat (6) @(posedge clk);
            rst_n = 1'b1;
            repeat (6) @(posedge clk);
        end
    endtask

    task automatic pulse_arm;
        begin
            @(posedge clk);
            arm_pulse <= 1'b1;
            @(posedge clk);
            arm_pulse <= 1'b0;
            repeat (6) @(posedge clk);
        end
    endtask

    task automatic pulse_clear;
        begin
            @(posedge clk);
            clear_pulse <= 1'b1;
            @(posedge clk);
            clear_pulse <= 1'b0;
            repeat (6) @(posedge clk);
        end
    endtask

    task automatic wait_valid;
        integer timeout;
        begin
            timeout = 0;
            while (!valid && timeout < 100) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(valid, "RFDC AXIS raw witness capture became valid")
        end
    endtask

    task automatic wait_invalid;
        integer timeout;
        begin
            timeout = 0;
            while (valid && timeout < 100) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(!valid, "RFDC AXIS raw witness valid cleared")
        end
    endtask

    task automatic read_lane(input integer beat, input integer lane);
        begin
            @(negedge clk);
            rd_word = beat * 4 + lane;
            @(posedge clk);
            #1;
            `TB_CHECK_EQ(rd_data, complex_word(beat, lane, 3), "RFDC AXIS raw witness buffer lane")
        end
    endtask

    integer beat;
    initial begin
        reset_dut();

        pulse_arm();
        @(negedge clk);
        tvalid = 1'b1;
        for (beat = 0; beat < 4; beat = beat + 1) begin
            tdata0 = make_lane_bus(beat, 0);
            tdata1 = make_lane_bus(beat, 1);
            tdata2 = make_lane_bus(beat, 2);
            tdata3 = make_lane_bus(beat, 3);
            @(posedge clk);
            @(negedge clk);
        end
        tvalid = 1'b0;

        wait_valid();
        `TB_CHECK(!capturing, "RFDC AXIS raw witness no longer capturing")
        `TB_CHECK(!overflow, "RFDC AXIS raw witness no overflow")
        `TB_CHECK(tvalid_seen, "RFDC AXIS raw witness saw TVALID")
        `TB_CHECK_EQ(beat_count, 9'd4, "RFDC AXIS raw witness beat count")
        `TB_CHECK_EQ(captured_channel, 3'd3, "RFDC AXIS raw witness selected channel")
        `TB_CHECK_EQ(captured_sample0, 64'h0000_0001_0000_0200, "RFDC AXIS raw witness sample0")
        `TB_CHECK_EQ(captured_rfdc_flags, 32'h0000_001f, "RFDC AXIS raw witness flags")
        `TB_CHECK_EQ(captured_valid_mask, 16'h00ff, "RFDC AXIS raw witness valid mask")

        read_lane(0, 0);
        read_lane(0, 1);
        read_lane(0, 2);
        read_lane(0, 3);
        read_lane(3, 0);
        read_lane(3, 3);

        pulse_clear();
        wait_invalid();

        `TB_PASS("tb_rfdc_axis_raw_witness_capture")
    end

endmodule
