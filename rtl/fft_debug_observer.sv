module fft_debug_observer #(
    parameter integer NFFT = 1024,
    parameter integer ADDR_W = 10,
    parameter integer OBS_SAMPLE_RATE_HZ = 61440000
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         ctrl_clk,
    input  wire         ctrl_rst_n,
    input  wire         streaming,
    input  wire [15:0]  active_port_mask,
    input  wire [255:0] s_axis_adc_tdata,
    input  wire         s_axis_adc_tvalid,
    input  wire         ctrl_capture_start_pulse,
    input  wire         ctrl_capture_clear_pulse,
    input  wire [ADDR_W-1:0] ctrl_time_rd_addr,
    input  wire [ADDR_W-1:0] ctrl_fft_rd_addr,
    output logic [31:0] ctrl_time_rd_data,
    output logic [31:0] ctrl_fft_rd_data,
    output logic        ctrl_busy,
    output logic        ctrl_done,
    output logic        ctrl_error,
    output logic [31:0] ctrl_capture_count,
    output logic [31:0] ctrl_peak_bin,
    output logic [31:0] ctrl_peak_power
);

    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_CFG  = 2'd1;
    localparam [1:0] ST_RUN  = 2'd2;

    logic ctrl_start_toggle;
    logic ctrl_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0] start_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    logic start_toggle_seen;
    logic clear_toggle_seen;
    wire  start_event = start_toggle_sync[2] ^ start_toggle_seen;
    wire  clear_event = clear_toggle_sync[2] ^ clear_toggle_seen;

    logic        debug_busy_data;
    logic        debug_done_data;
    logic        debug_error_data;
    logic [31:0] debug_capture_count_data;
    logic [31:0] debug_peak_bin_data;
    logic [31:0] debug_peak_power_data;

    (* ASYNC_REG = "TRUE" *) logic [1:0] busy_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [1:0] done_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [1:0] error_ctrl_sync;
    (* ASYNC_REG = "TRUE" *) logic [31:0] capture_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] peak_bin_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] peak_power_ctrl_meta;

    wire signed [15:0] sample_i = s_axis_adc_tdata[15:0];
    wire signed [15:0] sample_q = active_port_mask[1] ? s_axis_adc_tdata[31:16] : 16'sd0;
    wire [31:0] packed_sample = {sample_q, sample_i};
    wire sample_valid = streaming && s_axis_adc_tvalid;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_start_toggle <= 1'b0;
            ctrl_clear_toggle <= 1'b0;
            busy_ctrl_sync    <= 2'b00;
            done_ctrl_sync    <= 2'b00;
            error_ctrl_sync   <= 2'b00;
            capture_count_ctrl_meta <= 32'd0;
            ctrl_capture_count      <= 32'd0;
            peak_bin_ctrl_meta      <= 32'd0;
            ctrl_peak_bin           <= 32'd0;
            peak_power_ctrl_meta    <= 32'd0;
            ctrl_peak_power         <= 32'd0;
            ctrl_busy               <= 1'b0;
            ctrl_done               <= 1'b0;
            ctrl_error              <= 1'b0;
        end else begin
            if (ctrl_capture_start_pulse) begin
                ctrl_start_toggle <= ~ctrl_start_toggle;
            end
            if (ctrl_capture_clear_pulse) begin
                ctrl_clear_toggle <= ~ctrl_clear_toggle;
            end

            busy_ctrl_sync <= {busy_ctrl_sync[0], debug_busy_data};
            done_ctrl_sync <= {done_ctrl_sync[0], debug_done_data};
            error_ctrl_sync <= {error_ctrl_sync[0], debug_error_data};
            ctrl_busy  <= busy_ctrl_sync[1];
            ctrl_done  <= done_ctrl_sync[1];
            ctrl_error <= error_ctrl_sync[1];

            capture_count_ctrl_meta <= debug_capture_count_data;
            ctrl_capture_count      <= capture_count_ctrl_meta;
            peak_bin_ctrl_meta      <= debug_peak_bin_data;
            ctrl_peak_bin           <= peak_bin_ctrl_meta;
            peak_power_ctrl_meta    <= debug_peak_power_data;
            ctrl_peak_power         <= peak_power_ctrl_meta;
        end
    end

