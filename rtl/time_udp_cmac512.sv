`default_nettype none

module time_udp_cmac512 #(
    parameter integer DATA_W             = 1024,
    parameter integer N_ENDPOINTS        = 16,
    parameter integer N_TIME_ROUTES      = 8,
    parameter integer DATA_FIFO_DEPTH    = 256,
    parameter integer DATA_COUNT_W       = 9,
    parameter integer TOKEN_FIFO_DEPTH   = 16,
    parameter integer TOKEN_COUNT_W      = 5
) (
    input  wire                         s_clk,
    input  wire                         s_rst_n,
    input  wire                         s_clear,
    input  wire                         enable,
    input  wire                         drop_on_route_miss,
    input  wire [15:0]                  board_id,
    input  wire [15:0]                  global_input0,
    input  wire [15:0]                  epoch_mode,
    input  wire [15:0]                  packet_flags,
    input  wire [63:0]                  unix_seconds,
    input  wire [63:0]                  pps_count,
    input  wire [15:0]                  quant_mode,
    input  wire [31:0]                  scale_id,
    input  wire [47:0]                  src_mac,
    input  wire [31:0]                  src_ip,
    input  wire [15:0]                  time_input_mask,
    input  wire [N_ENDPOINTS-1:0]       endpoint_enable,
    input  wire [N_ENDPOINTS*32-1:0]    endpoint_ip_vec,
    input  wire [N_ENDPOINTS*48-1:0]    endpoint_mac_vec,
    input  wire [N_ENDPOINTS*16-1:0]    endpoint_src_port_vec,
    input  wire [N_ENDPOINTS*16-1:0]    endpoint_dst_port_vec,
    input  wire [N_TIME_ROUTES-1:0]     time_route_enable,
    input  wire [N_TIME_ROUTES*16-1:0]  time_route_input_mask_vec,
    input  wire [N_TIME_ROUTES*8-1:0]   time_route_endpoint_vec,
    input  wire                         time_multiflow_enable,
    input  wire [2:0]                   time_multiflow_base_endpoint,
    input  wire [3:0]                   time_multiflow_count,
    input  wire [DATA_W-1:0]            s_axis_tdata,
    input  wire [63:0]                  s_axis_sample0,
    input  wire                         s_axis_tvalid,
    output logic                        s_axis_tready,

    input  wire                         m_clk,
    input  wire                         m_rst_n,
    input  wire                         m_clear,
    output logic [511:0]                m_axis_tdata,
    output logic [63:0]                 m_axis_tkeep,
    output logic                        m_axis_tvalid,
    output logic                        m_axis_tlast,
    input  wire                         m_axis_tready,

    output logic [31:0]                 packet_count,
    output logic [31:0]                 udp_byte_count,
    output logic [31:0]                 frame_built_count,
    output logic [31:0]                 frame_byte_count,
    output logic [31:0]                 frame_dropped_count,
    output logic [31:0]                 route_miss_count,
    output logic [31:0]                 route_error_count,
    output logic [31:0]                 seq_no_debug,
    output logic [63:0]                 sample0_debug,
    output logic [63:0]                 frame_id_debug,
    output logic [7:0]                  selected_endpoint_id,
    output logic [5:0]                  selected_route_id,
    output logic                        selected_route_is_time,
    output logic [N_TIME_ROUTES*32-1:0] time_route_hit_count_vec,
    output wire [31:0]                  fifo_level_words,
    output logic [31:0]                 output_frame_count,
    output logic [31:0]                 backpressure_cycles,
    output wire                         fifo_full,
    output wire                         fifo_empty
);

    localparam integer PAYLOAD_BEATS       = 64;
    localparam integer PAYLOAD_BYTES       = 8192;
    localparam integer T510_HEADER_BYTES   = 128;
    localparam integer UDP_PAYLOAD_BYTES   = T510_HEADER_BYTES + PAYLOAD_BYTES;
    localparam integer UDP_HEADER_BYTES    = 8;
    localparam integer IPV4_HEADER_BYTES   = 20;
    localparam integer ETH_HEADER_BYTES    = 14;
    localparam integer ETH_UDP_PAYLOAD_OFF = ETH_HEADER_BYTES + IPV4_HEADER_BYTES + UDP_HEADER_BYTES;
    localparam integer SAMPLE_PAYLOAD_OFF  = ETH_UDP_PAYLOAD_OFF + T510_HEADER_BYTES;
    localparam integer UDP_LEN_BYTES       = UDP_HEADER_BYTES + UDP_PAYLOAD_BYTES;
    localparam integer IPV4_TOTAL_BYTES    = IPV4_HEADER_BYTES + UDP_LEN_BYTES;
    localparam integer FRAME_BYTES         = ETH_HEADER_BYTES + IPV4_TOTAL_BYTES;
    localparam integer FRAME_BEATS         = (FRAME_BYTES + 63) / 64;
    localparam integer FRAME_TAIL_BYTES    = FRAME_BYTES - ((FRAME_BEATS - 1) * 64);
    localparam [15:0] PAYLOAD_BEATS16      = PAYLOAD_BEATS;
    localparam [15:0] T510_HEADER_BYTES16  = T510_HEADER_BYTES;
    localparam [31:0] PAYLOAD_BYTES32      = PAYLOAD_BYTES;
    localparam [31:0] UDP_PAYLOAD_BYTES32  = UDP_PAYLOAD_BYTES;
    localparam [31:0] FRAME_BYTES32        = FRAME_BYTES;
    localparam [15:0] UDP_LEN16            = UDP_LEN_BYTES;
    localparam [15:0] IPV4_TOTAL16         = IPV4_TOTAL_BYTES;
    localparam integer N_ENDPOINTS_I       = N_ENDPOINTS;
    localparam [7:0]  PAYLOAD_LAST_PREFETCH_BASE = PAYLOAD_BEATS - 2;
    localparam [31:0] T510_MAGIC           = 32'h5435_3130;
    localparam [15:0] STREAM_TIME          = 16'd1;
    localparam [15:0] LOCAL_NINPUT         = 16'd8;
    localparam integer TOKEN_W             = 640;

    localparam integer TOK_SAMPLE0_LSB     = 0;
    localparam integer TOK_UNIX_LSB        = 64;
    localparam integer TOK_PPS_LSB         = 128;
    localparam integer TOK_FRAME_ID_LSB    = 192;
    localparam integer TOK_SEQ_LSB         = 256;
    localparam integer TOK_TIME_COUNT_LSB  = 288;
    localparam integer TOK_BOARD_LSB       = 304;
    localparam integer TOK_INPUT0_LSB      = 320;
    localparam integer TOK_EPOCH_LSB       = 336;
    localparam integer TOK_FLAGS_LSB       = 352;
    localparam integer TOK_QUANT_LSB       = 368;
    localparam integer TOK_SCALE_LSB       = 384;
    localparam integer TOK_SRC_MAC_LSB     = 416;
    localparam integer TOK_SRC_IP_LSB      = 464;
    localparam integer TOK_DST_MAC_LSB     = 496;
    localparam integer TOK_DST_IP_LSB      = 544;
    localparam integer TOK_SRC_PORT_LSB    = 576;
    localparam integer TOK_DST_PORT_LSB    = 592;
    localparam integer TOK_ENDPOINT_LSB    = 608;
    localparam integer TOK_ROUTE_LSB       = 616;

    localparam [1:0] S_IDLE    = 2'd0;
    localparam [1:0] S_CAPTURE = 2'd1;
    localparam [1:0] S_DROP    = 2'd2;

    localparam [2:0] M_IDLE  = 3'd0;
    localparam [2:0] M_SUM   = 3'd1;
    localparam [2:0] M_FOLD  = 3'd2;
    localparam [2:0] M_LOAD1 = 3'd3;
    localparam [2:0] M_SEND  = 3'd4;

    logic [1:0]  s_state;
    logic [15:0] capture_idx;
    logic [15:0] drop_remaining;
    logic [31:0] seq_no;
    logic [63:0] frame_id;
    logic [63:0] packet_sample0;
    logic [N_TIME_ROUTES*32-1:0] time_hit_counts;

    logic [2:0]  route_id_comb;
    logic [7:0]  endpoint_id_comb;
    logic [7:0]  route_endpoint_id_comb;
    logic [7:0]  multiflow_endpoint_id_comb;
    logic [2:0]  multiflow_mask_comb;
    logic [2:0]  multiflow_flow_id_comb;
    logic        multiflow_active_comb;
    logic        multiflow_endpoint_valid_comb;
    logic        route_found_comb;
    logic        route_endpoint_enabled_comb;
    logic [47:0] selected_dst_mac_comb;
    logic [31:0] selected_dst_ip_comb;
    logic [15:0] selected_src_port_comb;
    logic [15:0] selected_dst_port_comb;

    wire         s_fire = s_axis_tvalid && s_axis_tready;
    wire         final_capture_beat = (capture_idx + 16'd1) >= PAYLOAD_BEATS16;
    wire         route_ok_comb = route_endpoint_enabled_comb;
    wire         route_miss_comb = !route_found_comb;
    wire         route_error_comb = route_found_comb && !route_endpoint_enabled_comb;
    wire         should_drop_comb = !route_ok_comb && drop_on_route_miss;

    wire         fifo_rst = !s_rst_n || !m_rst_n || s_clear || m_clear;
    wire         data_wr_rst_busy;
    wire         data_rd_rst_busy;
    wire [DATA_COUNT_W-1:0] data_wr_data_count;
    wire [DATA_COUNT_W-1:0] data_rd_data_count;
    wire [DATA_W-1:0] data_fifo_dout;
    logic        data_wr_en;
    logic        data_rd_en;
    wire         data_fifo_full;
    wire         data_fifo_empty;

    wire         token_wr_rst_busy;
    wire         token_rd_rst_busy;
    wire [TOKEN_COUNT_W-1:0] token_wr_data_count;
    wire [TOKEN_COUNT_W-1:0] token_rd_data_count;
    wire [TOKEN_W-1:0] token_fifo_dout;
    logic [TOKEN_W-1:0] token_din;
    logic        token_wr_en;
    logic        token_rd_en;
    wire         token_fifo_full;
    wire         token_fifo_empty;

    logic [2:0]  m_state;
    logic [TOKEN_W-1:0] token_reg;
    logic [DATA_W-1:0] data_prefetch;
    logic              data_prefetch_valid;
    logic              data_prefetch_pop;
    logic              payload_sel;
    logic [175:0]      payload_a0;
    logic [175:0]      payload_a1;
    logic [511:0]      payload_b0;
    logic [511:0]      payload_b1;
    logic [335:0]      payload_c0;
    logic [335:0]      payload_c1;
    logic [7:0]  payload_base_idx;
    logic [7:0]  m_out_beat;
    logic [511:0] out_tdata;
    logic [63:0]  out_tkeep;
    logic         out_tvalid;
    logic         out_tlast;
    logic [31:0]  token_ip_sum;
    logic [15:0]  token_ip_checksum;
    logic [511:0] hdr_beat0_reg;
    logic [511:0] hdr_beat1_reg;
    logic [511:0] hdr_beat2_prefix_reg;
    logic [511:0] next_out_tdata;
    wire          m_fire = out_tvalid && m_axis_tready;
    wire          out_ready = !out_tvalid || m_axis_tready;
    wire          m_send_active = (m_state == M_SEND);
    wire          m_send_last = (m_out_beat == (FRAME_BEATS - 1));
    wire          m_shift_after = m_send_active && should_shift_after(m_out_beat);
    wire          m_shift_needs_prefetch = m_shift_after && (payload_base_idx < PAYLOAD_LAST_PREFETCH_BASE);
    wire          m_load_beat = m_send_active && out_ready && (!m_shift_needs_prefetch || data_prefetch_valid);

    assign fifo_full = data_fifo_full || token_fifo_full;
    assign fifo_empty = (!data_prefetch_valid && data_fifo_empty) || token_fifo_empty;
    assign fifo_level_words = {{(32-DATA_COUNT_W){1'b0}}, data_rd_data_count} + {31'd0, data_prefetch_valid};

    function automatic [31:0] endpoint_ip(input [7:0] idx);
        begin
            endpoint_ip = endpoint_ip_vec[idx*32 +: 32];
        end
    endfunction

    function automatic [47:0] endpoint_mac(input [7:0] idx);
        begin
            endpoint_mac = endpoint_mac_vec[idx*48 +: 48];
        end
    endfunction

    function automatic [15:0] endpoint_src_port(input [7:0] idx);
        begin
            endpoint_src_port = endpoint_src_port_vec[idx*16 +: 16];
        end
    endfunction

    function automatic [15:0] endpoint_dst_port(input [7:0] idx);
        begin
            endpoint_dst_port = endpoint_dst_port_vec[idx*16 +: 16];
        end
    endfunction

    function automatic [15:0] time_route_input_mask(input integer idx);
        begin
            time_route_input_mask = time_route_input_mask_vec[idx*16 +: 16];
        end
    endfunction

    function automatic [7:0] time_route_endpoint(input integer idx);
        begin
            time_route_endpoint = time_route_endpoint_vec[idx*8 +: 8];
        end
    endfunction

    function automatic [2:0] multiflow_mask(input [3:0] count);
        begin
            if (count >= 4'd8) begin
                multiflow_mask = 3'b111;
            end else if (count >= 4'd4) begin
                multiflow_mask = 3'b011;
            end else if (count >= 4'd2) begin
                multiflow_mask = 3'b001;
            end else begin
                multiflow_mask = 3'b000;
            end
        end
    endfunction

    integer route_idx;
    always_comb begin
        route_found_comb = 1'b0;
        route_id_comb = 3'd0;
        endpoint_id_comb = 8'd0;
        route_endpoint_id_comb = 8'd0;
        multiflow_mask_comb = multiflow_mask(time_multiflow_count);
        multiflow_flow_id_comb = seq_no[2:0] & multiflow_mask_comb;
        multiflow_endpoint_id_comb = {5'd0, time_multiflow_base_endpoint} + {5'd0, multiflow_flow_id_comb};
        multiflow_active_comb = time_multiflow_enable && (multiflow_mask_comb != 3'b000);
        multiflow_endpoint_valid_comb = ({28'd0, multiflow_endpoint_id_comb} < N_ENDPOINTS_I);
        route_endpoint_enabled_comb = 1'b0;
        for (route_idx = 0; route_idx < N_TIME_ROUTES; route_idx = route_idx + 1) begin
            if (!route_found_comb &&
                time_route_enable[route_idx] &&
                (time_route_input_mask(route_idx) == time_input_mask)) begin
                route_found_comb = 1'b1;
                route_id_comb = route_idx[2:0];
                route_endpoint_id_comb = time_route_endpoint(route_idx);
            end
        end
        if (route_found_comb) begin
            if (multiflow_active_comb) begin
                endpoint_id_comb = multiflow_endpoint_id_comb;
                route_endpoint_enabled_comb = multiflow_endpoint_valid_comb && endpoint_enable[endpoint_id_comb];
            end else begin
                endpoint_id_comb = route_endpoint_id_comb;
                route_endpoint_enabled_comb = ({24'd0, endpoint_id_comb} < N_ENDPOINTS_I) &&
                                              endpoint_enable[endpoint_id_comb];
            end
        end else if (!drop_on_route_miss && endpoint_enable[0]) begin
            endpoint_id_comb = 8'd0;
            route_endpoint_enabled_comb = 1'b1;
        end
        selected_dst_mac_comb = endpoint_mac(endpoint_id_comb);
        selected_dst_ip_comb = endpoint_ip(endpoint_id_comb);
        selected_src_port_comb = endpoint_src_port(endpoint_id_comb);
        selected_dst_port_comb = endpoint_dst_port(endpoint_id_comb);
    end

    always_comb begin
        token_din = {TOKEN_W{1'b0}};
        token_din[TOK_SAMPLE0_LSB +: 64] = packet_sample0;
        token_din[TOK_UNIX_LSB +: 64] = unix_seconds;
        token_din[TOK_PPS_LSB +: 64] = pps_count;
        token_din[TOK_FRAME_ID_LSB +: 64] = frame_id;
        token_din[TOK_SEQ_LSB +: 32] = seq_no;
        token_din[TOK_TIME_COUNT_LSB +: 16] = PAYLOAD_BEATS16;
        token_din[TOK_BOARD_LSB +: 16] = board_id;
        token_din[TOK_INPUT0_LSB +: 16] = global_input0;
        token_din[TOK_EPOCH_LSB +: 16] = epoch_mode;
        token_din[TOK_FLAGS_LSB +: 16] = packet_flags;
        token_din[TOK_QUANT_LSB +: 16] = quant_mode;
        token_din[TOK_SCALE_LSB +: 32] = scale_id;
        token_din[TOK_SRC_MAC_LSB +: 48] = src_mac;
        token_din[TOK_SRC_IP_LSB +: 32] = src_ip;
        token_din[TOK_DST_MAC_LSB +: 48] = selected_dst_mac_comb;
        token_din[TOK_DST_IP_LSB +: 32] = selected_dst_ip_comb;
        token_din[TOK_SRC_PORT_LSB +: 16] = selected_src_port_comb;
        token_din[TOK_DST_PORT_LSB +: 16] = selected_dst_port_comb;
        token_din[TOK_ENDPOINT_LSB +: 8] = endpoint_id_comb;
        token_din[TOK_ROUTE_LSB +: 3] = route_id_comb;
    end

    always_comb begin
        s_axis_tready = 1'b0;
        case (s_state)
            S_IDLE: begin
                if (enable) begin
                    if (route_ok_comb) begin
                        s_axis_tready = !data_wr_rst_busy &&
                                        !token_wr_rst_busy &&
                                        !data_fifo_full &&
                                        !token_fifo_full;
                    end else begin
                        s_axis_tready = drop_on_route_miss;
                    end
                end
            end
            S_CAPTURE: begin
                s_axis_tready = enable &&
                                !data_wr_rst_busy &&
                                !token_wr_rst_busy &&
                                !data_fifo_full &&
                                (!final_capture_beat || !token_fifo_full);
            end
            S_DROP: begin
                s_axis_tready = enable;
            end
            default: begin
            end
        endcase
    end

    always_comb begin
        data_wr_en = s_fire && ((s_state == S_CAPTURE) || ((s_state == S_IDLE) && route_ok_comb));
        token_wr_en = data_wr_en && (((s_state == S_IDLE) && (PAYLOAD_BEATS == 1)) ||
                                     ((s_state == S_CAPTURE) && final_capture_beat));
    end

    always_ff @(posedge s_clk or negedge s_rst_n) begin
        if (!s_rst_n) begin
            s_state <= S_IDLE;
            capture_idx <= 16'd0;
            drop_remaining <= 16'd0;
            seq_no <= 32'd0;
            frame_id <= 64'd0;
            packet_sample0 <= 64'd0;
            packet_count <= 32'd0;
            udp_byte_count <= 32'd0;
            frame_built_count <= 32'd0;
            frame_byte_count <= 32'd0;
            frame_dropped_count <= 32'd0;
            route_miss_count <= 32'd0;
            route_error_count <= 32'd0;
            seq_no_debug <= 32'd0;
            sample0_debug <= 64'd0;
            frame_id_debug <= 64'd0;
            selected_endpoint_id <= 8'd0;
            selected_route_id <= 6'd0;
            selected_route_is_time <= 1'b0;
            time_hit_counts <= {N_TIME_ROUTES*32{1'b0}};
            backpressure_cycles <= 32'd0;
        end else if (s_clear) begin
            s_state <= S_IDLE;
            capture_idx <= 16'd0;
            drop_remaining <= 16'd0;
            seq_no <= 32'd0;
            frame_id <= 64'd0;
            packet_sample0 <= 64'd0;
            packet_count <= 32'd0;
            udp_byte_count <= 32'd0;
            frame_built_count <= 32'd0;
            frame_byte_count <= 32'd0;
            frame_dropped_count <= 32'd0;
            route_miss_count <= 32'd0;
            route_error_count <= 32'd0;
            seq_no_debug <= 32'd0;
            sample0_debug <= 64'd0;
            frame_id_debug <= 64'd0;
            selected_endpoint_id <= 8'd0;
            selected_route_id <= 6'd0;
            selected_route_is_time <= 1'b0;
            time_hit_counts <= {N_TIME_ROUTES*32{1'b0}};
            backpressure_cycles <= 32'd0;
        end else begin
            if (s_axis_tvalid && !s_axis_tready) begin
                backpressure_cycles <= backpressure_cycles + 32'd1;
            end
            if (s_fire) begin
                case (s_state)
                    S_IDLE: begin
                        if (route_ok_comb) begin
                            packet_sample0 <= s_axis_sample0;
                            sample0_debug <= s_axis_sample0;
                            packet_count <= packet_count + 32'd1;
                            selected_endpoint_id <= endpoint_id_comb;
                            selected_route_id <= {3'd0, route_id_comb};
                            selected_route_is_time <= 1'b1;
                            if (PAYLOAD_BEATS == 1) begin
                                udp_byte_count <= udp_byte_count + UDP_PAYLOAD_BYTES32;
                                frame_built_count <= frame_built_count + 32'd1;
                                frame_byte_count <= frame_byte_count + FRAME_BYTES32;
                                time_hit_counts[route_id_comb*32 +: 32] <= time_hit_counts[route_id_comb*32 +: 32] + 32'd1;
                                seq_no <= seq_no + 32'd1;
                                frame_id <= frame_id + 64'd1;
                                seq_no_debug <= seq_no + 32'd1;
                                frame_id_debug <= frame_id + 64'd1;
                            end else begin
                                capture_idx <= 16'd1;
                                s_state <= S_CAPTURE;
                            end
                        end else begin
                            if (route_miss_comb) begin
                                route_miss_count <= route_miss_count + 32'd1;
                            end
                            if (route_error_comb) begin
                                route_error_count <= route_error_count + 32'd1;
                            end
                            frame_dropped_count <= frame_dropped_count + 32'd1;
                            drop_remaining <= PAYLOAD_BEATS16 - 16'd1;
                            if (PAYLOAD_BEATS != 1) begin
                                s_state <= S_DROP;
                            end
                        end
                    end
                    S_CAPTURE: begin
                        if (final_capture_beat) begin
                            udp_byte_count <= udp_byte_count + UDP_PAYLOAD_BYTES32;
                            frame_built_count <= frame_built_count + 32'd1;
                            frame_byte_count <= frame_byte_count + FRAME_BYTES32;
                            time_hit_counts[selected_route_id*32 +: 32] <= time_hit_counts[selected_route_id*32 +: 32] + 32'd1;
                            seq_no <= seq_no + 32'd1;
                            frame_id <= frame_id + 64'd1;
                            seq_no_debug <= seq_no + 32'd1;
                            frame_id_debug <= frame_id + 64'd1;
                            capture_idx <= 16'd0;
                            s_state <= S_IDLE;
                        end else begin
                            capture_idx <= capture_idx + 16'd1;
                        end
                    end
                    S_DROP: begin
                        if (drop_remaining <= 16'd1) begin
                            drop_remaining <= 16'd0;
                            s_state <= S_IDLE;
                        end else begin
                            drop_remaining <= drop_remaining - 16'd1;
                        end
                    end
                    default: begin
                        s_state <= S_IDLE;
                    end
                endcase
            end
        end
    end

    assign time_route_hit_count_vec = time_hit_counts;

    function automatic [63:0] token_sample0(input [TOKEN_W-1:0] token);
        token_sample0 = token[TOK_SAMPLE0_LSB +: 64];
    endfunction
    function automatic [63:0] token_unix(input [TOKEN_W-1:0] token);
        token_unix = token[TOK_UNIX_LSB +: 64];
    endfunction
    function automatic [63:0] token_pps(input [TOKEN_W-1:0] token);
        token_pps = token[TOK_PPS_LSB +: 64];
    endfunction
    function automatic [63:0] token_frame_id(input [TOKEN_W-1:0] token);
        token_frame_id = token[TOK_FRAME_ID_LSB +: 64];
    endfunction
    function automatic [31:0] token_seq(input [TOKEN_W-1:0] token);
        token_seq = token[TOK_SEQ_LSB +: 32];
    endfunction
    function automatic [15:0] token_time_count(input [TOKEN_W-1:0] token);
        token_time_count = token[TOK_TIME_COUNT_LSB +: 16];
    endfunction
    function automatic [15:0] token_board(input [TOKEN_W-1:0] token);
        token_board = token[TOK_BOARD_LSB +: 16];
    endfunction
    function automatic [15:0] token_input0(input [TOKEN_W-1:0] token);
        token_input0 = token[TOK_INPUT0_LSB +: 16];
    endfunction
    function automatic [15:0] token_epoch(input [TOKEN_W-1:0] token);
        token_epoch = token[TOK_EPOCH_LSB +: 16];
    endfunction
    function automatic [15:0] token_flags(input [TOKEN_W-1:0] token);
        token_flags = token[TOK_FLAGS_LSB +: 16];
    endfunction
    function automatic [15:0] token_quant(input [TOKEN_W-1:0] token);
        token_quant = token[TOK_QUANT_LSB +: 16];
    endfunction
    function automatic [31:0] token_scale(input [TOKEN_W-1:0] token);
        token_scale = token[TOK_SCALE_LSB +: 32];
    endfunction
    function automatic [47:0] token_src_mac(input [TOKEN_W-1:0] token);
        token_src_mac = token[TOK_SRC_MAC_LSB +: 48];
    endfunction
    function automatic [31:0] token_src_ip(input [TOKEN_W-1:0] token);
        token_src_ip = token[TOK_SRC_IP_LSB +: 32];
    endfunction
    function automatic [47:0] token_dst_mac(input [TOKEN_W-1:0] token);
        token_dst_mac = token[TOK_DST_MAC_LSB +: 48];
    endfunction
    function automatic [31:0] token_dst_ip(input [TOKEN_W-1:0] token);
        token_dst_ip = token[TOK_DST_IP_LSB +: 32];
    endfunction
    function automatic [15:0] token_src_port(input [TOKEN_W-1:0] token);
        token_src_port = token[TOK_SRC_PORT_LSB +: 16];
    endfunction
    function automatic [15:0] token_dst_port(input [TOKEN_W-1:0] token);
        token_dst_port = token[TOK_DST_PORT_LSB +: 16];
    endfunction

    function automatic [15:0] fold_checksum(input [31:0] sum_in);
        reg [31:0] sum_folded;
        begin
            sum_folded = sum_in;
            sum_folded = (sum_folded & 32'h0000_ffff) + (sum_folded >> 16);
            sum_folded = (sum_folded & 32'h0000_ffff) + (sum_folded >> 16);
            fold_checksum = ~sum_folded[15:0];
        end
    endfunction

    function automatic [31:0] ipv4_checksum_sum(
        input [15:0] total_len,
        input [15:0] ident,
        input [31:0] src_ip_value,
        input [31:0] dst_ip_value
    );
        reg [31:0] sum;
        begin
            sum = 32'd0;
            sum = sum + 16'h4500;
            sum = sum + total_len;
            sum = sum + ident;
            sum = sum + 16'h4000;
            sum = sum + 16'h4011;
            sum = sum + src_ip_value[31:16];
            sum = sum + src_ip_value[15:0];
            sum = sum + dst_ip_value[31:16];
            sum = sum + dst_ip_value[15:0];
            ipv4_checksum_sum = sum;
        end
    endfunction

    function automatic [63:0] t510_word_from_token(
        input [TOKEN_W-1:0] token,
        input integer idx
    );
        begin
            case (idx)
                0:  t510_word_from_token = {T510_MAGIC, 16'd2, T510_HEADER_BYTES16};
                1:  t510_word_from_token = {token_board(token), STREAM_TIME, token_epoch(token), token_flags(token)};
                2:  t510_word_from_token = token_unix(token);
                3:  t510_word_from_token = token_pps(token);
                4:  t510_word_from_token = token_sample0(token);
                5:  t510_word_from_token = token_frame_id(token);
                6:  t510_word_from_token = {token_seq(token), 16'd0, token_input0(token)};
                7:  t510_word_from_token = {16'd0, token_time_count(token), LOCAL_NINPUT, token_quant(token)};
                8:  t510_word_from_token = {token_scale(token), PAYLOAD_BYTES32};
                default: t510_word_from_token = 64'd0;
            endcase
        end
    endfunction

    function automatic [7:0] frame_header_byte(
        input [TOKEN_W-1:0] token,
        input [15:0] ip_sum,
        input integer abs_idx
    );
        integer rel;
        integer word_idx;
        integer byte_idx;
        reg [63:0] hdr_word;
        reg [31:0] seq_value;
        reg [31:0] src_ip_value;
        reg [31:0] dst_ip_value;
        reg [47:0] src_mac_value;
        reg [47:0] dst_mac_value;
        reg [15:0] src_port_value;
        reg [15:0] dst_port_value;
        begin
            frame_header_byte = 8'd0;
            seq_value = token_seq(token);
            src_ip_value = token_src_ip(token);
            dst_ip_value = token_dst_ip(token);
            src_mac_value = token_src_mac(token);
            dst_mac_value = token_dst_mac(token);
            src_port_value = token_src_port(token);
            dst_port_value = token_dst_port(token);
            if (abs_idx < 6) begin
                frame_header_byte = dst_mac_value[(5 - abs_idx)*8 +: 8];
            end else if (abs_idx < 12) begin
                rel = abs_idx - 6;
                frame_header_byte = src_mac_value[(5 - rel)*8 +: 8];
            end else if (abs_idx == 12) begin
                frame_header_byte = 8'h08;
            end else if (abs_idx == 13) begin
                frame_header_byte = 8'h00;
            end else if (abs_idx < ETH_UDP_PAYLOAD_OFF) begin
                rel = abs_idx - ETH_HEADER_BYTES;
                case (rel)
                    0:  frame_header_byte = 8'h45;
                    1:  frame_header_byte = 8'h00;
                    2:  frame_header_byte = IPV4_TOTAL16[15:8];
                    3:  frame_header_byte = IPV4_TOTAL16[7:0];
                    4:  frame_header_byte = seq_value[15:8];
                    5:  frame_header_byte = seq_value[7:0];
                    6:  frame_header_byte = 8'h40;
                    7:  frame_header_byte = 8'h00;
                    8:  frame_header_byte = 8'h40;
                    9:  frame_header_byte = 8'h11;
                    10: frame_header_byte = ip_sum[15:8];
                    11: frame_header_byte = ip_sum[7:0];
                    12: frame_header_byte = src_ip_value[31:24];
                    13: frame_header_byte = src_ip_value[23:16];
                    14: frame_header_byte = src_ip_value[15:8];
                    15: frame_header_byte = src_ip_value[7:0];
                    16: frame_header_byte = dst_ip_value[31:24];
                    17: frame_header_byte = dst_ip_value[23:16];
                    18: frame_header_byte = dst_ip_value[15:8];
                    19: frame_header_byte = dst_ip_value[7:0];
                    20: frame_header_byte = src_port_value[15:8];
                    21: frame_header_byte = src_port_value[7:0];
                    22: frame_header_byte = dst_port_value[15:8];
                    23: frame_header_byte = dst_port_value[7:0];
                    24: frame_header_byte = UDP_LEN16[15:8];
                    25: frame_header_byte = UDP_LEN16[7:0];
                    26: frame_header_byte = 8'h00;
                    27: frame_header_byte = 8'h00;
                    default: frame_header_byte = 8'd0;
                endcase
            end else if (abs_idx < SAMPLE_PAYLOAD_OFF) begin
                rel = abs_idx - ETH_UDP_PAYLOAD_OFF;
                word_idx = rel / 8;
                byte_idx = rel % 8;
                hdr_word = t510_word_from_token(token, word_idx);
                frame_header_byte = hdr_word[byte_idx*8 +: 8];
            end
        end
    endfunction

    function automatic [511:0] build_header_beat(
        input [TOKEN_W-1:0] token,
        input [15:0] ip_sum,
        input integer beat_idx
    );
        integer byte_i;
        integer abs_idx;
        begin
            build_header_beat = 512'd0;
            for (byte_i = 0; byte_i < 64; byte_i = byte_i + 1) begin
                abs_idx = beat_idx * 64 + byte_i;
                build_header_beat[byte_i*8 +: 8] = frame_header_byte(token, ip_sum, abs_idx);
            end
        end
    endfunction

    function automatic [175:0] payload_seg_a(input [1023:0] payload);
        begin
            payload_seg_a = payload[0 +: 176];
        end
    endfunction

    function automatic [511:0] payload_seg_b(input [1023:0] payload);
        begin
            payload_seg_b = payload[176 +: 512];
        end
    endfunction

    function automatic [335:0] payload_seg_c(input [1023:0] payload);
        begin
            payload_seg_c = payload[688 +: 336];
        end
    endfunction

    function automatic [511:0] insert_payload_first22(
        input [511:0] prefix,
        input [175:0] payload_a
    );
        begin
            insert_payload_first22 = prefix;
            insert_payload_first22[42*8 +: 22*8] = payload_a;
        end
    endfunction

    function automatic [511:0] payload_cross_window(
        input [335:0] current_payload_c,
        input [175:0] next_payload_a
    );
        begin
            payload_cross_window = 512'd0;
            payload_cross_window[0 +: 336] = current_payload_c;
            payload_cross_window[336 +: 176] = next_payload_a;
        end
    endfunction

    function automatic should_shift_after(input [7:0] beat_idx);
        begin
            should_shift_after = (beat_idx >= 8'd4) && !beat_idx[0] && (beat_idx < (FRAME_BEATS - 1));
        end
    endfunction

    always_comb begin
        case (m_out_beat)
            8'd0: next_out_tdata = hdr_beat0_reg;
            8'd1: next_out_tdata = hdr_beat1_reg;
            8'd2: begin
                next_out_tdata = payload_sel ?
                    insert_payload_first22(hdr_beat2_prefix_reg, payload_a1) :
                    insert_payload_first22(hdr_beat2_prefix_reg, payload_a0);
            end
            default: begin
                if (m_out_beat[0]) begin
                    next_out_tdata = payload_sel ? payload_b1 : payload_b0;
                end else begin
                    next_out_tdata = payload_sel ?
                        payload_cross_window(payload_c1, payload_a0) :
                        payload_cross_window(payload_c0, payload_a1);
                end
            end
        endcase
    end

    always_ff @(posedge m_clk or negedge m_rst_n) begin
        if (!m_rst_n) begin
            hdr_beat0_reg <= 512'd0;
            hdr_beat1_reg <= 512'd0;
            hdr_beat2_prefix_reg <= 512'd0;
        end else if (m_clear) begin
            hdr_beat0_reg <= 512'd0;
            hdr_beat1_reg <= 512'd0;
            hdr_beat2_prefix_reg <= 512'd0;
        end else if ((m_state == M_LOAD1) && data_prefetch_valid) begin
            hdr_beat0_reg <= build_header_beat(token_reg, token_ip_checksum, 0);
            hdr_beat1_reg <= build_header_beat(token_reg, token_ip_checksum, 1);
            hdr_beat2_prefix_reg <= build_header_beat(token_reg, token_ip_checksum, 2);
        end
    end

    always_ff @(posedge m_clk or negedge m_rst_n) begin
        if (!m_rst_n) begin
            data_prefetch <= {DATA_W{1'b0}};
            data_prefetch_valid <= 1'b0;
        end else if (m_clear) begin
            data_prefetch <= {DATA_W{1'b0}};
            data_prefetch_valid <= 1'b0;
        end else begin
            if (data_prefetch_pop) begin
                data_prefetch_valid <= 1'b0;
            end
            if (data_rd_en) begin
                data_prefetch <= data_fifo_dout;
                data_prefetch_valid <= 1'b1;
            end
        end
    end

    always_ff @(posedge m_clk or negedge m_rst_n) begin
        if (!m_rst_n) begin
            m_state <= M_IDLE;
            token_reg <= {TOKEN_W{1'b0}};
            token_ip_sum <= 32'd0;
            token_ip_checksum <= 16'd0;
            payload_sel <= 1'b0;
            payload_a0 <= 176'd0;
            payload_a1 <= 176'd0;
            payload_b0 <= 512'd0;
            payload_b1 <= 512'd0;
            payload_c0 <= 336'd0;
            payload_c1 <= 336'd0;
            payload_base_idx <= 8'd0;
            m_out_beat <= 8'd0;
            out_tdata <= 512'd0;
            out_tkeep <= 64'd0;
            out_tvalid <= 1'b0;
            out_tlast <= 1'b0;
            output_frame_count <= 32'd0;
        end else if (m_clear) begin
            m_state <= M_IDLE;
            token_reg <= {TOKEN_W{1'b0}};
            token_ip_sum <= 32'd0;
            token_ip_checksum <= 16'd0;
            payload_sel <= 1'b0;
            payload_a0 <= 176'd0;
            payload_a1 <= 176'd0;
            payload_b0 <= 512'd0;
            payload_b1 <= 512'd0;
            payload_c0 <= 336'd0;
            payload_c1 <= 336'd0;
            payload_base_idx <= 8'd0;
            m_out_beat <= 8'd0;
            out_tdata <= 512'd0;
            out_tkeep <= 64'd0;
            out_tvalid <= 1'b0;
            out_tlast <= 1'b0;
            output_frame_count <= 32'd0;
        end else begin
            if (m_fire && out_tlast) begin
                output_frame_count <= output_frame_count + 32'd1;
            end

            if (m_fire && !m_load_beat) begin
                out_tvalid <= 1'b0;
            end

            case (m_state)
                M_IDLE: begin
                    m_out_beat <= 8'd0;
                    payload_base_idx <= 8'd0;
                    if (!token_fifo_empty && data_prefetch_valid && !token_rd_rst_busy) begin
                        token_reg <= token_fifo_dout;
                        payload_a0 <= payload_seg_a(data_prefetch);
                        payload_b0 <= payload_seg_b(data_prefetch);
                        payload_c0 <= payload_seg_c(data_prefetch);
                        payload_sel <= 1'b0;
                        m_state <= M_SUM;
                    end
                end
                M_SUM: begin
                    token_ip_sum <= ipv4_checksum_sum(
                        IPV4_TOTAL16,
                        token_reg[TOK_SEQ_LSB +: 16],
                        token_reg[TOK_SRC_IP_LSB +: 32],
                        token_reg[TOK_DST_IP_LSB +: 32]
                    );
                    m_state <= M_FOLD;
                end
                M_FOLD: begin
                    token_ip_checksum <= fold_checksum(token_ip_sum);
                    m_state <= M_LOAD1;
                end
                M_LOAD1: begin
                    if (data_prefetch_valid) begin
                        payload_a1 <= payload_seg_a(data_prefetch);
                        payload_b1 <= payload_seg_b(data_prefetch);
                        payload_c1 <= payload_seg_c(data_prefetch);
                        m_state <= M_SEND;
                    end
                end
                M_SEND: begin
                    if (m_load_beat) begin
                        out_tdata <= next_out_tdata;
                        out_tkeep <= m_send_last ? ((64'h1 << FRAME_TAIL_BYTES) - 64'h1) : 64'hffff_ffff_ffff_ffff;
                        out_tlast <= m_send_last;
                        out_tvalid <= 1'b1;
                        if (m_send_last) begin
                            m_state <= M_IDLE;
                        end else begin
                            if (should_shift_after(m_out_beat)) begin
                                if (payload_sel) begin
                                    payload_a1 <= m_shift_needs_prefetch ? payload_seg_a(data_prefetch) : 176'd0;
                                    payload_b1 <= m_shift_needs_prefetch ? payload_seg_b(data_prefetch) : 512'd0;
                                    payload_c1 <= m_shift_needs_prefetch ? payload_seg_c(data_prefetch) : 336'd0;
                                    payload_sel <= 1'b0;
                                end else begin
                                    payload_a0 <= m_shift_needs_prefetch ? payload_seg_a(data_prefetch) : 176'd0;
                                    payload_b0 <= m_shift_needs_prefetch ? payload_seg_b(data_prefetch) : 512'd0;
                                    payload_c0 <= m_shift_needs_prefetch ? payload_seg_c(data_prefetch) : 336'd0;
                                    payload_sel <= 1'b1;
                                end
                                payload_base_idx <= payload_base_idx + 8'd1;
                            end
                            m_out_beat <= m_out_beat + 8'd1;
                        end
                    end
                end
                default: begin
                    m_state <= M_IDLE;
                end
            endcase
        end
    end

    always_comb begin
        token_rd_en = 1'b0;
        data_prefetch_pop = 1'b0;
        if (m_state == M_IDLE && !token_fifo_empty && data_prefetch_valid && !token_rd_rst_busy) begin
            token_rd_en = 1'b1;
            data_prefetch_pop = 1'b1;
        end else if (m_state == M_LOAD1 && data_prefetch_valid) begin
            data_prefetch_pop = 1'b1;
        end else if (m_load_beat && !m_send_last && should_shift_after(m_out_beat) && m_shift_needs_prefetch) begin
            data_prefetch_pop = 1'b1;
        end
    end

    always_comb begin
        data_rd_en = 1'b0;
        if (!data_prefetch_valid && !data_fifo_empty && !data_rd_rst_busy) begin
            data_rd_en = 1'b1;
        end
    end

    always_comb begin
        m_axis_tdata = out_tdata;
        m_axis_tkeep = out_tkeep;
        m_axis_tlast = out_tlast;
        m_axis_tvalid = out_tvalid;
    end

    xpm_fifo_async #(
        .CASCADE_HEIGHT(0),
        .CDC_SYNC_STAGES(2),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("block"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(DATA_FIFO_DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10),
        .PROG_FULL_THRESH(DATA_FIFO_DEPTH - 10),
        .RD_DATA_COUNT_WIDTH(DATA_COUNT_W),
        .READ_DATA_WIDTH(DATA_W),
        .READ_MODE("fwft"),
        .RELATED_CLOCKS(0),
        .SIM_ASSERT_CHK(0),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0),
        .WRITE_DATA_WIDTH(DATA_W),
        .WR_DATA_COUNT_WIDTH(DATA_COUNT_W)
    ) u_data_fifo (
        .almost_empty(),
        .almost_full(),
        .data_valid(),
        .dbiterr(),
        .dout(data_fifo_dout),
        .empty(data_fifo_empty),
        .full(data_fifo_full),
        .overflow(),
        .prog_empty(),
        .prog_full(),
        .rd_data_count(data_rd_data_count),
        .rd_rst_busy(data_rd_rst_busy),
        .sbiterr(),
        .underflow(),
        .wr_ack(),
        .wr_data_count(data_wr_data_count),
        .wr_rst_busy(data_wr_rst_busy),
        .din(s_axis_tdata),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .rd_clk(m_clk),
        .rd_en(data_rd_en),
        .rst(fifo_rst),
        .sleep(1'b0),
        .wr_clk(s_clk),
        .wr_en(data_wr_en)
    );

    xpm_fifo_async #(
        .CASCADE_HEIGHT(0),
        .CDC_SYNC_STAGES(2),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("distributed"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(TOKEN_FIFO_DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(5),
        .PROG_FULL_THRESH(TOKEN_FIFO_DEPTH - 5),
        .RD_DATA_COUNT_WIDTH(TOKEN_COUNT_W),
        .READ_DATA_WIDTH(TOKEN_W),
        .READ_MODE("fwft"),
        .RELATED_CLOCKS(0),
        .SIM_ASSERT_CHK(0),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0),
        .WRITE_DATA_WIDTH(TOKEN_W),
        .WR_DATA_COUNT_WIDTH(TOKEN_COUNT_W)
    ) u_token_fifo (
        .almost_empty(),
        .almost_full(),
        .data_valid(),
        .dbiterr(),
        .dout(token_fifo_dout),
        .empty(token_fifo_empty),
        .full(token_fifo_full),
        .overflow(),
        .prog_empty(),
        .prog_full(),
        .rd_data_count(token_rd_data_count),
        .rd_rst_busy(token_rd_rst_busy),
        .sbiterr(),
        .underflow(),
        .wr_ack(),
        .wr_data_count(token_wr_data_count),
        .wr_rst_busy(token_wr_rst_busy),
        .din(token_din),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .rd_clk(m_clk),
        .rd_en(token_rd_en),
        .rst(fifo_rst),
        .sleep(1'b0),
        .wr_clk(s_clk),
        .wr_en(token_wr_en)
    );

endmodule

`default_nettype wire
