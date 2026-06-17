`include "tb_common.svh"

module tb_rfdc_fullrate_preview;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic ctrl_clk = 1'b0;
    logic ctrl_rst_n = 1'b0;
    logic streaming = 1'b0;
    logic [7:0] input_mask = 8'h03;
    logic [15:0] sample_base = 16'd0;
    logic [63:0] sample0_base = 64'd128;
    logic capture_start = 1'b0;
    logic capture_clear = 1'b0;
    logic [2:0] rd_input = 3'd0;
    logic [9:0] rd_addr = 10'd0;
    wire [31:0] rd_data;
    wire busy;
    wire done;
    wire error;
    wire [31:0] capture_count;
    wire [63:0] sample0;
    logic [1:0] audit_source_select = 2'd0;
    logic audit_event_enable = 1'b0;
    logic audit_freeze_on_event = 1'b1;
    logic audit_clear = 1'b0;
    logic [15:0] audit_event_threshold = 16'd28000;
    logic [7:0] event_rd_addr = 8'd0;
    wire [31:0] event_rd_data;
    wire [31:0] audit_status;
    wire [31:0] audit_start_count;
    wire [31:0] audit_first_count;
    wire [31:0] audit_done_count;
    wire [63:0] audit_start_sample0;
    wire [63:0] audit_first_sample0;
    wire [63:0] audit_done_sample0;
    wire [31:0] audit_latency;
    wire [31:0] audit_capture_beats;
    wire [31:0] audit_valid_gap_count;
    wire [31:0] audit_sample0_error_count;
    wire [63:0] event_sample0;
    wire [31:0] event_max_code;
    wire [31:0] event_info;
    wire [31:0] event_rfdc_flags;
    wire [31:0] event_dac_phase_epoch;

    always #5 clk = ~clk;
    always #5 ctrl_clk = ~ctrl_clk;

    function automatic [31:0] sample_word(input [15:0] sample_idx, input integer ch);
        reg [15:0] i_sample;
        reg [15:0] q_sample;
        begin
            i_sample = 16'h1000 + sample_idx + (ch * 16);
            q_sample = 16'h4000 + sample_idx + (ch * 16);
            sample_word = {q_sample, i_sample};
        end
    endfunction

    function automatic [255:0] make_bus(input [15:0] sample_idx);
        begin
            make_bus = {
                sample_word(sample_idx, 7),
                sample_word(sample_idx, 6),
                sample_word(sample_idx, 5),
                sample_word(sample_idx, 4),
                sample_word(sample_idx, 3),
                sample_word(sample_idx, 2),
                sample_word(sample_idx, 1),
                sample_word(sample_idx, 0)
            };
        end
    endfunction

    multi_preview_observer dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .streaming(streaming),
        .input_mask(input_mask),
        .s_axis_adc_tdata0(make_bus(sample_base + 16'd0)),
        .s_axis_adc_tdata1(make_bus(sample_base + 16'd1)),
        .s_axis_adc_tdata2(make_bus(sample_base + 16'd2)),
        .s_axis_adc_tdata3(make_bus(sample_base + 16'd3)),
        .s_axis_adc_sample0(sample0_base + sample_base),
        .s_axis_adc_tvalid(1'b1),
        .audit_source_select(audit_source_select),
        .audit_event_enable(audit_event_enable),
        .audit_freeze_on_event(audit_freeze_on_event),
        .audit_clear_pulse(audit_clear),
        .audit_event_threshold(audit_event_threshold),
        .rfdc_status_flags(32'h0000_000f),
        .dac_phase_epoch_ctrl(32'd7),
        .ctrl_capture_start_pulse(capture_start),
        .ctrl_capture_clear_pulse(capture_clear),
        .ctrl_rd_input(rd_input),
        .ctrl_rd_addr(rd_addr),
        .ctrl_event_rd_addr(event_rd_addr),
        .ctrl_rd_data(rd_data),
        .ctrl_event_rd_data(event_rd_data),
        .ctrl_busy(busy),
        .ctrl_done(done),
        .ctrl_error(error),
        .ctrl_capture_count(capture_count),
        .ctrl_sample0(sample0),
        .ctrl_audit_status(audit_status),
        .ctrl_audit_start_count(audit_start_count),
        .ctrl_audit_first_count(audit_first_count),
        .ctrl_audit_done_count(audit_done_count),
        .ctrl_audit_start_sample0(audit_start_sample0),
        .ctrl_audit_first_sample0(audit_first_sample0),
        .ctrl_audit_done_sample0(audit_done_sample0),
        .ctrl_audit_start_to_first_latency(audit_latency),
        .ctrl_audit_capture_beats(audit_capture_beats),
        .ctrl_audit_valid_gap_count(audit_valid_gap_count),
        .ctrl_audit_sample0_error_count(audit_sample0_error_count),
        .ctrl_event_sample0(event_sample0),
        .ctrl_event_max_code(event_max_code),
        .ctrl_event_info(event_info),
        .ctrl_event_rfdc_flags(event_rfdc_flags),
        .ctrl_event_dac_phase_epoch(event_dac_phase_epoch)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            sample_base <= 16'd0;
        end else if (streaming) begin
            sample_base <= sample_base + 16'd4;
        end
    end

    task automatic read_preview(input [2:0] ch, input [9:0] addr, output [31:0] data);
        begin
            rd_input <= ch;
            rd_addr <= addr;
            repeat (3) @(posedge ctrl_clk);
            data = rd_data;
        end
    endtask

    initial begin
        reg [31:0] data;
        reg [15:0] first_sample;
        integer timeout;

        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        ctrl_rst_n <= 1'b1;
        repeat (4) @(posedge ctrl_clk);

        capture_start <= 1'b1;
        @(posedge ctrl_clk);
        capture_start <= 1'b0;
        @(posedge clk);
        streaming <= 1'b1;

        timeout = 0;
        while (!done && timeout < 400) begin
            @(posedge ctrl_clk);
            timeout = timeout + 1;
        end
        `TB_CHECK(done, "full-rate preview capture completes")
        `TB_CHECK(!error, "full-rate preview has no error")
        `TB_CHECK_EQ(capture_count, 32'd1024, "full-rate preview captures 1024 samples")
        `TB_CHECK_EQ(sample0[1:0], 2'd0, "full-rate preview sample0 is a baseband sample index")
        `TB_CHECK_EQ(audit_start_count, 32'd1, "audit start count")
        `TB_CHECK_EQ(audit_first_count, 32'd1, "audit first write count")
        `TB_CHECK_EQ(audit_done_count, 32'd1, "audit done count")
        `TB_CHECK_EQ(audit_capture_beats, 32'd256, "audit captures 256 beats for 1024 full-rate samples")
        `TB_CHECK_EQ(audit_sample0_error_count, 32'd0, "audit sample0 step clean")
        `TB_CHECK_EQ(audit_valid_gap_count, 32'd0, "audit valid gap clean")
        `TB_CHECK_EQ(audit_first_sample0, sample0, "audit first sample0 matches preview metadata")
        `TB_CHECK_EQ(audit_done_sample0, sample0 + 64'd1020, "audit done sample0 is last beat base")
        first_sample = sample0[15:0] - sample0_base[15:0];

        read_preview(3'd0, 10'd0, data);
        `TB_CHECK_EQ(data, sample_word(first_sample + 16'd0, 0), "CH0 sample0 matches sample0 metadata")
        read_preview(3'd0, 10'd1, data);
        `TB_CHECK_EQ(data, sample_word(first_sample + 16'd1, 0), "CH0 sample1")
        read_preview(3'd0, 10'd2, data);
        `TB_CHECK_EQ(data, sample_word(first_sample + 16'd2, 0), "CH0 sample2")
        read_preview(3'd0, 10'd3, data);
        `TB_CHECK_EQ(data, sample_word(first_sample + 16'd3, 0), "CH0 sample3")
        read_preview(3'd1, 10'd0, data);
        `TB_CHECK_EQ(data, sample_word(first_sample + 16'd0, 1), "CH1 sample0 shares capture base")

        read_preview(3'd2, 10'd0, data);
        `TB_CHECK_EQ(data, 32'd0, "inactive CH2 remains zero")
        `TB_PASS("tb_rfdc_fullrate_preview")
    end

endmodule
