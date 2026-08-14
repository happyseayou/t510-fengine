`timescale 1ns/1ps

module tb_pl_mts_sync_clk;
    logic pl_clk_p = 1'b0;
    wire  pl_clk_n = ~pl_clk_p;
    logic adc_axis_clk = 1'b0;
    logic dac_axis_clk = 1'b0;
    logic pl_sys_ref_p = 1'b0;
    wire  pl_sys_ref_n = ~pl_sys_ref_p;
    wire  pl_clk;
    wire  user_sysref_adc;
    wire  user_sysref_dac;
    wire  pl_sysref_capture;
    wire  pl_sysref_capture_legacy;
    wire [31:0] pl_count_gray;
    wire [31:0] adc_count_gray;
    wire [31:0] dac_count_gray;
    wire [2:0] levels;
    real sysref_half_period_ns = 50.0;
    logic sysref_enable = 1'b0;

    function automatic [31:0] gray_to_binary(input [31:0] gray);
        integer idx;
        begin
            gray_to_binary[31] = gray[31];
            for (idx = 30; idx >= 0; idx = idx - 1)
                gray_to_binary[idx] = gray_to_binary[idx + 1] ^ gray[idx];
        end
    endfunction

    pl_mts_sync_clk dut (
        .pl_clk_p(pl_clk_p),
        .pl_clk_n(pl_clk_n),
        .pl_sys_ref_p(pl_sys_ref_p),
        .pl_sys_ref_n(pl_sys_ref_n),
        .pl_clk(pl_clk),
        .user_sysref_adc(pl_sysref_capture),
        .user_sysref_dac(pl_sysref_capture_legacy)
    );

    pl_mts_axis_recapture recapture (
        .pl_clk(pl_clk),
        .adc_axis_clk(adc_axis_clk),
        .dac_axis_clk(dac_axis_clk),
        .pl_sysref_capture(pl_sysref_capture),
        .user_sysref_adc(user_sysref_adc),
        .user_sysref_dac(user_sysref_dac),
        .sysref_pl_edge_count_gray(pl_count_gray),
        .sysref_adc_edge_count_gray(adc_count_gray),
        .sysref_dac_edge_count_gray(dac_count_gray),
        .sysref_capture_levels(levels)
    );

    always #3.125 pl_clk_p = ~pl_clk_p;
    initial begin
        #1.7;
        forever #6.25 adc_axis_clk = ~adc_axis_clk;
    end
    initial begin
        #4.1;
        forever #6.25 dac_axis_clk = ~dac_axis_clk;
    end
    initial begin
        forever begin
            #(sysref_half_period_ns);
            if (sysref_enable)
                pl_sys_ref_p = ~pl_sys_ref_p;
            else
                pl_sys_ref_p = 1'b0;
        end
    end

    task automatic require_counts_close(input string label);
        integer pl_count;
        integer adc_count;
        integer dac_count;
        begin
            pl_count = gray_to_binary(pl_count_gray);
            adc_count = gray_to_binary(adc_count_gray);
            dac_count = gray_to_binary(dac_count_gray);
            if ((pl_count < 2) || ((pl_count-adc_count) < 0) ||
                ((pl_count-adc_count) > 1) || ((pl_count-dac_count) < 0) ||
                ((pl_count-dac_count) > 1)) begin
                $error("%s count mismatch PL=%0d ADC=%0d DAC=%0d", label,
                       pl_count, adc_count, dac_count);
                $fatal(1);
            end
        end
    endtask

    initial begin
        integer before_pl;
        integer before_adc;
        integer before_dac;
        #40;
        sysref_enable = 1'b1;
        #1000;
        require_counts_close("10 MHz");

        sysref_enable = 1'b0;
        #250;
        before_pl = gray_to_binary(pl_count_gray);
        before_adc = gray_to_binary(adc_count_gray);
        before_dac = gray_to_binary(dac_count_gray);
        #250;
        if ((gray_to_binary(pl_count_gray) != before_pl) ||
            (gray_to_binary(adc_count_gray) != before_adc) ||
            (gray_to_binary(dac_count_gray) != before_dac)) begin
            $error("gated SYSREF counters did not stop");
            $fatal(1);
        end

        sysref_half_period_ns = 100.0;
        sysref_enable = 1'b1;
        #1200;
        require_counts_close("5 MHz");
        $display("PASS tb_pl_mts_sync_clk");
        $finish;
    end
endmodule
