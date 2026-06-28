`default_nettype none

module time_axis512_ddr_ring #(
    parameter integer AXI_ADDR_W    = 40,
    parameter integer AXI_DATA_W    = 128,
    parameter integer AXI_ID_W      = 6,
    parameter integer AXIS_DATA_W   = 512,
    parameter integer AXIS_KEEP_W   = AXIS_DATA_W / 8,
    parameter integer FRAME_BEATS    = 131,
    parameter integer DEFAULT_SLOTS  = 64
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         clear,
    input  wire                         enable,
    input  wire [AXI_ADDR_W-1:0]        base_addr,
    input  wire [15:0]                  ring_slots_cfg,

    input  wire [AXIS_DATA_W-1:0]       s_axis_tdata,
    input  wire [AXIS_KEEP_W-1:0]       s_axis_tkeep,
    input  wire                         s_axis_tvalid,
    input  wire                         s_axis_tlast,
    output wire                         s_axis_tready,

    output wire [AXIS_DATA_W-1:0]       m_axis_tdata,
    output wire [AXIS_KEEP_W-1:0]       m_axis_tkeep,
    output wire                         m_axis_tvalid,
    output wire                         m_axis_tlast,
    input  wire                         m_axis_tready,

    output logic [AXI_ID_W-1:0]         m_axi_awid,
    output logic [AXI_ADDR_W-1:0]       m_axi_awaddr,
    output logic [7:0]                  m_axi_awlen,
    output logic [2:0]                  m_axi_awsize,
    output logic [1:0]                  m_axi_awburst,
    output logic                        m_axi_awlock,
    output logic [3:0]                  m_axi_awcache,
    output logic [2:0]                  m_axi_awprot,
    output logic [3:0]                  m_axi_awqos,
    output logic                        m_axi_awvalid,
    input  wire                         m_axi_awready,
    output logic [AXI_DATA_W-1:0]       m_axi_wdata,
    output logic [AXI_DATA_W/8-1:0]     m_axi_wstrb,
    output logic                        m_axi_wlast,
    output logic                        m_axi_wvalid,
    input  wire                         m_axi_wready,
    input  wire [AXI_ID_W-1:0]          m_axi_bid,
    input  wire [1:0]                   m_axi_bresp,
    input  wire                         m_axi_bvalid,
    output logic                        m_axi_bready,
    output logic [AXI_ID_W-1:0]         m_axi_arid,
    output logic [AXI_ADDR_W-1:0]       m_axi_araddr,
    output logic [7:0]                  m_axi_arlen,
    output logic [2:0]                  m_axi_arsize,
    output logic [1:0]                  m_axi_arburst,
    output logic                        m_axi_arlock,
    output logic [3:0]                  m_axi_arcache,
    output logic [2:0]                  m_axi_arprot,
    output logic [3:0]                  m_axi_arqos,
    output logic                        m_axi_arvalid,
    input  wire                         m_axi_arready,
    input  wire [AXI_ID_W-1:0]          m_axi_rid,
    input  wire [AXI_DATA_W-1:0]        m_axi_rdata,
    input  wire [1:0]                   m_axi_rresp,
    input  wire                         m_axi_rlast,
    input  wire                         m_axi_rvalid,
    output logic                        m_axi_rready,

    output wire [31:0]                  occupancy_frames,
    output logic [31:0]                 write_frame_count,
    output logic [31:0]                 read_frame_count,
    output logic [31:0]                 drop_frame_count,
    output logic [31:0]                 error_count,
    output wire [31:0]                  status
);

    localparam integer AXI_BYTES        = AXI_DATA_W / 8;
    localparam integer AXIS_BYTES       = AXIS_DATA_W / 8;
    localparam integer AXIS_SEGMENTS    = AXIS_DATA_W / AXI_DATA_W;
    localparam integer FRAME_DATA_BYTES  = FRAME_BEATS * AXIS_BYTES;
    localparam integer META_BYTES        = AXI_BYTES;
    localparam integer FRAME_STRIDE      = META_BYTES + FRAME_DATA_BYTES;
    localparam [15:0]  DEFAULT_SLOTS16   = DEFAULT_SLOTS;
    localparam [AXI_ADDR_W-1:0] AXI_BYTES_ADDR = AXI_BYTES;
    localparam [AXI_ADDR_W-1:0] AXIS_BYTES_ADDR = AXIS_BYTES;
    localparam [AXI_ADDR_W-1:0] META_BYTES_ADDR = META_BYTES;
    localparam [AXI_ADDR_W-1:0] FRAME_STRIDE_ADDR = FRAME_STRIDE;
    localparam [2:0]   AXI_SIZE_16B      = 3'd4;

    localparam [2:0] W_IDLE      = 3'd0;
    localparam [2:0] W_DATA      = 3'd1;
    localparam [2:0] W_RESP      = 3'd2;
    localparam [2:0] W_META      = 3'd3;
    localparam [2:0] W_META_RESP = 3'd4;
    localparam [2:0] W_DROP      = 3'd5;

    localparam [2:0] R_IDLE      = 3'd0;
    localparam [2:0] R_META      = 3'd1;
    localparam [2:0] R_META_WAIT = 3'd2;
    localparam [2:0] R_DATA      = 3'd3;
    localparam [2:0] R_DATA_WAIT = 3'd4;
    localparam [2:0] R_PREP      = 3'd5;
    localparam [2:0] R_HOLD      = 3'd6;

    logic [2:0] w_state;
    logic [2:0] r_state;

    logic [AXIS_DATA_W-1:0] ingress_tdata;
    logic [AXIS_KEEP_W-1:0] ingress_tkeep;
    logic                   ingress_tvalid;
    logic                   ingress_tlast;
    logic                   ingress_tready;
    logic                   ingress_s_ready;

    logic [AXI_ADDR_W-1:0]  wr_frame_addr;
    logic [15:0]            wr_slot;
    logic [15:0]            wr_beat_idx;
    logic [15:0]            wr_frame_beats;
    logic [AXIS_DATA_W-1:0]  wr_data_reg;
    logic [AXIS_KEEP_W-1:0]  wr_keep_reg;
    logic                   wr_last_reg;
    logic [2:0]             wr_seg;
    logic                   wr_aw_seen;
    logic                   wr_w_seen;
    logic                   wr_drop_active;

    logic [AXI_ADDR_W-1:0]  rd_frame_addr;
    logic [15:0]            rd_slot;
    logic [15:0]            rd_beat_idx;
    logic [15:0]            rd_frame_beats;
    logic [AXIS_KEEP_W-1:0]  rd_last_keep;
    logic [AXIS_DATA_W-1:0]  rd_data_reg;
    logic [2:0]             rd_seg;
    logic                   rd_last_seen;
    logic [127:0]           rd_meta_word;

    logic [AXIS_DATA_W-1:0]  out_data_reg;
    logic [AXIS_KEEP_W-1:0]  out_keep_reg;
    logic                   out_last_reg;
    logic                   out_valid;

    wire                    pass_through = !enable;
    wire                    out_ready = !out_valid || m_axis_tready;
    wire                    s_fire = ingress_tvalid && ingress_tready;
    wire                    m_fire = out_valid && m_axis_tready;
    wire                    axi_aw_fire = m_axi_awvalid && m_axi_awready;
    wire                    axi_w_fire = m_axi_wvalid && m_axi_wready;
    wire                    axi_b_fire = m_axi_bvalid && m_axi_bready;
    wire                    axi_ar_fire = m_axi_arvalid && m_axi_arready;
    wire                    axi_r_fire = m_axi_rvalid && m_axi_rready;
    wire                    wr_data_last_seg_fire = axi_w_fire && (wr_seg == (AXIS_SEGMENTS - 1));
    wire                    wr_data_aw_done_next = wr_aw_seen || axi_aw_fire;
    wire                    wr_data_w_done_next = wr_w_seen || wr_data_last_seg_fire;
    wire                    wr_meta_aw_done_next = wr_aw_seen || axi_aw_fire;
    wire                    wr_meta_w_done_next = wr_w_seen || axi_w_fire;
    wire [15:0]             active_slots = (ring_slots_cfg == 16'd0) ? DEFAULT_SLOTS16 : ring_slots_cfg;
    wire                    ring_full = (occupancy_frames >= {16'd0, active_slots});
    wire                    ring_empty = (occupancy_frames == 32'd0);

    function automatic [AXI_ADDR_W-1:0] frame_addr_for_slot(input [15:0] slot);
        begin
            frame_addr_for_slot = base_addr + (slot * FRAME_STRIDE_ADDR);
        end
    endfunction

    function automatic [AXI_ADDR_W-1:0] data_addr_for_beat(
        input [AXI_ADDR_W-1:0] frame_addr,
        input [15:0] beat_idx
    );
        begin
            data_addr_for_beat = frame_addr + META_BYTES_ADDR + (beat_idx * AXIS_BYTES_ADDR);
        end
    endfunction

    function automatic [AXI_ADDR_W-1:0] meta_addr_for_frame(
        input [AXI_ADDR_W-1:0] frame_addr
    );
        begin
            meta_addr_for_frame = frame_addr;
        end
    endfunction

    function automatic [AXI_DATA_W-1:0] burst_word(
        input [AXIS_DATA_W-1:0] data,
        input [2:0] seg
    );
        begin
            burst_word = data[seg*AXI_DATA_W +: AXI_DATA_W];
        end
    endfunction

    function automatic [127:0] meta_word(
        input [15:0] frame_beats,
        input [AXIS_KEEP_W-1:0] last_keep,
        input logic last_seen
    );
        begin
            meta_word = 128'd0;
            meta_word[63:0]   = last_keep;
            meta_word[79:64]  = frame_beats;
            meta_word[80]     = last_seen;
        end
    endfunction

    function automatic [15:0] meta_frame_beats(input [127:0] meta);
        begin
            if ((meta[79:64] == 16'd0) || (meta[79:64] > FRAME_BEATS[15:0])) begin
                meta_frame_beats = FRAME_BEATS[15:0];
            end else begin
                meta_frame_beats = meta[79:64];
            end
        end
    endfunction

    assign occupancy_frames = write_frame_count - read_frame_count;

    assign s_axis_tready = pass_through ? m_axis_tready : ingress_s_ready;
    assign m_axis_tdata   = pass_through ? s_axis_tdata  : out_data_reg;
    assign m_axis_tkeep   = pass_through ? s_axis_tkeep  : out_keep_reg;
    assign m_axis_tvalid  = pass_through ? s_axis_tvalid : out_valid;
    assign m_axis_tlast   = pass_through ? s_axis_tlast  : out_last_reg;

    axis512_register_slice #(
        .DATA_W(512),
        .KEEP_W(64)
    ) u_ingress_slice (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear || !enable),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(ingress_s_ready),
        .m_axis_tdata(ingress_tdata),
        .m_axis_tkeep(ingress_tkeep),
        .m_axis_tvalid(ingress_tvalid),
        .m_axis_tlast(ingress_tlast),
        .m_axis_tready(ingress_tready)
    );

    assign ingress_tready = enable && ((w_state == W_IDLE) || (w_state == W_DROP));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w_state <= W_IDLE;
            r_state <= R_IDLE;
            wr_frame_addr <= {AXI_ADDR_W{1'b0}};
            wr_slot <= 16'd0;
            wr_beat_idx <= 16'd0;
            wr_frame_beats <= 16'd0;
            wr_data_reg <= {AXIS_DATA_W{1'b0}};
            wr_keep_reg <= {AXIS_KEEP_W{1'b0}};
            wr_last_reg <= 1'b0;
            wr_seg <= 3'd0;
            wr_aw_seen <= 1'b0;
            wr_w_seen <= 1'b0;
            wr_drop_active <= 1'b0;
            rd_frame_addr <= {AXI_ADDR_W{1'b0}};
            rd_slot <= 16'd0;
            rd_beat_idx <= 16'd0;
            rd_frame_beats <= 16'd0;
            rd_last_keep <= {AXIS_KEEP_W{1'b0}};
            rd_data_reg <= {AXIS_DATA_W{1'b0}};
            rd_seg <= 3'd0;
            rd_last_seen <= 1'b0;
            rd_meta_word <= 128'd0;
            out_data_reg <= {AXIS_DATA_W{1'b0}};
            out_keep_reg <= {AXIS_KEEP_W{1'b0}};
            out_last_reg <= 1'b0;
            out_valid <= 1'b0;
            write_frame_count <= 32'd0;
            read_frame_count <= 32'd0;
            drop_frame_count <= 32'd0;
            error_count <= 32'd0;
            m_axi_awid <= {AXI_ID_W{1'b0}};
            m_axi_awaddr <= {AXI_ADDR_W{1'b0}};
            m_axi_awlen <= 8'd0;
            m_axi_awsize <= 3'd0;
            m_axi_awburst <= 2'd0;
            m_axi_awlock <= 1'b0;
            m_axi_awcache <= 4'd0;
            m_axi_awprot <= 3'd0;
            m_axi_awqos <= 4'd0;
            m_axi_awvalid <= 1'b0;
            m_axi_wdata <= {AXI_DATA_W{1'b0}};
            m_axi_wstrb <= {AXI_DATA_W/8{1'b0}};
            m_axi_wlast <= 1'b0;
            m_axi_wvalid <= 1'b0;
            m_axi_bready <= 1'b0;
            m_axi_arid <= {AXI_ID_W{1'b0}};
            m_axi_araddr <= {AXI_ADDR_W{1'b0}};
            m_axi_arlen <= 8'd0;
            m_axi_arsize <= 3'd0;
            m_axi_arburst <= 2'd0;
            m_axi_arlock <= 1'b0;
            m_axi_arcache <= 4'd0;
            m_axi_arprot <= 3'd0;
            m_axi_arqos <= 4'd0;
            m_axi_arvalid <= 1'b0;
            m_axi_rready <= 1'b0;
        end else if (clear) begin
            w_state <= W_IDLE;
            r_state <= R_IDLE;
            wr_frame_addr <= base_addr;
            wr_slot <= 16'd0;
            wr_beat_idx <= 16'd0;
            wr_frame_beats <= 16'd0;
            wr_data_reg <= {AXIS_DATA_W{1'b0}};
            wr_keep_reg <= {AXIS_KEEP_W{1'b0}};
            wr_last_reg <= 1'b0;
            wr_seg <= 3'd0;
            wr_aw_seen <= 1'b0;
            wr_w_seen <= 1'b0;
            wr_drop_active <= 1'b0;
            rd_frame_addr <= base_addr;
            rd_slot <= 16'd0;
            rd_beat_idx <= 16'd0;
            rd_frame_beats <= 16'd0;
            rd_last_keep <= {AXIS_KEEP_W{1'b0}};
            rd_data_reg <= {AXIS_DATA_W{1'b0}};
            rd_seg <= 3'd0;
            rd_last_seen <= 1'b0;
            rd_meta_word <= 128'd0;
            out_data_reg <= {AXIS_DATA_W{1'b0}};
            out_keep_reg <= {AXIS_KEEP_W{1'b0}};
            out_last_reg <= 1'b0;
            out_valid <= 1'b0;
            write_frame_count <= 32'd0;
            read_frame_count <= 32'd0;
            drop_frame_count <= 32'd0;
            error_count <= 32'd0;
            m_axi_awid <= {AXI_ID_W{1'b0}};
            m_axi_awaddr <= base_addr;
            m_axi_awlen <= 8'd0;
            m_axi_awsize <= 3'd0;
            m_axi_awburst <= 2'd0;
            m_axi_awlock <= 1'b0;
            m_axi_awcache <= 4'd0;
            m_axi_awprot <= 3'd0;
            m_axi_awqos <= 4'd0;
            m_axi_awvalid <= 1'b0;
            m_axi_wdata <= {AXI_DATA_W{1'b0}};
            m_axi_wstrb <= {AXI_DATA_W/8{1'b0}};
            m_axi_wlast <= 1'b0;
            m_axi_wvalid <= 1'b0;
            m_axi_bready <= 1'b0;
            m_axi_arid <= {AXI_ID_W{1'b0}};
            m_axi_araddr <= base_addr;
            m_axi_arlen <= 8'd0;
            m_axi_arsize <= 3'd0;
            m_axi_arburst <= 2'd0;
            m_axi_arlock <= 1'b0;
            m_axi_arcache <= 4'd0;
            m_axi_arprot <= 3'd0;
            m_axi_arqos <= 4'd0;
            m_axi_arvalid <= 1'b0;
            m_axi_rready <= 1'b0;
        end else begin
            if (!enable) begin
                w_state <= W_IDLE;
                r_state <= R_IDLE;
                wr_drop_active <= 1'b0;
                out_valid <= 1'b0;
                m_axi_awvalid <= 1'b0;
                m_axi_wvalid <= 1'b0;
                m_axi_bready <= 1'b0;
                m_axi_arvalid <= 1'b0;
                m_axi_rready <= 1'b0;
                wr_aw_seen <= 1'b0;
                wr_w_seen <= 1'b0;
            end

            if (m_fire) begin
                out_valid <= 1'b0;
            end

            if (enable) begin
                // Writer path.
                if (s_fire && w_state == W_IDLE) begin
                    if ((wr_frame_beats == 16'd0) && ring_full) begin
                        wr_drop_active <= 1'b1;
                        if (ingress_tlast) begin
                            drop_frame_count <= drop_frame_count + 32'd1;
                            wr_drop_active <= 1'b0;
                            w_state <= W_IDLE;
                        end else begin
                            w_state <= W_DROP;
                        end
                    end else begin
                        if (wr_frame_beats == 16'd0) begin
                            wr_frame_addr <= frame_addr_for_slot(wr_slot);
                        end
                        wr_frame_beats <= wr_frame_beats + 16'd1;
                        wr_data_reg <= ingress_tdata;
                        wr_keep_reg <= ingress_tkeep;
                        wr_last_reg <= ingress_tlast;
                        wr_seg <= 3'd0;
                        wr_aw_seen <= 1'b0;
                        wr_w_seen <= 1'b0;
                        m_axi_awid <= {AXI_ID_W{1'b0}};
                        m_axi_awaddr <= data_addr_for_beat(
                            (wr_frame_beats == 16'd0) ? frame_addr_for_slot(wr_slot) : wr_frame_addr,
                            wr_beat_idx
                        );
                        m_axi_awlen <= 8'd3;
                        m_axi_awsize <= AXI_SIZE_16B;
                        m_axi_awburst <= 2'b01;
                        m_axi_awlock <= 1'b0;
                        m_axi_awcache <= 4'b0011;
                        m_axi_awprot <= 3'b000;
                        m_axi_awqos <= 4'd0;
                        m_axi_awvalid <= 1'b1;
                        m_axi_wdata <= burst_word(ingress_tdata, 3'd0);
                        m_axi_wstrb <= {AXI_DATA_W/8{1'b1}};
                        m_axi_wlast <= (AXIS_SEGMENTS == 1);
                        m_axi_wvalid <= 1'b1;
                        m_axi_bready <= 1'b0;
                        w_state <= W_DATA;
                    end
                end

                if (w_state == W_DATA) begin
                    if (axi_aw_fire) begin
                        m_axi_awvalid <= 1'b0;
                        wr_aw_seen <= 1'b1;
                    end
                    if (axi_w_fire) begin
                        if (wr_seg == (AXIS_SEGMENTS - 1)) begin
                            m_axi_wvalid <= 1'b0;
                            wr_w_seen <= 1'b1;
                        end else begin
                            wr_seg <= wr_seg + 3'd1;
                            m_axi_wdata <= burst_word(wr_data_reg, wr_seg + 3'd1);
                            m_axi_wlast <= ((wr_seg + 1) == (AXIS_SEGMENTS - 1));
                        end
                    end
                    if (wr_data_aw_done_next && wr_data_w_done_next) begin
                        m_axi_bready <= 1'b1;
                        w_state <= W_RESP;
                    end
                end else if (w_state == W_RESP) begin
                    if (axi_b_fire) begin
                        m_axi_bready <= 1'b0;
                        if (m_axi_bresp != 2'b00) begin
                            error_count <= error_count + 32'd1;
                            drop_frame_count <= drop_frame_count + 32'd1;
                            wr_beat_idx <= 16'd0;
                            wr_frame_beats <= 16'd0;
                            wr_drop_active <= 1'b0;
                            w_state <= W_IDLE;
                        end else if (wr_last_reg) begin
                            wr_aw_seen <= 1'b0;
                            wr_w_seen <= 1'b0;
                            m_axi_awid <= {AXI_ID_W{1'b0}};
                            m_axi_awaddr <= meta_addr_for_frame(wr_frame_addr);
                            m_axi_awlen <= 8'd0;
                            m_axi_awsize <= AXI_SIZE_16B;
                            m_axi_awburst <= 2'b01;
                            m_axi_awlock <= 1'b0;
                            m_axi_awcache <= 4'b0011;
                            m_axi_awprot <= 3'b000;
                            m_axi_awqos <= 4'd0;
                            m_axi_awvalid <= 1'b1;
                            m_axi_wdata <= meta_word(wr_frame_beats, wr_keep_reg, wr_last_reg);
                            m_axi_wstrb <= {AXI_DATA_W/8{1'b1}};
                            m_axi_wlast <= 1'b1;
                            m_axi_wvalid <= 1'b1;
                            w_state <= W_META;
                        end else begin
                            wr_beat_idx <= wr_beat_idx + 16'd1;
                            wr_aw_seen <= 1'b0;
                            wr_w_seen <= 1'b0;
                            w_state <= W_IDLE;
                        end
                    end
                end else if (w_state == W_META) begin
                    if (axi_aw_fire) begin
                        m_axi_awvalid <= 1'b0;
                        wr_aw_seen <= 1'b1;
                    end
                    if (axi_w_fire) begin
                        m_axi_wvalid <= 1'b0;
                        wr_w_seen <= 1'b1;
                    end
                    if (wr_meta_aw_done_next && wr_meta_w_done_next) begin
                        m_axi_bready <= 1'b1;
                        w_state <= W_META_RESP;
                    end
                end else if (w_state == W_META_RESP) begin
                    if (axi_b_fire) begin
                        m_axi_bready <= 1'b0;
                        if (m_axi_bresp != 2'b00) begin
                            error_count <= error_count + 32'd1;
                            drop_frame_count <= drop_frame_count + 32'd1;
                        end else begin
                            write_frame_count <= write_frame_count + 32'd1;
                            if ((wr_slot + 16'd1) >= active_slots) begin
                                wr_slot <= 16'd0;
                                wr_frame_addr <= base_addr;
                            end else begin
                                wr_slot <= wr_slot + 16'd1;
                                wr_frame_addr <= frame_addr_for_slot(wr_slot + 16'd1);
                            end
                        end
                        wr_beat_idx <= 16'd0;
                        wr_frame_beats <= 16'd0;
                        wr_aw_seen <= 1'b0;
                        wr_w_seen <= 1'b0;
                        wr_drop_active <= 1'b0;
                        w_state <= W_IDLE;
                    end
                end else if (w_state == W_DROP) begin
                    if (s_fire && ingress_tlast) begin
                        wr_drop_active <= 1'b0;
                        drop_frame_count <= drop_frame_count + 32'd1;
                        w_state <= W_IDLE;
                    end
                end

                // Reader path.
                if (r_state == R_IDLE) begin
                    if (!ring_empty && out_ready) begin
                        m_axi_arid <= {AXI_ID_W{1'b0}};
                        m_axi_araddr <= meta_addr_for_frame(rd_frame_addr);
                        m_axi_arlen <= 8'd0;
                        m_axi_arsize <= AXI_SIZE_16B;
                        m_axi_arburst <= 2'b01;
                        m_axi_arlock <= 1'b0;
                        m_axi_arcache <= 4'b0011;
                        m_axi_arprot <= 3'b000;
                        m_axi_arqos <= 4'd0;
                        m_axi_arvalid <= 1'b1;
                        m_axi_rready <= 1'b0;
                        r_state <= R_META;
                    end
                end else if (r_state == R_META) begin
                    if (axi_ar_fire) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready <= 1'b1;
                        r_state <= R_META_WAIT;
                    end
                end else if (r_state == R_META_WAIT) begin
                    if (axi_r_fire) begin
                        if (m_axi_rresp != 2'b00 || !m_axi_rlast) begin
                            error_count <= error_count + 32'd1;
                        end
                        rd_meta_word <= m_axi_rdata;
                        rd_last_keep <= m_axi_rdata[63:0];
                        rd_last_seen <= m_axi_rdata[80];
                        rd_frame_beats <= meta_frame_beats(m_axi_rdata);
                        rd_beat_idx <= 16'd0;
                        rd_seg <= 3'd0;
                        m_axi_rready <= 1'b0;
                        r_state <= R_DATA;
                    end
                end else if (r_state == R_DATA) begin
                    if (out_ready) begin
                        m_axi_arid <= {AXI_ID_W{1'b0}};
                        m_axi_araddr <= data_addr_for_beat(rd_frame_addr, rd_beat_idx);
                        m_axi_arlen <= 8'd3;
                        m_axi_arsize <= AXI_SIZE_16B;
                        m_axi_arburst <= 2'b01;
                        m_axi_arlock <= 1'b0;
                        m_axi_arcache <= 4'b0011;
                        m_axi_arprot <= 3'b000;
                        m_axi_arqos <= 4'd0;
                        m_axi_arvalid <= 1'b1;
                        m_axi_rready <= 1'b0;
                        r_state <= R_DATA_WAIT;
                    end
                end else if (r_state == R_DATA_WAIT) begin
                    if (axi_ar_fire) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready <= 1'b1;
                    end
                    if (axi_r_fire) begin
                        if (m_axi_rresp != 2'b00) begin
                            error_count <= error_count + 32'd1;
                        end
                        case (rd_seg)
                            3'd0: rd_data_reg[0*AXI_DATA_W +: AXI_DATA_W] <= m_axi_rdata;
                            3'd1: rd_data_reg[1*AXI_DATA_W +: AXI_DATA_W] <= m_axi_rdata;
                            3'd2: rd_data_reg[2*AXI_DATA_W +: AXI_DATA_W] <= m_axi_rdata;
                            default: rd_data_reg[3*AXI_DATA_W +: AXI_DATA_W] <= m_axi_rdata;
                        endcase
                        if (rd_seg == (AXIS_SEGMENTS - 1)) begin
                            if (!m_axi_rlast) begin
                                error_count <= error_count + 32'd1;
                            end
                            m_axi_rready <= 1'b0;
                            r_state <= R_PREP;
                        end else begin
                            rd_seg <= rd_seg + 3'd1;
                        end
                    end
                end else if (r_state == R_PREP) begin
                    if (out_ready) begin
                        out_data_reg <= rd_data_reg;
                        out_keep_reg <= ((rd_beat_idx + 16'd1) >= rd_frame_beats) ? rd_last_keep : {AXIS_KEEP_W{1'b1}};
                        out_last_reg <= (rd_beat_idx + 16'd1) >= rd_frame_beats;
                        out_valid <= 1'b1;
                        r_state <= R_HOLD;
                    end
                end else if (r_state == R_HOLD) begin
                    if (m_fire) begin
                        if (out_last_reg) begin
                            read_frame_count <= read_frame_count + 32'd1;
                            if ((rd_slot + 16'd1) >= active_slots) begin
                                rd_slot <= 16'd0;
                                rd_frame_addr <= base_addr;
                            end else begin
                                rd_slot <= rd_slot + 16'd1;
                                rd_frame_addr <= frame_addr_for_slot(rd_slot + 16'd1);
                            end
                            rd_beat_idx <= 16'd0;
                            r_state <= R_IDLE;
                        end else begin
                            rd_beat_idx <= rd_beat_idx + 16'd1;
                            rd_seg <= 3'd0;
                            r_state <= R_DATA;
                        end
                    end
                end
        end
    end
    end

    assign status = {
        drop_frame_count[7:0],
        error_count[7:0],
        occupancy_frames[7:0],
        write_frame_count[7:0]
    };

endmodule

`default_nettype wire
