`include "tb_common.svh"

module tb_sync_fsm;

    localparam [3:0] ST_RESET        = 4'd0;
    localparam [3:0] ST_CLOCK_CONFIG = 4'd1;
    localparam [3:0] ST_RFDC_CONFIG  = 4'd2;
    localparam [3:0] ST_WAIT_LOCK    = 4'd3;
    localparam [3:0] ST_WAIT_PPS     = 4'd4;
    localparam [3:0] ST_ARMED        = 4'd5;
    localparam [3:0] ST_STREAMING    = 4'd6;
    localparam [3:0] ST_STOPPING     = 4'd7;
    localparam [3:0] ST_ERROR        = 4'd8;
    localparam [1:0] SYNC_EXTERNAL_PPS   = 2'd0;
    localparam [1:0] SYNC_SOFTWARE_EPOCH = 2'd1;
    localparam [1:0] SYNC_FREE_RUN       = 2'd2;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic arm_req = 1'b0;
    logic stop_req = 1'b0;
    logic soft_epoch_req = 1'b0;
    logic soft_reset_req = 1'b0;
    logic [1:0] sync_mode = SYNC_EXTERNAL_PPS;
    logic ref_locked = 1'b0;
    logic rfdc_ready = 1'b0;
    logic pps_in = 1'b0;
    logic sync_error = 1'b0;
    wire [3:0] state;
    wire armed;
    wire streaming;
    wire waiting_for_epoch;
    wire epoch_reset_pulse;

    always #5 clk = ~clk;

    sync_fsm dut (
        .clk(clk),
        .rst_n(rst_n),
        .arm_req(arm_req),
        .stop_req(stop_req),
        .soft_epoch_req(soft_epoch_req),
        .soft_reset_req(soft_reset_req),
        .sync_mode(sync_mode),
        .ref_locked(ref_locked),
        .rfdc_ready(rfdc_ready),
        .pps_in(pps_in),
        .sync_error(sync_error),
        .state(state),
        .armed(armed),
        .streaming(streaming),
        .waiting_for_epoch(waiting_for_epoch),
        .epoch_reset_pulse(epoch_reset_pulse)
    );

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            arm_req = 1'b0;
            stop_req = 1'b0;
            soft_epoch_req = 1'b0;
            soft_reset_req = 1'b0;
            sync_mode = SYNC_EXTERNAL_PPS;
            ref_locked = 1'b0;
            rfdc_ready = 1'b0;
            pps_in = 1'b0;
            sync_error = 1'b0;
            repeat (4) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
            @(posedge clk);
            #1;
        end
    endtask

    task automatic pulse_pps;
        begin
            @(posedge clk);
            pps_in <= 1'b1;
            @(posedge clk);
            pps_in <= 1'b0;
            #1;
        end
    endtask

    task automatic pulse_soft_epoch;
        begin
            @(posedge clk);
            soft_epoch_req <= 1'b1;
            @(posedge clk);
            soft_epoch_req <= 1'b0;
            #1;
        end
    endtask

    task automatic tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        reset_dut();
        `TB_CHECK_EQ(state, ST_CLOCK_CONFIG, "reset exits to CLOCK_CONFIG")

        repeat (3) tick();
        `TB_CHECK_EQ(state, ST_CLOCK_CONFIG, "CLOCK_CONFIG waits for ref lock")

        arm_req = 1'b1;
        ref_locked = 1'b1;
        tick();
        `TB_CHECK_EQ(state, ST_RFDC_CONFIG, "ref lock advances to RFDC_CONFIG")
        tick();
        `TB_CHECK_EQ(state, ST_WAIT_LOCK, "RFDC_CONFIG advances to WAIT_LOCK")
        repeat (2) tick();
        `TB_CHECK_EQ(state, ST_WAIT_LOCK, "WAIT_LOCK waits for RFDC ready")

        rfdc_ready = 1'b1;
        tick();
        `TB_CHECK_EQ(state, ST_WAIT_PPS, "RFDC ready advances to WAIT_PPS")
        tick();
        `TB_CHECK_EQ(state, ST_ARMED, "arm request advances to ARMED")
        `TB_CHECK(armed, "armed asserted in ARMED")
        `TB_CHECK(!streaming, "streaming is low before PPS")
        `TB_CHECK(waiting_for_epoch, "external PPS mode waits for epoch")

        pulse_pps();
        `TB_CHECK_EQ(state, ST_STREAMING, "PPS starts STREAMING")
        `TB_CHECK(streaming, "streaming asserted after PPS")
        `TB_CHECK(epoch_reset_pulse, "epoch reset pulse on PPS")
        tick();
        `TB_CHECK(!epoch_reset_pulse, "epoch reset pulse is one cycle")

        stop_req = 1'b1;
        tick();
        stop_req = 1'b0;
        `TB_CHECK_EQ(state, ST_STOPPING, "stop request enters STOPPING")
        `TB_CHECK(!streaming, "streaming clears on stop")
        tick();
        `TB_CHECK_EQ(state, ST_RESET, "STOPPING returns to RESET")

        arm_req = 1'b1;
        ref_locked = 1'b1;
        rfdc_ready = 1'b1;
        repeat (6) tick();
        if (state != ST_ARMED) begin
            repeat (6) tick();
        end
        `TB_CHECK_EQ(state, ST_ARMED, "second arm reaches ARMED")
        pulse_pps();
        `TB_CHECK_EQ(state, ST_STREAMING, "second PPS starts STREAMING")
        sync_error = 1'b1;
        tick();
        sync_error = 1'b0;
        `TB_CHECK_EQ(state, ST_ERROR, "sync error enters ERROR")
        `TB_CHECK(!streaming, "streaming clears on error")

        soft_reset_req = 1'b1;
        tick();
        soft_reset_req = 1'b0;
        `TB_CHECK_EQ(state, ST_RESET, "soft reset leaves ERROR")

        reset_dut();
        sync_mode = SYNC_SOFTWARE_EPOCH;
        arm_req = 1'b1;
        ref_locked = 1'b1;
        rfdc_ready = 1'b1;
        repeat (6) tick();
        if (state != ST_ARMED) begin
            repeat (6) tick();
        end
        `TB_CHECK_EQ(state, ST_ARMED, "software epoch mode reaches ARMED")
        `TB_CHECK(waiting_for_epoch, "software epoch mode waits for trigger")
        pulse_pps();
        `TB_CHECK_EQ(state, ST_ARMED, "software epoch mode ignores PPS")
        pulse_soft_epoch();
        `TB_CHECK_EQ(state, ST_STREAMING, "software epoch trigger starts STREAMING")
        `TB_CHECK(epoch_reset_pulse, "software epoch creates epoch pulse")

        reset_dut();
        sync_mode = SYNC_FREE_RUN;
        arm_req = 1'b1;
        ref_locked = 1'b1;
        rfdc_ready = 1'b1;
        repeat (8) tick();
        `TB_CHECK_EQ(state, ST_STREAMING, "free-run mode starts without PPS")
        `TB_CHECK(streaming, "free-run streaming asserted")
        `TB_CHECK(!waiting_for_epoch, "free-run does not wait for epoch")

        `TB_PASS("tb_sync_fsm")
    end

endmodule
