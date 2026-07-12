`timescale 1ns/1ps
`default_nettype none

module tb_t510_cmac_pause;
    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic [511:0] tx_data = '0;
    logic [63:0] tx_keep = '1;
    logic tx_valid = 1'b0;
    logic tx_last = 1'b0;
    logic test_pass = 1'b0;
    wire tx_ready;

    always #1.55 clk = ~clk;

    t510_cmac_qsfp0 dut (
        .init_clk(clk),
        .reset_n(reset_n),
        .gt_ref_clk_p(1'b0),
        .gt_ref_clk_n(1'b0),
        .gt_rxp_in(4'd0),
        .gt_rxn_in(4'd0),
        .gt_txp_out(),
        .gt_txn_out(),
        .tx_clk(),
        .tx_rst_n(),
        .tx_axis_tdata(tx_data),
        .tx_axis_tkeep(tx_keep),
        .tx_axis_tvalid(tx_valid),
        .tx_axis_tlast(tx_last),
        .tx_axis_tready(tx_ready),
        .gt_refclk_seen(),
        .gt_powergood(),
        .gt_tx_reset_done(),
        .gt_rx_reset_done(),
        .gt_locked(),
        .cmac_reset_done(),
        .cmac_tx_ready(),
        .local_fault(),
        .remote_fault(),
        .link_up(),
        .tx_underflow(),
        .tx_overflow(),
        .rx_aligned(),
        .rx_status(),
        .rx_local_fault(),
        .rx_internal_local_fault(),
        .tx_local_fault_detail(),
        .an_autoneg_complete(),
        .an_lp_ability_valid(),
        .an_lp_autoneg_able(),
        .an_lp_ability_100gbase_cr4(),
        .an_rs_fec_enable(),
        .lt_signal_detect(),
        .lt_training(),
        .lt_training_fail(),
        .lt_frame_lock()
    );

    task automatic check_true(input logic condition, input string message);
        if (!condition) begin
            $error("FAIL: %s", message);
            $fatal(1);
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);
        reset_n <= 1'b1;
        repeat (3) @(posedge clk);
        check_true(tx_ready, "ready after reset");

        // An idle link must stop before accepting the first beat.
        force dut.rx_pause_req = 9'h100;
        repeat (4) @(posedge clk);
        check_true(!tx_ready, "global pause blocks an idle transmitter");
        check_true(!dut.tx_axis_tvalid_gated, "CMAC valid is gated while paused");
        release dut.rx_pause_req;
        repeat (4) @(posedge clk);
        check_true(tx_ready, "zero quanta/resume releases the transmitter");

        // Once a frame has started, pause must wait for TLAST and must not
        // create a mid-frame AXI gap.
        tx_valid <= 1'b1;
        tx_last <= 1'b0;
        @(posedge clk);
        check_true(tx_ready, "first frame beat accepted");
        force dut.rx_pause_req = 9'h100;
        repeat (4) begin
            @(posedge clk);
            check_true(tx_ready, "in-flight frame remains contiguous");
        end
        tx_last <= 1'b1;
        @(posedge clk);
        check_true(tx_ready, "TLAST accepted before pause");
        tx_last <= 1'b0;
        @(posedge clk);
        check_true(!tx_ready, "pause takes effect at packet boundary");
        check_true(!dut.tx_axis_tvalid_gated, "next frame is held out of CMAC");

        release dut.rx_pause_req;
        repeat (4) @(posedge clk);
        check_true(tx_ready, "transmission resumes after pause timer expires");

        tx_valid <= 1'b0;
        test_pass = 1'b1;
        $display("PASS: tb_t510_cmac_pause");
        $finish;
    end
endmodule

`default_nettype wire
