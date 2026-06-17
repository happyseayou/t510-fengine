`include "tb_common.svh"

module tb_fft_debug_observer;

    localparam integer NFFT = 1024;
    localparam integer TONE_BIN = 7;
    localparam integer TONE_AMP = 1000;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic streaming = 1'b0;
    logic [15:0] active_port_mask = 16'h0001;
    logic [255:0] s_axis_adc_tdata = 256'd0;
    logic s_axis_adc_tvalid = 1'b0;
    logic start_pulse = 1'b0;
    logic clear_pulse = 1'b0;
    logic [9:0] time_rd_addr = 10'd0;
    logic [9:0] fft_rd_addr = 10'd0;
    wire [31:0] time_rd_data;
    wire [31:0] fft_rd_data;
    wire busy;
    wire done;
    wire error;
    wire [31:0] capture_count;
    wire [31:0] peak_bin;
    wire [31:0] peak_power;

    always #5 clk = ~clk;

    function automatic signed [15:0] sine_sample(input integer n);
        real angle;
        real value;
        begin
            angle = 6.2831853071795864769 * TONE_BIN * n / NFFT;
            value = TONE_AMP * $sin(angle);
            sine_sample = $rtoi(value);
        end
    endfunction

    fft_debug_observer dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(clk),
        .ctrl_rst_n(rst_n),
        .streaming(streaming),
        .active_port_mask(active_port_mask),
        .s_axis_adc_tdata(s_axis_adc_tdata),
        .s_axis_adc_tvalid(s_axis_adc_tvalid),
        .ctrl_capture_start_pulse(start_pulse),
        .ctrl_capture_clear_pulse(clear_pulse),
        .ctrl_time_rd_addr(time_rd_addr),
        .ctrl_fft_rd_addr(fft_rd_addr),
        .ctrl_time_rd_data(time_rd_data),
        .ctrl_fft_rd_data(fft_rd_data),
        .ctrl_busy(busy),
        .ctrl_done(done),
        .ctrl_error(error),
        .ctrl_capture_count(capture_count),
        .ctrl_peak_bin(peak_bin),
        .ctrl_peak_power(peak_power)
    );

    task automatic read_time(input [9:0] addr, output [31:0] data);
        begin
            time_rd_addr <= addr;
            repeat (2) @(posedge clk);
            data = time_rd_data;
        end
    endtask

    task automatic read_fft(input [9:0] addr, output [31:0] data);
        begin
            fft_rd_addr <= addr;
            repeat (2) @(posedge clk);
            data = fft_rd_data;
        end
    endtask

    task automatic feed_tone_frame;
        integer n;
        reg signed [15:0] sample;
        begin
            s_axis_adc_tvalid <= 1'b1;
            for (n = 0; n < NFFT; n = n + 1) begin
                sample = sine_sample(n);
                s_axis_adc_tdata <= {240'd0, sample};
                @(posedge clk);
            end
            s_axis_adc_tvalid <= 1'b0;
        end
    endtask

    initial begin
        reg [31:0] rd;
        rst_n = 1'b0;
        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        streaming <= 1'b1;
        start_pulse <= 1'b1;
        @(posedge clk);
        start_pulse <= 1'b0;
        repeat (8) @(posedge clk);

        feed_tone_frame();

        repeat (8) @(posedge clk);
        `TB_CHECK(done, "debug observer capture done")
        `TB_CHECK(!busy, "debug observer no longer busy")
        `TB_CHECK(!error, "debug observer has no error")
        `TB_CHECK_EQ(capture_count, 32'd1024, "debug observer capture count")

        read_time(10'd0, rd);
        `TB_CHECK_EQ(rd[31:16], 16'd0, "debug time Q is zero for real-only mask")
        `TB_CHECK_EQ($signed(rd[15:0]), sine_sample(0), "debug time sample0")
        read_time(10'd1, rd);
        `TB_CHECK_EQ($signed(rd[15:0]), sine_sample(1), "debug time sample1")
        read_fft(TONE_BIN, rd);
        `TB_CHECK(rd != 32'd0, "debug FFT peak bin buffer nonzero")
        `TB_CHECK_EQ(peak_bin, TONE_BIN, "debug observer peak bin")
        `TB_CHECK(peak_power != 32'd0, "debug observer peak power nonzero")

        clear_pulse <= 1'b1;
        @(posedge clk);
        clear_pulse <= 1'b0;
        repeat (10) @(posedge clk);
        `TB_CHECK(!done, "debug clear drops done")

        `TB_PASS("tb_fft_debug_observer")
    end

endmodule
