module udp_frame_builder #(
    parameter integer DATA_W = 64
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 clear,
    input  wire [47:0]          src_mac,
    input  wire [31:0]          src_ip,
    input  wire [47:0]          s_dst_mac,
    input  wire [31:0]          s_dst_ip,
    input  wire [15:0]          s_src_udp_port,
    input  wire [15:0]          s_dst_udp_port,
    input  wire [31:0]          s_t510_payload_bytes,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [DATA_W/8-1:0]  s_axis_tkeep,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    output logic                s_axis_tready,
    output logic [DATA_W-1:0]   m_axis_tdata,
    output logic [DATA_W/8-1:0] m_axis_tkeep,
    output logic                m_axis_tvalid,
    output logic                m_axis_tlast,
    input  wire                 m_axis_tready,
    output logic [31:0]         frame_built_count,
    output logic [31:0]         frame_byte_count
);

    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_HDR0    = 3'd1;
    localparam [2:0] ST_HDR1    = 3'd2;
    localparam [2:0] ST_HDR2    = 3'd3;
    localparam [2:0] ST_HDR3    = 3'd4;
    localparam [2:0] ST_HDR4    = 3'd5;
    localparam [2:0] ST_MIX     = 3'd6;
    localparam [2:0] ST_PAYLOAD = 3'd7;

    logic [2:0] state;
    logic       tail_pending;
    logic [63:0] first_word;
    logic        first_last;
    logic [15:0] carry_bytes;
    logic [47:0] dst_mac_latched;
    logic [31:0] dst_ip_latched;
    logic [15:0] src_udp_port_latched;
    logic [15:0] dst_udp_port_latched;
    logic [31:0] t510_payload_bytes_latched;
    logic [15:0] ipv4_total_len_latched;
    logic [15:0] udp_len_latched;
    logic [15:0] ip_ident_latched;
    logic [15:0] ip_checksum_latched;
    logic [31:0] frame_len_latched;

    function automatic [63:0] pack8(
        input [7:0] b0,
        input [7:0] b1,
        input [7:0] b2,
        input [7:0] b3,
        input [7:0] b4,
        input [7:0] b5,
        input [7:0] b6,
        input [7:0] b7
    );
        begin
            pack8 = {b7, b6, b5, b4, b3, b2, b1, b0};
        end
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

    function automatic [15:0] ipv4_checksum(
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
            ipv4_checksum = fold_checksum(sum);
        end
    endfunction

    function automatic [63:0] header_word(input [2:0] idx);
        begin
            case (idx)
                3'd0: header_word = pack8(
                    dst_mac_latched[47:40],
                    dst_mac_latched[39:32],
                    dst_mac_latched[31:24],
                    dst_mac_latched[23:16],
                    dst_mac_latched[15:8],
                    dst_mac_latched[7:0],
                    src_mac[47:40],
                    src_mac[39:32]
                );
                3'd1: header_word = pack8(
                    src_mac[31:24],
                    src_mac[23:16],
                    src_mac[15:8],
                    src_mac[7:0],
                    8'h08,
                    8'h00,
                    8'h45,
                    8'h00
                );
                3'd2: header_word = pack8(
                    ipv4_total_len_latched[15:8],
                    ipv4_total_len_latched[7:0],
                    ip_ident_latched[15:8],
                    ip_ident_latched[7:0],
                    8'h40,
                    8'h00,
                    8'h40,
                    8'h11
                );
                3'd3: header_word = pack8(
                    ip_checksum_latched[15:8],
                    ip_checksum_latched[7:0],
                    src_ip[31:24],
                    src_ip[23:16],
                    src_ip[15:8],
                    src_ip[7:0],
                    dst_ip_latched[31:24],
                    dst_ip_latched[23:16]
                );
                default: header_word = pack8(
                    dst_ip_latched[15:8],
                    dst_ip_latched[7:0],
                    src_udp_port_latched[15:8],
                    src_udp_port_latched[7:0],
                    dst_udp_port_latched[15:8],
                    dst_udp_port_latched[7:0],
                    udp_len_latched[15:8],
                    udp_len_latched[7:0]
                );
            endcase
        end
    endfunction

    wire s_fire = s_axis_tvalid && s_axis_tready;
    wire m_fire = m_axis_tvalid && m_axis_tready;
    wire [31:0] udp_payload_bytes_next = 32'd128 + s_t510_payload_bytes;
    wire [31:0] udp_len_next = 32'd8 + udp_payload_bytes_next;
    wire [31:0] ipv4_total_len_next = 32'd20 + udp_len_next;
    wire [31:0] frame_len_next = 32'd14 + ipv4_total_len_next;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                     <= ST_IDLE;
            tail_pending              <= 1'b0;
            first_word                <= 64'd0;
            first_last                <= 1'b0;
            carry_bytes               <= 16'd0;
            dst_mac_latched           <= 48'd0;
            dst_ip_latched            <= 32'd0;
            src_udp_port_latched      <= 16'd0;
            dst_udp_port_latched      <= 16'd0;
            t510_payload_bytes_latched <= 32'd8192;
            ipv4_total_len_latched    <= 16'd0;
            udp_len_latched           <= 16'd0;
            ip_ident_latched          <= 16'd0;
            ip_checksum_latched       <= 16'd0;
            frame_len_latched         <= 32'd0;
            frame_built_count         <= 32'd0;
            frame_byte_count          <= 32'd0;
        end else if (clear) begin
            state             <= ST_IDLE;
            tail_pending      <= 1'b0;
            frame_built_count <= 32'd0;
            frame_byte_count  <= 32'd0;
        end else begin
            case (state)
                ST_IDLE: begin
                    tail_pending <= 1'b0;
                    if (s_fire) begin
                        first_word                 <= s_axis_tdata;
                        first_last                 <= s_axis_tlast;
                        dst_mac_latched            <= s_dst_mac;
                        dst_ip_latched             <= s_dst_ip;
                        src_udp_port_latched       <= s_src_udp_port;
                        dst_udp_port_latched       <= s_dst_udp_port;
                        t510_payload_bytes_latched <= s_t510_payload_bytes;
                        ipv4_total_len_latched     <= ipv4_total_len_next[15:0];
                        udp_len_latched            <= udp_len_next[15:0];
                        ip_ident_latched           <= frame_built_count[15:0];
                        ip_checksum_latched        <= ipv4_checksum(ipv4_total_len_next[15:0], frame_built_count[15:0], src_ip, s_dst_ip);
                        frame_len_latched          <= frame_len_next;
                        frame_built_count          <= frame_built_count + 32'd1;
                        state                      <= ST_HDR0;
                    end
                end

                ST_HDR0: if (m_fire) state <= ST_HDR1;
                ST_HDR1: if (m_fire) state <= ST_HDR2;
                ST_HDR2: if (m_fire) state <= ST_HDR3;
                ST_HDR3: if (m_fire) state <= ST_HDR4;
                ST_HDR4: if (m_fire) state <= ST_MIX;

                ST_MIX: begin
                    if (m_fire) begin
                        carry_bytes <= first_word[63:48];
                        if (first_last) begin
                            tail_pending <= 1'b1;
                        end
                        state <= ST_PAYLOAD;
                    end
                end

                ST_PAYLOAD: begin
                    if (tail_pending) begin
                        if (m_fire) begin
                            frame_byte_count <= frame_byte_count + frame_len_latched;
                            tail_pending     <= 1'b0;
                            state            <= ST_IDLE;
                        end
                    end else if (s_fire) begin
                        carry_bytes <= s_axis_tdata[63:48];
                        if (s_axis_tlast) begin
                            tail_pending <= 1'b1;
                        end
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
        m_axis_tdata  = 64'd0;
        m_axis_tkeep  = 8'h00;
        m_axis_tvalid = 1'b0;
        m_axis_tlast  = 1'b0;

        case (state)
            ST_IDLE: begin
                s_axis_tready = enable;
            end
            ST_HDR0: begin
                m_axis_tdata  = header_word(3'd0);
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_HDR1: begin
                m_axis_tdata  = header_word(3'd1);
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_HDR2: begin
                m_axis_tdata  = header_word(3'd2);
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_HDR3: begin
                m_axis_tdata  = header_word(3'd3);
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_HDR4: begin
                m_axis_tdata  = header_word(3'd4);
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_MIX: begin
                m_axis_tdata = pack8(
                    8'h00,
                    8'h00,
                    first_word[7:0],
                    first_word[15:8],
                    first_word[23:16],
                    first_word[31:24],
                    first_word[39:32],
                    first_word[47:40]
                );
                m_axis_tkeep  = 8'hff;
                m_axis_tvalid = 1'b1;
            end
            ST_PAYLOAD: begin
                if (tail_pending) begin
                    m_axis_tdata = pack8(
                        carry_bytes[7:0],
                        carry_bytes[15:8],
                        8'h00,
                        8'h00,
                        8'h00,
                        8'h00,
                        8'h00,
                        8'h00
                    );
                    m_axis_tkeep  = 8'h03;
                    m_axis_tvalid = 1'b1;
                    m_axis_tlast  = 1'b1;
                end else begin
                    s_axis_tready = m_axis_tready;
                    m_axis_tdata = pack8(
                        carry_bytes[7:0],
                        carry_bytes[15:8],
                        s_axis_tdata[7:0],
                        s_axis_tdata[15:8],
                        s_axis_tdata[23:16],
                        s_axis_tdata[31:24],
                        s_axis_tdata[39:32],
                        s_axis_tdata[47:40]
                    );
                    m_axis_tkeep  = 8'hff;
                    m_axis_tvalid = s_axis_tvalid;
                end
            end
            default: begin
            end
        endcase
    end

endmodule
