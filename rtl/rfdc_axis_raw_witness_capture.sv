module rfdc_axis_raw_witness_capture #(
    parameter integer CAPTURE_BEATS = 256,
    parameter integer BEAT_COUNT_W  = $clog2(CAPTURE_BEATS + 1),
    parameter integer ADDR_W        = $clog2(CAPTURE_BEATS),
    parameter integer RD_WORD_W     = $clog2(CAPTURE_BEATS * 4)
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         ctrl_clk,
    input  wire                         ctrl_rst_n,
    input  wire                         arm_pulse_ctrl,
    input  wire                         clear_pulse_ctrl,
    input  wire [2:0]                   channel_select_ctrl,
    input  wire [BEAT_COUNT_W-1:0]      capture_beats_ctrl,
    input  wire [255:0]                 s_axis_adc_tdata0,
    input  wire [255:0]                 s_axis_adc_tdata1,
    input  wire [255:0]                 s_axis_adc_tdata2,
    input  wire [255:0]                 s_axis_adc_tdata3,
    input  wire [63:0]                  s_axis_adc_sample0,
    input  wire                         s_axis_adc_tvalid,
    input  wire [31:0]                  rfdc_status_flags,
    input  wire [15:0]                  rfdc_current_valid_mask,
    input  wire [RD_WORD_W-1:0]         ctrl_rd_word,
    output wire [31:0]                  ctrl_rd_data,
    output wire                         ctrl_armed,
    output wire                         ctrl_valid,
    output wire                         ctrl_capturing,
    output wire                         ctrl_overflow,
    output wire                         ctrl_tvalid_seen,
    output wire [BEAT_COUNT_W-1:0]      ctrl_beat_count,
    output wire [2:0]                   ctrl_channel_select,
    output wire [63:0]                  ctrl_sample0,
    output wire [31:0]                  ctrl_rfdc_flags,
    output wire [15:0]                  ctrl_valid_mask
);

    localparam [BEAT_COUNT_W-1:0] CAPTURE_BEATS_COUNT = CAPTURE_BEATS;
    localparam [ADDR_W-1:0]       CAPTURE_BEATS_ADDR  = CAPTURE_BEATS - 1;

    logic arm_toggle_ctrl;
    logic clear_toggle_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0] arm_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    logic arm_toggle_seen;
    logic clear_toggle_seen;
    wire arm_pulse_data = arm_toggle_sync[2] ^ arm_toggle_seen;
    wire clear_pulse_data = clear_toggle_sync[2] ^ clear_toggle_seen;

    wire [2:0] channel_select_data;
    wire [BEAT_COUNT_W-1:0] capture_beats_data_raw;
    wire [BEAT_COUNT_W-1:0] capture_limit_data =
        ((capture_beats_data_raw == {BEAT_COUNT_W{1'b0}}) ||
         (capture_beats_data_raw > CAPTURE_BEATS_COUNT)) ?
        CAPTURE_BEATS_COUNT : capture_beats_data_raw;

    logic armed_data;
    logic valid_data;
    logic capturing_data;
    logic overflow_data;
    logic tvalid_seen_data;
    logic [BEAT_COUNT_W-1:0] beat_count_data;
    logic [2:0] channel_select_latched_data;
    logic [63:0] sample0_data;
    logic [31:0] rfdc_flags_data;
    logic [15:0] valid_mask_data;

    wire [31:0] selected_word0 = complex_pair(s_axis_adc_tdata0, channel_select_latched_data);
    wire [31:0] selected_word1 = complex_pair(s_axis_adc_tdata1, channel_select_latched_data);
    wire [31:0] selected_word2 = complex_pair(s_axis_adc_tdata2, channel_select_latched_data);
    wire [31:0] selected_word3 = complex_pair(s_axis_adc_tdata3, channel_select_latched_data);
    wire [127:0] selected_beat_word = {
        selected_word3,
        selected_word2,
        selected_word1,
        selected_word0
    };

    wire capture_active = armed_data && !valid_data;
    wire write_fire = capture_active && s_axis_adc_tvalid;
    wire capture_write_en = write_fire && (beat_count_data < CAPTURE_BEATS_COUNT);
    wire [ADDR_W-1:0] capture_write_addr = beat_count_data[ADDR_W-1:0];
    wire [ADDR_W-1:0] ctrl_rd_addr = ctrl_rd_word[RD_WORD_W-1:2];
    wire [1:0] ctrl_rd_lane = ctrl_rd_word[1:0];
    wire [127:0] ctrl_rd_word_data;

    function automatic [31:0] complex_pair(
        input [255:0] data,
        input [2:0] idx
    );
        logic signed [15:0] i_sample;
        logic signed [15:0] q_sample;
        begin
            i_sample = data[(idx * 32) +: 16];
            q_sample = data[(idx * 32 + 16) +: 16];
            complex_pair = {q_sample, i_sample};
        end
    endfunction

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

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_toggle_sync             <= 3'b000;
            clear_toggle_sync           <= 3'b000;
            arm_toggle_seen             <= 1'b0;
            clear_toggle_seen           <= 1'b0;
            armed_data                  <= 1'b0;
            valid_data                  <= 1'b0;
            capturing_data              <= 1'b0;
            overflow_data               <= 1'b0;
            tvalid_seen_data            <= 1'b0;
            beat_count_data             <= {BEAT_COUNT_W{1'b0}};
            channel_select_latched_data <= 3'd0;
            sample0_data                <= 64'd0;
            rfdc_flags_data             <= 32'd0;
            valid_mask_data             <= 16'd0;
        end else begin
            arm_toggle_sync   <= {arm_toggle_sync[1:0], arm_toggle_ctrl};
            clear_toggle_sync <= {clear_toggle_sync[1:0], clear_toggle_ctrl};
            arm_toggle_seen   <= arm_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];

            if (clear_pulse_data) begin
                armed_data       <= 1'b0;
                valid_data       <= 1'b0;
                capturing_data   <= 1'b0;
                overflow_data    <= 1'b0;
                tvalid_seen_data <= 1'b0;
                beat_count_data  <= {BEAT_COUNT_W{1'b0}};
            end

            if (arm_pulse_data) begin
                armed_data                  <= 1'b1;
                valid_data                  <= 1'b0;
                capturing_data              <= 1'b0;
                overflow_data               <= 1'b0;
                tvalid_seen_data            <= 1'b0;
                beat_count_data             <= {BEAT_COUNT_W{1'b0}};
                channel_select_latched_data <= channel_select_data;
            end

            if (capture_active && s_axis_adc_tvalid) begin
                tvalid_seen_data <= 1'b1;
            end

            if (write_fire) begin
                if (beat_count_data == {BEAT_COUNT_W{1'b0}}) begin
                    sample0_data    <= s_axis_adc_sample0;
                    rfdc_flags_data <= rfdc_status_flags;
                    valid_mask_data <= rfdc_current_valid_mask;
                end

                if ((beat_count_data + {{(BEAT_COUNT_W-1){1'b0}}, 1'b1}) >= capture_limit_data) begin
                    armed_data     <= 1'b0;
                    valid_data     <= 1'b1;
                    capturing_data <= 1'b0;
                end else begin
                    capturing_data <= 1'b1;
                end
                beat_count_data <= beat_count_data + {{(BEAT_COUNT_W-1){1'b0}}, 1'b1};
            end
        end
    end

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(ADDR_W),
        .ADDR_WIDTH_B(ADDR_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(128),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("independent_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE((1 << ADDR_W) * 128),
        .MESSAGE_CONTROL(0),
        .READ_DATA_WIDTH_B(128),
        .READ_LATENCY_B(1),
        .READ_RESET_VALUE_B("0"),
        .RST_MODE_A("SYNC"),
        .RST_MODE_B("SYNC"),
        .USE_EMBEDDED_CONSTRAINT(0),
        .USE_MEM_INIT(0),
        .WAKEUP_TIME("disable_sleep"),
        .WRITE_DATA_WIDTH_A(128),
        .WRITE_MODE_B("read_first")
    ) u_capture_bram (
        .dbiterrb(),
        .doutb(ctrl_rd_word_data),
        .sbiterrb(),
        .addra(capture_write_addr),
        .addrb(ctrl_rd_addr),
        .clka(clk),
        .clkb(ctrl_clk),
        .dina(selected_beat_word),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!ctrl_rst_n),
        .sleep(1'b0),
        .wea(capture_write_en)
    );

    assign ctrl_rd_data = ctrl_rd_word_data[ctrl_rd_lane*32 +: 32];

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(3)
    ) u_channel_select_cdc (
        .src_clk(ctrl_clk),
        .src_in(channel_select_ctrl),
        .dest_clk(clk),
        .dest_out(channel_select_data)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(BEAT_COUNT_W)
    ) u_capture_beats_cdc (
        .src_clk(ctrl_clk),
        .src_in(capture_beats_ctrl),
        .dest_clk(clk),
        .dest_out(capture_beats_data_raw)
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

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(BEAT_COUNT_W)
    ) u_beat_count_cdc (
        .src_clk(clk),
        .src_in(beat_count_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_beat_count)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(3)
    ) u_channel_latched_cdc (
        .src_clk(clk),
        .src_in(channel_select_latched_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_channel_select)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(64)
    ) u_sample0_cdc (
        .src_clk(clk),
        .src_in(sample0_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_sample0)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(32)
    ) u_rfdc_flags_cdc (
        .src_clk(clk),
        .src_in(rfdc_flags_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_rfdc_flags)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(16)
    ) u_valid_mask_cdc (
        .src_clk(clk),
        .src_in(valid_mask_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_valid_mask)
    );

endmodule
