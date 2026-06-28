`include "tb_common.svh"

module tb_time_axis512_ddr_ring;

    localparam integer AXI_ADDR_W  = 16;
    localparam integer AXI_DATA_W  = 128;
    localparam integer AXI_ID_W    = 6;
    localparam integer AXIS_DATA_W = 512;
    localparam integer AXIS_KEEP_W = 64;
    localparam integer FRAME_BEATS = 3;
    localparam integer DEFAULT_SLOTS = 2;
    localparam logic [AXI_ADDR_W-1:0] BASE_ADDR = 16'h1000;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic enable = 1'b0;
    logic [AXI_ADDR_W-1:0] base_addr = BASE_ADDR;
    logic [15:0] ring_slots_cfg = DEFAULT_SLOTS[15:0];

    logic [AXIS_DATA_W-1:0] s_tdata = '0;
    logic [AXIS_KEEP_W-1:0] s_tkeep = '0;
    logic s_tvalid = 1'b0;
    logic s_tlast = 1'b0;
    wire  s_tready;

    wire [AXIS_DATA_W-1:0] m_tdata;
    wire [AXIS_KEEP_W-1:0] m_tkeep;
    wire m_tvalid;
    wire m_tlast;
    logic m_tready = 1'b1;

    wire [AXI_ID_W-1:0] m_axi_awid;
    wire [AXI_ADDR_W-1:0] m_axi_awaddr;
    wire [7:0] m_axi_awlen;
    wire [2:0] m_axi_awsize;
    wire [1:0] m_axi_awburst;
    wire m_axi_awlock;
    wire [3:0] m_axi_awcache;
    wire [2:0] m_axi_awprot;
    wire [3:0] m_axi_awqos;
    wire m_axi_awvalid;
    logic m_axi_awready = 1'b1;
    wire [AXI_DATA_W-1:0] m_axi_wdata;
    wire [AXI_DATA_W/8-1:0] m_axi_wstrb;
    wire m_axi_wlast;
    wire m_axi_wvalid;
    logic m_axi_wready = 1'b1;
    logic [AXI_ID_W-1:0] m_axi_bid = '0;
    logic [1:0] m_axi_bresp = 2'b00;
    logic m_axi_bvalid = 1'b0;
    wire m_axi_bready;
    wire [AXI_ID_W-1:0] m_axi_arid;
    wire [AXI_ADDR_W-1:0] m_axi_araddr;
    wire [7:0] m_axi_arlen;
    wire [2:0] m_axi_arsize;
    wire [1:0] m_axi_arburst;
    wire m_axi_arlock;
    wire [3:0] m_axi_arcache;
    wire [2:0] m_axi_arprot;
    wire [3:0] m_axi_arqos;
    wire m_axi_arvalid;
    logic m_axi_arready = 1'b1;
    logic [AXI_ID_W-1:0] m_axi_rid = '0;
    logic [AXI_DATA_W-1:0] m_axi_rdata = '0;
    logic [1:0] m_axi_rresp = 2'b00;
    logic m_axi_rlast = 1'b0;
    logic m_axi_rvalid = 1'b0;
    wire m_axi_rready;

    wire [31:0] occupancy_frames;
    wire [31:0] write_frame_count;
    wire [31:0] read_frame_count;
    wire [31:0] drop_frame_count;
    wire [31:0] error_count;
    wire [31:0] status;

    logic [127:0] mem [0:4095];
    logic [AXI_ADDR_W-1:0] wr_addr = '0;
    logic [AXI_ADDR_W-1:0] rd_addr = '0;
    logic [7:0] rd_remaining = 8'd0;

    always #3 clk = ~clk;

    time_axis512_ddr_ring #(
        .AXI_ADDR_W(AXI_ADDR_W),
        .AXI_DATA_W(AXI_DATA_W),
        .AXI_ID_W(AXI_ID_W),
        .AXIS_DATA_W(AXIS_DATA_W),
        .AXIS_KEEP_W(AXIS_KEEP_W),
        .FRAME_BEATS(FRAME_BEATS),
        .DEFAULT_SLOTS(DEFAULT_SLOTS)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .clear(clear),
        .enable(enable),
        .base_addr(base_addr),
        .ring_slots_cfg(ring_slots_cfg),
        .s_axis_tdata(s_tdata),
        .s_axis_tkeep(s_tkeep),
        .s_axis_tvalid(s_tvalid),
        .s_axis_tlast(s_tlast),
        .s_axis_tready(s_tready),
        .m_axis_tdata(m_tdata),
        .m_axis_tkeep(m_tkeep),
        .m_axis_tvalid(m_tvalid),
        .m_axis_tlast(m_tlast),
        .m_axis_tready(m_tready),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_awqos(m_axi_awqos),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_arqos(m_axi_arqos),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready),
        .occupancy_frames(occupancy_frames),
        .write_frame_count(write_frame_count),
        .read_frame_count(read_frame_count),
        .drop_frame_count(drop_frame_count),
        .error_count(error_count),
        .status(status)
    );

    wire aw_fire = m_axi_awvalid && m_axi_awready;
    wire w_fire = m_axi_wvalid && m_axi_wready;
    wire b_fire = m_axi_bvalid && m_axi_bready;
    wire ar_fire = m_axi_arvalid && m_axi_arready;
    wire r_fire = m_axi_rvalid && m_axi_rready;

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            wr_addr <= '0;
            rd_addr <= '0;
            rd_remaining <= 8'd0;
            m_axi_bvalid <= 1'b0;
            m_axi_bresp <= 2'b00;
            m_axi_rvalid <= 1'b0;
            m_axi_rdata <= '0;
            m_axi_rresp <= 2'b00;
            m_axi_rlast <= 1'b0;
        end else begin
            if (aw_fire) begin
                wr_addr <= m_axi_awaddr;
            end
            if (w_fire) begin
                mem[(aw_fire ? m_axi_awaddr : wr_addr) >> 4] <= m_axi_wdata;
                wr_addr <= (aw_fire ? m_axi_awaddr : wr_addr) + 16'd16;
                if (m_axi_wlast) begin
                    m_axi_bvalid <= 1'b1;
                    m_axi_bresp <= 2'b00;
                end
            end
            if (b_fire) begin
                m_axi_bvalid <= 1'b0;
            end

            if (ar_fire) begin
                rd_addr <= m_axi_araddr + 16'd16;
                rd_remaining <= m_axi_arlen;
                m_axi_rdata <= mem[m_axi_araddr >> 4];
                m_axi_rlast <= (m_axi_arlen == 8'd0);
                m_axi_rvalid <= 1'b1;
                m_axi_rresp <= 2'b00;
            end else if (r_fire) begin
                if (rd_remaining == 8'd0) begin
                    m_axi_rvalid <= 1'b0;
                    m_axi_rlast <= 1'b0;
                end else begin
                    m_axi_rdata <= mem[rd_addr >> 4];
                    rd_addr <= rd_addr + 16'd16;
                    rd_remaining <= rd_remaining - 8'd1;
                    m_axi_rlast <= (rd_remaining == 8'd1);
                    m_axi_rvalid <= 1'b1;
                end
            end
        end
    end

    function automatic [511:0] make_data(input integer frame_idx, input integer beat_idx);
        integer lane;
        begin
            make_data = 512'd0;
            for (lane = 0; lane < 64; lane = lane + 1) begin
                make_data[lane*8 +: 8] = (frame_idx * 8'h31) + (beat_idx * 8'h11) + lane[7:0];
            end
        end
    endfunction

    function automatic [63:0] make_keep(input integer beat_idx);
        begin
            make_keep = (beat_idx == (FRAME_BEATS - 1)) ? 64'h0000_0000_0000_0fff
                                                         : 64'hffff_ffff_ffff_ffff;
        end
    endfunction

    task automatic pulse_clear;
        begin
            @(negedge clk);
            clear = 1'b1;
            @(negedge clk);
            clear = 1'b0;
        end
    endtask

    task automatic send_beat(input integer frame_idx, input integer beat_idx);
        begin
            @(negedge clk);
            s_tdata = make_data(frame_idx, beat_idx);
            s_tkeep = make_keep(beat_idx);
            s_tlast = (beat_idx == (FRAME_BEATS - 1));
            s_tvalid = 1'b1;
            do begin
                @(posedge clk);
            end while (!s_tready);
            @(negedge clk);
            s_tvalid = 1'b0;
            s_tlast = 1'b0;
            s_tkeep = '0;
            s_tdata = '0;
        end
    endtask

    task automatic send_frame(input integer frame_idx);
        integer beat_idx;
        begin
            for (beat_idx = 0; beat_idx < FRAME_BEATS; beat_idx = beat_idx + 1) begin
                send_beat(frame_idx, beat_idx);
            end
        end
    endtask

    task automatic expect_beat(input integer frame_idx, input integer beat_idx);
        integer timeout;
        begin
            timeout = 0;
            while (!m_tvalid && timeout < 2000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            `TB_CHECK(m_tvalid, "DDR ring output valid")
            `TB_CHECK_EQ(m_tdata, make_data(frame_idx, beat_idx), "DDR ring data beat")
            `TB_CHECK_EQ(m_tkeep, make_keep(beat_idx), "DDR ring keep beat")
            `TB_CHECK_EQ(m_tlast, (beat_idx == (FRAME_BEATS - 1)), "DDR ring last beat")
            @(posedge clk);
        end
    endtask

    task automatic expect_frame(input integer frame_idx);
        integer beat_idx;
        begin
            for (beat_idx = 0; beat_idx < FRAME_BEATS; beat_idx = beat_idx + 1) begin
                expect_beat(frame_idx, beat_idx);
            end
        end
    endtask

    initial begin
        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        enable = 1'b0;
        m_tready = 1'b1;
        @(negedge clk);
        s_tdata = make_data(9, 0);
        s_tkeep = make_keep(0);
        s_tlast = 1'b0;
        s_tvalid = 1'b1;
        @(posedge clk);
        `TB_CHECK(m_tvalid, "DDR ring pass-through valid")
        `TB_CHECK_EQ(m_tdata, make_data(9, 0), "DDR ring pass-through data")
        @(negedge clk);
        s_tvalid = 1'b0;
        s_tdata = '0;
        s_tkeep = '0;
        s_tlast = 1'b0;

        enable = 1'b1;
        pulse_clear();
        m_tready = 1'b1;
        send_frame(0);
        expect_frame(0);
        `TB_CHECK_EQ(write_frame_count, 32'd1, "DDR ring write count after readback")
        `TB_CHECK_EQ(read_frame_count, 32'd1, "DDR ring read count after readback")
        `TB_CHECK_EQ(drop_frame_count, 32'd0, "DDR ring no drop after readback")
        `TB_CHECK_EQ(error_count, 32'd0, "DDR ring no errors after readback")

        pulse_clear();
        ring_slots_cfg = 16'd1;
        m_tready = 1'b0;
        send_frame(1);
        wait (write_frame_count == 32'd1);
        `TB_CHECK_EQ(occupancy_frames, 32'd1, "DDR ring occupancy full")
        send_frame(2);
        wait (drop_frame_count == 32'd1);
        `TB_CHECK_EQ(write_frame_count, 32'd1, "DDR ring no write on dropped frame")
        m_tready = 1'b1;
        expect_frame(1);
        `TB_CHECK_EQ(read_frame_count, 32'd1, "DDR ring read count after drop test")
        `TB_CHECK_EQ(occupancy_frames, 32'd0, "DDR ring occupancy empty")
        `TB_CHECK_EQ(error_count, 32'd0, "DDR ring no errors after drop test")

        `TB_PASS("tb_time_axis512_ddr_ring")
    end

endmodule
