`include "tb_common.svh"

module tb_t510_fengine_top_smoke;

    localparam [31:0] START_TUSER = 32'd64;
    localparam [63:0] START_SAMPLE0 = 64'h0000_0001_0000_0100;
    localparam [63:0] EXPECTED_PACKET_SAMPLE0 = START_SAMPLE0;
    localparam [63:0] EXPECTED_SPEC_PACKET_SAMPLE0 = START_SAMPLE0 + 64'd4;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic pps_in = 1'b0;
    logic ref_lock_in = 1'b1;
    logic rfdc_ready_in = 1'b1;
    logic [31:0] s_axi_awaddr = 32'd0;
    logic        s_axi_awvalid = 1'b0;
    wire         s_axi_awready;
    logic [31:0] s_axi_wdata = 32'd0;
    logic [3:0]  s_axi_wstrb = 4'hf;
    logic        s_axi_wvalid = 1'b0;
    wire         s_axi_wready;
    wire [1:0]   s_axi_bresp;
    wire         s_axi_bvalid;
    logic        s_axi_bready = 1'b0;
    logic [31:0] s_axi_araddr = 32'd0;
    logic        s_axi_arvalid = 1'b0;
    wire         s_axi_arready;
    wire [31:0]  s_axi_rdata;
    wire [1:0]   s_axi_rresp;
    wire         s_axi_rvalid;
    logic        s_axi_rready = 1'b0;
    logic [1023:0] s_axis_adc_tdata = 1024'd0;
    logic [31:0]  s_axis_adc_tuser = 32'd0;
    logic [63:0]  s_axis_adc_sample0 = START_SAMPLE0;
    logic         s_axis_adc_tvalid = 1'b0;
    logic         s_axis_adc_tlast = 1'b0;
    wire          s_axis_adc_tready;
    wire [63:0]   m_axis_tx_tdata;
    wire [7:0]    m_axis_tx_tkeep;
    wire          m_axis_tx_tvalid;
    wire          m_axis_tx_tlast;
    logic         m_axis_tx_tready = 1'b1;
    wire [511:0]  cmac_tx_axis_tdata;
    wire [63:0]   cmac_tx_axis_tkeep;
    wire          cmac_tx_axis_tvalid;
    wire          cmac_tx_axis_tlast;
    wire          irq;
    integer       adc_beat_idx = 0;

    always #5 clk = ~clk;

    function automatic [255:0] make_subsample(input integer beat, input integer sub);
        begin
            make_subsample = {
                64'h3000_0000_0000_0003 + (beat * 16) + (sub * 4),
                64'h3000_0000_0000_0002 + (beat * 16) + (sub * 4),
                64'h3000_0000_0000_0001 + (beat * 16) + (sub * 4),
                64'h3000_0000_0000_0000 + (beat * 16) + (sub * 4)
            };
        end
    endfunction

    function automatic [1023:0] make_sample(input integer beat);
        begin
            make_sample = {
                make_subsample(beat, 3),
                make_subsample(beat, 2),
                make_subsample(beat, 1),
                make_subsample(beat, 0)
            };
        end
    endfunction

    t510_fengine_top dut (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(clk),
        .ctrl_rst_n(rst_n),
        .pps_in(pps_in),
        .ref_lock_in(ref_lock_in),
        .rfdc_ready_in(rfdc_ready_in),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .s_axis_adc_tdata(s_axis_adc_tdata),
        .s_axis_adc_tuser(s_axis_adc_tuser),
        .s_axis_adc_sample0(s_axis_adc_sample0),
        .s_axis_adc_tvalid(s_axis_adc_tvalid),
        .s_axis_adc_tlast(s_axis_adc_tlast),
        .s_axis_adc_tready(s_axis_adc_tready),
        .s_axis_preview_tdata0(s_axis_adc_tdata[255:0]),
        .s_axis_preview_tdata1(s_axis_adc_tdata[511:256]),
        .s_axis_preview_tdata2(s_axis_adc_tdata[767:512]),
        .s_axis_preview_tdata3(s_axis_adc_tdata[1023:768]),
        .s_axis_preview_sample0(s_axis_adc_sample0),
        .s_axis_preview_tvalid(s_axis_adc_tvalid && s_axis_adc_tready),
        .rfdc_status_flags(32'h0000_000f),
        .rfdc_sample_count(64'd0),
        .rfdc_dropped_count(32'd0),
        .rfdc_current_valid_mask(16'hffff),
        .rfdc_seen_valid_mask(16'hffff),
        .dac_audit_phase_epoch_seen(32'd0),
        .dac_audit_ch0_phase_acc(32'd0),
        .dac_audit_ch0_phase_step(32'd0),
        .dac_audit_ch0_phase0(32'd0),
        .dac_audit_ch0_mode(32'd0),
        .dac_tx_witness_armed(1'b0),
        .dac_tx_witness_valid(1'b0),
        .dac_tx_witness_capturing(1'b0),
        .dac_tx_witness_overflow(1'b0),
        .dac_tx_witness_tvalid_seen(1'b0),
        .dac_tx_witness_tready_seen(1'b0),
        .dac_tx_witness_ready_gap_seen(1'b0),
        .dac_tx_witness_word_count(9'd0),
        .dac_tx_witness_phase_epoch(32'd0),
        .dac_tx_witness_phase_acc(32'd0),
        .dac_tx_witness_phase_step(32'd0),
        .dac_tx_witness_phase0(32'd0),
        .dac_tx_witness_mode(32'd0),
        .dac_tx_witness_ready_gap_count(32'd0),
        .dac_tx_witness_rd_data(32'd0),
        .rfdc_active_port_mask(),
        .m_axis_tx_tdata(m_axis_tx_tdata),
        .m_axis_tx_tkeep(m_axis_tx_tkeep),
        .m_axis_tx_tvalid(m_axis_tx_tvalid),
        .m_axis_tx_tlast(m_axis_tx_tlast),
        .m_axis_tx_tready(m_axis_tx_tready),
        .cmac_tx_clk(clk),
        .cmac_tx_rst_n(rst_n),
        .cmac_tx_axis_tdata(cmac_tx_axis_tdata),
        .cmac_tx_axis_tkeep(cmac_tx_axis_tkeep),
        .cmac_tx_axis_tvalid(cmac_tx_axis_tvalid),
        .cmac_tx_axis_tlast(cmac_tx_axis_tlast),
        .cmac_tx_axis_tready(1'b1),
        .m_axi_ddr_awid(),
        .m_axi_ddr_awaddr(),
        .m_axi_ddr_awlen(),
        .m_axi_ddr_awsize(),
        .m_axi_ddr_awburst(),
        .m_axi_ddr_awlock(),
        .m_axi_ddr_awcache(),
        .m_axi_ddr_awprot(),
        .m_axi_ddr_awqos(),
        .m_axi_ddr_awvalid(),
        .m_axi_ddr_awready(1'b1),
        .m_axi_ddr_wdata(),
        .m_axi_ddr_wstrb(),
        .m_axi_ddr_wlast(),
        .m_axi_ddr_wvalid(),
        .m_axi_ddr_wready(1'b1),
        .m_axi_ddr_bid(6'd0),
        .m_axi_ddr_bresp(2'b00),
        .m_axi_ddr_bvalid(1'b0),
        .m_axi_ddr_bready(),
        .m_axi_ddr_arid(),
        .m_axi_ddr_araddr(),
        .m_axi_ddr_arlen(),
        .m_axi_ddr_arsize(),
        .m_axi_ddr_arburst(),
        .m_axi_ddr_arlock(),
        .m_axi_ddr_arcache(),
        .m_axi_ddr_arprot(),
        .m_axi_ddr_arqos(),
        .m_axi_ddr_arvalid(),
        .m_axi_ddr_arready(1'b1),
        .m_axi_ddr_rid(6'd0),
        .m_axi_ddr_rdata(128'd0),
        .m_axi_ddr_rresp(2'b00),
        .m_axi_ddr_rlast(1'b0),
        .m_axi_ddr_rvalid(1'b0),
        .m_axi_ddr_rready(),
        .tx_link_status_flags(32'h0000_101c),
        .tx_dry_run_packet_count(32'd0),
        .tx_dry_run_byte_count(32'd0),
        .dac_tone_enable(),
        .dac_tone_amplitude(),
        .dac_tone_phase_step(),
        .dac_enable_mask(),
        .dac_tone_amplitude_vec(),
        .dac_tone_phase_step_vec(),
        .dac_tone_phase0_vec(),
        .dac_tone_phase_inject_vec(),
        .dac_tone_mode_vec(),
        .dac_phase_epoch(),
        .dac_tx_witness_arm_pulse(),
        .dac_tx_witness_clear_pulse(),
        .dac_tx_witness_capture_words(),
        .dac_tx_witness_rd_word(),
        .irq(irq)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            adc_beat_idx <= 0;
            s_axis_adc_tdata <= make_sample(0);
            s_axis_adc_tuser <= START_TUSER;
            s_axis_adc_sample0 <= START_SAMPLE0;
        end else if (s_axis_adc_tvalid && s_axis_adc_tready) begin
            adc_beat_idx <= adc_beat_idx + 1;
            s_axis_adc_tdata <= make_sample(adc_beat_idx + 1);
            s_axis_adc_tuser <= s_axis_adc_tuser + 32'd1;
            s_axis_adc_sample0 <= s_axis_adc_sample0 + 64'd4;
        end
    end

    task automatic reset_dut;
        begin
            rst_n = 1'b0;
            pps_in = 1'b0;
            s_axi_awvalid = 1'b0;
            s_axi_wvalid = 1'b0;
            s_axi_bready = 1'b0;
            s_axi_arvalid = 1'b0;
            s_axi_rready = 1'b0;
            s_axis_adc_tvalid = 1'b0;
            s_axis_adc_tuser = START_TUSER;
            s_axis_adc_sample0 = START_SAMPLE0;
            repeat (8) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic axi_write(input [31:0] addr, input [31:0] data);
        begin
            @(posedge clk);
            s_axi_awaddr <= addr;
            s_axi_awvalid <= 1'b1;
            s_axi_wdata <= data;
            s_axi_wstrb <= 4'hf;
            s_axi_wvalid <= 1'b1;
            s_axi_bready <= 1'b1;
            @(posedge clk);
            s_axi_awvalid <= 1'b0;
            while (!s_axi_bvalid) begin
                @(posedge clk);
            end
            `TB_CHECK_EQ(s_axi_bresp, 2'b00, "top AXI write response")
            @(posedge clk);
            s_axi_wvalid <= 1'b0;
            s_axi_bready <= 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic axi_read(input [31:0] addr, output [31:0] data);
        begin
            @(posedge clk);
            s_axi_araddr <= addr;
            s_axi_arvalid <= 1'b1;
            s_axi_rready <= 1'b1;
            @(posedge clk);
            s_axi_arvalid <= 1'b0;
            while (!s_axi_rvalid) begin
                @(posedge clk);
            end
            data = s_axi_rdata;
            `TB_CHECK_EQ(s_axi_rresp, 2'b00, "top AXI read response")
            @(posedge clk);
            s_axi_rready <= 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic wait_for_state(input [3:0] expected_state);
        reg [31:0] rd;
        integer timeout;
        begin
            timeout = 0;
            rd = 32'd0;
            while ((rd[11:8] != expected_state) && (timeout < 80)) begin
                axi_read(16'h0010, rd);
                timeout = timeout + 1;
            end
            `TB_CHECK_EQ(rd[11:8], expected_state, "top FSM state wait")
        end
    endtask

    task automatic pulse_pps;
        begin
            @(posedge clk);
            pps_in <= 1'b1;
            @(posedge clk);
            pps_in <= 1'b0;
        end
    endtask

    task automatic check_default_waits_without_pps;
        reg [31:0] rd;
        begin
            reset_dut();
            axi_write(16'h000c, 32'h0000_0001);
            wait_for_state(4'd5);
            repeat (10) @(posedge clk);
            axi_read(16'h0010, rd);
            `TB_CHECK_EQ(rd[0], 1'b1, "default external PPS mode arms")
            `TB_CHECK_EQ(rd[1], 1'b0, "default external PPS mode does not stream without PPS")
            `TB_CHECK_EQ(rd[3:2], 2'd0, "default sync mode is external PPS")
            `TB_CHECK_EQ(rd[4], 1'b1, "default mode waits for epoch")
        end
    endtask

    task automatic collect_header(input integer expected_stream_type, input bit expect_tx);
        reg [63:0] word0;
        reg [63:0] word1;
        reg [63:0] word5;
        integer seen;
        integer timeout;
        integer timeout_limit;
        begin
            word0 = 64'd0;
            word1 = 64'd0;
            word5 = 64'd0;
            seen = 0;
            timeout = 0;
            timeout_limit = (!expect_tx) ? 2200 : ((expected_stream_type == 0) ? 560000 : 2200);
            while ((seen < 6) && (timeout < timeout_limit)) begin
                @(posedge clk);
                if (m_axis_tx_tvalid && m_axis_tx_tready) begin
                    if (seen == 0) begin
                        word0 = m_axis_tx_tdata;
                    end else if (seen == 1) begin
                        word1 = m_axis_tx_tdata;
                    end else if (seen == 5) begin
                        word5 = m_axis_tx_tdata;
                    end
                    seen = seen + 1;
                end
                timeout = timeout + 1;
            end

            if (expect_tx) begin
                `TB_CHECK_EQ(seen, 6, "top TX frame header observed")
                if (expected_stream_type == 1) begin
                    `TB_CHECK_EQ(word0, 64'h0002_b295_d5eb_c008, "top TIME frame dst/src MAC")
                end else begin
                    `TB_CHECK_EQ(word0, 64'h0002_b295_d5eb_c008, "top SPEC frame dst/src MAC")
                end
                `TB_CHECK_EQ(word1, 64'h0045_0008_0100_0000, "top Ethernet type and IPv4 start")
                `TB_CHECK_EQ(word5[15:0], 16'h0000, "top UDP checksum disabled")
                `TB_CHECK_EQ(word5[63:16], 48'h3130_0002_0080, "top T510 payload starts after UDP")
            end else begin
                `TB_CHECK_EQ(seen, 0, "snapshot mode should not emit TX in current shell")
            end
        end
    endtask

    task automatic run_mode(input [1:0] mode_value, input integer expected_stream_type, input bit expect_tx);
        begin
            reset_dut();
            axi_write(16'h0020, 32'h0000_0002);
            axi_write(16'h0008, {30'd0, mode_value});
            axi_write(16'h000c, 32'h0000_0001);
            wait_for_state(4'd6);
            s_axis_adc_tvalid = 1'b1;
            collect_header(expected_stream_type, expect_tx);
            s_axis_adc_tvalid = 1'b0;
        end
    endtask

    task automatic wait_for_header_capture_valid;
        reg [31:0] rd;
        integer timeout;
        begin
            rd = 32'd0;
            timeout = 0;
            while (!rd[1] && timeout < 120) begin
                axi_read(16'h037c, rd);
                timeout = timeout + 1;
            end
            `TB_CHECK(rd[1], "top TX header capture valid")
            `TB_CHECK_EQ(rd[20:16], 5'd16, "top TX header capture word count")
        end
    endtask

    task automatic wait_for_frame_capture_valid;
        reg [31:0] rd;
        integer timeout;
        begin
            rd = 32'd0;
            timeout = 0;
            while (!rd[1] && timeout < 120) begin
                axi_read(16'hb034, rd);
                timeout = timeout + 1;
            end
            `TB_CHECK(rd[1], "top TX frame capture valid")
            `TB_CHECK_EQ(rd[20:16], 5'd16, "top TX frame capture word count")
        end
    endtask

    task automatic wait_for_payload_witness_valid;
        reg [31:0] rd;
        integer timeout;
        begin
            rd = 32'd0;
            timeout = 0;
            while (!rd[1] && timeout < 160) begin
                axi_read(16'h0794, rd);
                timeout = timeout + 1;
            end
            `TB_CHECK(rd[1], "top TX payload witness valid")
            `TB_CHECK_EQ(rd[18:8], 11'd128, "top TX payload witness word count")
        end
    endtask

    task automatic run_spec_header_capture;
        reg [31:0] rd;
        begin
            reset_dut();
            axi_write(16'h0020, 32'h0000_0002);
            axi_write(16'h0008, 32'd0);
            axi_write(16'h0378, 32'h0000_0001);
            axi_write(16'hb030, 32'h0000_0001);
            axi_write(16'h0798, 32'h0000_0001);
            axi_write(16'h079c, 32'd128);
            axi_write(16'h0790, 32'h0000_0003);
            axi_write(16'h0790, 32'h0000_0001);
            axi_write(16'h000c, 32'h0000_0001);
            wait_for_state(4'd6);
            s_axis_adc_tvalid = 1'b1;
            collect_header(0, 1'b1);
            wait_for_header_capture_valid();
            wait_for_frame_capture_valid();
            wait_for_payload_witness_valid();
            s_axis_adc_tvalid = 1'b0;

            axi_read(16'h0370, rd);
            `TB_CHECK(rd > 32'd0, "top TX FIFO high-water is nonzero")
            axi_read(16'h0380, rd);
            `TB_CHECK_EQ(rd, 32'h0002_0080, "top captured header word0 low")
            axi_read(16'h0384, rd);
            `TB_CHECK_EQ(rd, 32'h5435_3130, "top captured header word0 high")
            axi_read(16'h0388, rd);
            `TB_CHECK_EQ(rd, 32'h0001_000a, "top captured header word1 low")
            axi_read(16'h038c, rd);
            `TB_CHECK_EQ(rd, 32'h0000_0000, "top captured header word1 high")
            axi_read(16'h03a0, rd);
            axi_read(16'h03a4, rd);
            axi_read(16'h03b8, rd);
            `TB_CHECK_EQ(rd, 32'h0008_0000, "top captured SPEC layout word7 low")
            axi_read(16'h03bc, rd);
            `TB_CHECK_EQ(rd, 32'h0100_0001, "top captured SPEC layout word7 high")
            axi_read(16'h0904, rd);
            `TB_CHECK(rd[1], "top PFB config valid")
            axi_read(16'hb004, rd);
            `TB_CHECK(rd[1], "top TX dry-run active")
            `TB_CHECK_EQ(rd[0], 1'b0, "top TX link remains down in preflight")
            axi_read(16'hb040, rd);
            `TB_CHECK_EQ(rd, 32'hd5eb_c008, "top captured frame word0 low")
            axi_read(16'hb044, rd);
            `TB_CHECK_EQ(rd, 32'h0002_b295, "top captured frame word0 high")
            axi_read(16'h07a0, rd);
            axi_read(16'h07a4, rd);
            axi_read(16'h07c0, rd);
            `TB_CHECK_EQ(rd, 32'd8192, "top witness payload bytes")
            axi_read(32'h0001_0000, rd);
            `TB_CHECK_EQ(rd, 32'h0002_0080, "top witness buffer word0 low")
            axi_read(32'h0001_0004, rd);
            `TB_CHECK_EQ(rd, 32'h5435_3130, "top witness buffer word0 high")
        end
    endtask

    task automatic collect_science_spec_cmac_frame;
        reg [511:0] beat0;
        reg [511:0] beat1;
        reg [511:0] beat2;
        reg [31:0] rd_science;
        reg [31:0] rd_pfb_status;
        reg [31:0] rd_pfb_frames;
        reg [31:0] rd_spec_packets;
        reg [31:0] rd_spec_frames;
        reg [31:0] rd_cmac_source;
        reg [7:0]  spec_status_byte1;
        integer spec_udp_seen;
        integer mux_seen;
        integer slice_seen;
        integer seen;
        integer timeout;
        begin
            beat0 = 512'd0;
            beat1 = 512'd0;
            beat2 = 512'd0;
            spec_udp_seen = 0;
            mux_seen = 0;
            slice_seen = 0;
            seen = 0;
            timeout = 0;
            while ((seen < 3) && (timeout < 560000)) begin
                @(posedge clk);
                if (dut.wide_spec_live_cmac_tvalid && dut.wide_spec_live_cmac_tready) begin
                    spec_udp_seen = spec_udp_seen + 1;
                end
                if (dut.cmac_mux_axis_tvalid && dut.cmac_mux_axis_tready) begin
                    mux_seen = mux_seen + 1;
                end
                if (cmac_tx_axis_tvalid && dut.cmac_tx_axis_tready) begin
                    slice_seen = slice_seen + 1;
                end
                if (cmac_tx_axis_tvalid) begin
                    if (seen == 0) begin
                        beat0 = cmac_tx_axis_tdata;
                    end else if (seen == 1) begin
                        beat1 = cmac_tx_axis_tdata;
                    end else begin
                        beat2 = cmac_tx_axis_tdata;
                    end
                    seen = seen + 1;
                end
                timeout = timeout + 1;
            end

            if (seen != 3) begin
                axi_read(16'hd004, rd_science);
                axi_read(16'h0904, rd_pfb_status);
                axi_read(16'h0920, rd_pfb_frames);
                axi_read(16'h0304, rd_spec_packets);
                axi_read(16'hb008, rd_spec_frames);
                axi_read(16'hb704, rd_cmac_source);
                $display("top production SPEC timeout debug: science=0x%08x pfb_status=0x%08x pfb_frames=%0d spec_packets=%0d spec_frames=%0d cmac_source=0x%08x spec_udp_seen=%0d mux_seen=%0d slice_seen=%0d adc_beat_idx=%0d spec_valid=%b spec_ready=%b mux_valid=%b mux_ready=%b slice_valid=%b slice_ready=%b",
                         rd_science, rd_pfb_status, rd_pfb_frames, rd_spec_packets, rd_spec_frames, rd_cmac_source,
                         spec_udp_seen, mux_seen, slice_seen, adc_beat_idx,
                         dut.wide_spec_live_cmac_tvalid, dut.wide_spec_live_cmac_tready,
                         dut.cmac_mux_axis_tvalid, dut.cmac_mux_axis_tready,
                         cmac_tx_axis_tvalid, dut.cmac_tx_axis_tready);
            end
            `TB_CHECK_EQ(seen, 3, "top production SPEC CMAC header beats observed")
            `TB_CHECK_EQ(beat0[0*8 +: 8], 8'h08, "top production SPEC dst mac byte0")
            `TB_CHECK_EQ(beat0[5*8 +: 8], 8'hb2, "top production SPEC dst mac byte5")
            `TB_CHECK_EQ(beat0[12*8 +: 8], 8'h08, "top production SPEC ethertype high")
            `TB_CHECK_EQ(beat0[13*8 +: 8], 8'h00, "top production SPEC ethertype low")
            `TB_CHECK_EQ(beat0[34*8 +: 8], 8'h0f, "top production SPEC udp src port high")
            `TB_CHECK_EQ(beat0[35*8 +: 8], 8'ha8, "top production SPEC udp src port low")
            `TB_CHECK_EQ(beat0[36*8 +: 8], 8'h10, "top production SPEC udp dst port high")
            `TB_CHECK_EQ(beat0[37*8 +: 8], 8'hd4, "top production SPEC udp dst port low")
            `TB_CHECK_EQ(beat0[42*8 +: 8], 8'h80, "top production SPEC T510 header bytes low")
            `TB_CHECK_EQ(beat0[44*8 +: 8], 8'h02, "top production SPEC T510 version low")
            `TB_CHECK_EQ(beat0[46*8 +: 8], 8'h30, "top production SPEC T510 magic byte0")
            `TB_CHECK_EQ(beat0[49*8 +: 8], 8'h54, "top production SPEC T510 magic byte3")
            `TB_CHECK_EQ(beat1[(98-64)*8 +: 8], 8'h00, "top production SPEC quant low")
            `TB_CHECK_EQ(beat1[(100-64)*8 +: 8], 8'h08, "top production SPEC ninput low")
            `TB_CHECK_EQ(beat1[(102-64)*8 +: 8], 8'h01, "top production SPEC time_count low")
            `TB_CHECK_EQ(beat1[(104-64)*8 +: 8], 8'h00, "top production SPEC chan_count low")
            `TB_CHECK_EQ(beat1[(105-64)*8 +: 8], 8'h01, "top production SPEC chan_count high")
            `TB_CHECK_EQ(beat1[(106-64)*8 +: 8], 8'h00, "top production SPEC payload bytes byte0")
            `TB_CHECK_EQ(beat1[(107-64)*8 +: 8], 8'h20, "top production SPEC payload bytes byte1")
            `TB_CHECK_EQ(beat1[(114-64)*8 +: 8], 8'h10, "top production SPEC block_count low")
            `TB_CHECK_EQ(beat1[(116-64)*8 +: 8], 8'h00, "top production SPEC block_index low")
            `TB_CHECK_EQ(beat1[(118-64)*8 +: 8], 8'h00, "top production SPEC nchan byte0")
            `TB_CHECK_EQ(beat1[(119-64)*8 +: 8], 8'h10, "top production SPEC nchan byte1")
            `TB_CHECK_EQ(beat1[(120-64)*8 +: 8], 8'h01, "top production SPEC product byte0")
            `TB_CHECK_EQ(beat1[(121-64)*8 +: 8], 8'hf1, "top production SPEC product byte1")
            spec_status_byte1 = beat1[(123-64)*8 +: 8];
            `TB_CHECK((spec_status_byte1 & 8'h01) != 8'd0, "top production SPEC FFT-only status bit")
            `TB_CHECK((spec_status_byte1 & 8'h02) != 8'd0, "top production SPEC XFFT configured status bit")
            `TB_CHECK_EQ(beat2[0*8 +: 8], 8'h00, "top production SPEC taps low")
            `TB_CHECK_EQ(beat2[1*8 +: 8], 8'h00, "top production SPEC taps high")
        end
    endtask

    task automatic run_production_spec_cmac;
        reg [31:0] rd;
        begin
            reset_dut();
            axi_write(16'h0020, 32'h0000_0002);
            axi_write(16'h0008, 32'd0);
            axi_write(32'h0000_b000, 32'h0000_0016);
            axi_write(32'h0000_d008, 32'd1);
            axi_write(32'h0000_d00c, 32'd2);
            axi_write(32'h0000_d010, 32'd100_000_000);
            axi_write(32'h0000_d014, 32'd2);
            axi_write(32'h0000_d018, 32'd31_457);
            axi_write(16'h0900, 32'h0000_0003);
            axi_write(16'h000c, 32'h0000_0001);
            wait_for_state(4'd6);
            s_axis_adc_tvalid = 1'b1;
            collect_science_spec_cmac_frame();
            s_axis_adc_tvalid = 1'b0;

            axi_read(16'h0304, rd);
            `TB_CHECK(rd > 32'd0, "top production SPEC packet counter increments")
            axi_read(16'h0338, rd);
            `TB_CHECK((rd < 32'd4096) && (rd[7:0] == 8'd0), "top production SPEC chan0 is a valid 256-channel block")
            axi_write(32'h0000_b130, 32'd0);
            axi_read(32'h0000_b140, rd);
            `TB_CHECK(rd > 32'd0, "top production SPEC route 0 hit")
        end
    endtask

    initial begin
        check_default_waits_without_pps();
`ifdef T510_STAGE27H_PRODUCTION_ONLY
        run_production_spec_cmac();
`else
        run_mode(2'd0, 0, 1'b1);
        run_spec_header_capture();
        run_production_spec_cmac();
        run_mode(2'd1, 1, 1'b1);
        run_mode(2'd2, 0, 1'b1);
        run_mode(2'd3, 0, 1'b0);
`endif
        `TB_PASS("tb_t510_fengine_top_smoke")
    end

endmodule
