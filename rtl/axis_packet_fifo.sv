module axis_packet_fifo #(
    parameter integer DATA_W  = 64,
    parameter integer DEPTH   = 4096,
    parameter integer COUNT_W = 13
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 clear,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [DATA_W/8-1:0]  s_axis_tkeep,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [DATA_W/8-1:0]  m_axis_tkeep,
    output wire                 m_axis_tvalid,
    output wire                 m_axis_tlast,
    input  wire                 m_axis_tready,
    output wire [31:0]          level_words,
    output logic [31:0]         high_water_words,
    output logic [31:0]         backpressure_cycles
);

    localparam integer KEEP_W = DATA_W / 8;
    localparam integer FIFO_W = DATA_W + KEEP_W + 1;

    wire                 fifo_rst = !rst_n || clear;
    wire [FIFO_W-1:0]    fifo_din = {s_axis_tlast, s_axis_tkeep, s_axis_tdata};
    wire [FIFO_W-1:0]    fifo_dout;
    wire                 fifo_full;
    wire                 fifo_empty;
    wire                 wr_rst_busy;
    wire                 rd_rst_busy;
    wire [COUNT_W-1:0]   wr_data_count;
    wire [COUNT_W-1:0]   rd_data_count;
    wire                 fifo_m_valid;

    assign s_axis_tready = !fifo_full && !wr_rst_busy;
    assign fifo_m_valid  = !fifo_empty && !rd_rst_busy;
    assign m_axis_tvalid = fifo_m_valid;
    assign m_axis_tdata  = fifo_dout[DATA_W-1:0];
    assign m_axis_tkeep  = fifo_dout[DATA_W +: KEEP_W];
    assign m_axis_tlast  = fifo_dout[DATA_W + KEEP_W];
    assign level_words   = {{(32-COUNT_W){1'b0}}, rd_data_count};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            high_water_words     <= 32'd0;
            backpressure_cycles  <= 32'd0;
        end else if (clear || wr_rst_busy || rd_rst_busy) begin
            high_water_words     <= 32'd0;
            backpressure_cycles  <= 32'd0;
        end else begin
            if (level_words > high_water_words) begin
                high_water_words <= level_words;
            end
            if (s_axis_tvalid && !s_axis_tready) begin
                backpressure_cycles <= backpressure_cycles + 32'd1;
            end
        end
    end

    xpm_fifo_sync #(
        .FIFO_MEMORY_TYPE("block"),
        .ECC_MODE("no_ecc"),
        .FIFO_WRITE_DEPTH(DEPTH),
        .WRITE_DATA_WIDTH(FIFO_W),
        .WR_DATA_COUNT_WIDTH(COUNT_W),
        .READ_MODE("fwft"),
        .FIFO_READ_LATENCY(1),
        .READ_DATA_WIDTH(FIFO_W),
        .RD_DATA_COUNT_WIDTH(COUNT_W),
        .DOUT_RESET_VALUE("0"),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0)
    ) u_fifo (
        .sleep(1'b0),
        .rst(fifo_rst),
        .wr_clk(clk),
        .wr_en(s_axis_tvalid && s_axis_tready),
        .din(fifo_din),
        .full(fifo_full),
        .prog_full(),
        .wr_data_count(wr_data_count),
        .overflow(),
        .wr_rst_busy(wr_rst_busy),
        .almost_full(),
        .wr_ack(),
        .rd_en(fifo_m_valid && m_axis_tready),
        .dout(fifo_dout),
        .empty(fifo_empty),
        .prog_empty(),
        .rd_data_count(rd_data_count),
        .underflow(),
        .rd_rst_busy(rd_rst_busy),
        .almost_empty(),
        .data_valid(),
        .injectsbiterr(1'b0),
        .injectdbiterr(1'b0),
        .sbiterr(),
        .dbiterr()
    );

endmodule
