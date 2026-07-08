`include "tb_common.svh"

module tb_t510_fengine_board_top;

    logic pl_clk_p = 1'b0;
    logic pl_clk_n = 1'b1;
    logic pps_in = 1'b0;
    logic qsfp0_modprsl = 1'b0;
    logic qsfp0_intl = 1'b1;
    wire qsfp0_resetl;
    wire qsfp0_lpmode;
    wire qsfp0_modsell;
    wire pl_led0;
    wire pl_led1;
    wire pl_led2;
    wire pl_led3;

    always #5 begin
        pl_clk_p = ~pl_clk_p;
        pl_clk_n = ~pl_clk_n;
    end

    t510_fengine_synthetic_board_top dut (
        .pl_clk_p(pl_clk_p),
        .pl_clk_n(pl_clk_n),
        .pps_in(pps_in),
        .qsfp0_modprsl(qsfp0_modprsl),
        .qsfp0_intl(qsfp0_intl),
        .qsfp0_resetl(qsfp0_resetl),
        .qsfp0_lpmode(qsfp0_lpmode),
        .qsfp0_modsell(qsfp0_modsell),
        .pl_led0(pl_led0),
        .pl_led1(pl_led1),
        .pl_led2(pl_led2),
        .pl_led3(pl_led3)
    );

    task automatic pulse_pps;
        begin
            @(posedge pl_clk_p);
            pps_in <= 1'b1;
            @(posedge pl_clk_p);
            pps_in <= 1'b0;
        end
    endtask

    initial begin
        integer timeout;

        repeat (40) @(posedge pl_clk_p);
        `TB_CHECK(qsfp0_resetl, "QSFP reset deasserted")
        `TB_CHECK(!qsfp0_lpmode, "QSFP low-power mode disabled")
        `TB_CHECK(!qsfp0_modsell, "QSFP module selected")
        `TB_CHECK(pl_led0, "reference/clock-chain LED asserted after reset")
        `TB_CHECK(!pl_led1, "PPS blink LED idle before PPS")
        `TB_CHECK(!pl_led2, "PPS recent LED low before PPS")
        `TB_CHECK(pl_led3, "sync error LED asserted before PPS")

        timeout = 0;
        while (dut.test_sample_counter == 64'd0 && timeout < 5000) begin
            @(posedge pl_clk_p);
            timeout = timeout + 1;
        end
        `TB_CHECK(dut.test_sample_counter > 64'd0, "test ADC source accepted")
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        `TB_CHECK(!dut.tx_activity_latched, "production top stays quiet before explicit science start")
        `TB_CHECK_EQ(dut.tx_word_count, 32'd0, "production top has no default dry-run TX")
`else
        timeout = 0;
        while (!dut.tx_activity_latched && timeout < 5000) begin
            @(posedge pl_clk_p);
            timeout = timeout + 1;
        end
        `TB_CHECK(dut.tx_activity_latched, "TX activity latched internally")
        `TB_CHECK(dut.tx_word_count > 32'd0, "TX word count increments")
`endif

        pulse_pps();
        repeat (8) @(posedge pl_clk_p);
        `TB_CHECK(pl_led1, "PPS blink LED asserted after PPS edge")
        `TB_CHECK(pl_led2, "PPS recent LED asserted after PPS edge")
        `TB_CHECK(!pl_led3, "sync error LED clears after recent PPS")

        `TB_PASS("tb_t510_fengine_board_top")
    end

endmodule
