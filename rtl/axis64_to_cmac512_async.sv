`default_nettype none

module axis64_to_cmac512_async #(
    parameter integer FIFO_DEPTH = 1024,
    parameter integer COUNT_W    = 11,
    parameter integer TOKEN_DEPTH = 16,
    parameter integer TOKEN_COUNT_W = 5
) (
    input  wire         s_clk,
    input  wire         s_rst_n,
    input  wire         s_clear,
    input  wire [63:0]  s_axis_tdata,
    input  wire [7:0]   s_axis_tkeep,
    input  wire         s_axis_tvalid,
    input  wire         s_axis_tlast,
    output wire         s_axis_tready,
    input  wire         m_clk,
    input  wire         m_rst_n,
    output wire [511:0] m_axis_tdata,
    output wire [63:0]  m_axis_tkeep,
    output wire         m_axis_tvalid,
    output wire         m_axis_tlast,
    input  wire         m_axis_tready,
    output wire [31:0]  fifo_level_words,
    output logic [31:0] input_frame_count,
    output logic [31:0] output_frame_count,
    output logic [31:0] backpressure_cycles,
    output wire         fifo_full,
    output wire         fifo_empty
);

    localparam integer FIFO_W = 512 + 64 + 1;

    logic [511:0] pack_data;
    logic [63:0]  pack_keep;
    logic [511:0] pack_data_next;
    logic [63:0]  pack_keep_next;
    logic [2:0]   pack_lane;

    wire          final_lane = (pack_lane == 3'd7) || s_axis_tlast;
    wire          fifo_rst = !s_rst_n || !m_rst_n || s_clear;
    wire          wr_rst_busy;
    wire          rd_rst_busy;
    wire [COUNT_W-1:0] wr_data_count;
    wire [COUNT_W-1:0] rd_data_count;
    wire          token_wr_rst_busy;
    wire          token_rd_rst_busy;
    wire [TOKEN_COUNT_W-1:0] token_wr_data_count;
    wire [TOKEN_COUNT_W-1:0] token_rd_data_count;
    wire          token_fifo_empty;
    wire          token_fifo_full;
    wire          token_fifo_dout;
    wire [FIFO_W-1:0] fifo_din;
    wire [FIFO_W-1:0] fifo_dout;
    wire          s_fire = s_axis_tvalid && s_axis_tready;
    wire          wr_en = s_fire && final_lane;
    wire          frame_token_wr_en = s_fire && s_axis_tlast;
    logic         frame_active;
    wire          frame_start = !frame_active &&
                                !rd_rst_busy &&
                                !token_rd_rst_busy &&
                                !fifo_empty &&
                                !token_fifo_empty;
    wire          m_valid = (frame_active || frame_start) && !fifo_empty && !rd_rst_busy;
    wire          rd_en = m_valid && m_axis_tready;

    assign s_axis_tready = !wr_rst_busy &&
                           !token_wr_rst_busy &&
                           (!final_lane || !fifo_full) &&
                           (!s_axis_tlast || !token_fifo_full);
    assign fifo_din = {
        s_axis_tlast,
        pack_keep_next,
        pack_data_next
    };
    assign m_axis_tdata = fifo_dout[511:0];
    assign m_axis_tkeep = fifo_dout[512 +: 64];
    assign m_axis_tlast = fifo_dout[576];
    assign m_axis_tvalid = m_valid;
    assign fifo_level_words = {{(32-COUNT_W){1'b0}}, rd_data_count};

    always_ff @(posedge m_clk or negedge m_rst_n) begin
        if (!m_rst_n) begin
            frame_active <= 1'b0;
        end else if (m_valid && m_axis_tready && m_axis_tlast) begin
            frame_active <= 1'b0;
        end else if (frame_start) begin
            frame_active <= 1'b1;
        end
    end

    always_comb begin
        pack_data_next = pack_data;
        pack_keep_next = pack_keep;
        case (pack_lane)
            3'd0: begin
                pack_data_next[63:0] = s_axis_tdata;
                pack_keep_next[7:0] = s_axis_tkeep;
            end
            3'd1: begin
                pack_data_next[127:64] = s_axis_tdata;
                pack_keep_next[15:8] = s_axis_tkeep;
            end
            3'd2: begin
                pack_data_next[191:128] = s_axis_tdata;
                pack_keep_next[23:16] = s_axis_tkeep;
            end
            3'd3: begin
                pack_data_next[255:192] = s_axis_tdata;
                pack_keep_next[31:24] = s_axis_tkeep;
            end
            3'd4: begin
                pack_data_next[319:256] = s_axis_tdata;
                pack_keep_next[39:32] = s_axis_tkeep;
            end
            3'd5: begin
                pack_data_next[383:320] = s_axis_tdata;
                pack_keep_next[47:40] = s_axis_tkeep;
            end
            3'd6: begin
                pack_data_next[447:384] = s_axis_tdata;
                pack_keep_next[55:48] = s_axis_tkeep;
            end
            default: begin
                pack_data_next[511:448] = s_axis_tdata;
                pack_keep_next[63:56] = s_axis_tkeep;
            end
        endcase
    end

    always_ff @(posedge s_clk or negedge s_rst_n) begin
        if (!s_rst_n) begin
            pack_data <= 512'd0;
            pack_keep <= 64'd0;
            pack_lane <= 3'd0;
            input_frame_count <= 32'd0;
            backpressure_cycles <= 32'd0;
        end else if (s_clear) begin
            pack_data <= 512'd0;
            pack_keep <= 64'd0;
            pack_lane <= 3'd0;
            input_frame_count <= 32'd0;
            backpressure_cycles <= 32'd0;
        end else begin
            if (s_axis_tvalid && !s_axis_tready) begin
                backpressure_cycles <= backpressure_cycles + 32'd1;
            end
            if (s_fire) begin
                if (final_lane) begin
                    pack_data <= 512'd0;
                    pack_keep <= 64'd0;
                    pack_lane <= 3'd0;
                    if (s_axis_tlast) begin
                        input_frame_count <= input_frame_count + 32'd1;
                    end
                end else begin
                    pack_data <= pack_data_next;
                    pack_keep <= pack_keep_next;
                    pack_lane <= pack_lane + 3'd1;
                end
            end
        end
    end

    always_ff @(posedge m_clk or negedge m_rst_n) begin
        if (!m_rst_n) begin
            output_frame_count <= 32'd0;
        end else if (m_axis_tvalid && m_axis_tready && m_axis_tlast) begin
            output_frame_count <= output_frame_count + 32'd1;
        end
    end

    xpm_fifo_async #(
        .CASCADE_HEIGHT(0),
        .CDC_SYNC_STAGES(2),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("distributed"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(TOKEN_DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(5),
        .PROG_FULL_THRESH(TOKEN_DEPTH - 5),
        .RD_DATA_COUNT_WIDTH(TOKEN_COUNT_W),
        .READ_DATA_WIDTH(1),
        .READ_MODE("fwft"),
        .RELATED_CLOCKS(0),
        .SIM_ASSERT_CHK(0),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0),
        .WRITE_DATA_WIDTH(1),
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
        .din(1'b1),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .rd_clk(m_clk),
        .rd_en(frame_start),
        .rst(fifo_rst),
        .sleep(1'b0),
        .wr_clk(s_clk),
        .wr_en(frame_token_wr_en)
    );

    xpm_fifo_async #(
        .CASCADE_HEIGHT(0),
        .CDC_SYNC_STAGES(2),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("block"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(FIFO_DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10),
        .PROG_FULL_THRESH(FIFO_DEPTH - 10),
        .RD_DATA_COUNT_WIDTH(COUNT_W),
        .READ_DATA_WIDTH(FIFO_W),
        .READ_MODE("fwft"),
        .RELATED_CLOCKS(0),
        .SIM_ASSERT_CHK(0),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0),
        .WRITE_DATA_WIDTH(FIFO_W),
        .WR_DATA_COUNT_WIDTH(COUNT_W)
    ) u_fifo (
        .almost_empty(),
        .almost_full(),
        .data_valid(),
        .dbiterr(),
        .dout(fifo_dout),
        .empty(fifo_empty),
        .full(fifo_full),
        .overflow(),
        .prog_empty(),
        .prog_full(),
        .rd_data_count(rd_data_count),
        .rd_rst_busy(rd_rst_busy),
        .sbiterr(),
        .underflow(),
        .wr_ack(),
        .wr_data_count(wr_data_count),
        .wr_rst_busy(wr_rst_busy),
        .din(fifo_din),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .rd_clk(m_clk),
        .rd_en(rd_en),
        .rst(fifo_rst),
        .sleep(1'b0),
        .wr_clk(s_clk),
        .wr_en(wr_en)
    );

endmodule

`default_nettype wire
