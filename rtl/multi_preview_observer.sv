module multi_preview_observer #(
    parameter integer NINPUT = 8,
    parameter integer NSAMP  = 1024,
    parameter integer ADDR_W = 10,
    parameter bit     PRODUCTION_27H = 1'b0
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
    input  wire [1:0]                   audit_source_select,
    input  wire                         audit_event_enable,
    input  wire                         audit_freeze_on_event,
    input  wire                         audit_clear_pulse,
    input  wire [15:0]                  audit_event_threshold,
    input  wire [31:0]                  rfdc_status_flags,
    input  wire [31:0]                  dac_phase_epoch_ctrl,
    input  wire                         ctrl_capture_start_pulse,
    input  wire                         ctrl_capture_clear_pulse,
    input  wire [2:0]                   ctrl_rd_input,
    input  wire [ADDR_W-1:0]            ctrl_rd_addr,
    input  wire [7:0]                   ctrl_event_rd_addr,
    output logic [31:0]                 ctrl_rd_data,
    output logic [31:0]                 ctrl_event_rd_data,
    output logic                        ctrl_busy,
    output logic                        ctrl_done,
    output logic                        ctrl_error,
    output logic [31:0]                 ctrl_capture_count,
    output logic [63:0]                 ctrl_sample0,
    output logic [31:0]                 ctrl_audit_status,
    output logic [31:0]                 ctrl_audit_start_count,
    output logic [31:0]                 ctrl_audit_first_count,
    output logic [31:0]                 ctrl_audit_done_count,
    output logic [63:0]                 ctrl_audit_start_sample0,
    output logic [63:0]                 ctrl_audit_first_sample0,
    output logic [63:0]                 ctrl_audit_done_sample0,
    output logic [31:0]                 ctrl_audit_start_to_first_latency,
    output logic [31:0]                 ctrl_audit_capture_beats,
    output logic [31:0]                 ctrl_audit_valid_gap_count,
    output logic [31:0]                 ctrl_audit_sample0_error_count,
    output logic [63:0]                 ctrl_event_sample0,
    output logic [31:0]                 ctrl_event_max_code,
    output logic [31:0]                 ctrl_event_info,
    output logic [31:0]                 ctrl_event_rfdc_flags,
    output logic [31:0]                 ctrl_event_dac_phase_epoch
);

    localparam [1:0] ST_IDLE = 2'd0;
    localparam [1:0] ST_RUN  = 2'd1;
    localparam [1:0] SRC_RFDC = 2'd0;
    localparam [1:0] SRC_DDS  = 2'd1;
    localparam [1:0] SRC_RAMP = 2'd2;

    logic ctrl_start_toggle;
    logic ctrl_clear_toggle;
    logic ctrl_audit_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0] start_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0] audit_clear_toggle_sync;
    logic start_toggle_seen;
    logic clear_toggle_seen;
    logic audit_clear_toggle_seen;
    wire  start_event = start_toggle_sync[2] ^ start_toggle_seen;
    wire  clear_event = clear_toggle_sync[2] ^ clear_toggle_seen;
    wire  audit_clear_event = audit_clear_toggle_sync[2] ^ audit_clear_toggle_seen;

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

    (* ASYNC_REG = "TRUE" *) logic [1:0] audit_source_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0] audit_source_data;
    (* ASYNC_REG = "TRUE" *) logic audit_event_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic audit_event_enable_data;
    (* ASYNC_REG = "TRUE" *) logic audit_freeze_meta;
    (* ASYNC_REG = "TRUE" *) logic audit_freeze_data;
    (* ASYNC_REG = "TRUE" *) logic [15:0] audit_threshold_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] audit_threshold_data;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_phase_epoch_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] dac_phase_epoch_data;

    logic [63:0] internal_sample0;
    logic [31:0] internal_phase;

    wire [1:0] selected_source = PRODUCTION_27H ? SRC_RFDC :
                                  ((audit_source_data == SRC_RAMP) ? SRC_RAMP :
                                   (audit_source_data == SRC_DDS)  ? SRC_DDS  : SRC_RFDC);
    wire        synthetic_valid = !PRODUCTION_27H && streaming;
    wire [63:0] synthetic_sample0 = internal_sample0;

    wire [255:0] dds_tdata0;
    wire [255:0] dds_tdata1;
    wire [255:0] dds_tdata2;
    wire [255:0] dds_tdata3;
    wire [255:0] ramp_tdata0;
    wire [255:0] ramp_tdata1;
    wire [255:0] ramp_tdata2;
    wire [255:0] ramp_tdata3;

    wire [255:0] source_tdata0 = (selected_source == SRC_DDS)  ? dds_tdata0  :
                                  (selected_source == SRC_RAMP) ? ramp_tdata0 : s_axis_adc_tdata0;
    wire [255:0] source_tdata1 = (selected_source == SRC_DDS)  ? dds_tdata1  :
                                  (selected_source == SRC_RAMP) ? ramp_tdata1 : s_axis_adc_tdata1;
    wire [255:0] source_tdata2 = (selected_source == SRC_DDS)  ? dds_tdata2  :
                                  (selected_source == SRC_RAMP) ? ramp_tdata2 : s_axis_adc_tdata2;
    wire [255:0] source_tdata3 = (selected_source == SRC_DDS)  ? dds_tdata3  :
                                  (selected_source == SRC_RAMP) ? ramp_tdata3 : s_axis_adc_tdata3;
    wire [63:0]  source_sample0 = (selected_source == SRC_RFDC) ? s_axis_adc_sample0 : synthetic_sample0;
    wire         source_tvalid  = (selected_source == SRC_RFDC) ? s_axis_adc_tvalid  : synthetic_valid;

    wire                  preview_write_fire = (state == ST_RUN) && streaming && source_tvalid;
    wire [ADDR_W-3:0]     preview_wr_addr = sample_index[ADDR_W-1:2];
    wire [ADDR_W-3:0]     preview_rd_addr = ctrl_rd_addr[ADDR_W-1:2];
    wire [1:0]            preview_rd_lane = ctrl_rd_addr[1:0];
    wire [NINPUT-1:0]     preview_wea;
    wire [NINPUT*32-1:0]  preview_wr_data_bus [0:3];
    wire [NINPUT*32-1:0]  preview_rd_data_bus [0:3];

    logic [31:0] audit_start_count_data;
    logic [31:0] audit_first_count_data;
    logic [31:0] audit_done_count_data;
    logic [63:0] audit_start_sample0_data;
    logic [63:0] audit_first_sample0_data;
    logic [63:0] audit_done_sample0_data;
    logic [31:0] audit_latency_counter;
    logic [31:0] audit_start_to_first_latency_data;
    logic [31:0] audit_capture_beats_data;
    logic [31:0] audit_valid_gap_count_data;
    logic [31:0] audit_sample0_error_count_data;
    logic [63:0] audit_last_sample0;
    logic        audit_have_last_sample0;
    logic        audit_first_seen;
    logic        audit_event_valid_data;
    logic        audit_event_active_data;
    logic        audit_event_overflow_data;
    logic        audit_sample0_nonmonotonic_data;
    logic        audit_valid_gap_seen_data;
    logic        audit_sample0_error_seen_data;
    logic [63:0] event_sample0_data;
    logic [31:0] event_max_code_data;
    logic [31:0] event_info_data;
    logic [31:0] event_rfdc_flags_data;
    logic [31:0] event_dac_phase_epoch_data;
    logic [7:0]  event_wr_index;
    logic [31:0] event_buffer [0:255];

    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_status_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_start_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_first_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_done_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] audit_start_sample0_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] audit_first_sample0_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] audit_done_sample0_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_start_to_first_latency_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_capture_beats_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_valid_gap_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] audit_sample0_error_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] event_sample0_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] event_max_code_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] event_info_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] event_rfdc_flags_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] event_dac_phase_epoch_meta;

    wire [31:0] audit_status_data = {
        24'd0,
        selected_source,
        audit_sample0_error_seen_data,
        audit_valid_gap_seen_data,
        audit_sample0_nonmonotonic_data,
        audit_event_overflow_data,
        audit_event_active_data,
        audit_event_valid_data
    };

    function automatic [31:0] complex_pair(
        input [255:0] data,
        input integer idx
    );
        logic signed [15:0] i_sample;
        logic signed [15:0] q_sample;
        begin
            i_sample = data[(idx * 32) +: 16];
            q_sample = data[(idx * 32 + 16) +: 16];
            complex_pair = {q_sample, i_sample};
        end
    endfunction

    function automatic [16:0] abs16(input [15:0] raw);
        begin
            abs16 = raw[15] ? ({1'b0, ~raw} + 17'd1) : {1'b0, raw};
        end
    endfunction

    function automatic [16:0] max_abs_word(input [31:0] word);
        reg [16:0] i_abs;
        reg [16:0] q_abs;
        begin
            i_abs = abs16(word[15:0]);
            q_abs = abs16(word[31:16]);
            max_abs_word = (i_abs >= q_abs) ? i_abs : q_abs;
        end
    endfunction

    function automatic [31:0] ramp_word(input [63:0] base, input integer lane, input integer ch);
        reg [15:0] i_sample;
        reg [15:0] q_sample;
        begin
            i_sample = base[15:0] + lane[15:0] + (ch[15:0] << 8);
            q_sample = 16'h8000 ^ i_sample;
            ramp_word = {q_sample, i_sample};
        end
    endfunction

    function automatic signed [15:0] dds_sin16(input [3:0] idx);
        begin
            case (idx)
                4'h0: dds_sin16 = 16'sd0;
                4'h1: dds_sin16 = 16'sd1567;
                4'h2: dds_sin16 = 16'sd2896;
                4'h3: dds_sin16 = 16'sd3784;
                4'h4: dds_sin16 = 16'sd4096;
                4'h5: dds_sin16 = 16'sd3784;
                4'h6: dds_sin16 = 16'sd2896;
                4'h7: dds_sin16 = 16'sd1567;
                4'h8: dds_sin16 = 16'sd0;
                4'h9: dds_sin16 = -16'sd1567;
                4'ha: dds_sin16 = -16'sd2896;
                4'hb: dds_sin16 = -16'sd3784;
                4'hc: dds_sin16 = -16'sd4096;
                4'hd: dds_sin16 = -16'sd3784;
                4'he: dds_sin16 = -16'sd2896;
                default: dds_sin16 = -16'sd1567;
            endcase
        end
    endfunction

    function automatic [31:0] dds_word(input [31:0] phase, input integer lane, input integer ch);
        reg [31:0] ph;
        reg [3:0] phase_idx;
        reg signed [15:0] i_sample;
        reg signed [15:0] q_sample;
        begin
            ph = phase + (lane[31:0] << 28) + (ch[31:0] << 24);
            phase_idx = ph[31:28];
            i_sample = dds_sin16(phase_idx);
            q_sample = dds_sin16(phase_idx + 4'd4);
            dds_word = {q_sample[15:0], i_sample[15:0]};
        end
    endfunction

    function automatic [255:0] make_ramp_bus(input [63:0] base, input integer lane);
        integer idx;
        begin
            make_ramp_bus = 256'd0;
            for (idx = 0; idx < NINPUT; idx = idx + 1) begin
                make_ramp_bus[idx*32 +: 32] = ramp_word(base, lane, idx);
            end
        end
    endfunction

    function automatic [255:0] make_dds_bus(input [31:0] phase, input integer lane);
        integer idx;
        begin
            make_dds_bus = 256'd0;
            for (idx = 0; idx < NINPUT; idx = idx + 1) begin
                make_dds_bus[idx*32 +: 32] = dds_word(phase, lane, idx);
            end
        end
    endfunction

    assign dds_tdata0 = PRODUCTION_27H ? 256'd0 : make_dds_bus(internal_phase, 0);
    assign dds_tdata1 = PRODUCTION_27H ? 256'd0 : make_dds_bus(internal_phase, 1);
    assign dds_tdata2 = PRODUCTION_27H ? 256'd0 : make_dds_bus(internal_phase, 2);
    assign dds_tdata3 = PRODUCTION_27H ? 256'd0 : make_dds_bus(internal_phase, 3);
    assign ramp_tdata0 = PRODUCTION_27H ? 256'd0 : make_ramp_bus(synthetic_sample0, 0);
    assign ramp_tdata1 = PRODUCTION_27H ? 256'd0 : make_ramp_bus(synthetic_sample0, 1);
    assign ramp_tdata2 = PRODUCTION_27H ? 256'd0 : make_ramp_bus(synthetic_sample0, 2);
    assign ramp_tdata3 = PRODUCTION_27H ? 256'd0 : make_ramp_bus(synthetic_sample0, 3);

    wire [31:0] event_word0 = PRODUCTION_27H ? 32'd0 : complex_pair(source_tdata0, 0);
    wire [31:0] event_word1 = PRODUCTION_27H ? 32'd0 : complex_pair(source_tdata1, 0);
    wire [31:0] event_word2 = PRODUCTION_27H ? 32'd0 : complex_pair(source_tdata2, 0);
    wire [31:0] event_word3 = PRODUCTION_27H ? 32'd0 : complex_pair(source_tdata3, 0);
    wire [16:0] event_abs0 = PRODUCTION_27H ? 17'd0 : max_abs_word(event_word0);
    wire [16:0] event_abs1 = PRODUCTION_27H ? 17'd0 : max_abs_word(event_word1);
    wire [16:0] event_abs2 = PRODUCTION_27H ? 17'd0 : max_abs_word(event_word2);
    wire [16:0] event_abs3 = PRODUCTION_27H ? 17'd0 : max_abs_word(event_word3);
    wire [16:0] event_max01 = (event_abs0 >= event_abs1) ? event_abs0 : event_abs1;
    wire [16:0] event_max23 = (event_abs2 >= event_abs3) ? event_abs2 : event_abs3;
    wire [16:0] event_max_abs = (event_max01 >= event_max23) ? event_max01 : event_max23;
    wire [1:0] event_max_lane =
        (event_abs0 >= event_abs1 && event_abs0 >= event_abs2 && event_abs0 >= event_abs3) ? 2'd0 :
        (event_abs1 >= event_abs2 && event_abs1 >= event_abs3) ? 2'd1 :
        (event_abs2 >= event_abs3) ? 2'd2 : 2'd3;
    wire audit_trigger_hit = !PRODUCTION_27H && audit_event_enable_data && streaming && source_tvalid &&
                             (event_max_abs >= {1'b0, audit_threshold_data}) &&
                             (audit_threshold_data != 16'd0);

    genvar lane_idx;
    genvar mem_idx;
    generate
        for (lane_idx = 0; lane_idx < 4; lane_idx = lane_idx + 1) begin : g_lane_pack
            for (mem_idx = 0; mem_idx < NINPUT; mem_idx = mem_idx + 1) begin : g_lane_input_pack
                if (lane_idx == 0) begin : g_l0
                    assign preview_wr_data_bus[lane_idx][mem_idx*32 +: 32] = complex_pair(source_tdata0, mem_idx);
                end else if (lane_idx == 1) begin : g_l1
                    assign preview_wr_data_bus[lane_idx][mem_idx*32 +: 32] = complex_pair(source_tdata1, mem_idx);
                end else if (lane_idx == 2) begin : g_l2
                    assign preview_wr_data_bus[lane_idx][mem_idx*32 +: 32] = complex_pair(source_tdata2, mem_idx);
                end else begin : g_l3
                    assign preview_wr_data_bus[lane_idx][mem_idx*32 +: 32] = complex_pair(source_tdata3, mem_idx);
                end
            end
        end
    endgenerate

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_start_toggle <= 1'b0;
            ctrl_clear_toggle <= 1'b0;
            ctrl_audit_clear_toggle <= 1'b0;
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
            audit_status_meta <= 32'd0;
            ctrl_audit_status <= 32'd0;
            audit_start_count_meta <= 32'd0;
            ctrl_audit_start_count <= 32'd0;
            audit_first_count_meta <= 32'd0;
            ctrl_audit_first_count <= 32'd0;
            audit_done_count_meta <= 32'd0;
            ctrl_audit_done_count <= 32'd0;
            audit_start_sample0_meta <= 64'd0;
            ctrl_audit_start_sample0 <= 64'd0;
            audit_first_sample0_meta <= 64'd0;
            ctrl_audit_first_sample0 <= 64'd0;
            audit_done_sample0_meta <= 64'd0;
            ctrl_audit_done_sample0 <= 64'd0;
            audit_start_to_first_latency_meta <= 32'd0;
            ctrl_audit_start_to_first_latency <= 32'd0;
            audit_capture_beats_meta <= 32'd0;
            ctrl_audit_capture_beats <= 32'd0;
            audit_valid_gap_count_meta <= 32'd0;
            ctrl_audit_valid_gap_count <= 32'd0;
            audit_sample0_error_count_meta <= 32'd0;
            ctrl_audit_sample0_error_count <= 32'd0;
            event_sample0_meta <= 64'd0;
            ctrl_event_sample0 <= 64'd0;
            event_max_code_meta <= 32'd0;
            ctrl_event_max_code <= 32'd0;
            event_info_meta <= 32'd0;
            ctrl_event_info <= 32'd0;
            event_rfdc_flags_meta <= 32'd0;
            ctrl_event_rfdc_flags <= 32'd0;
            event_dac_phase_epoch_meta <= 32'd0;
            ctrl_event_dac_phase_epoch <= 32'd0;
            ctrl_event_rd_data <= 32'd0;
        end else begin
            if (ctrl_capture_start_pulse) begin
                ctrl_start_toggle <= ~ctrl_start_toggle;
            end
            if (ctrl_capture_clear_pulse) begin
                ctrl_clear_toggle <= ~ctrl_clear_toggle;
            end
            if (audit_clear_pulse) begin
                ctrl_audit_clear_toggle <= ~ctrl_audit_clear_toggle;
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

            if (PRODUCTION_27H) begin
                audit_status_meta <= 32'd0;
                ctrl_audit_status <= 32'd0;
                audit_start_count_meta <= 32'd0;
                ctrl_audit_start_count <= 32'd0;
                audit_first_count_meta <= 32'd0;
                ctrl_audit_first_count <= 32'd0;
                audit_done_count_meta <= 32'd0;
                ctrl_audit_done_count <= 32'd0;
                audit_start_sample0_meta <= 64'd0;
                ctrl_audit_start_sample0 <= 64'd0;
                audit_first_sample0_meta <= 64'd0;
                ctrl_audit_first_sample0 <= 64'd0;
                audit_done_sample0_meta <= 64'd0;
                ctrl_audit_done_sample0 <= 64'd0;
                audit_start_to_first_latency_meta <= 32'd0;
                ctrl_audit_start_to_first_latency <= 32'd0;
                audit_capture_beats_meta <= 32'd0;
                ctrl_audit_capture_beats <= 32'd0;
                audit_valid_gap_count_meta <= 32'd0;
                ctrl_audit_valid_gap_count <= 32'd0;
                audit_sample0_error_count_meta <= 32'd0;
                ctrl_audit_sample0_error_count <= 32'd0;
                event_sample0_meta <= 64'd0;
                ctrl_event_sample0 <= 64'd0;
                event_max_code_meta <= 32'd0;
                ctrl_event_max_code <= 32'd0;
                event_info_meta <= 32'd0;
                ctrl_event_info <= 32'd0;
                event_rfdc_flags_meta <= 32'd0;
                ctrl_event_rfdc_flags <= 32'd0;
                event_dac_phase_epoch_meta <= 32'd0;
                ctrl_event_dac_phase_epoch <= 32'd0;
                ctrl_event_rd_data <= 32'd0;
            end else begin
                audit_status_meta <= audit_status_data;
                ctrl_audit_status <= audit_status_meta;
                audit_start_count_meta <= audit_start_count_data;
                ctrl_audit_start_count <= audit_start_count_meta;
                audit_first_count_meta <= audit_first_count_data;
                ctrl_audit_first_count <= audit_first_count_meta;
                audit_done_count_meta <= audit_done_count_data;
                ctrl_audit_done_count <= audit_done_count_meta;
                audit_start_sample0_meta <= audit_start_sample0_data;
                ctrl_audit_start_sample0 <= audit_start_sample0_meta;
                audit_first_sample0_meta <= audit_first_sample0_data;
                ctrl_audit_first_sample0 <= audit_first_sample0_meta;
                audit_done_sample0_meta <= audit_done_sample0_data;
                ctrl_audit_done_sample0 <= audit_done_sample0_meta;
                audit_start_to_first_latency_meta <= audit_start_to_first_latency_data;
                ctrl_audit_start_to_first_latency <= audit_start_to_first_latency_meta;
                audit_capture_beats_meta <= audit_capture_beats_data;
                ctrl_audit_capture_beats <= audit_capture_beats_meta;
                audit_valid_gap_count_meta <= audit_valid_gap_count_data;
                ctrl_audit_valid_gap_count <= audit_valid_gap_count_meta;
                audit_sample0_error_count_meta <= audit_sample0_error_count_data;
                ctrl_audit_sample0_error_count <= audit_sample0_error_count_meta;
                event_sample0_meta <= event_sample0_data;
                ctrl_event_sample0 <= event_sample0_meta;
                event_max_code_meta <= event_max_code_data;
                ctrl_event_max_code <= event_max_code_meta;
                event_info_meta <= event_info_data;
                ctrl_event_info <= event_info_meta;
                event_rfdc_flags_meta <= event_rfdc_flags_data;
                ctrl_event_rfdc_flags <= event_rfdc_flags_meta;
                event_dac_phase_epoch_meta <= event_dac_phase_epoch_data;
                ctrl_event_dac_phase_epoch <= event_dac_phase_epoch_meta;
                ctrl_event_rd_data <= event_buffer[ctrl_event_rd_addr];
            end
        end
    end

    generate
        for (mem_idx = 0; mem_idx < NINPUT; mem_idx = mem_idx + 1) begin : g_preview_bram
            assign preview_wea[mem_idx] = preview_write_fire && active_mask_data[mem_idx];

            for (lane_idx = 0; lane_idx < 4; lane_idx = lane_idx + 1) begin : g_preview_lane_bram
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
                    .doutb(preview_rd_data_bus[lane_idx][mem_idx*32 +: 32]),
                    .sbiterrb(),
                    .addra(preview_wr_addr),
                    .addrb(preview_rd_addr),
                    .clka(clk),
                    .clkb(ctrl_clk),
                    .dina(preview_wr_data_bus[lane_idx][mem_idx*32 +: 32]),
                    .ena(1'b1),
                    .enb(1'b1),
                    .injectdbiterra(1'b0),
                    .injectsbiterra(1'b0),
                    .regceb(1'b1),
                    .rstb(!ctrl_rst_n),
                    .sleep(1'b0),
                    .wea(preview_wea[mem_idx])
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

    integer event_init_idx;
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
            audit_clear_toggle_sync <= 3'b000;
            start_toggle_seen <= 1'b0;
            clear_toggle_seen <= 1'b0;
            audit_clear_toggle_seen <= 1'b0;
            audit_source_meta <= SRC_RFDC;
            audit_source_data <= SRC_RFDC;
            audit_event_enable_meta <= 1'b0;
            audit_event_enable_data <= 1'b0;
            audit_freeze_meta <= 1'b0;
            audit_freeze_data <= 1'b0;
            audit_threshold_meta <= 16'd28000;
            audit_threshold_data <= 16'd28000;
            dac_phase_epoch_meta <= 32'd0;
            dac_phase_epoch_data <= 32'd0;
            internal_sample0 <= 64'd0;
            internal_phase <= 32'd0;
            audit_start_count_data <= 32'd0;
            audit_first_count_data <= 32'd0;
            audit_done_count_data <= 32'd0;
            audit_start_sample0_data <= 64'd0;
            audit_first_sample0_data <= 64'd0;
            audit_done_sample0_data <= 64'd0;
            audit_latency_counter <= 32'd0;
            audit_start_to_first_latency_data <= 32'd0;
            audit_capture_beats_data <= 32'd0;
            audit_valid_gap_count_data <= 32'd0;
            audit_sample0_error_count_data <= 32'd0;
            audit_last_sample0 <= 64'd0;
            audit_have_last_sample0 <= 1'b0;
            audit_first_seen <= 1'b0;
            audit_event_valid_data <= 1'b0;
            audit_event_active_data <= 1'b0;
            audit_event_overflow_data <= 1'b0;
            audit_sample0_nonmonotonic_data <= 1'b0;
            audit_valid_gap_seen_data <= 1'b0;
            audit_sample0_error_seen_data <= 1'b0;
            event_sample0_data <= 64'd0;
            event_max_code_data <= 32'd0;
            event_info_data <= 32'd0;
            event_rfdc_flags_data <= 32'd0;
            event_dac_phase_epoch_data <= 32'd0;
            event_wr_index <= 8'd0;
            for (event_init_idx = 0; event_init_idx < 256; event_init_idx = event_init_idx + 1) begin
                event_buffer[event_init_idx] <= 32'd0;
            end
        end else begin
            start_toggle_sync <= {start_toggle_sync[1:0], ctrl_start_toggle};
            clear_toggle_sync <= {clear_toggle_sync[1:0], ctrl_clear_toggle};
            audit_clear_toggle_sync <= {audit_clear_toggle_sync[1:0], ctrl_audit_clear_toggle};
            start_toggle_seen <= start_toggle_sync[2];
            clear_toggle_seen <= clear_toggle_sync[2];
            audit_clear_toggle_seen <= audit_clear_toggle_sync[2];
            if (PRODUCTION_27H) begin
                audit_source_meta <= SRC_RFDC;
                audit_source_data <= SRC_RFDC;
                audit_event_enable_meta <= 1'b0;
                audit_event_enable_data <= 1'b0;
                audit_freeze_meta <= 1'b1;
                audit_freeze_data <= 1'b1;
                audit_threshold_meta <= 16'd0;
                audit_threshold_data <= 16'd0;
                dac_phase_epoch_meta <= 32'd0;
                dac_phase_epoch_data <= 32'd0;
            end else begin
                audit_source_meta <= audit_source_select;
                audit_source_data <= audit_source_meta;
                audit_event_enable_meta <= audit_event_enable;
                audit_event_enable_data <= audit_event_enable_meta;
                audit_freeze_meta <= audit_freeze_on_event;
                audit_freeze_data <= audit_freeze_meta;
                audit_threshold_meta <= audit_event_threshold;
                audit_threshold_data <= audit_threshold_meta;
                dac_phase_epoch_meta <= dac_phase_epoch_ctrl;
                dac_phase_epoch_data <= dac_phase_epoch_meta;
            end

            if (!PRODUCTION_27H && streaming) begin
                internal_sample0 <= internal_sample0 + 64'd4;
                // Four full-rate samples are packed into each AXIS beat, so
                // the next beat must advance by four DDS sample steps.
                internal_phase <= internal_phase + 32'h4000_0000;
            end

            if (!PRODUCTION_27H && audit_clear_event) begin
                audit_event_valid_data <= 1'b0;
                audit_event_active_data <= 1'b0;
                audit_event_overflow_data <= 1'b0;
                audit_sample0_nonmonotonic_data <= 1'b0;
                audit_valid_gap_seen_data <= 1'b0;
                audit_sample0_error_seen_data <= 1'b0;
                audit_valid_gap_count_data <= 32'd0;
                audit_sample0_error_count_data <= 32'd0;
                event_wr_index <= 8'd0;
            end

            if (clear_event) begin
                done_data <= 1'b0;
                error_data <= 1'b0;
                capture_count_data <= 32'd0;
            end

            if (!PRODUCTION_27H && audit_event_active_data && streaming && source_tvalid) begin
                event_buffer[event_wr_index] <= event_word0;
                event_buffer[event_wr_index + 8'd1] <= event_word1;
                event_buffer[event_wr_index + 8'd2] <= event_word2;
                event_buffer[event_wr_index + 8'd3] <= event_word3;
                if (event_wr_index >= 8'd252) begin
                    audit_event_active_data <= 1'b0;
                    audit_event_valid_data <= 1'b1;
                end else begin
                    event_wr_index <= event_wr_index + 8'd4;
                end
            end else if (!PRODUCTION_27H && audit_trigger_hit) begin
                if (audit_event_valid_data && audit_freeze_data) begin
                    audit_event_overflow_data <= 1'b1;
                end else begin
                    audit_event_active_data <= 1'b1;
                    audit_event_valid_data <= 1'b0;
                    event_wr_index <= 8'd0;
                    event_sample0_data <= source_sample0 + {62'd0, event_max_lane};
                    event_max_code_data <= {15'd0, event_max_abs};
                    event_info_data <= {14'd0, selected_source, 8'd0, 2'd0, event_max_lane, 4'd0};
                    event_rfdc_flags_data <= rfdc_status_flags;
                    event_dac_phase_epoch_data <= dac_phase_epoch_data;
                    event_buffer[8'd0] <= event_word0;
                    event_buffer[8'd1] <= event_word1;
                    event_buffer[8'd2] <= event_word2;
                    event_buffer[8'd3] <= event_word3;
                    event_wr_index <= 8'd4;
                end
            end

            case (state)
                ST_IDLE: begin
                    busy_data <= 1'b0;
                    if (start_event) begin
                        active_mask_data <= (input_mask == {NINPUT{1'b0}}) ? {{NINPUT-1{1'b0}}, 1'b1} : input_mask;
                        sample_index <= {ADDR_W+1{1'b0}};
                        capture_count_data <= 32'd0;
                        sample0_data <= 64'd0;
                        done_data <= 1'b0;
                        error_data <= 1'b0;
                        busy_data <= 1'b1;
                        if (!PRODUCTION_27H) begin
                            audit_start_count_data <= audit_start_count_data + 32'd1;
                            audit_start_sample0_data <= source_sample0;
                            audit_latency_counter <= 32'd0;
                            audit_capture_beats_data <= 32'd0;
                        end
                        audit_have_last_sample0 <= 1'b0;
                        audit_first_seen <= 1'b0;
                        state <= ST_RUN;
                    end
                end

                ST_RUN: begin
                    if (!PRODUCTION_27H) begin
                        audit_latency_counter <= audit_latency_counter + 32'd1;
                    end
                    if (!PRODUCTION_27H && streaming && !source_tvalid) begin
                        audit_valid_gap_seen_data <= 1'b1;
                        audit_valid_gap_count_data <= audit_valid_gap_count_data + 32'd1;
                    end
                    if (preview_write_fire) begin
                        if (!audit_first_seen) begin
                            audit_first_seen <= 1'b1;
                            if (!PRODUCTION_27H) begin
                                audit_first_count_data <= audit_first_count_data + 32'd1;
                                audit_first_sample0_data <= source_sample0;
                                audit_start_to_first_latency_data <= audit_latency_counter;
                            end
                            sample0_data <= source_sample0;
                        end
                        if (!PRODUCTION_27H && audit_have_last_sample0) begin
                            if (source_sample0 <= audit_last_sample0) begin
                                audit_sample0_nonmonotonic_data <= 1'b1;
                            end
                            if (source_sample0 != audit_last_sample0 + 64'd4) begin
                                audit_sample0_error_seen_data <= 1'b1;
                                audit_sample0_error_count_data <= audit_sample0_error_count_data + 32'd1;
                            end
                        end
                        audit_last_sample0 <= source_sample0;
                        audit_have_last_sample0 <= 1'b1;
                        if (!PRODUCTION_27H) begin
                            audit_capture_beats_data <= audit_capture_beats_data + 32'd1;
                        end
                        capture_count_data <= {21'd0, sample_index} + 32'd4;
                        if (sample_index >= NSAMP-4) begin
                            busy_data <= 1'b0;
                            done_data <= 1'b1;
                            if (!PRODUCTION_27H) begin
                                audit_done_count_data <= audit_done_count_data + 32'd1;
                                audit_done_sample0_data <= source_sample0;
                            end
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
