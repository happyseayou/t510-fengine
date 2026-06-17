module tx_payload_witness_capture #(
    parameter integer DATA_W        = 64,
    parameter integer CAPTURE_WORDS = 1056,
    parameter integer COUNT_W       = $clog2(CAPTURE_WORDS + 1),
    parameter integer RD_WORD_W     = $clog2(CAPTURE_WORDS * (DATA_W / 32))
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 ctrl_clk,
    input  wire                 ctrl_rst_n,
    input  wire                 arm_pulse_ctrl,
    input  wire                 clear_pulse_ctrl,
    input  wire                 data_clear_pulse,
    input  wire [1:0]           stream_filter_ctrl,
    input  wire [COUNT_W-1:0]   capture_words_ctrl,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    input  wire                 s_axis_tready,
    input  wire [2:0]           route_endpoint_id,
    input  wire [2:0]           route_id,
    input  wire                 route_is_time,
    input  wire [31:0]          rfdc_status_flags,
    input  wire [63:0]          rfdc_sample_count,
    input  wire [31:0]          dac_phase_epoch,
    input  wire [RD_WORD_W-1:0] ctrl_rd_word,
    output wire [31:0]          ctrl_rd_data,
    output wire                 ctrl_armed,
    output wire                 ctrl_valid,
    output wire                 ctrl_capturing,
    output wire [COUNT_W-1:0]   ctrl_word_count,
    output wire [15:0]          ctrl_stream_type,
    output wire [63:0]          ctrl_sample0,
    output wire [63:0]          ctrl_frame_id,
    output wire [31:0]          ctrl_seq_no,
    output wire [31:0]          ctrl_chan0,
    output wire [63:0]          ctrl_layout_word,
    output wire [31:0]          ctrl_payload_bytes,
    output wire [31:0]          ctrl_route_meta,
    output wire [31:0]          ctrl_rfdc_flags,
    output wire [63:0]          ctrl_rfdc_sample_count,
    output wire [31:0]          ctrl_dac_phase_epoch,
    output wire                 ctrl_overflow,
    output wire                 ctrl_filter_mismatch
);

    localparam [1:0] FILTER_ANY  = 2'd0;
    localparam [1:0] FILTER_SPEC = 2'd1;
    localparam [1:0] FILTER_TIME = 2'd2;
    localparam [15:0] STREAM_SPEC = 16'd0;
    localparam [15:0] STREAM_TIME = 16'd1;
    localparam integer META_W = 448;
    localparam [COUNT_W-1:0] CAPTURE_WORDS_COUNT = CAPTURE_WORDS;

    logic arm_toggle_ctrl;
    logic clear_toggle_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0] arm_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    logic arm_toggle_seen;
    logic clear_toggle_seen;
    wire arm_pulse_data = arm_toggle_sync[2] ^ arm_toggle_seen;
    wire clear_pulse_data = clear_toggle_sync[2] ^ clear_toggle_seen;

    wire [1:0] stream_filter_data;

    wire [COUNT_W-1:0] capture_words_data_raw;
    wire [COUNT_W-1:0] capture_limit_data =
        (capture_words_data_raw == {COUNT_W{1'b0}} || capture_words_data_raw > CAPTURE_WORDS_COUNT) ?
        CAPTURE_WORDS_COUNT : capture_words_data_raw;

    logic armed_data;
    logic valid_data;
    logic capturing_data;
    logic in_packet_data;
    logic skip_packet_data;
    logic overflow_data;
    logic filter_mismatch_data;
    logic [COUNT_W-1:0] word_count_data;
    logic [15:0] stream_type_data;
    logic [63:0] sample0_data;
    logic [63:0] frame_id_data;
    logic [31:0] seq_no_data;
    logic [31:0] chan0_data;
    logic [63:0] layout_word_data;
    logic [31:0] payload_bytes_data;
    logic [31:0] route_meta_data;
    logic [31:0] rfdc_flags_data;
    logic [63:0] rfdc_sample_count_data;
    logic [31:0] dac_phase_epoch_data;
    wire [DATA_W-1:0] ctrl_rd_word_data;
    logic [META_W-1:0] meta_bus_data;
    wire [META_W-1:0] meta_bus_ctrl;
    wire fire = s_axis_tvalid && s_axis_tready;
    wire packet_start = fire && !in_packet_data;
    wire [COUNT_W-1:0] ctrl_rd_addr =
        (ctrl_rd_word[RD_WORD_W-1:1] < CAPTURE_WORDS_COUNT) ?
        ctrl_rd_word[RD_WORD_W-1:1] : {COUNT_W{1'b0}};
    wire capture_write_start = fire && packet_start && armed_data && !valid_data;
    wire capture_write_body = fire && capturing_data && !valid_data && (word_count_data < CAPTURE_WORDS_COUNT);
    wire capture_write_en = capture_write_start || capture_write_body;
    wire [COUNT_W-1:0] capture_write_addr = capture_write_start ? {COUNT_W{1'b0}} : word_count_data;

    function automatic logic filter_matches(
        input [1:0] filter_value,
        input [15:0] stream_value
    );
        begin
            case (filter_value)
                FILTER_ANY:  filter_matches = 1'b1;
                FILTER_SPEC: filter_matches = (stream_value == STREAM_SPEC);
                FILTER_TIME: filter_matches = (stream_value == STREAM_TIME);
                default:     filter_matches = 1'b1;
            endcase
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

    always_comb begin
        meta_bus_data[0 +: 64]    = sample0_data;
        meta_bus_data[64 +: 64]   = frame_id_data;
        meta_bus_data[128 +: 32]  = seq_no_data;
        meta_bus_data[160 +: 32]  = chan0_data;
        meta_bus_data[192 +: 64]  = layout_word_data;
        meta_bus_data[256 +: 32]  = payload_bytes_data;
        meta_bus_data[288 +: 32]  = route_meta_data;
        meta_bus_data[320 +: 32]  = rfdc_flags_data;
        meta_bus_data[352 +: 64]  = rfdc_sample_count_data;
        meta_bus_data[416 +: 32]  = dac_phase_epoch_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_toggle_sync       <= 3'b000;
            clear_toggle_sync     <= 3'b000;
            arm_toggle_seen       <= 1'b0;
            clear_toggle_seen     <= 1'b0;
            armed_data            <= 1'b0;
            valid_data            <= 1'b0;
            capturing_data        <= 1'b0;
            in_packet_data        <= 1'b0;
            skip_packet_data      <= 1'b0;
            overflow_data         <= 1'b0;
            filter_mismatch_data  <= 1'b0;
            word_count_data       <= 8'd0;
            stream_type_data      <= 16'd0;
            sample0_data          <= 64'd0;
            frame_id_data         <= 64'd0;
            seq_no_data           <= 32'd0;
            chan0_data            <= 32'd0;
            layout_word_data      <= 64'd0;
            payload_bytes_data    <= 32'd0;
            route_meta_data       <= 32'd0;
            rfdc_flags_data       <= 32'd0;
            rfdc_sample_count_data <= 64'd0;
            dac_phase_epoch_data  <= 32'd0;
        end else begin
            arm_toggle_sync   <= {arm_toggle_sync[1:0], arm_toggle_ctrl};
            clear_toggle_sync <= {clear_toggle_sync[1:0], clear_toggle_ctrl};
            arm_toggle_seen   <= arm_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];

            if (clear_pulse_data || data_clear_pulse) begin
                if (clear_pulse_data) begin
                    armed_data       <= 1'b0;
                end
                valid_data           <= 1'b0;
                capturing_data       <= 1'b0;
                skip_packet_data     <= 1'b0;
                overflow_data        <= 1'b0;
                filter_mismatch_data <= 1'b0;
                word_count_data      <= 8'd0;
            end

            if (arm_pulse_data) begin
                armed_data           <= 1'b1;
                valid_data           <= 1'b0;
                capturing_data       <= 1'b0;
                skip_packet_data     <= 1'b0;
                overflow_data        <= 1'b0;
                filter_mismatch_data <= 1'b0;
                word_count_data      <= 8'd0;
            end

            if (fire) begin
                if (packet_start && armed_data && !valid_data) begin
                    capturing_data        <= 1'b1;
                    skip_packet_data      <= 1'b0;
                    word_count_data       <= {{(COUNT_W-1){1'b0}}, 1'b1};
                    stream_type_data      <= 16'd0;
                    sample0_data          <= 64'd0;
                    frame_id_data         <= 64'd0;
                    seq_no_data           <= 32'd0;
                    chan0_data            <= 32'd0;
                    layout_word_data      <= 64'd0;
                    payload_bytes_data    <= 32'd0;
                    route_meta_data       <= 32'd0;
                    rfdc_flags_data       <= rfdc_status_flags;
                    rfdc_sample_count_data <= rfdc_sample_count;
                    dac_phase_epoch_data  <= dac_phase_epoch;
                    if ((capture_limit_data <= {{(COUNT_W-1){1'b0}}, 1'b1}) || s_axis_tlast) begin
                        capturing_data <= 1'b0;
                        armed_data     <= 1'b0;
                        valid_data     <= 1'b1;
                    end
                end else if (capturing_data && !valid_data) begin
                    if (word_count_data >= CAPTURE_WORDS_COUNT) begin
                        overflow_data <= 1'b1;
                    end

                    if (word_count_data == {{(COUNT_W-1){1'b0}}, 1'b1}) begin
                        stream_type_data <= s_axis_tdata[47:32];
                        route_meta_data  <= {s_axis_tdata[47:32], 4'd0, route_is_time, route_id, route_endpoint_id, 5'd0};
                        if (!filter_matches(stream_filter_data, s_axis_tdata[47:32])) begin
                            capturing_data       <= 1'b0;
                            skip_packet_data     <= !s_axis_tlast;
                            filter_mismatch_data <= 1'b1;
                            word_count_data      <= {COUNT_W{1'b0}};
                        end
                    end
                    if (word_count_data == {{(COUNT_W-3){1'b0}}, 3'd4}) begin
                        sample0_data <= s_axis_tdata;
                    end
                    if (word_count_data == {{(COUNT_W-3){1'b0}}, 3'd5}) begin
                        frame_id_data <= s_axis_tdata;
                    end
                    if (word_count_data == {{(COUNT_W-3){1'b0}}, 3'd6}) begin
                        seq_no_data <= s_axis_tdata[63:32];
                        chan0_data  <= s_axis_tdata[31:0];
                    end
                    if (word_count_data == {{(COUNT_W-3){1'b0}}, 3'd7}) begin
                        layout_word_data <= s_axis_tdata;
                    end
                    if (word_count_data == {{(COUNT_W-4){1'b0}}, 4'd8}) begin
                        payload_bytes_data <= s_axis_tdata[31:0];
                    end

                    if (filter_matches(stream_filter_data, (word_count_data == {{(COUNT_W-1){1'b0}}, 1'b1}) ? s_axis_tdata[47:32] : stream_type_data)) begin
                        if (s_axis_tlast || ((word_count_data + {{(COUNT_W-1){1'b0}}, 1'b1}) >= capture_limit_data)) begin
                            capturing_data  <= 1'b0;
                            armed_data      <= 1'b0;
                            valid_data      <= 1'b1;
                            word_count_data <= word_count_data + {{(COUNT_W-1){1'b0}}, 1'b1};
                        end else begin
                            word_count_data <= word_count_data + {{(COUNT_W-1){1'b0}}, 1'b1};
                        end
                    end
                end else if (skip_packet_data && s_axis_tlast) begin
                    skip_packet_data <= 1'b0;
                end

                in_packet_data <= !s_axis_tlast;
            end
        end
    end

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(2)
    ) u_filter_cdc (
        .src_clk(ctrl_clk),
        .src_in(stream_filter_ctrl),
        .dest_clk(clk),
        .dest_out(stream_filter_data)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(COUNT_W)
    ) u_capture_words_cdc (
        .src_clk(ctrl_clk),
        .src_in(capture_words_ctrl),
        .dest_clk(clk),
        .dest_out(capture_words_data_raw)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_armed_cdc (
        .src_clk(clk),
        .src_in(armed_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_armed)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_valid_cdc (
        .src_clk(clk),
        .src_in(valid_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_valid)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_capturing_cdc (
        .src_clk(clk),
        .src_in(capturing_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_capturing)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_overflow_cdc (
        .src_clk(clk),
        .src_in(overflow_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_overflow)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_filter_mismatch_cdc (
        .src_clk(clk),
        .src_in(filter_mismatch_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_filter_mismatch)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(COUNT_W)
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
        .WIDTH(16)
    ) u_stream_type_cdc (
        .src_clk(clk),
        .src_in(stream_type_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_stream_type)
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

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(COUNT_W),
        .ADDR_WIDTH_B(COUNT_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(DATA_W),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("independent_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE((1 << COUNT_W) * DATA_W),
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

    assign ctrl_rd_data = ctrl_rd_word[0] ? ctrl_rd_word_data[63:32] : ctrl_rd_word_data[31:0];

    assign ctrl_sample0           = meta_bus_ctrl[0 +: 64];
    assign ctrl_frame_id          = meta_bus_ctrl[64 +: 64];
    assign ctrl_seq_no            = meta_bus_ctrl[128 +: 32];
    assign ctrl_chan0             = meta_bus_ctrl[160 +: 32];
    assign ctrl_layout_word       = meta_bus_ctrl[192 +: 64];
    assign ctrl_payload_bytes     = meta_bus_ctrl[256 +: 32];
    assign ctrl_route_meta        = meta_bus_ctrl[288 +: 32];
    assign ctrl_rfdc_flags        = meta_bus_ctrl[320 +: 32];
    assign ctrl_rfdc_sample_count = meta_bus_ctrl[352 +: 64];
    assign ctrl_dac_phase_epoch   = meta_bus_ctrl[416 +: 32];

endmodule
