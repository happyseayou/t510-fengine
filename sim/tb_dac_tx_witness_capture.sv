`include "tb_common.svh"

module tb_dac_tx_witness_capture;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic arm_pulse = 1'b0;
    logic clear_pulse = 1'b0;
    logic [8:0] capture_words = 9'd4;
    logic [127:0] s_axis_tdata = 128'd0;
    logic s_axis_tvalid = 1'b0;
    logic s_axis_tready = 1'b1;
    logic [31:0] phase_epoch = 32'd23;
    logic [31:0] phase_acc = 32'h1234_5678;
    logic [31:0] phase_step = 32'h0102_0304;
    logic [31:0] phase0 = 32'h4000_0000;
    logic [31:0] mode = 32'd1;
    logic [9:0] rd_word = 10'd0;
    wire [31:0] rd_data;
    wire armed;
    wire valid;
    wire capturing;
    wire overflow;
    wire tvalid_seen;
    wire tready_seen;
    wire ready_gap_seen;
    wire [8:0] word_count;
    wire [31:0] captured_phase_epoch;
    wire [31:0] captured_phase_acc;
    wire [31:0] captured_phase_step;
    wire [31:0] captured_phase0;
    wire [31:0] captured_mode;
    wire [31:0] ready_gap_count;

    always #5 clk = ~clk;

    dac_tx_witness_capture #(
        .DATA_W(128),
        .CAPTURE_WORDS(256)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(clk),
        .ctrl_rst_n(rst_n),
        .arm_pulse_ctrl(arm_pulse),
        .clear_pulse_ctrl(clear_pulse),
        .capture_words_ctrl(capture_words),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .phase_epoch(phase_epoch),
        .phase_acc(phase_acc),
        .phase_step(phase_step),
        .phase0(phase0),
        .mode(mode),
        .ctrl_rd_word(rd_word),
        .ctrl_rd_data(rd_data),
        .ctrl_armed(armed),
        .ctrl_valid(valid),
        .ctrl_capturing(capturing),
        .ctrl_overflow(overflow),
        .ctrl_tvalid_seen(tvalid_seen),
        .ctrl_tready_seen(tready_seen),
        .ctrl_ready_gap_seen(ready_gap_seen),
        .ctrl_word_count(word_count),
        .ctrl_phase_epoch(captured_phase_epoch),
        .ctrl_phase_acc(captured_phase_acc),
        .ctrl_phase_step(captured_phase_step),
        .ctrl_phase0(captured_phase0),
        .ctrl_mode(captured_mode),
        .ctrl_ready_gap_count(ready_gap_count)
    );

    function automatic [127:0] dac_word(input integer idx);
        begin
            dac_word = {
                32'hd003_0000 + idx[31:0],
                32'hd002_0000 + idx[31:0],
                32'hd001_0000 + idx[31:0],
                32'hd000_0000 + idx[31:0]
            };
        end
    endfunction

    function automatic [31:0] dac_word_lane(input integer idx, input integer lane);
        logic [127:0] word;
        begin
            word = dac_word(idx);
            dac_word_lane = word[lane*32 +: 32];
        end
    endfunction

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            arm_pulse = 1'b0;
            clear_pulse = 1'b0;
            s_axis_tvalid = 1'b0;
            s_axis_tready = 1'b1;
            repeat (6) @(posedge clk);
            rst_n = 1'b1;
            repeat (4) @(posedge clk);
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
            while (!valid && timeout < 80) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(valid, "DAC TX witness capture became valid")
        end
    endtask

    task automatic wait_invalid;
        integer timeout;
        begin
            timeout = 0;
            while (valid && timeout < 80) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(!valid, "DAC TX witness valid cleared")
        end
    endtask

    task automatic read_lane(input integer word_idx, input integer lane);
        begin
            @(negedge clk);
            rd_word = word_idx * 4 + lane;
            @(posedge clk);
            #1;
            `TB_CHECK_EQ(rd_data, dac_word_lane(word_idx, lane), "DAC TX witness buffer lane")
        end
    endtask

    integer idx;
    initial begin
        reset_dut();

        pulse_arm();
        @(negedge clk);
        s_axis_tvalid = 1'b1;
        s_axis_tready = 1'b0;
        s_axis_tdata = dac_word(0);
        @(posedge clk);
        @(negedge clk);
        s_axis_tready = 1'b1;
        for (idx = 0; idx < 4; idx = idx + 1) begin
            s_axis_tdata = dac_word(idx);
            s_axis_tvalid = 1'b1;
            @(posedge clk);
            @(negedge clk);
        end
        s_axis_tvalid = 1'b0;
        s_axis_tdata = 128'd0;

        wait_valid();
        `TB_CHECK(!capturing, "DAC TX witness no longer capturing")
        `TB_CHECK(!overflow, "DAC TX witness no overflow")
        `TB_CHECK(tvalid_seen, "DAC TX witness saw TVALID")
        `TB_CHECK(tready_seen, "DAC TX witness saw TREADY")
        `TB_CHECK(ready_gap_seen, "DAC TX witness saw ready gap")
        `TB_CHECK_EQ(word_count, 9'd4, "DAC TX witness word count")
        `TB_CHECK_EQ(ready_gap_count, 32'd1, "DAC TX witness ready gap count")
        `TB_CHECK_EQ(captured_phase_epoch, 32'd23, "DAC TX witness phase epoch")
        `TB_CHECK_EQ(captured_phase_acc, 32'h1234_5678, "DAC TX witness phase accumulator")
        `TB_CHECK_EQ(captured_phase_step, 32'h0102_0304, "DAC TX witness phase step")
        `TB_CHECK_EQ(captured_phase0, 32'h4000_0000, "DAC TX witness phase0")
        `TB_CHECK_EQ(captured_mode, 32'd1, "DAC TX witness mode")

        read_lane(0, 0);
        read_lane(0, 1);
        read_lane(0, 2);
        read_lane(0, 3);
        read_lane(3, 0);
        read_lane(3, 3);

        pulse_clear();
        wait_invalid();

        `TB_PASS("tb_dac_tx_witness_capture")
    end

endmodule
