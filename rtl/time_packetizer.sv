module time_packetizer #(
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
    input  wire [15:0]          quant_mode,
    input  wire [15:0]          scale_mode,
    input  wire [31:0]          scale_id,
    input  wire [15:0]          time_payload_nsamp,
    input  wire [31:0]          packet_interval_beats,
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
    output logic [31:0]         dropped_count,
    output logic [31:0]         udp_byte_count,
    output logic [31:0]         seq_no_debug,
    output logic [63:0]         sample0_debug,
    output logic [63:0]         frame_id_debug
);

    localparam [2:0] ST_IDLE         = 3'd0;
    localparam [2:0] ST_CAPTURE      = 3'd1;
    localparam [2:0] ST_HEADER       = 3'd2;
    localparam [2:0] ST_PRELOAD_WAIT = 3'd3;
    localparam [2:0] ST_PRELOAD_LOAD = 3'd4;
    localparam [2:0] ST_PAYLOAD      = 3'd5;

    localparam [31:0] T510_MAGIC      = 32'h5435_3130;
    localparam [15:0] STREAM_TYPE     = 16'd1;
    localparam [15:0] HEADER_BYTES    = 16'd128;
    localparam [31:0] PAYLOAD_BYTES   = 32'd8192;
    localparam [15:0] LOCAL_NINPUT    = 16'd8;
    localparam integer MAX_PAYLOAD_BEATS = PAYLOAD_BYTES / (DATA_W / 8);
    localparam integer ADDR_W = $clog2(MAX_PAYLOAD_BEATS);
    localparam integer SUBWORDS_PER_BEAT = DATA_W / OUT_W;
    localparam integer SUBWORD_W = (SUBWORDS_PER_BEAT <= 1) ? 1 : $clog2(SUBWORDS_PER_BEAT);
    localparam [SUBWORD_W-1:0] LAST_SUBWORD = SUBWORDS_PER_BEAT - 1;

    logic [2:0]                state;
    logic [4:0]                header_idx;
    logic [SUBWORD_W-1:0]      payload_subword;
    logic [15:0]               payload_beats;
    logic [15:0]               capture_idx;
    logic [15:0]               payload_read_idx;
    logic [DATA_W-1:0]         payload_reg;
    logic [ADDR_W-1:0]         payload_rd_addr;
    wire  [DATA_W-1:0]         payload_mem_rd_data;
    logic [31:0]               seq_no;
    logic [63:0]               sample0;
    logic [63:0]               frame_id;
    logic [31:0]               interval_count;
    wire                       low_rate_mode = (packet_interval_beats != 32'd0);
    wire                       input_fire = enable && s_axis_tvalid && s_axis_tready;
    wire                       capture_write_en =
        (((state == ST_IDLE) && (interval_count == 32'd0)) || (state == ST_CAPTURE)) &&
        input_fire;
    wire [ADDR_W-1:0]          capture_write_addr =
        (state == ST_IDLE) ? {ADDR_W{1'b0}} : capture_idx[ADDR_W-1:0];

    function automatic [15:0] capture_limit(input [15:0] requested);
        begin
            if (requested == 16'd0 || requested > MAX_PAYLOAD_BEATS[15:0]) begin
                capture_limit = MAX_PAYLOAD_BEATS[15:0];
            end else begin
                capture_limit = requested;
            end
        end
    endfunction

    function automatic [63:0] header_word(input [4:0] idx);
        begin
            case (idx)
                5'd0:  header_word = {T510_MAGIC, 16'd2, HEADER_BYTES};
                5'd1:  header_word = {board_id, STREAM_TYPE, epoch_mode, packet_flags};
                5'd2:  header_word = unix_seconds;
                5'd3:  header_word = pps_count;
                5'd4:  header_word = sample0;
                5'd5:  header_word = frame_id;
                5'd6:  header_word = {seq_no, 16'd0, global_input0};
                5'd7:  header_word = {16'd0, payload_beats, LOCAL_NINPUT, quant_mode};
                5'd8:  header_word = {scale_id, PAYLOAD_BYTES};
                5'd9:  header_word = 64'd0;
                default: header_word = 64'd0;
            endcase
        end
    endfunction

    function automatic [31:0] interval_reload(input [31:0] interval);
        begin
            if (interval <= 32'd1) begin
                interval_reload = 32'd0;
            end else begin
                interval_reload = interval - 32'd1;
            end
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                <= ST_IDLE;
            header_idx           <= 5'd0;
            payload_subword      <= 2'd0;
            payload_beats        <= 16'd0;
            capture_idx          <= 16'd0;
            payload_read_idx     <= 16'd0;
            payload_reg          <= {DATA_W{1'b0}};
            payload_rd_addr      <= {ADDR_W{1'b0}};
            seq_no               <= 32'd0;
            sample0              <= 64'd0;
            frame_id             <= 64'd0;
            interval_count        <= 32'd0;
            packet_count         <= 32'd0;
            dropped_count        <= 32'd0;
            udp_byte_count       <= 32'd0;
        end else begin
            if (stream_reset) begin
                state                <= ST_IDLE;
                header_idx           <= 5'd0;
                payload_subword      <= 2'd0;
                payload_beats        <= 16'd0;
                capture_idx          <= 16'd0;
                payload_read_idx     <= 16'd0;
                payload_reg          <= {DATA_W{1'b0}};
                payload_rd_addr      <= {ADDR_W{1'b0}};
                seq_no               <= 32'd0;
                sample0              <= 64'd0;
                frame_id             <= 64'd0;
                interval_count        <= 32'd0;
            end else begin
            case (state)
                ST_IDLE: begin
                    if (input_fire) begin
                        if (low_rate_mode && interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                            dropped_count  <= dropped_count + 32'd1;
                        end else begin
                            payload_beats    <= capture_limit(time_payload_nsamp);
                            capture_idx      <= 16'd1;
                            payload_subword  <= 2'd0;
                            payload_read_idx <= 16'd0;
                            sample0          <= s_axis_sample0;
                            packet_count     <= packet_count + 32'd1;
                            interval_count   <= low_rate_mode ? interval_reload(packet_interval_beats) : 32'd0;
                            if (capture_limit(time_payload_nsamp) <= 16'd1) begin
                                state      <= ST_HEADER;
                                header_idx <= 5'd0;
                            end else begin
                                state <= ST_CAPTURE;
                            end
                        end
                    end
                end

                ST_CAPTURE: begin
                    if (input_fire) begin
                        if (low_rate_mode && interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                        end
                        if ((capture_idx + 16'd1) >= payload_beats) begin
                            state       <= ST_HEADER;
                            header_idx  <= 5'd0;
                            capture_idx <= 16'd0;
                        end else begin
                            capture_idx <= capture_idx + 16'd1;
                        end
                    end
                end

                ST_HEADER: begin
                    if (low_rate_mode && input_fire) begin
                        if (interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                        end
                        dropped_count <= dropped_count + 32'd1;
                    end
                    if (m_axis_tready) begin
                        if (header_idx == HEADER_WORDS - 1) begin
                            state            <= ST_PRELOAD_WAIT;
                            header_idx       <= 5'd0;
                            payload_read_idx <= 16'd0;
                            payload_subword  <= 2'd0;
                            payload_rd_addr  <= {ADDR_W{1'b0}};
                        end else begin
                            header_idx <= header_idx + 5'd1;
                        end
                        udp_byte_count <= udp_byte_count + 32'd8;
                    end
                end

                ST_PRELOAD_WAIT: begin
                    if (low_rate_mode && input_fire) begin
                        if (interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                        end
                        dropped_count <= dropped_count + 32'd1;
                    end
                    state <= ST_PRELOAD_LOAD;
                end

                ST_PRELOAD_LOAD: begin
                    if (low_rate_mode && input_fire) begin
                        if (interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                        end
                        dropped_count <= dropped_count + 32'd1;
                    end
                    payload_reg <= payload_mem_rd_data;
                    state       <= ST_PAYLOAD;
                end

                ST_PAYLOAD: begin
                    if (low_rate_mode && input_fire) begin
                        if (interval_count != 32'd0) begin
                            interval_count <= interval_count - 32'd1;
                        end
                        dropped_count <= dropped_count + 32'd1;
                    end
                    if (m_axis_tready) begin
                        udp_byte_count <= udp_byte_count + 32'd8;
                        if (payload_subword == LAST_SUBWORD) begin
                            if ((payload_read_idx + 16'd1) >= payload_beats) begin
                                state            <= ST_IDLE;
                                payload_read_idx <= 16'd0;
                                seq_no           <= seq_no + 32'd1;
                                frame_id         <= frame_id + 64'd1;
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
                s_axis_tready = enable && low_rate_mode;
                m_axis_tdata  = header_word(header_idx);
                m_axis_tvalid = 1'b1;
            end
            ST_PRELOAD_WAIT: begin
                s_axis_tready = enable && low_rate_mode;
            end
            ST_PRELOAD_LOAD: begin
                s_axis_tready = enable && low_rate_mode;
            end
            ST_PAYLOAD: begin
                s_axis_tready = enable && low_rate_mode;
                m_axis_tdata  = payload_reg[payload_subword*OUT_W +: OUT_W];
                m_axis_tvalid = 1'b1;
                m_axis_tlast  = ((payload_read_idx + 16'd1) >= payload_beats) &&
                                (payload_subword == LAST_SUBWORD);
            end
            default: begin
            end
        endcase
    end

    assign seq_no_debug   = seq_no;
    assign sample0_debug  = sample0;
    assign frame_id_debug = frame_id;

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
        .MEMORY_SIZE(MAX_PAYLOAD_BEATS * DATA_W),
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
