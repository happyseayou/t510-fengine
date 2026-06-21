`default_nettype none

module t510_qsfp_test_frame_gen (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         enable,
    input  wire         clear,
    input  wire [31:0]  interval_cycles,
    input  wire [47:0]  src_mac,
    input  wire [31:0]  src_ip,
    input  wire [47:0]  dst_mac,
    input  wire [31:0]  dst_ip,
    input  wire [15:0]  src_udp_port,
    input  wire [15:0]  dst_udp_port,
    input  wire [31:0]  core_version,
    input  wire [15:0]  board_id,
    input  wire [31:0]  status_flags,
    input  wire [63:0]  sample_count,
    output logic [511:0] m_axis_tdata,
    output logic [63:0]  m_axis_tkeep,
    output logic         m_axis_tvalid,
    output logic         m_axis_tlast,
    input  wire          m_axis_tready,
    output logic [31:0]  packet_count,
    output logic [31:0]  byte_count
);

    localparam [15:0] IPV4_TOTAL_LEN = 16'd50;
    localparam [15:0] UDP_LEN        = 16'd30;
    localparam [31:0] MIN_INTERVAL   = 32'd1024;

    typedef enum logic [2:0] {
        ST_IDLE  = 3'd0,
        ST_SUM1  = 3'd1,
        ST_SUM2  = 3'd2,
        ST_SUM3  = 3'd3,
        ST_FRAME = 3'd4,
        ST_SEND  = 3'd5
    } state_t;

    state_t state;
    logic [31:0] gap_count;
    logic [31:0] seq_no;
    logic [31:0] seq_latched;
    logic [47:0] src_mac_latched;
    logic [47:0] dst_mac_latched;
    logic [31:0] src_ip_latched;
    logic [31:0] dst_ip_latched;
    logic [15:0] src_udp_port_latched;
    logic [15:0] dst_udp_port_latched;
    logic [31:0] core_version_latched;
    logic [15:0] board_id_latched;
    logic [31:0] status_flags_latched;
    logic [63:0] sample_count_latched;
    logic [31:0] checksum_sum_a;
    logic [31:0] checksum_sum_b;
    logic [31:0] checksum_sum_c;
    logic [31:0] checksum_sum_d;
    logic [31:0] checksum_sum_e;
    logic [31:0] checksum_sum_f;
    logic [31:0] checksum_total;
    logic [15:0] ip_checksum;

    function automatic [15:0] fold_checksum(input [31:0] sum_in);
        reg [31:0] sum_folded;
        begin
            sum_folded = sum_in;
            sum_folded = (sum_folded & 32'h0000_ffff) + (sum_folded >> 16);
            sum_folded = (sum_folded & 32'h0000_ffff) + (sum_folded >> 16);
            fold_checksum = ~sum_folded[15:0];
        end
    endfunction

    wire fire = m_axis_tvalid && m_axis_tready;
    wire [31:0] interval_clamped =
        (interval_cycles < MIN_INTERVAL) ? MIN_INTERVAL : interval_cycles;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state         <= ST_IDLE;
            gap_count     <= 32'd0;
            seq_no        <= 32'd0;
            seq_latched   <= 32'd0;
            src_mac_latched <= 48'd0;
            dst_mac_latched <= 48'd0;
            src_ip_latched <= 32'd0;
            dst_ip_latched <= 32'd0;
            src_udp_port_latched <= 16'd0;
            dst_udp_port_latched <= 16'd0;
            core_version_latched <= 32'd0;
            board_id_latched <= 16'd0;
            status_flags_latched <= 32'd0;
            sample_count_latched <= 64'd0;
            checksum_sum_a <= 32'd0;
            checksum_sum_b <= 32'd0;
            checksum_sum_c <= 32'd0;
            checksum_sum_d <= 32'd0;
            checksum_sum_e <= 32'd0;
            checksum_sum_f <= 32'd0;
            checksum_total <= 32'd0;
            ip_checksum   <= 16'd0;
            m_axis_tdata  <= 512'd0;
            m_axis_tkeep  <= 64'd0;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast  <= 1'b0;
            packet_count  <= 32'd0;
            byte_count    <= 32'd0;
        end else if (clear) begin
            gap_count     <= 32'd0;
            seq_no        <= 32'd0;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast  <= 1'b0;
            packet_count  <= 32'd0;
            byte_count    <= 32'd0;
            state         <= ST_IDLE;
        end else begin
            case (state)
                ST_IDLE: begin
                    if (!enable) begin
                        gap_count <= interval_clamped;
                    end else if (gap_count != 32'd0) begin
                        gap_count <= gap_count - 32'd1;
                    end else begin
                        seq_latched <= seq_no;
                        src_mac_latched <= src_mac;
                        dst_mac_latched <= dst_mac;
                        src_ip_latched <= src_ip;
                        dst_ip_latched <= dst_ip;
                        src_udp_port_latched <= src_udp_port;
                        dst_udp_port_latched <= dst_udp_port;
                        core_version_latched <= core_version;
                        board_id_latched <= board_id;
                        status_flags_latched <= status_flags;
                        sample_count_latched <= sample_count;
                        checksum_sum_a <= {16'd0, 16'h4500} + {16'd0, IPV4_TOTAL_LEN};
                        checksum_sum_b <= {16'd0, seq_no[15:0]} + 32'h0000_4000;
                        checksum_sum_c <= 32'h0000_4011 + {16'd0, src_ip[31:16]};
                        checksum_sum_d <= {16'd0, src_ip[15:0]} + {16'd0, dst_ip[31:16]};
                        checksum_sum_e <= {16'd0, dst_ip[15:0]};
                        state <= ST_SUM1;
                    end
                end
                ST_SUM1: begin
                    if (!enable) begin
                        state <= ST_IDLE;
                        gap_count <= interval_clamped;
                    end else begin
                        checksum_sum_f <= checksum_sum_a + checksum_sum_b;
                        checksum_total <= checksum_sum_c + checksum_sum_d + checksum_sum_e;
                        state <= ST_SUM2;
                    end
                end
                ST_SUM2: begin
                    if (!enable) begin
                        state <= ST_IDLE;
                        gap_count <= interval_clamped;
                    end else begin
                        checksum_total <= checksum_sum_f + checksum_total;
                        state <= ST_SUM3;
                    end
                end
                ST_SUM3: begin
                    if (!enable) begin
                        state <= ST_IDLE;
                        gap_count <= interval_clamped;
                    end else begin
                        ip_checksum <= fold_checksum(checksum_total);
                        state <= ST_FRAME;
                    end
                end
                ST_FRAME: begin
                    m_axis_tdata <= 512'd0;
                    // Ethernet header, byte 0 first on AXIS.
                    m_axis_tdata[  0 +: 8] <= dst_mac_latched[47:40];
                    m_axis_tdata[  8 +: 8] <= dst_mac_latched[39:32];
                    m_axis_tdata[ 16 +: 8] <= dst_mac_latched[31:24];
                    m_axis_tdata[ 24 +: 8] <= dst_mac_latched[23:16];
                    m_axis_tdata[ 32 +: 8] <= dst_mac_latched[15:8];
                    m_axis_tdata[ 40 +: 8] <= dst_mac_latched[7:0];
                    m_axis_tdata[ 48 +: 8] <= src_mac_latched[47:40];
                    m_axis_tdata[ 56 +: 8] <= src_mac_latched[39:32];
                    m_axis_tdata[ 64 +: 8] <= src_mac_latched[31:24];
                    m_axis_tdata[ 72 +: 8] <= src_mac_latched[23:16];
                    m_axis_tdata[ 80 +: 8] <= src_mac_latched[15:8];
                    m_axis_tdata[ 88 +: 8] <= src_mac_latched[7:0];
                    m_axis_tdata[ 96 +: 8] <= 8'h08;
                    m_axis_tdata[104 +: 8] <= 8'h00;

                    // IPv4 header, UDP, checksum valid, UDP checksum disabled.
                    m_axis_tdata[112 +: 8] <= 8'h45;
                    m_axis_tdata[120 +: 8] <= 8'h00;
                    m_axis_tdata[128 +: 8] <= IPV4_TOTAL_LEN[15:8];
                    m_axis_tdata[136 +: 8] <= IPV4_TOTAL_LEN[7:0];
                    m_axis_tdata[144 +: 8] <= seq_latched[15:8];
                    m_axis_tdata[152 +: 8] <= seq_latched[7:0];
                    m_axis_tdata[160 +: 8] <= 8'h40;
                    m_axis_tdata[168 +: 8] <= 8'h00;
                    m_axis_tdata[176 +: 8] <= 8'h40;
                    m_axis_tdata[184 +: 8] <= 8'h11;
                    m_axis_tdata[192 +: 8] <= ip_checksum[15:8];
                    m_axis_tdata[200 +: 8] <= ip_checksum[7:0];
                    m_axis_tdata[208 +: 8] <= src_ip_latched[31:24];
                    m_axis_tdata[216 +: 8] <= src_ip_latched[23:16];
                    m_axis_tdata[224 +: 8] <= src_ip_latched[15:8];
                    m_axis_tdata[232 +: 8] <= src_ip_latched[7:0];
                    m_axis_tdata[240 +: 8] <= dst_ip_latched[31:24];
                    m_axis_tdata[248 +: 8] <= dst_ip_latched[23:16];
                    m_axis_tdata[256 +: 8] <= dst_ip_latched[15:8];
                    m_axis_tdata[264 +: 8] <= dst_ip_latched[7:0];
                    m_axis_tdata[272 +: 8] <= src_udp_port_latched[15:8];
                    m_axis_tdata[280 +: 8] <= src_udp_port_latched[7:0];
                    m_axis_tdata[288 +: 8] <= dst_udp_port_latched[15:8];
                    m_axis_tdata[296 +: 8] <= dst_udp_port_latched[7:0];
                    m_axis_tdata[304 +: 8] <= UDP_LEN[15:8];
                    m_axis_tdata[312 +: 8] <= UDP_LEN[7:0];
                    m_axis_tdata[320 +: 8] <= 8'h00;
                    m_axis_tdata[328 +: 8] <= 8'h00;

                    // 22 byte Stage 24 heartbeat payload.
                    m_axis_tdata[336 +: 8] <= 8'h54; // T
                    m_axis_tdata[344 +: 8] <= 8'h35; // 5
                    m_axis_tdata[352 +: 8] <= 8'h31; // 1
                    m_axis_tdata[360 +: 8] <= 8'h30; // 0
                    m_axis_tdata[368 +: 8] <= core_version_latched[31:24];
                    m_axis_tdata[376 +: 8] <= core_version_latched[23:16];
                    m_axis_tdata[384 +: 8] <= core_version_latched[15:8];
                    m_axis_tdata[392 +: 8] <= core_version_latched[7:0];
                    m_axis_tdata[400 +: 8] <= seq_latched[31:24];
                    m_axis_tdata[408 +: 8] <= seq_latched[23:16];
                    m_axis_tdata[416 +: 8] <= seq_latched[15:8];
                    m_axis_tdata[424 +: 8] <= seq_latched[7:0];
                    m_axis_tdata[432 +: 8] <= sample_count_latched[31:24];
                    m_axis_tdata[440 +: 8] <= sample_count_latched[23:16];
                    m_axis_tdata[448 +: 8] <= sample_count_latched[15:8];
                    m_axis_tdata[456 +: 8] <= sample_count_latched[7:0];
                    m_axis_tdata[464 +: 8] <= status_flags_latched[31:24];
                    m_axis_tdata[472 +: 8] <= status_flags_latched[23:16];
                    m_axis_tdata[480 +: 8] <= status_flags_latched[15:8];
                    m_axis_tdata[488 +: 8] <= status_flags_latched[7:0];
                    m_axis_tdata[496 +: 8] <= board_id_latched[15:8];
                    m_axis_tdata[504 +: 8] <= board_id_latched[7:0];
                    m_axis_tkeep  <= 64'hffff_ffff_ffff_ffff;
                    m_axis_tvalid <= 1'b1;
                    m_axis_tlast  <= 1'b1;
                    state <= ST_SEND;
                end
                ST_SEND: begin
                    if (fire) begin
                        m_axis_tvalid <= 1'b0;
                        m_axis_tlast  <= 1'b0;
                        seq_no        <= seq_no + 32'd1;
                        packet_count  <= packet_count + 32'd1;
                        byte_count    <= byte_count + 32'd64;
                        gap_count     <= interval_clamped;
                        state         <= ST_IDLE;
                    end
                end
                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

endmodule

`default_nettype wire
