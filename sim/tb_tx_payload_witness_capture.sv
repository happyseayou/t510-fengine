`include "tb_common.svh"

module tb_tx_payload_witness_capture;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic arm_pulse = 1'b0;
    logic clear_pulse = 1'b0;
    logic [1:0] stream_filter = 2'd0;
    logic [7:0] capture_words = 8'd128;
    logic [63:0] s_axis_tdata = 64'd0;
    logic s_axis_tvalid = 1'b0;
    logic s_axis_tlast = 1'b0;
    logic s_axis_tready = 1'b1;
    logic [2:0] route_endpoint_id = 3'd0;
    logic [2:0] route_id = 3'd0;
    logic route_is_time = 1'b0;
    logic [7:0] rd_word = 8'd0;
    wire [31:0] rd_data;
    wire armed;
    wire valid;
    wire capturing;
    wire [7:0] word_count;
    wire [15:0] stream_type;
    wire [63:0] sample0;
    wire [63:0] frame_id;
    wire [31:0] seq_no;
    wire [31:0] chan0;
    wire [63:0] layout_word;
    wire [31:0] payload_bytes;
    wire [31:0] route_meta;
    wire [31:0] rfdc_flags;
    wire [63:0] rfdc_sample_count;
    wire [31:0] dac_phase_epoch;
    wire overflow;
    wire filter_mismatch;

    always #5 clk = ~clk;

    tx_payload_witness_capture #(
        .DATA_W(64),
        .CAPTURE_WORDS(128)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(clk),
        .ctrl_rst_n(rst_n),
        .arm_pulse_ctrl(arm_pulse),
        .clear_pulse_ctrl(clear_pulse),
        .data_clear_pulse(1'b0),
        .stream_filter_ctrl(stream_filter),
        .capture_words_ctrl(capture_words),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(s_axis_tready),
        .route_endpoint_id(route_endpoint_id),
        .route_id(route_id),
        .route_is_time(route_is_time),
        .rfdc_status_flags(32'h0000_000f),
        .rfdc_sample_count(64'h0000_0001_0000_0200),
        .dac_phase_epoch(32'd23),
        .ctrl_rd_word(rd_word),
        .ctrl_rd_data(rd_data),
        .ctrl_armed(armed),
        .ctrl_valid(valid),
        .ctrl_capturing(capturing),
        .ctrl_word_count(word_count),
        .ctrl_stream_type(stream_type),
        .ctrl_sample0(sample0),
        .ctrl_frame_id(frame_id),
        .ctrl_seq_no(seq_no),
        .ctrl_chan0(chan0),
        .ctrl_layout_word(layout_word),
        .ctrl_payload_bytes(payload_bytes),
        .ctrl_route_meta(route_meta),
        .ctrl_rfdc_flags(rfdc_flags),
        .ctrl_rfdc_sample_count(rfdc_sample_count),
        .ctrl_dac_phase_epoch(dac_phase_epoch),
        .ctrl_overflow(overflow),
        .ctrl_filter_mismatch(filter_mismatch)
    );

    function automatic [63:0] packet_word(input integer idx, input logic [15:0] stream);
        begin
            case (idx)
                0: packet_word = 64'h5435_3130_0002_0080;
                1: packet_word = {16'h005a, stream, 16'h0001, 16'h000a};
                2: packet_word = 64'h1111_2222_3333_4444;
                3: packet_word = 64'h0000_0000_0000_0007;
                4: packet_word = 64'h0000_0001_0000_0100;
                5: packet_word = 64'h0000_0000_0000_0042;
                6: packet_word = {32'h0000_0011, 32'd64};
                7: packet_word = 64'h0040_0004_0008_0000;
                8: packet_word = 64'h0000_0000_0000_2000;
                default: packet_word = 64'hf00d_0000_0000_0000 + idx;
            endcase
        end
    endfunction

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            arm_pulse = 1'b0;
            clear_pulse = 1'b0;
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
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

    task automatic send_packet(input logic [15:0] stream, input integer words);
        integer idx;
        begin
            for (idx = 0; idx < words; idx = idx + 1) begin
                @(negedge clk);
                s_axis_tdata = packet_word(idx, stream);
                s_axis_tvalid = 1'b1;
                s_axis_tlast = (idx == words - 1);
                @(posedge clk);
            end
            @(negedge clk);
            s_axis_tvalid = 1'b0;
            s_axis_tlast = 1'b0;
            s_axis_tdata = 64'd0;
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
            `TB_CHECK(valid, "payload witness capture became valid")
        end
    endtask

    initial begin
        reset_dut();

        stream_filter = 2'd1;
        route_endpoint_id = 3'd2;
        route_id = 3'd3;
        route_is_time = 1'b0;
        pulse_arm();
        send_packet(16'd0, 32);
        wait_valid();
        `TB_CHECK(!capturing, "payload witness no longer capturing")
        `TB_CHECK(!overflow, "payload witness no overflow")
        `TB_CHECK(!filter_mismatch, "payload witness no filter mismatch")
        `TB_CHECK_EQ(word_count, 8'd32, "payload witness word count")
        `TB_CHECK_EQ(stream_type, 16'd0, "payload witness SPEC stream type")
        `TB_CHECK_EQ(sample0, 64'h0000_0001_0000_0100, "payload witness sample0")
        `TB_CHECK_EQ(frame_id, 64'h0000_0000_0000_0042, "payload witness frame id")
        `TB_CHECK_EQ(seq_no, 32'h0000_0011, "payload witness seq")
        `TB_CHECK_EQ(chan0, 32'd64, "payload witness chan0")
        `TB_CHECK_EQ(layout_word, 64'h0040_0004_0008_0000, "payload witness layout")
        `TB_CHECK_EQ(payload_bytes, 32'd8192, "payload witness payload bytes")
        `TB_CHECK_EQ(route_meta[10:8], 3'd3, "payload witness route id")
        `TB_CHECK_EQ(route_meta[7:5], 3'd2, "payload witness endpoint id")
        `TB_CHECK_EQ(rfdc_flags, 32'h0000_000f, "payload witness RFDC flags")
        `TB_CHECK_EQ(rfdc_sample_count, 64'h0000_0001_0000_0200, "payload witness RFDC sample count")
        `TB_CHECK_EQ(dac_phase_epoch, 32'd23, "payload witness DAC phase epoch")
        rd_word = 8'd0;
        #1;
        `TB_CHECK_EQ(rd_data, 32'h0002_0080, "payload witness buffer word0 low")
        rd_word = 8'd1;
        #1;
        `TB_CHECK_EQ(rd_data, 32'h5435_3130, "payload witness buffer word0 high")

        pulse_clear();
        stream_filter = 2'd2;
        route_is_time = 1'b1;
        pulse_arm();
        send_packet(16'd0, 20);
        repeat (10) @(posedge clk);
        `TB_CHECK(!valid, "SPEC packet ignored by TIME filter")
        `TB_CHECK(filter_mismatch, "payload witness records filter mismatch")
        send_packet(16'd1, 20);
        wait_valid();
        `TB_CHECK_EQ(stream_type, 16'd1, "payload witness TIME stream type")
        `TB_CHECK_EQ(route_meta[7:5], 3'd2, "TIME route endpoint preserved")
        `TB_CHECK(route_meta[11], "TIME route flag preserved")

        `TB_PASS("tb_tx_payload_witness_capture")
    end

endmodule
