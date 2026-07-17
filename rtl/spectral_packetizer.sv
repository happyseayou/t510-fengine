module spectral_packetizer #(
    parameter integer DATA_W       = 256,
    parameter integer OUT_W        = 64,
    parameter integer HEADER_WORDS = 16
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 stream_reset,
    input  wire [15:0]          board_id,
    input  wire [15:0]          global_input0,
    input  wire [15:0]          epoch_mode,
    input  wire [15:0]          packet_flags,
    input  wire [63:0]          unix_seconds,
    input  wire [63:0]          pps_count,
    input  wire [63:0]          sync_generation,
    input  wire [63:0]          sync_observation_tag,
    input  wire [63:0]          sync_metadata,
    input  wire [63:0]          sync_status,
    input  wire [15:0]          quant_mode,
    input  wire [15:0]          scale_mode,
    input  wire [31:0]          scale_id,
    input  wire [31:0]          spec_chan0,
    input  wire [15:0]          spec_time_count,
    input  wire [15:0]          spec_chan_count,
    input  wire [15:0]          spec_nchan,
    input  wire [15:0]          spec_taps,
    input  wire [15:0]          spec_fft_shift,
    input  wire [31:0]          spec_sample_rate_hz,
    input  wire [31:0]          spec_status_flags,
    input  wire [31:0]          chan_split,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [63:0]          s_axis_sample0,
    input  wire                 s_axis_tvalid,
    output logic                s_axis_tready,
    output logic [OUT_W-1:0]    m_axis_tdata,
    output logic [OUT_W/8-1:0]  m_axis_tkeep,
    output logic                m_axis_tvalid,
    output logic                m_axis_tlast,
    input  wire                 m_axis_tready,
    output logic [31:0]         packet_count,
    output logic [31:0]         udp_byte_count,
    output logic [31:0]         seq_no_debug,
    output logic [63:0]         frame_id_debug,
    output logic [31:0]         chan0_debug
);

    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_CAPTURE = 3'd1;
    localparam [2:0] ST_HEADER  = 3'd2;
    localparam [2:0] ST_PRELOAD_WAIT = 3'd3;
    localparam [2:0] ST_PRELOAD_LOAD = 3'd4;
    localparam [2:0] ST_PAYLOAD      = 3'd5;

    localparam [31:0] T510_MAGIC    = 32'h5435_3130;
    localparam [15:0] STREAM_TYPE   = 16'd0;
    localparam [15:0] PRODUCT_FENGINE_IQ16 = 16'hf101;
    localparam [15:0] LOCAL_NINPUT  = 16'd8;
    localparam [15:0] HEADER_BYTES  = 16'd128;
    localparam [31:0] PAYLOAD_BYTES = 32'd8192;
    localparam integer PAYLOAD_BEATS = PAYLOAD_BYTES / (DATA_W / 8);
    localparam integer ADDR_W = $clog2(PAYLOAD_BEATS);
    localparam integer SUBWORDS_PER_BEAT = DATA_W / OUT_W;
    localparam integer SUBWORD_W = (SUBWORDS_PER_BEAT <= 1) ? 1 : $clog2(SUBWORDS_PER_BEAT);
    localparam [SUBWORD_W-1:0] LAST_SUBWORD = SUBWORDS_PER_BEAT - 1;

    logic [2:0]                state;
    logic [4:0]                header_idx;
    logic [SUBWORD_W-1:0]      payload_subword;
    logic [15:0]               capture_idx;
    logic [15:0]               payload_read_idx;
    logic [DATA_W-1:0]         payload_reg;
    logic [ADDR_W-1:0]         payload_rd_addr;
    wire  [DATA_W-1:0]         payload_mem_rd_data;
    logic [31:0]               seq_no;
    logic [63:0]               sample0;
    logic [63:0]               frame_id;
    logic [15:0]               pkt_epoch_mode;
    logic [15:0]               pkt_packet_flags;
    logic [15:0]               pkt_quant_mode;
    logic [15:0]               pkt_scale_mode;
    logic [31:0]               pkt_scale_id;
    logic [31:0]               pkt_spec_chan0;
    logic [15:0]               pkt_spec_time_count;
    logic [15:0]               pkt_spec_chan_count;
    logic [15:0]               pkt_spec_nchan;
    logic [15:0]               pkt_spec_taps;
    logic [15:0]               pkt_spec_fft_shift;
    logic [31:0]               pkt_spec_sample_rate_hz;
    logic [31:0]               pkt_spec_status_flags;
    logic [31:0]               pkt_chan_split;
    wire                       capture_write_en =
        ((state == ST_IDLE) || (state == ST_CAPTURE)) && enable && s_axis_tvalid;
    wire [ADDR_W-1:0]          capture_write_addr =
        (state == ST_IDLE) ? {ADDR_W{1'b0}} : capture_idx[ADDR_W-1:0];
    wire [15:0]                block_count =
        block_count_from_pow2_chan_count(pkt_spec_nchan, pkt_spec_chan_count);
    wire [15:0]                block_index =
        block_index_from_pow2_chan_count(pkt_spec_chan0, pkt_spec_chan_count);

    function automatic [15:0] block_count_from_pow2_chan_count(
        input [15:0] nchan_value,
        input [15:0] chan_count_value
    );
        begin
            case (chan_count_value)
                16'd1:    block_count_from_pow2_chan_count = nchan_value;
                16'd2:    block_count_from_pow2_chan_count = (nchan_value[0] == 1'b0) ? {1'b0, nchan_value[15:1]} : 16'd0;
                16'd4:    block_count_from_pow2_chan_count = (nchan_value[1:0] == 2'd0) ? {2'd0, nchan_value[15:2]} : 16'd0;
                16'd8:    block_count_from_pow2_chan_count = (nchan_value[2:0] == 3'd0) ? {3'd0, nchan_value[15:3]} : 16'd0;
                16'd16:   block_count_from_pow2_chan_count = (nchan_value[3:0] == 4'd0) ? {4'd0, nchan_value[15:4]} : 16'd0;
                16'd32:   block_count_from_pow2_chan_count = (nchan_value[4:0] == 5'd0) ? {5'd0, nchan_value[15:5]} : 16'd0;
                16'd64:   block_count_from_pow2_chan_count = (nchan_value[5:0] == 6'd0) ? {6'd0, nchan_value[15:6]} : 16'd0;
                16'd128:  block_count_from_pow2_chan_count = (nchan_value[6:0] == 7'd0) ? {7'd0, nchan_value[15:7]} : 16'd0;
                16'd256:  block_count_from_pow2_chan_count = (nchan_value[7:0] == 8'd0) ? {8'd0, nchan_value[15:8]} : 16'd0;
                16'd512:  block_count_from_pow2_chan_count = (nchan_value[8:0] == 9'd0) ? {9'd0, nchan_value[15:9]} : 16'd0;
                16'd1024: block_count_from_pow2_chan_count = (nchan_value[9:0] == 10'd0) ? {10'd0, nchan_value[15:10]} : 16'd0;
                16'd2048: block_count_from_pow2_chan_count = (nchan_value[10:0] == 11'd0) ? {11'd0, nchan_value[15:11]} : 16'd0;
                16'd4096: block_count_from_pow2_chan_count = (nchan_value[11:0] == 12'd0) ? {12'd0, nchan_value[15:12]} : 16'd0;
                default:  block_count_from_pow2_chan_count = 16'd0;
            endcase
        end
    endfunction

    function automatic [15:0] block_index_from_pow2_chan_count(
        input [31:0] chan0_value,
        input [15:0] chan_count_value
    );
        begin
            case (chan_count_value)
                16'd1:    block_index_from_pow2_chan_count = chan0_value[15:0];
                16'd2:    block_index_from_pow2_chan_count = (chan0_value[0] == 1'b0) ? chan0_value[16:1] : 16'd0;
                16'd4:    block_index_from_pow2_chan_count = (chan0_value[1:0] == 2'd0) ? chan0_value[17:2] : 16'd0;
                16'd8:    block_index_from_pow2_chan_count = (chan0_value[2:0] == 3'd0) ? chan0_value[18:3] : 16'd0;
                16'd16:   block_index_from_pow2_chan_count = (chan0_value[3:0] == 4'd0) ? chan0_value[19:4] : 16'd0;
                16'd32:   block_index_from_pow2_chan_count = (chan0_value[4:0] == 5'd0) ? chan0_value[20:5] : 16'd0;
                16'd64:   block_index_from_pow2_chan_count = (chan0_value[5:0] == 6'd0) ? chan0_value[21:6] : 16'd0;
                16'd128:  block_index_from_pow2_chan_count = (chan0_value[6:0] == 7'd0) ? chan0_value[22:7] : 16'd0;
                16'd256:  block_index_from_pow2_chan_count = (chan0_value[7:0] == 8'd0) ? chan0_value[23:8] : 16'd0;
                16'd512:  block_index_from_pow2_chan_count = (chan0_value[8:0] == 9'd0) ? chan0_value[24:9] : 16'd0;
                16'd1024: block_index_from_pow2_chan_count = (chan0_value[9:0] == 10'd0) ? chan0_value[25:10] : 16'd0;
                16'd2048: block_index_from_pow2_chan_count = (chan0_value[10:0] == 11'd0) ? chan0_value[26:11] : 16'd0;
                16'd4096: block_index_from_pow2_chan_count = (chan0_value[11:0] == 12'd0) ? chan0_value[27:12] : 16'd0;
                default:  block_index_from_pow2_chan_count = 16'd0;
            endcase
        end
    endfunction

    function automatic [63:0] header_word(input [4:0] idx);
        begin
            case (idx)
                5'd0:  header_word = {T510_MAGIC,
                    (sync_generation != 64'd0) ? 16'd3 : 16'd2,
                    HEADER_BYTES};
                5'd1:  header_word = {board_id, STREAM_TYPE, pkt_epoch_mode, pkt_packet_flags};
                5'd2:  header_word = unix_seconds;
                5'd3:  header_word = pps_count;
                5'd4:  header_word = sample0;
                5'd5:  header_word = frame_id;
                5'd6:  header_word = {seq_no, pkt_spec_chan0};
                5'd7:  header_word = {pkt_spec_chan_count, pkt_spec_time_count, LOCAL_NINPUT, pkt_quant_mode};
                5'd8:  header_word = {pkt_scale_id, PAYLOAD_BYTES};
                5'd9:  header_word = {PRODUCT_FENGINE_IQ16, pkt_spec_nchan, block_index, block_count};
                5'd10: header_word = {pkt_spec_taps, pkt_spec_fft_shift, pkt_spec_status_flags};
                5'd11: header_word = {pkt_spec_sample_rate_hz, pkt_scale_mode, 15'd0, (pkt_spec_chan0 >= pkt_chan_split)};
                5'd12: header_word = sync_generation;
                5'd13: header_word = sync_observation_tag;
                5'd14: header_word = sync_metadata;
                5'd15: header_word = sync_status;
                default: header_word = 64'd0;
            endcase
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                <= ST_IDLE;
            header_idx           <= 5'd0;
            payload_subword      <= 2'd0;
            capture_idx          <= 16'd0;
            payload_read_idx     <= 16'd0;
            payload_reg          <= {DATA_W{1'b0}};
            payload_rd_addr      <= {ADDR_W{1'b0}};
            seq_no               <= 32'd0;
            sample0              <= 64'd0;
            frame_id             <= 64'd0;
            pkt_epoch_mode        <= 16'd0;
            pkt_packet_flags      <= 16'd0;
            pkt_quant_mode        <= 16'd0;
            pkt_scale_mode        <= 16'd0;
            pkt_scale_id          <= 32'd0;
            pkt_spec_chan0        <= 32'd0;
            pkt_spec_time_count   <= 16'd0;
            pkt_spec_chan_count   <= 16'd0;
            pkt_spec_nchan        <= 16'd0;
            pkt_spec_taps         <= 16'd0;
            pkt_spec_fft_shift    <= 16'd0;
            pkt_spec_sample_rate_hz <= 32'd0;
            pkt_spec_status_flags <= 32'd0;
            pkt_chan_split        <= 32'd0;
            packet_count         <= 32'd0;
            udp_byte_count       <= 32'd0;
        end else begin
            if (stream_reset) begin
                state                <= ST_IDLE;
                header_idx           <= 5'd0;
                payload_subword      <= 2'd0;
                capture_idx          <= 16'd0;
                payload_read_idx     <= 16'd0;
                payload_reg          <= {DATA_W{1'b0}};
                payload_rd_addr      <= {ADDR_W{1'b0}};
                seq_no               <= 32'd0;
                sample0              <= 64'd0;
                frame_id             <= 64'd0;
                pkt_epoch_mode        <= 16'd0;
                pkt_packet_flags      <= 16'd0;
                pkt_quant_mode        <= 16'd0;
                pkt_scale_mode        <= 16'd0;
                pkt_scale_id          <= 32'd0;
                pkt_spec_chan0        <= 32'd0;
                pkt_spec_time_count   <= 16'd0;
                pkt_spec_chan_count   <= 16'd0;
                pkt_spec_nchan        <= 16'd0;
                pkt_spec_taps         <= 16'd0;
                pkt_spec_fft_shift    <= 16'd0;
                pkt_spec_sample_rate_hz <= 32'd0;
                pkt_spec_status_flags <= 32'd0;
                pkt_chan_split        <= 32'd0;
            end else begin
            case (state)
                ST_IDLE: begin
                    if (enable && s_axis_tvalid) begin
                        capture_idx      <= 16'd1;
                        payload_subword  <= 2'd0;
                        payload_read_idx <= 16'd0;
                        sample0          <= s_axis_sample0;
                        pkt_epoch_mode    <= epoch_mode;
                        pkt_packet_flags  <= packet_flags;
                        pkt_quant_mode    <= quant_mode;
                        pkt_scale_mode    <= scale_mode;
                        pkt_scale_id      <= scale_id;
                        pkt_spec_chan0    <= spec_chan0;
                        pkt_spec_time_count <= spec_time_count;
                        pkt_spec_chan_count <= spec_chan_count;
                        pkt_spec_nchan    <= spec_nchan;
                        pkt_spec_taps     <= spec_taps;
                        pkt_spec_fft_shift <= spec_fft_shift;
                        pkt_spec_sample_rate_hz <= spec_sample_rate_hz;
                        pkt_spec_status_flags <= spec_status_flags;
                        pkt_chan_split    <= chan_split;
                        packet_count     <= packet_count + 32'd1;
                        if (PAYLOAD_BEATS <= 1) begin
                            state      <= ST_HEADER;
                            header_idx <= 5'd0;
                        end else begin
                            state <= ST_CAPTURE;
                        end
                    end
                end

                ST_CAPTURE: begin
                    if (enable && s_axis_tvalid) begin
                        if ((capture_idx + 16'd1) >= PAYLOAD_BEATS[15:0]) begin
                            state       <= ST_HEADER;
                            header_idx  <= 5'd0;
                            capture_idx <= 16'd0;
                        end else begin
                            capture_idx <= capture_idx + 16'd1;
                        end
                    end
                end

                ST_HEADER: begin
                    if (m_axis_tready) begin
                        if (header_idx == HEADER_WORDS - 1) begin
                            state            <= ST_PRELOAD_WAIT;
                            header_idx       <= 5'd0;
                            payload_read_idx <= 16'd0;
                            payload_subword   <= 2'd0;
                            payload_rd_addr   <= {ADDR_W{1'b0}};
                        end else begin
                            header_idx <= header_idx + 5'd1;
                        end
                        udp_byte_count <= udp_byte_count + 32'd8;
                    end
                end

                ST_PRELOAD_WAIT: begin
                    state <= ST_PRELOAD_LOAD;
                end

                ST_PRELOAD_LOAD: begin
                    payload_reg <= payload_mem_rd_data;
                    state       <= ST_PAYLOAD;
                end

                ST_PAYLOAD: begin
                    if (m_axis_tready) begin
                        udp_byte_count <= udp_byte_count + 32'd8;
                        if (payload_subword == LAST_SUBWORD) begin
                            if ((payload_read_idx + 16'd1) >= PAYLOAD_BEATS[15:0]) begin
                                state            <= ST_IDLE;
                                payload_read_idx <= 16'd0;
                                seq_no           <= seq_no + 32'd1;
                                if ((block_count == 16'd0) || (block_index + 16'd1 >= block_count)) begin
                                    frame_id     <= frame_id + 64'd1;
                                end
                            end else begin
                                payload_read_idx <= payload_read_idx + 16'd1;
                                payload_rd_addr  <= payload_read_idx + 16'd1;
                                payload_subword  <= {SUBWORD_W{1'b0}};
                                state            <= ST_PRELOAD_WAIT;
                            end
                        end else begin
                            payload_subword <= payload_subword + 1'b1;
                        end
                    end
                end
            endcase
            end
        end
    end

    always_comb begin
        s_axis_tready = 1'b0;
        m_axis_tdata  = {OUT_W{1'b0}};
        m_axis_tkeep  = {OUT_W/8{1'b1}};
        m_axis_tvalid = 1'b0;
        m_axis_tlast  = 1'b0;

        case (state)
            ST_IDLE: begin
                s_axis_tready = enable;
            end
            ST_CAPTURE: begin
                s_axis_tready = enable;
            end
            ST_HEADER: begin
                m_axis_tdata  = header_word(header_idx);
                m_axis_tvalid = 1'b1;
            end
            ST_PRELOAD_WAIT: begin
            end
            ST_PRELOAD_LOAD: begin
            end
            ST_PAYLOAD: begin
                m_axis_tdata  = payload_reg[payload_subword*OUT_W +: OUT_W];
                m_axis_tvalid = 1'b1;
                m_axis_tlast  = ((payload_read_idx + 16'd1) >= PAYLOAD_BEATS[15:0]) &&
                                (payload_subword == LAST_SUBWORD);
            end
            default: begin
            end
        endcase
    end

    assign seq_no_debug   = seq_no;
    assign frame_id_debug = frame_id;
    assign chan0_debug    = pkt_spec_chan0;

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(ADDR_W),
        .ADDR_WIDTH_B(ADDR_W),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(DATA_W),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("common_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE(PAYLOAD_BEATS * DATA_W),
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
    ) u_payload_bram (
        .dbiterrb(),
        .doutb(payload_mem_rd_data),
        .sbiterrb(),
        .addra(capture_write_addr),
        .addrb(payload_rd_addr),
        .clka(clk),
        .clkb(clk),
        .dina(s_axis_tdata),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!rst_n),
        .sleep(1'b0),
        .wea(capture_write_en)
    );

endmodule
