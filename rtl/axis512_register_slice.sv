`default_nettype none

module axis512_register_slice #(
    parameter integer DATA_W  = 512,
    parameter integer KEEP_W  = DATA_W / 8,
    parameter integer DEPTH   = 2,
    parameter integer COUNT_W = 5
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  clear,

    input  wire [DATA_W-1:0]     s_axis_tdata,
    input  wire [KEEP_W-1:0]     s_axis_tkeep,
    input  wire                  s_axis_tvalid,
    input  wire                  s_axis_tlast,
    output wire                  s_axis_tready,

    output wire [DATA_W-1:0]     m_axis_tdata,
    output wire [KEEP_W-1:0]     m_axis_tkeep,
    output wire                  m_axis_tvalid,
    output wire                  m_axis_tlast,
    input  wire                  m_axis_tready
);

    localparam integer FIFO_W = DATA_W + KEEP_W + 1;

    wire [FIFO_W-1:0] fifo_din = {s_axis_tlast, s_axis_tkeep, s_axis_tdata};

    generate
        if (DEPTH <= 1) begin : g_single
            logic [FIFO_W-1:0] out_reg = {FIFO_W{1'b0}};
            logic              out_valid = 1'b0;
            wire               out_ready = m_axis_tready || !out_valid;

            assign s_axis_tready = out_ready;
            assign m_axis_tvalid = out_valid;
            assign m_axis_tdata = out_reg[DATA_W-1:0];
            assign m_axis_tkeep = out_reg[DATA_W +: KEEP_W];
            assign m_axis_tlast = out_reg[DATA_W + KEEP_W];

            always_ff @(posedge clk) begin
                if (!rst_n || clear) begin
                    out_reg <= {FIFO_W{1'b0}};
                    out_valid <= 1'b0;
                end else if (out_ready) begin
                    if (s_axis_tvalid) begin
                        out_reg <= fifo_din;
                        out_valid <= 1'b1;
                    end else begin
                        out_valid <= 1'b0;
                    end
                end
            end
        end else begin : g_fifo
            localparam integer PTR_W = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
            localparam [PTR_W-1:0] LAST_PTR = DEPTH - 1;
            localparam [COUNT_W-1:0] DEPTH_COUNT = DEPTH;
            localparam integer DATA_CHUNKS = 8;
            localparam integer DATA_CHUNK_W = DATA_W / DATA_CHUNKS;
            localparam integer KEEP_CHUNK_W = KEEP_W / DATA_CHUNKS;

            logic [DATA_W-1:0] slot_data [0:DEPTH-1];
            logic [KEEP_W-1:0] slot_keep [0:DEPTH-1];
            logic              slot_last [0:DEPTH-1];
            logic [PTR_W-1:0]  wr_ptr = {PTR_W{1'b0}};
            logic [PTR_W-1:0]  rd_ptr = {PTR_W{1'b0}};
            logic [COUNT_W-1:0] count = {COUNT_W{1'b0}};

            wire fifo_not_full = (count < DEPTH_COUNT);
            wire fifo_not_empty = (count != {COUNT_W{1'b0}});
            wire wr_fire = s_axis_tvalid && fifo_not_full;
            wire rd_fire = fifo_not_empty && m_axis_tready;
            (* keep = "true", max_fanout = 96 *)
            wire [DATA_CHUNKS-1:0] wr_fire_chunk = {DATA_CHUNKS{wr_fire}};

            assign s_axis_tready = fifo_not_full;
            assign m_axis_tvalid = fifo_not_empty;
            assign m_axis_tdata = slot_data[rd_ptr];
            assign m_axis_tkeep = slot_keep[rd_ptr];
            assign m_axis_tlast = slot_last[rd_ptr];

            function automatic [PTR_W-1:0] ptr_next(input [PTR_W-1:0] ptr);
                begin
                    if (ptr == LAST_PTR) begin
                        ptr_next = {PTR_W{1'b0}};
                    end else begin
                        ptr_next = ptr + 1'b1;
                    end
                end
            endfunction

            integer i;
            integer chunk;
            always_ff @(posedge clk) begin
                if (!rst_n || clear) begin
                    wr_ptr <= {PTR_W{1'b0}};
                    rd_ptr <= {PTR_W{1'b0}};
                    count <= {COUNT_W{1'b0}};
                    for (i = 0; i < DEPTH; i = i + 1) begin
                        slot_data[i] <= {DATA_W{1'b0}};
                        slot_keep[i] <= {KEEP_W{1'b0}};
                        slot_last[i] <= 1'b0;
                    end
                end else begin
                    if (wr_fire) begin
                        wr_ptr <= ptr_next(wr_ptr);
                        slot_last[wr_ptr] <= s_axis_tlast;
                    end
                    for (chunk = 0; chunk < DATA_CHUNKS; chunk = chunk + 1) begin
                        if (wr_fire_chunk[chunk]) begin
                            slot_data[wr_ptr][chunk*DATA_CHUNK_W +: DATA_CHUNK_W] <=
                                s_axis_tdata[chunk*DATA_CHUNK_W +: DATA_CHUNK_W];
                            slot_keep[wr_ptr][chunk*KEEP_CHUNK_W +: KEEP_CHUNK_W] <=
                                s_axis_tkeep[chunk*KEEP_CHUNK_W +: KEEP_CHUNK_W];
                        end
                    end
                    if (rd_fire) begin
                        rd_ptr <= ptr_next(rd_ptr);
                    end
                    unique case ({wr_fire, rd_fire})
                        2'b10: count <= count + 1'b1;
                        2'b01: count <= count - 1'b1;
                        default: count <= count;
                    endcase
                end
            end
        end
    endgenerate

endmodule

`default_nettype wire