`ifdef T510_SIM_FFT_MODEL
    logic [31:0] time_mem [0:NFFT-1];
    logic [31:0] fft_mem  [0:NFFT-1];
    logic [1:0] state;
    logic [ADDR_W:0] input_count;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_time_rd_data <= 32'd0;
            ctrl_fft_rd_data <= 32'd0;
        end else begin
            ctrl_time_rd_data <= time_mem[ctrl_time_rd_addr];
            ctrl_fft_rd_data <= fft_mem[ctrl_fft_rd_addr];
        end
    end

    task automatic compute_fft_model;
        integer n;
        integer prev_val;
        integer cur_val;
        integer next_val;
        integer peak_idx;
        integer peak_val;
        reg [31:0] peak_power_next;
        reg [31:0] peak_bin_next;
        begin
            peak_power_next = 32'd0;
            peak_bin_next = 32'd0;
            peak_idx = 0;
            peak_val = 0;
            for (n = 0; n < NFFT; n = n + 1) begin
                fft_mem[n] = 32'd0;
            end
            for (n = 1; n < NFFT-1; n = n + 1) begin
                if (peak_idx == 0) begin
                    prev_val = $signed({{16{time_mem[n-1][15]}}, time_mem[n-1][15:0]});
                    cur_val = $signed({{16{time_mem[n][15]}}, time_mem[n][15:0]});
                    next_val = $signed({{16{time_mem[n+1][15]}}, time_mem[n+1][15:0]});
                    if ((cur_val > 0) && (cur_val >= prev_val) && (cur_val > next_val)) begin
                        peak_idx = n;
                        peak_val = cur_val;
                    end
                end
            end
            if (peak_idx != 0) begin
                peak_bin_next = (NFFT + (2 * peak_idx)) / (4 * peak_idx);
                if (peak_bin_next >= NFFT) begin
                    peak_bin_next = 32'd0;
                end
                peak_power_next = peak_val[15:0] * peak_val[15:0];
                fft_mem[peak_bin_next[ADDR_W-1:0]] = peak_power_next;
            end
            debug_peak_power_data = peak_power_next;
            debug_peak_bin_data = peak_bin_next;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            input_count <= {ADDR_W+1{1'b0}};
            debug_busy_data <= 1'b0;
            debug_done_data <= 1'b0;
            debug_error_data <= 1'b0;
            debug_capture_count_data <= 32'd0;
            debug_peak_bin_data <= 32'd0;
            debug_peak_power_data <= 32'd0;
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
                debug_done_data <= 1'b0;
                debug_error_data <= 1'b0;
            end

            case (state)
                ST_IDLE: begin
                    debug_busy_data <= 1'b0;
                    if (start_event) begin
                        input_count <= {ADDR_W+1{1'b0}};
                        debug_busy_data <= 1'b1;
                        debug_done_data <= 1'b0;
                        debug_error_data <= 1'b0;
                        debug_capture_count_data <= 32'd0;
                        debug_peak_bin_data <= 32'd0;
                        debug_peak_power_data <= 32'd0;
                        state <= ST_RUN;
                    end
                end

                ST_RUN: begin
                    if (sample_valid) begin
                        time_mem[input_count[ADDR_W-1:0]] = packed_sample;
                        debug_capture_count_data <= {21'd0, input_count} + 32'd1;
                        if (input_count == NFFT-1) begin
                            compute_fft_model();
                            debug_busy_data <= 1'b0;
                            debug_done_data <= 1'b1;
                            input_count <= {ADDR_W+1{1'b0}};
                            state <= ST_IDLE;
                        end else begin
                            input_count <= input_count + 1'b1;
                        end
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end
`else
    logic [1:0] state;
    logic [ADDR_W:0] input_count;
    logic [ADDR_W:0] output_count;
    logic time_we;
    logic fft_we;
    logic [ADDR_W-1:0] time_wr_addr;
    logic [ADDR_W-1:0] fft_wr_addr;
    logic [31:0] time_wr_data;
    logic [31:0] fft_wr_data;
    wire [0:0] time_wea = time_we;
    wire [0:0] fft_wea = fft_we;

    wire [15:0] fft_config_tdata = 16'h0001;
    wire        fft_config_tvalid = (state == ST_CFG);
    wire        fft_config_tready;
    wire [31:0] fft_s_axis_tdata = packed_sample;
    wire        fft_s_axis_tvalid = (state == ST_RUN) && (input_count < NFFT) && sample_valid;
    wire        fft_s_axis_tready;
    wire        fft_s_axis_tlast = (input_count == NFFT-1);
    wire [31:0] fft_m_axis_tdata;
    wire        fft_m_axis_tvalid;
    wire        fft_m_axis_tlast;
    wire        event_frame_started;
    wire        event_tlast_unexpected;
    wire        event_tlast_missing;
    wire        event_data_in_channel_halt;

    wire fft_input_fire = fft_s_axis_tvalid && fft_s_axis_tready;

    wire signed [15:0] fft_re = fft_m_axis_tdata[15:0];
    wire signed [15:0] fft_im = fft_m_axis_tdata[31:16];
    wire signed [31:0] fft_re_sq = fft_re * fft_re;
    wire signed [31:0] fft_im_sq = fft_im * fft_im;
    wire [32:0] fft_power_full = {1'b0, fft_re_sq[31:0]} + {1'b0, fft_im_sq[31:0]};
    wire [31:0] fft_power = fft_power_full[32] ? 32'hffff_ffff : fft_power_full[31:0];

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(ADDR_W),
        .ADDR_WIDTH_B(ADDR_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(32),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("independent_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE(NFFT * 32),
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
    ) u_time_bram (
        .dbiterrb(),
        .doutb(ctrl_time_rd_data),
        .sbiterrb(),
        .addra(time_wr_addr),
        .addrb(ctrl_time_rd_addr),
        .clka(clk),
        .clkb(ctrl_clk),
        .dina(time_wr_data),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!ctrl_rst_n),
        .sleep(1'b0),
        .wea(time_wea)
    );

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(ADDR_W),
        .ADDR_WIDTH_B(ADDR_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(32),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("independent_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE(NFFT * 32),
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
    ) u_fft_bram (
        .dbiterrb(),
        .doutb(ctrl_fft_rd_data),
        .sbiterrb(),
        .addra(fft_wr_addr),
        .addrb(ctrl_fft_rd_addr),
        .clka(clk),
        .clkb(ctrl_clk),
        .dina(fft_wr_data),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!ctrl_rst_n),
        .sleep(1'b0),
        .wea(fft_wea)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            input_count <= {ADDR_W+1{1'b0}};
            output_count <= {ADDR_W+1{1'b0}};
            time_we <= 1'b0;
            fft_we <= 1'b0;
            time_wr_addr <= {ADDR_W{1'b0}};
            fft_wr_addr <= {ADDR_W{1'b0}};
            time_wr_data <= 32'd0;
            fft_wr_data <= 32'd0;
            debug_busy_data <= 1'b0;
            debug_done_data <= 1'b0;
            debug_error_data <= 1'b0;
            debug_capture_count_data <= 32'd0;
            debug_peak_bin_data <= 32'd0;
            debug_peak_power_data <= 32'd0;
            start_toggle_sync <= 3'b000;
            clear_toggle_sync <= 3'b000;
            start_toggle_seen <= 1'b0;
            clear_toggle_seen <= 1'b0;
        end else begin
            time_we <= 1'b0;
            fft_we <= 1'b0;
            start_toggle_sync <= {start_toggle_sync[1:0], ctrl_start_toggle};
            clear_toggle_sync <= {clear_toggle_sync[1:0], ctrl_clear_toggle};
            start_toggle_seen <= start_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];

            if (clear_event) begin
                debug_done_data <= 1'b0;
                debug_error_data <= 1'b0;
            end

            if (event_tlast_unexpected || event_tlast_missing) begin
                debug_error_data <= 1'b1;
            end

            case (state)
                ST_IDLE: begin
                    debug_busy_data <= 1'b0;
                    if (start_event) begin
                        input_count <= {ADDR_W+1{1'b0}};
                        output_count <= {ADDR_W+1{1'b0}};
                        debug_busy_data <= 1'b1;
                        debug_done_data <= 1'b0;
                        debug_error_data <= 1'b0;
                        debug_capture_count_data <= 32'd0;
                        debug_peak_bin_data <= 32'd0;
                        debug_peak_power_data <= 32'd0;
                        state <= ST_CFG;
                    end
                end

                ST_CFG: begin
                    if (fft_config_tready) begin
                        state <= ST_RUN;
                    end
                end

                ST_RUN: begin
                    if (fft_input_fire) begin
                        time_we <= 1'b1;
                        time_wr_addr <= input_count[ADDR_W-1:0];
                        time_wr_data <= packed_sample;
                        debug_capture_count_data <= {21'd0, input_count} + 32'd1;
                        input_count <= input_count + 1'b1;
                    end

                    if (fft_m_axis_tvalid) begin
                        fft_we <= 1'b1;
                        fft_wr_addr <= output_count[ADDR_W-1:0];
                        fft_wr_data <= fft_power;
                        if (fft_power > debug_peak_power_data) begin
                            debug_peak_power_data <= fft_power;
                            debug_peak_bin_data <= {21'd0, output_count};
                        end
                        if (fft_m_axis_tlast != (output_count == NFFT-1)) begin
                            debug_error_data <= 1'b1;
                        end
                        if (output_count == NFFT-1) begin
                            debug_busy_data <= 1'b0;
                            debug_done_data <= 1'b1;
                            state <= ST_IDLE;
                        end
                        output_count <= output_count + 1'b1;
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

    t510_debug_xfft u_debug_xfft (
        .aclk(clk),
        .s_axis_config_tdata(fft_config_tdata),
        .s_axis_config_tvalid(fft_config_tvalid),
        .s_axis_config_tready(fft_config_tready),
        .s_axis_data_tdata(fft_s_axis_tdata),
        .s_axis_data_tvalid(fft_s_axis_tvalid),
        .s_axis_data_tready(fft_s_axis_tready),
        .s_axis_data_tlast(fft_s_axis_tlast),
        .m_axis_data_tdata(fft_m_axis_tdata),
        .m_axis_data_tvalid(fft_m_axis_tvalid),
        .m_axis_data_tlast(fft_m_axis_tlast),
        .event_frame_started(event_frame_started),
        .event_tlast_unexpected(event_tlast_unexpected),
        .event_tlast_missing(event_tlast_missing),
        .event_data_in_channel_halt(event_data_in_channel_halt)
    );
`endif

endmodule
