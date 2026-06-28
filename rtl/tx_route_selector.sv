module tx_route_selector #(
    parameter integer DATA_W        = 64,
    parameter integer N_ENDPOINTS   = 72,
    parameter integer N_SPEC_ROUTES = 64,
    parameter integer N_TIME_ROUTES = 8,
    parameter integer HEADER_WORDS  = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         enable,
    input  wire                         clear,
    input  wire                         drop_on_route_miss,
    input  wire [15:0]                  time_input_mask,
    input  wire [N_ENDPOINTS-1:0]       endpoint_enable,
    input  wire [N_ENDPOINTS*32-1:0]    endpoint_ip_vec,
    input  wire [N_ENDPOINTS*48-1:0]    endpoint_mac_vec,
    input  wire [N_ENDPOINTS*16-1:0]    endpoint_src_port_vec,
    input  wire [N_ENDPOINTS*16-1:0]    endpoint_dst_port_vec,
    input  wire [N_SPEC_ROUTES-1:0]     spec_route_enable,
    input  wire [N_SPEC_ROUTES*32-1:0]  spec_route_chan0_vec,
    input  wire [N_SPEC_ROUTES*16-1:0]  spec_route_chan_count_vec,
    input  wire [N_SPEC_ROUTES*8-1:0]   spec_route_endpoint_vec,
    input  wire [N_TIME_ROUTES-1:0]     time_route_enable,
    input  wire [N_TIME_ROUTES*16-1:0]  time_route_input_mask_vec,
    input  wire [N_TIME_ROUTES*8-1:0]   time_route_endpoint_vec,
    input  wire [DATA_W-1:0]            s_axis_tdata,
    input  wire [DATA_W/8-1:0]          s_axis_tkeep,
    input  wire                         s_axis_tvalid,
    input  wire                         s_axis_tlast,
    output logic                        s_axis_tready,
    output logic [DATA_W-1:0]           m_axis_tdata,
    output logic [DATA_W/8-1:0]         m_axis_tkeep,
    output logic                        m_axis_tvalid,
    output logic                        m_axis_tlast,
    input  wire                         m_axis_tready,
    output logic [47:0]                 m_dst_mac,
    output logic [31:0]                 m_dst_ip,
    output logic [15:0]                 m_src_udp_port,
    output logic [15:0]                 m_dst_udp_port,
    output logic [31:0]                 m_t510_payload_bytes,
    output logic [15:0]                 m_stream_type,
    output logic [7:0]                  m_endpoint_id,
    output logic [5:0]                  m_route_id,
    output logic                        m_route_is_time,
    output logic [31:0]                 frame_forwarded_count,
    output logic [31:0]                 frame_dropped_count,
    output logic [31:0]                 route_miss_count,
    output logic [31:0]                 route_error_count,
    output logic [7:0]                  selected_endpoint_id,
    output logic [5:0]                  selected_route_id,
    output logic                        selected_route_is_time,
    output logic [N_SPEC_ROUTES*32-1:0] spec_route_hit_count_vec,
    output logic [N_TIME_ROUTES*32-1:0] time_route_hit_count_vec
);

    localparam [15:0] STREAM_SPEC = 16'd0;
    localparam [15:0] STREAM_TIME = 16'd1;

    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_CAPTURE = 3'd1;
    localparam [2:0] ST_REPLAY  = 3'd2;
    localparam [2:0] ST_STREAM  = 3'd3;
    localparam [2:0] ST_DROP    = 3'd4;

    logic [2:0] state;
    logic [4:0] capture_idx;
    logic [4:0] replay_idx;
    logic [DATA_W-1:0] header_words [0:HEADER_WORDS-1];

    logic [15:0] parsed_stream_type;
    logic [31:0] parsed_chan0;
    logic [15:0] parsed_chan_count;
    logic [31:0] parsed_payload_bytes;

    logic [47:0] selected_dst_mac;
    logic [31:0] selected_dst_ip;
    logic [15:0] selected_src_udp_port;
    logic [15:0] selected_dst_udp_port;
    logic [15:0] selected_stream_type;
    logic [31:0] selected_payload_bytes;

    logic route_found;
    logic route_endpoint_enabled;
    logic route_is_time_comb;
    logic [5:0] route_id_comb;
    logic [7:0] endpoint_id_comb;
    logic [31:0] packet_chan_end;
    logic [31:0] route_chan_end;

    logic [N_SPEC_ROUTES*32-1:0] spec_hit_counts;
    logic [N_TIME_ROUTES*32-1:0] time_hit_counts;

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

    function automatic [31:0] spec_route_chan0(input integer idx);
        begin
            spec_route_chan0 = spec_route_chan0_vec[idx*32 +: 32];
        end
    endfunction

    function automatic [15:0] spec_route_chan_count(input integer idx);
        begin
            spec_route_chan_count = spec_route_chan_count_vec[idx*16 +: 16];
        end
    endfunction

    function automatic [7:0] spec_route_endpoint(input integer idx);
        begin
            spec_route_endpoint = spec_route_endpoint_vec[idx*8 +: 8];
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

    integer route_idx;
    integer clear_idx;
    integer pack_idx;

    always_comb begin
        route_found            = 1'b0;
        route_endpoint_enabled = 1'b0;
        route_is_time_comb     = 1'b0;
        route_id_comb          = 6'd0;
        endpoint_id_comb       = 8'd0;
        packet_chan_end        = parsed_chan0 + {16'd0, parsed_chan_count};
        route_chan_end         = 32'd0;

        if (parsed_stream_type == STREAM_SPEC) begin
            for (route_idx = 0; route_idx < N_SPEC_ROUTES; route_idx = route_idx + 1) begin
                route_chan_end = spec_route_chan0(route_idx) + {16'd0, spec_route_chan_count(route_idx)};
                if (!route_found &&
                    spec_route_enable[route_idx] &&
                    (spec_route_chan_count(route_idx) != 16'd0) &&
                    (parsed_chan_count != 16'd0) &&
                    (parsed_chan0 >= spec_route_chan0(route_idx)) &&
                    (packet_chan_end <= route_chan_end)) begin
                    route_found        = 1'b1;
                    route_is_time_comb = 1'b0;
                    route_id_comb      = route_idx[5:0];
                    endpoint_id_comb   = spec_route_endpoint(route_idx);
                end
            end
        end else if (parsed_stream_type == STREAM_TIME) begin
            for (route_idx = 0; route_idx < N_TIME_ROUTES; route_idx = route_idx + 1) begin
                if (!route_found &&
                    time_route_enable[route_idx] &&
                    (time_route_input_mask(route_idx) == time_input_mask)) begin
                    route_found        = 1'b1;
                    route_is_time_comb = 1'b1;
                    route_id_comb      = {3'd0, route_idx[2:0]};
                    endpoint_id_comb   = time_route_endpoint(route_idx);
                end
            end
        end

        if (route_found) begin
            route_endpoint_enabled = ({24'd0, endpoint_id_comb} < N_ENDPOINTS) &&
                                     endpoint_enable[endpoint_id_comb];
        end else if (!drop_on_route_miss && endpoint_enable[0]) begin
            endpoint_id_comb       = 8'd0;
            route_endpoint_enabled = 1'b1;
        end
    end

    wire s_fire = s_axis_tvalid && s_axis_tready;
    wire m_fire = m_axis_tvalid && m_axis_tready;
    wire route_ok_comb = route_endpoint_enabled;
    wire route_miss_comb = !route_found;
    wire route_error_comb = route_found && !route_endpoint_enabled;
    wire should_drop_comb = !route_ok_comb && drop_on_route_miss;

    task automatic latch_selected_route;
        begin
            selected_endpoint_id    <= endpoint_id_comb;
            selected_route_id       <= route_id_comb;
            selected_route_is_time  <= route_is_time_comb;
            selected_dst_mac        <= endpoint_mac(endpoint_id_comb);
            selected_dst_ip         <= endpoint_ip(endpoint_id_comb);
            selected_src_udp_port   <= endpoint_src_port(endpoint_id_comb);
            selected_dst_udp_port   <= endpoint_dst_port(endpoint_id_comb);
            selected_stream_type    <= parsed_stream_type;
            selected_payload_bytes  <= parsed_payload_bytes;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                  <= ST_IDLE;
            capture_idx            <= 5'd0;
            replay_idx             <= 5'd0;
            parsed_stream_type     <= 16'd0;
            parsed_chan0           <= 32'd0;
            parsed_chan_count      <= 16'd0;
            parsed_payload_bytes   <= 32'd8192;
            selected_endpoint_id   <= 8'd0;
            selected_route_id      <= 6'd0;
            selected_route_is_time <= 1'b0;
            selected_dst_mac       <= 48'd0;
            selected_dst_ip        <= 32'd0;
            selected_src_udp_port  <= 16'd0;
            selected_dst_udp_port  <= 16'd0;
            selected_stream_type   <= 16'd0;
            selected_payload_bytes <= 32'd8192;
            frame_forwarded_count  <= 32'd0;
            frame_dropped_count    <= 32'd0;
            route_miss_count       <= 32'd0;
            route_error_count      <= 32'd0;
            spec_hit_counts        <= {N_SPEC_ROUTES*32{1'b0}};
            time_hit_counts        <= {N_TIME_ROUTES*32{1'b0}};
            for (clear_idx = 0; clear_idx < HEADER_WORDS; clear_idx = clear_idx + 1) begin
                header_words[clear_idx] <= {DATA_W{1'b0}};
            end
        end else if (clear) begin
            state                  <= ST_IDLE;
            capture_idx            <= 5'd0;
            replay_idx             <= 5'd0;
            frame_forwarded_count  <= 32'd0;
            frame_dropped_count    <= 32'd0;
            route_miss_count       <= 32'd0;
            route_error_count      <= 32'd0;
            spec_hit_counts        <= {N_SPEC_ROUTES*32{1'b0}};
            time_hit_counts        <= {N_TIME_ROUTES*32{1'b0}};
        end else begin
            case (state)
                ST_IDLE: begin
                    replay_idx <= 5'd0;
                    if (s_fire) begin
                        header_words[0]     <= s_axis_tdata;
                        capture_idx         <= 5'd1;
                        parsed_stream_type  <= 16'd0;
                        parsed_chan0        <= 32'd0;
                        parsed_chan_count   <= 16'd0;
                        parsed_payload_bytes <= 32'd8192;
                        if (s_axis_tlast) begin
                            state <= ST_IDLE;
                            route_error_count   <= route_error_count + 32'd1;
                            frame_dropped_count <= frame_dropped_count + 32'd1;
                        end else begin
                            state <= ST_CAPTURE;
                        end
                    end
                end

                ST_CAPTURE: begin
                    if (s_fire) begin
                        header_words[capture_idx] <= s_axis_tdata;
                        if (capture_idx == 5'd1) begin
                            parsed_stream_type <= s_axis_tdata[47:32];
                        end
                        if (capture_idx == 5'd6) begin
                            parsed_chan0 <= s_axis_tdata[31:0];
                        end
                        if (capture_idx == 5'd7) begin
                            parsed_chan_count <= s_axis_tdata[63:48];
                        end
                        if (capture_idx == 5'd8) begin
                            parsed_payload_bytes <= s_axis_tdata[31:0];
                        end
                        if (s_axis_tlast && (capture_idx != HEADER_WORDS - 1)) begin
                            state <= ST_IDLE;
                            route_error_count   <= route_error_count + 32'd1;
                            frame_dropped_count <= frame_dropped_count + 32'd1;
                        end else if (capture_idx == HEADER_WORDS - 1) begin
                            if (route_miss_comb) begin
                                route_miss_count <= route_miss_count + 32'd1;
                            end
                            if (route_error_comb) begin
                                route_error_count <= route_error_count + 32'd1;
                            end
                            if (should_drop_comb) begin
                                frame_dropped_count <= frame_dropped_count + 32'd1;
                                state <= s_axis_tlast ? ST_IDLE : ST_DROP;
                            end else begin
                                latch_selected_route();
                                frame_forwarded_count <= frame_forwarded_count + 32'd1;
                                if (route_found && route_endpoint_enabled && (parsed_stream_type == STREAM_SPEC)) begin
                                    spec_hit_counts[route_id_comb*32 +: 32] <= spec_hit_counts[route_id_comb*32 +: 32] + 32'd1;
                                end
                                if (route_found && route_endpoint_enabled && (parsed_stream_type == STREAM_TIME)) begin
                                    time_hit_counts[route_id_comb*32 +: 32] <= time_hit_counts[route_id_comb*32 +: 32] + 32'd1;
                                end
                                replay_idx <= 5'd0;
                                state <= ST_REPLAY;
                            end
                        end else begin
                            capture_idx <= capture_idx + 5'd1;
                        end
                    end
                end

                ST_REPLAY: begin
                    if (m_fire) begin
                        if (replay_idx == HEADER_WORDS - 1) begin
                            replay_idx <= 5'd0;
                            state      <= ST_STREAM;
                        end else begin
                            replay_idx <= replay_idx + 5'd1;
                        end
                    end
                end

                ST_STREAM: begin
                    if (s_fire && s_axis_tlast) begin
                        state <= ST_IDLE;
                    end
                end

                ST_DROP: begin
                    if (s_fire && s_axis_tlast) begin
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

    always_comb begin
        s_axis_tready = 1'b0;
        m_axis_tdata  = {DATA_W{1'b0}};
        m_axis_tkeep  = {DATA_W/8{1'b0}};
        m_axis_tvalid = 1'b0;
        m_axis_tlast  = 1'b0;

        case (state)
            ST_IDLE: begin
                s_axis_tready = enable;
            end
            ST_CAPTURE: begin
                s_axis_tready = 1'b1;
            end
            ST_REPLAY: begin
                m_axis_tdata  = header_words[replay_idx];
                m_axis_tkeep  = {DATA_W/8{1'b1}};
                m_axis_tvalid = 1'b1;
                m_axis_tlast  = 1'b0;
            end
            ST_STREAM: begin
                s_axis_tready = m_axis_tready;
                m_axis_tdata  = s_axis_tdata;
                m_axis_tkeep  = s_axis_tkeep;
                m_axis_tvalid = s_axis_tvalid;
                m_axis_tlast  = s_axis_tlast;
            end
            ST_DROP: begin
                s_axis_tready = 1'b1;
            end
            default: begin
            end
        endcase
    end

    always_comb begin
        m_dst_mac            = selected_dst_mac;
        m_dst_ip             = selected_dst_ip;
        m_src_udp_port       = selected_src_udp_port;
        m_dst_udp_port       = selected_dst_udp_port;
        m_t510_payload_bytes = selected_payload_bytes;
        m_stream_type        = selected_stream_type;
        m_endpoint_id        = selected_endpoint_id;
        m_route_id           = selected_route_id;
        m_route_is_time      = selected_route_is_time;
    end

    always_comb begin
        spec_route_hit_count_vec = spec_hit_counts;
        time_route_hit_count_vec = time_hit_counts;
    end

endmodule
