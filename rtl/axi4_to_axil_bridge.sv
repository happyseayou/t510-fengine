(* keep_hierarchy = "yes" *)
module axi4_to_axil_bridge #(
    parameter integer ADDR_W = 32,
    parameter integer DATA_W = 32,
    parameter integer ID_W   = 16
) (
    input  wire                 clk,
    input  wire                 rst_n,

    input  wire [ADDR_W-1:0]    s_axi_awaddr,
    input  wire [ID_W-1:0]      s_axi_awid,
    input  wire [7:0]           s_axi_awlen,
    input  wire [2:0]           s_axi_awsize,
    input  wire [1:0]           s_axi_awburst,
    input  wire                 s_axi_awvalid,
    output logic                s_axi_awready,
    input  wire [DATA_W-1:0]    s_axi_wdata,
    input  wire [DATA_W/8-1:0]  s_axi_wstrb,
    input  wire                 s_axi_wlast,
    input  wire                 s_axi_wvalid,
    output logic                s_axi_wready,
    output logic [ID_W-1:0]     s_axi_bid,
    output logic [1:0]          s_axi_bresp,
    output logic                s_axi_bvalid,
    input  wire                 s_axi_bready,

    input  wire [ADDR_W-1:0]    s_axi_araddr,
    input  wire [ID_W-1:0]      s_axi_arid,
    input  wire [7:0]           s_axi_arlen,
    input  wire [2:0]           s_axi_arsize,
    input  wire [1:0]           s_axi_arburst,
    input  wire                 s_axi_arvalid,
    output logic                s_axi_arready,
    output logic [ID_W-1:0]     s_axi_rid,
    output logic [DATA_W-1:0]   s_axi_rdata,
    output logic [1:0]          s_axi_rresp,
    output logic                s_axi_rlast,
    output logic                s_axi_rvalid,
    input  wire                 s_axi_rready,

    output logic [ADDR_W-1:0]   m_axil_awaddr,
    output logic                m_axil_awvalid,
    input  wire                 m_axil_awready,
    output logic [DATA_W-1:0]   m_axil_wdata,
    output logic [DATA_W/8-1:0] m_axil_wstrb,
    output logic                m_axil_wvalid,
    input  wire                 m_axil_wready,
    input  wire [1:0]           m_axil_bresp,
    input  wire                 m_axil_bvalid,
    output logic                m_axil_bready,

    output logic [ADDR_W-1:0]   m_axil_araddr,
    output logic                m_axil_arvalid,
    input  wire                 m_axil_arready,
    input  wire [DATA_W-1:0]    m_axil_rdata,
    input  wire [1:0]           m_axil_rresp,
    input  wire                 m_axil_rvalid,
    output logic                m_axil_rready
);

    localparam [1:0] BURST_FIXED = 2'b00;
    localparam [1:0] BURST_INCR  = 2'b01;

    typedef enum logic [1:0] {
        W_IDLE,
        W_WAIT_DATA,
        W_SEND_AXIL,
        W_WAIT_RESP
    } write_state_t;

    typedef enum logic [1:0] {
        R_IDLE,
        R_SEND_AXIL,
        R_WAIT_AXIL,
        R_SEND_FULL
    } read_state_t;

    write_state_t              w_state;
    read_state_t               r_state;

    logic [ADDR_W-1:0]         w_addr;
    logic [ID_W-1:0]           w_id;
    logic [7:0]                w_beats_left;
    logic [2:0]                w_size;
    logic [1:0]                w_burst;
    logic [1:0]                w_resp_accum;
    logic [DATA_W-1:0]         wdata_latched;
    logic [DATA_W/8-1:0]       wstrb_latched;
    logic                      wlast_latched;
    logic                      w_aw_done;
    logic                      w_w_done;

    logic [ADDR_W-1:0]         r_addr;
    logic [ID_W-1:0]           r_id;
    logic [7:0]                r_beats_left;
    logic [2:0]                r_size;
    logic [1:0]                r_burst;

    function automatic [ADDR_W-1:0] next_addr(
        input [ADDR_W-1:0] addr,
        input [2:0]        size,
        input [1:0]        burst
    );
        logic [ADDR_W-1:0] step;
        begin
            step = {{(ADDR_W-1){1'b0}}, 1'b1} << size;
            if (burst == BURST_FIXED) begin
                next_addr = addr;
            end else begin
                next_addr = addr + step;
            end
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w_state         <= W_IDLE;
            s_axi_awready   <= 1'b0;
            s_axi_wready    <= 1'b0;
            s_axi_bid       <= {ID_W{1'b0}};
            s_axi_bresp     <= 2'b00;
            s_axi_bvalid    <= 1'b0;
            m_axil_awaddr   <= {ADDR_W{1'b0}};
            m_axil_awvalid  <= 1'b0;
            m_axil_wdata    <= {DATA_W{1'b0}};
            m_axil_wstrb    <= {(DATA_W/8){1'b0}};
            m_axil_wvalid   <= 1'b0;
            m_axil_bready   <= 1'b0;
            w_addr          <= {ADDR_W{1'b0}};
            w_id            <= {ID_W{1'b0}};
            w_beats_left    <= 8'd0;
            w_size          <= 3'd0;
            w_burst         <= BURST_INCR;
            w_resp_accum    <= 2'b00;
            wdata_latched   <= {DATA_W{1'b0}};
            wstrb_latched   <= {(DATA_W/8){1'b0}};
            wlast_latched   <= 1'b0;
            w_aw_done       <= 1'b0;
            w_w_done        <= 1'b0;
        end else begin
            s_axi_awready  <= 1'b0;
            s_axi_wready   <= 1'b0;
            m_axil_bready  <= 1'b0;

            if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end

            case (w_state)
                W_IDLE: begin
                    if (!s_axi_bvalid) begin
                        s_axi_awready <= 1'b1;
                    end
                    if (s_axi_awvalid && s_axi_awready) begin
                        w_addr       <= s_axi_awaddr;
                        w_id         <= s_axi_awid;
                        w_beats_left <= s_axi_awlen;
                        w_size       <= s_axi_awsize;
                        w_burst      <= s_axi_awburst;
                        w_resp_accum <= 2'b00;
                        w_state      <= W_WAIT_DATA;
                    end
                end

                W_WAIT_DATA: begin
                    s_axi_wready <= 1'b1;
                    if (s_axi_wvalid && s_axi_wready) begin
                        wdata_latched  <= s_axi_wdata;
                        wstrb_latched  <= s_axi_wstrb;
                        wlast_latched  <= s_axi_wlast;
                        m_axil_awaddr  <= w_addr;
                        m_axil_wdata   <= s_axi_wdata;
                        m_axil_wstrb   <= s_axi_wstrb;
                        m_axil_awvalid <= 1'b1;
                        m_axil_wvalid  <= 1'b1;
                        w_aw_done      <= 1'b0;
                        w_w_done       <= 1'b0;
                        w_state        <= W_SEND_AXIL;
                    end
                end

                W_SEND_AXIL: begin
                    if (m_axil_awvalid && m_axil_awready) begin
                        m_axil_awvalid <= 1'b0;
                        w_aw_done      <= 1'b1;
                    end
                    if (m_axil_wvalid && m_axil_wready) begin
                        m_axil_wvalid <= 1'b0;
                        w_w_done      <= 1'b1;
                    end
                    if ((w_aw_done || (m_axil_awvalid && m_axil_awready)) &&
                        (w_w_done  || (m_axil_wvalid && m_axil_wready))) begin
                        w_state <= W_WAIT_RESP;
                    end
                end

                W_WAIT_RESP: begin
                    m_axil_bready <= 1'b1;
                    if (m_axil_bvalid && m_axil_bready) begin
                        w_resp_accum <= w_resp_accum | m_axil_bresp;
                        if ((w_beats_left == 8'd0) || wlast_latched) begin
                            s_axi_bid    <= w_id;
                            s_axi_bresp  <= w_resp_accum | m_axil_bresp;
                            s_axi_bvalid <= 1'b1;
                            w_state      <= W_IDLE;
                        end else begin
                            w_addr       <= next_addr(w_addr, w_size, w_burst);
                            w_beats_left <= w_beats_left - 8'd1;
                            w_state      <= W_WAIT_DATA;
                        end
                    end
                end

                default: w_state <= W_IDLE;
            endcase
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            r_state        <= R_IDLE;
            s_axi_arready  <= 1'b0;
            s_axi_rid      <= {ID_W{1'b0}};
            s_axi_rdata    <= {DATA_W{1'b0}};
            s_axi_rresp    <= 2'b00;
            s_axi_rlast    <= 1'b0;
            s_axi_rvalid   <= 1'b0;
            m_axil_araddr  <= {ADDR_W{1'b0}};
            m_axil_arvalid <= 1'b0;
            m_axil_rready  <= 1'b0;
            r_addr         <= {ADDR_W{1'b0}};
            r_id           <= {ID_W{1'b0}};
            r_beats_left   <= 8'd0;
            r_size         <= 3'd0;
            r_burst        <= BURST_INCR;
        end else begin
            s_axi_arready <= 1'b0;
            m_axil_rready <= 1'b0;

            case (r_state)
                R_IDLE: begin
                    if (!s_axi_rvalid) begin
                        s_axi_arready <= 1'b1;
                    end
                    if (s_axi_arvalid && s_axi_arready) begin
                        r_addr         <= s_axi_araddr;
                        r_id           <= s_axi_arid;
                        r_beats_left   <= s_axi_arlen;
                        r_size         <= s_axi_arsize;
                        r_burst        <= s_axi_arburst;
                        m_axil_araddr  <= s_axi_araddr;
                        m_axil_arvalid <= 1'b1;
                        r_state        <= R_SEND_AXIL;
                    end
                end

                R_SEND_AXIL: begin
                    if (m_axil_arvalid && m_axil_arready) begin
                        m_axil_arvalid <= 1'b0;
                        r_state        <= R_WAIT_AXIL;
                    end
                end

                R_WAIT_AXIL: begin
                    m_axil_rready <= 1'b1;
                    if (m_axil_rvalid && m_axil_rready) begin
                        s_axi_rid    <= r_id;
                        s_axi_rdata  <= m_axil_rdata;
                        s_axi_rresp  <= m_axil_rresp;
                        s_axi_rlast  <= (r_beats_left == 8'd0);
                        s_axi_rvalid <= 1'b1;
                        r_state      <= R_SEND_FULL;
                    end
                end

                R_SEND_FULL: begin
                    if (s_axi_rvalid && s_axi_rready) begin
                        s_axi_rvalid <= 1'b0;
                        if (r_beats_left == 8'd0) begin
                            r_state <= R_IDLE;
                        end else begin
                            r_addr         <= next_addr(r_addr, r_size, r_burst);
                            r_beats_left   <= r_beats_left - 8'd1;
                            m_axil_araddr  <= next_addr(r_addr, r_size, r_burst);
                            m_axil_arvalid <= 1'b1;
                            r_state        <= R_SEND_AXIL;
                        end
                    end
                end

                default: r_state <= R_IDLE;
            endcase
        end
    end

endmodule
