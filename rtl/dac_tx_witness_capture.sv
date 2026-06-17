module dac_tx_witness_capture #(
    parameter integer DATA_W        = 128,
    parameter integer CAPTURE_WORDS = 256
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 ctrl_clk,
    input  wire                 ctrl_rst_n,
    input  wire                 arm_pulse_ctrl,
    input  wire                 clear_pulse_ctrl,
    input  wire [8:0]           capture_words_ctrl,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tready,
    input  wire [31:0]          phase_epoch,
    input  wire [31:0]          phase_acc,
    input  wire [31:0]          phase_step,
    input  wire [31:0]          phase0,
    input  wire [31:0]          mode,
    input  wire [9:0]           ctrl_rd_word,
    output wire [31:0]          ctrl_rd_data,
    output wire                 ctrl_armed,
    output wire                 ctrl_valid,
    output wire                 ctrl_capturing,
    output wire                 ctrl_overflow,
    output wire                 ctrl_tvalid_seen,
    output wire                 ctrl_tready_seen,
    output wire                 ctrl_ready_gap_seen,
    output wire [8:0]           ctrl_word_count,
    output wire [31:0]          ctrl_phase_epoch,
    output wire [31:0]          ctrl_phase_acc,
    output wire [31:0]          ctrl_phase_step,
    output wire [31:0]          ctrl_phase0,
    output wire [31:0]          ctrl_mode,
    output wire [31:0]          ctrl_ready_gap_count
);

    localparam [8:0] CAPTURE_WORDS_U9 = CAPTURE_WORDS;
    localparam integer ADDR_W = $clog2(CAPTURE_WORDS);
    localparam integer META_W = 192;

    logic arm_toggle_ctrl;
    logic clear_toggle_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0] arm_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    logic arm_toggle_seen;
    logic clear_toggle_seen;
    wire arm_pulse_data = arm_toggle_sync[2] ^ arm_toggle_seen;
    wire clear_pulse_data = clear_toggle_sync[2] ^ clear_toggle_seen;

    wire [8:0] capture_words_data_raw;
    wire [8:0] capture_limit_data =
        ((capture_words_data_raw == 9'd0) || (capture_words_data_raw > CAPTURE_WORDS_U9)) ?
        CAPTURE_WORDS_U9 : capture_words_data_raw;

    logic armed_data;
    logic valid_data;
    logic capturing_data;
    logic overflow_data;
    logic tvalid_seen_data;
    logic tready_seen_data;
    logic ready_gap_seen_data;
    logic [8:0] word_count_data;
    logic [31:0] phase_epoch_data;
    logic [31:0] phase_acc_data;
    logic [31:0] phase_step_data;
    logic [31:0] phase0_data;
    logic [31:0] mode_data;
    logic [31:0] ready_gap_count_data;
    logic [META_W-1:0] meta_bus_data;
    wire [META_W-1:0] meta_bus_ctrl;

    wire [DATA_W-1:0] ctrl_rd_word_data;
    logic [1:0] ctrl_rd_lane_q;

    wire fire = s_axis_tvalid && s_axis_tready;
    wire capture_active = armed_data && !valid_data;
    wire write_fire = capture_active && fire;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            arm_toggle_ctrl   <= 1'b0;
            clear_toggle_ctrl <= 1'b0;
        end else begin
            if (arm_pulse_ctrl) begin
                arm_toggle_ctrl <= ~arm_toggle_ctrl;
            end
            if (clear_pulse_ctrl) begin
                clear_toggle_ctrl <= ~clear_toggle_ctrl;
            end
        end
    end

    always_comb begin
        meta_bus_data[0 +: 32]   = phase_epoch_data;
        meta_bus_data[32 +: 32]  = phase_acc_data;
        meta_bus_data[64 +: 32]  = phase_step_data;
        meta_bus_data[96 +: 32]  = phase0_data;
        meta_bus_data[128 +: 32] = mode_data;
        meta_bus_data[160 +: 32] = ready_gap_count_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_toggle_sync      <= 3'b000;
            clear_toggle_sync    <= 3'b000;
            arm_toggle_seen      <= 1'b0;
            clear_toggle_seen    <= 1'b0;
            armed_data           <= 1'b0;
            valid_data           <= 1'b0;
            capturing_data       <= 1'b0;
            overflow_data        <= 1'b0;
            tvalid_seen_data     <= 1'b0;
            tready_seen_data     <= 1'b0;
            ready_gap_seen_data  <= 1'b0;
            word_count_data      <= 9'd0;
            phase_epoch_data     <= 32'd0;
            phase_acc_data       <= 32'd0;
            phase_step_data      <= 32'd0;
            phase0_data          <= 32'd0;
            mode_data            <= 32'd0;
            ready_gap_count_data <= 32'd0;
        end else begin
            arm_toggle_sync   <= {arm_toggle_sync[1:0], arm_toggle_ctrl};
            clear_toggle_sync <= {clear_toggle_sync[1:0], clear_toggle_ctrl};
            arm_toggle_seen   <= arm_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];

            if (clear_pulse_data) begin
                armed_data           <= 1'b0;
                valid_data           <= 1'b0;
                capturing_data       <= 1'b0;
                overflow_data        <= 1'b0;
                tvalid_seen_data     <= 1'b0;
                tready_seen_data     <= 1'b0;
                ready_gap_seen_data  <= 1'b0;
                word_count_data      <= 9'd0;
                ready_gap_count_data <= 32'd0;
            end

            if (arm_pulse_data) begin
                armed_data           <= 1'b1;
                valid_data           <= 1'b0;
                capturing_data       <= 1'b0;
                overflow_data        <= 1'b0;
                tvalid_seen_data     <= 1'b0;
                tready_seen_data     <= 1'b0;
                ready_gap_seen_data  <= 1'b0;
                word_count_data      <= 9'd0;
                ready_gap_count_data <= 32'd0;
            end

            if (capture_active) begin
                if (s_axis_tvalid) begin
                    tvalid_seen_data <= 1'b1;
                end
                if (s_axis_tready) begin
                    tready_seen_data <= 1'b1;
                end
                if (s_axis_tvalid && !s_axis_tready) begin
                    ready_gap_seen_data <= 1'b1;
                    if (ready_gap_count_data != 32'hffff_ffff) begin
                        ready_gap_count_data <= ready_gap_count_data + 32'd1;
                    end
                end
            end

            if (write_fire) begin
                if (word_count_data >= CAPTURE_WORDS_U9) begin
                    overflow_data <= 1'b1;
                end

                if (word_count_data == 9'd0) begin
                    phase_epoch_data <= phase_epoch;
                    phase_acc_data   <= phase_acc;
                    phase_step_data  <= phase_step;
                    phase0_data      <= phase0;
                    mode_data        <= mode;
                end

                if ((word_count_data + 9'd1) >= capture_limit_data) begin
                    armed_data      <= 1'b0;
                    valid_data      <= 1'b1;
                    capturing_data  <= 1'b0;
                    word_count_data <= word_count_data + 9'd1;
                end else begin
                    capturing_data  <= 1'b1;
                    word_count_data <= word_count_data + 9'd1;
                end
            end
        end
    end

    wire capture_write_en = write_fire && (word_count_data < CAPTURE_WORDS_U9);
    wire [ADDR_W-1:0] capture_write_addr = word_count_data[ADDR_W-1:0];
    wire [ADDR_W-1:0] ctrl_rd_addr = ctrl_rd_word[ADDR_W+1:2];

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(ADDR_W),
        .ADDR_WIDTH_B(ADDR_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(DATA_W),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("independent_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE((1 << ADDR_W) * DATA_W),
        .MESSAGE_CONTROL(0),
        .READ_DATA_WIDTH_B(DATA_W),
        .READ_LATENCY_B(1),
        .READ_RESET_VALUE_B("0"),
        .RST_MODE_A("SYNC"),
        .RST_MODE_B("SYNC"),
        .USE_EMBEDDED_CONSTRAINT(0),
        .USE_MEM_INIT(0),
        .WAKEUP_TIME("disable_sleep"),
        .WRITE_DATA_WIDTH_A(DATA_W),
        .WRITE_MODE_B("read_first")
    ) u_capture_bram (
        .dbiterrb(),
        .doutb(ctrl_rd_word_data),
        .sbiterrb(),
        .addra(capture_write_addr),
        .addrb(ctrl_rd_addr),
        .clka(clk),
        .clkb(ctrl_clk),
        .dina(s_axis_tdata),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!ctrl_rst_n),
        .sleep(1'b0),
        .wea(capture_write_en)
    );

    always_ff @(posedge ctrl_clk) begin
        ctrl_rd_lane_q    <= ctrl_rd_word[1:0];
    end

    assign ctrl_rd_data = ctrl_rd_word_data[ctrl_rd_lane_q*32 +: 32];

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(9)
    ) u_capture_words_cdc (
        .src_clk(ctrl_clk),
        .src_in(capture_words_ctrl),
        .dest_clk(clk),
        .dest_out(capture_words_data_raw)
    );

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_armed_cdc (.src_clk(clk), .src_in(armed_data), .dest_clk(ctrl_clk), .dest_out(ctrl_armed));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_valid_cdc (.src_clk(clk), .src_in(valid_data), .dest_clk(ctrl_clk), .dest_out(ctrl_valid));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_capturing_cdc (.src_clk(clk), .src_in(capturing_data), .dest_clk(ctrl_clk), .dest_out(ctrl_capturing));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_overflow_cdc (.src_clk(clk), .src_in(overflow_data), .dest_clk(ctrl_clk), .dest_out(ctrl_overflow));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_tvalid_seen_cdc (.src_clk(clk), .src_in(tvalid_seen_data), .dest_clk(ctrl_clk), .dest_out(ctrl_tvalid_seen));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_tready_seen_cdc (.src_clk(clk), .src_in(tready_seen_data), .dest_clk(ctrl_clk), .dest_out(ctrl_tready_seen));

    xpm_cdc_single #(.DEST_SYNC_FF(3), .INIT_SYNC_FF(0), .SIM_ASSERT_CHK(0), .SRC_INPUT_REG(1))
    u_ready_gap_seen_cdc (.src_clk(clk), .src_in(ready_gap_seen_data), .dest_clk(ctrl_clk), .dest_out(ctrl_ready_gap_seen));

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(9)
    ) u_count_cdc (
        .src_clk(clk),
        .src_in(word_count_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_word_count)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(META_W)
    ) u_meta_bus_cdc (
        .src_clk(clk),
        .src_in(meta_bus_data),
        .dest_clk(ctrl_clk),
        .dest_out(meta_bus_ctrl)
    );

    assign ctrl_phase_epoch     = meta_bus_ctrl[0 +: 32];
    assign ctrl_phase_acc       = meta_bus_ctrl[32 +: 32];
    assign ctrl_phase_step      = meta_bus_ctrl[64 +: 32];
    assign ctrl_phase0          = meta_bus_ctrl[96 +: 32];
    assign ctrl_mode            = meta_bus_ctrl[128 +: 32];
    assign ctrl_ready_gap_count = meta_bus_ctrl[160 +: 32];

endmodule
