module multi_preview_observer #(
    parameter integer NINPUT = 8,
    parameter integer NSAMP  = 1024,
    parameter integer ADDR_W = 10
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         ctrl_clk,
    input  wire                         ctrl_rst_n,
    input  wire                         streaming,
    input  wire [NINPUT-1:0]            input_mask,
    input  wire [255:0]                 s_axis_adc_tdata0,
    input  wire [255:0]                 s_axis_adc_tdata1,
    input  wire [255:0]                 s_axis_adc_tdata2,
    input  wire [255:0]                 s_axis_adc_tdata3,
    input  wire [63:0]                  s_axis_adc_sample0,
    input  wire                         s_axis_adc_tvalid,
    input  wire                         ctrl_capture_start_pulse,
    input  wire                         ctrl_capture_clear_pulse,
    input  wire [2:0]                   ctrl_rd_input,
    input  wire [ADDR_W-1:0]            ctrl_rd_addr,
    output logic [31:0]                 ctrl_rd_data,
    output logic                        ctrl_busy,
    output logic                        ctrl_done,
    output logic                        ctrl_error,
    output logic [31:0]                 ctrl_capture_count,
    output logic [63:0]                 ctrl_sample0
);

    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_RUN  = 2'd1;

    logic ctrl_start_toggle;
    logic ctrl_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0] start_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    logic start_toggle_seen;
    logic clear_toggle_seen;
    wire start_event = start_toggle_sync[2] ^ start_toggle_seen;
    wire clear_event = clear_toggle_sync[2] ^ clear_toggle_seen;

    logic [1:0] state;
    logic [ADDR_W:0] sample_index;
    logic [NINPUT-1:0] active_mask_data;
    logic busy_data;
    logic done_data;
    logic error_data;
    logic [31:0] capture_count_data;
    logic [63:0] sample0_data;

    (* ASYNC_REG = "TRUE" *) logic [1:0] busy_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [1:0] done_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [1:0] error_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [31:0] capture_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] sample0_ctrl_meta;

    // RFDC produces a continuous observation stream even while science output is
    // stopped.  Calibration previews are deliberately captured in that quiescent
    // state, so capture validity must not be gated by the science FSM.
    wire preview_write_fire = (state == ST_RUN) && s_axis_adc_tvalid;
    wire [ADDR_W-3:0] preview_wr_addr = sample_index[ADDR_W-1:2];
    wire [ADDR_W-3:0] preview_rd_addr = ctrl_rd_addr[ADDR_W-1:2];
    wire [1:0] preview_rd_lane = ctrl_rd_addr[1:0];
    wire [NINPUT-1:0] preview_wea;
    wire [NINPUT*32-1:0] preview_wr_data_bus [0:3];
    wire [NINPUT*32-1:0] preview_rd_data_bus [0:3];

    function automatic [31:0] complex_pair(input [255:0] bus, input integer channel);
        begin
            complex_pair = bus[channel*32 +: 32];
        end
    endfunction

    genvar lane_idx;
    genvar input_idx;
    generate
        for (lane_idx = 0; lane_idx < 4; lane_idx = lane_idx + 1) begin : g_lane_pack
            for (input_idx = 0; input_idx < NINPUT; input_idx = input_idx + 1) begin : g_input_pack
                if (lane_idx == 0) begin : g_l0
                    assign preview_wr_data_bus[lane_idx][input_idx*32 +: 32] =
                        complex_pair(s_axis_adc_tdata0, input_idx);
                end else if (lane_idx == 1) begin : g_l1
                    assign preview_wr_data_bus[lane_idx][input_idx*32 +: 32] =
                        complex_pair(s_axis_adc_tdata1, input_idx);
                end else if (lane_idx == 2) begin : g_l2
                    assign preview_wr_data_bus[lane_idx][input_idx*32 +: 32] =
                        complex_pair(s_axis_adc_tdata2, input_idx);
                end else begin : g_l3
                    assign preview_wr_data_bus[lane_idx][input_idx*32 +: 32] =
                        complex_pair(s_axis_adc_tdata3, input_idx);
                end
            end
        end

        for (input_idx = 0; input_idx < NINPUT; input_idx = input_idx + 1) begin : g_preview_bram
            assign preview_wea[input_idx] = preview_write_fire && active_mask_data[input_idx];
            for (lane_idx = 0; lane_idx < 4; lane_idx = lane_idx + 1) begin : g_lane_bram
                xpm_memory_sdpram #(
                    .ADDR_WIDTH_A(ADDR_W-2),
                    .ADDR_WIDTH_B(ADDR_W-2),
                    .AUTO_SLEEP_TIME(0),
                    .BYTE_WRITE_WIDTH_A(32),
                    .CASCADE_HEIGHT(0),
                    .CLOCKING_MODE("independent_clock"),
                    .ECC_MODE("no_ecc"),
                    .MEMORY_INIT_FILE("none"),
                    .MEMORY_INIT_PARAM("0"),
                    .MEMORY_OPTIMIZATION("true"),
                    .MEMORY_PRIMITIVE("block"),
                    .MEMORY_SIZE((NSAMP / 4) * 32),
                    .MESSAGE_CONTROL(0),
                    .READ_DATA_WIDTH_B(32),
                    .READ_LATENCY_B(1),
                    .READ_RESET_VALUE_B("0"),
                    .RST_MODE_A("SYNC"),
                    .RST_MODE_B("SYNC"),
                    .USE_EMBEDDED_CONSTRAINT(0),
                    .USE_MEM_INIT(0),
                    .WAKEUP_TIME("disable_sleep"),
                    .WRITE_DATA_WIDTH_A(32),
                    .WRITE_MODE_B("read_first")
                ) u_preview_bram (
                    .dbiterrb(),
                    .doutb(preview_rd_data_bus[lane_idx][input_idx*32 +: 32]),
                    .sbiterrb(),
                    .addra(preview_wr_addr),
                    .addrb(preview_rd_addr),
                    .clka(clk),
                    .clkb(ctrl_clk),
                    .dina(preview_wr_data_bus[lane_idx][input_idx*32 +: 32]),
                    .ena(1'b1),
                    .enb(1'b1),
                    .injectdbiterra(1'b0),
                    .injectsbiterra(1'b0),
                    .regceb(1'b1),
                    .rstb(!ctrl_rst_n),
                    .sleep(1'b0),
                    .wea(preview_wea[input_idx])
                );
            end
        end
    endgenerate

    always_comb begin
        ctrl_rd_data = 32'd0;
        if (ctrl_rd_input < NINPUT) begin
            ctrl_rd_data = preview_rd_data_bus[preview_rd_lane][ctrl_rd_input*32 +: 32];
        end
    end

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_start_toggle <= 1'b0;
            ctrl_clear_toggle <= 1'b0;
            busy_ctrl_sync <= 2'b00;
            done_ctrl_sync <= 2'b00;
            error_ctrl_sync <= 2'b00;
            capture_count_ctrl_meta <= 32'd0;
            sample0_ctrl_meta <= 64'd0;
            ctrl_busy <= 1'b0;
            ctrl_done <= 1'b0;
            ctrl_error <= 1'b0;
            ctrl_capture_count <= 32'd0;
            ctrl_sample0 <= 64'd0;
        end else begin
            if (ctrl_capture_start_pulse) begin
                ctrl_start_toggle <= ~ctrl_start_toggle;
            end
            if (ctrl_capture_clear_pulse) begin
                ctrl_clear_toggle <= ~ctrl_clear_toggle;
            end
            busy_ctrl_sync <= {busy_ctrl_sync[0], busy_data};
            done_ctrl_sync <= {done_ctrl_sync[0], done_data};
            error_ctrl_sync <= {error_ctrl_sync[0], error_data};
            ctrl_busy <= busy_ctrl_sync[1];
            ctrl_done <= done_ctrl_sync[1];
            ctrl_error <= error_ctrl_sync[1];
            capture_count_ctrl_meta <= capture_count_data;
            ctrl_capture_count <= capture_count_ctrl_meta;
            sample0_ctrl_meta <= sample0_data;
            ctrl_sample0 <= sample0_ctrl_meta;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            sample_index <= {ADDR_W+1{1'b0}};
            active_mask_data <= {{NINPUT-1{1'b0}}, 1'b1};
            busy_data <= 1'b0;
            done_data <= 1'b0;
            error_data <= 1'b0;
            capture_count_data <= 32'd0;
            sample0_data <= 64'd0;
            start_toggle_sync <= 3'b000;
            clear_toggle_sync <= 3'b000;
            start_toggle_seen <= 1'b0;
            clear_toggle_seen <= 1'b0;
        end else begin
            start_toggle_sync <= {start_toggle_sync[1:0], ctrl_start_toggle};
            clear_toggle_sync <= {clear_toggle_sync[1:0], ctrl_clear_toggle};
            start_toggle_seen <= start_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];
            if (clear_event) begin
                done_data <= 1'b0;
                error_data <= 1'b0;
                capture_count_data <= 32'd0;
            end
            case (state)
                ST_IDLE: begin
                    busy_data <= 1'b0;
                    if (start_event) begin
                        active_mask_data <= (input_mask == {NINPUT{1'b0}}) ?
                            {{NINPUT-1{1'b0}}, 1'b1} : input_mask;
                        sample_index <= {ADDR_W+1{1'b0}};
                        capture_count_data <= 32'd0;
                        sample0_data <= 64'd0;
                        done_data <= 1'b0;
                        error_data <= 1'b0;
                        busy_data <= 1'b1;
                        state <= ST_RUN;
                    end
                end
                ST_RUN: begin
                    if (preview_write_fire) begin
                        if (sample_index == 0) begin
                            sample0_data <= s_axis_adc_sample0;
                        end
                        capture_count_data <= {21'd0, sample_index} + 32'd4;
                        if (sample_index >= NSAMP-4) begin
                            busy_data <= 1'b0;
                            done_data <= 1'b1;
                            sample_index <= {ADDR_W+1{1'b0}};
                            state <= ST_IDLE;
                        end else begin
                            sample_index <= sample_index + 3'd4;
                        end
                    end
                end
                default: state <= ST_IDLE;
            endcase
        end
    end

endmodule
