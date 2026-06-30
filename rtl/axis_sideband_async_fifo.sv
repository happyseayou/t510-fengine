`default_nettype none

module axis_sideband_async_fifo #(
    parameter integer DATA_W  = 1024,
    parameter integer SIDE_W  = 64,
    parameter integer DEPTH   = 2048,
    parameter integer COUNT_W = 12
) (
    input  wire                 s_clk,
    input  wire                 s_rst_n,
    input  wire                 s_clear,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [SIDE_W-1:0]    s_axis_tside,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,

    input  wire                 m_clk,
    input  wire                 m_rst_n,
    input  wire                 m_clear,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [SIDE_W-1:0]    m_axis_tside,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,

    output wire [31:0]          wr_level_words,
    output wire [31:0]          rd_level_words,
    output wire                 fifo_full,
    output wire                 fifo_empty
);

    localparam integer FIFO_W = DATA_W + SIDE_W;

    wire                 fifo_rst = !s_rst_n || !m_rst_n || s_clear || m_clear;
    wire [FIFO_W-1:0]    fifo_din = {s_axis_tside, s_axis_tdata};
    wire [FIFO_W-1:0]    fifo_dout;
    wire                 wr_rst_busy;
    wire                 rd_rst_busy;
    wire [COUNT_W-1:0]   wr_data_count;
    wire [COUNT_W-1:0]   rd_data_count;

    assign s_axis_tready = !fifo_full && !wr_rst_busy;
    assign m_axis_tvalid = !fifo_empty && !rd_rst_busy;
    assign m_axis_tdata = fifo_dout[0 +: DATA_W];
    assign m_axis_tside = fifo_dout[DATA_W +: SIDE_W];
    assign wr_level_words = {{(32-COUNT_W){1'b0}}, wr_data_count};
    assign rd_level_words = {{(32-COUNT_W){1'b0}}, rd_data_count};

    xpm_fifo_async #(
        .CASCADE_HEIGHT(0),
        .CDC_SYNC_STAGES(2),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("block"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10),
        .PROG_FULL_THRESH(DEPTH - 10),
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
        .rd_en(m_axis_tvalid && m_axis_tready),
        .rst(fifo_rst),
        .sleep(1'b0),
        .wr_clk(s_clk),
        .wr_en(s_axis_tvalid && s_axis_tready)
    );

endmodule

`default_nettype wire
