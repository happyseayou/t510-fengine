`include "tb_common.svh"

module tb_t510_fengine_top_smoke;

    localparam [31:0] START_TUSER = 32'd64;
    localparam [63:0] START_SAMPLE0 = 64'h0000_0001_0000_0100;
    localparam [63:0] EXPECTED_PACKET_SAMPLE0 = START_SAMPLE0 + 64'd4;

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
    logic [255:0] s_axis_adc_tdata = 256'd0;
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
    wire          irq;
    integer       adc_beat_idx = 0;

    always #5 clk = ~clk;

    function automatic [255:0] make_sample(input integer beat);
        begin
            make_sample = {
                64'h3000_0000_0000_0003 + beat,
                64'h3000_0000_0000_0002 + beat,
                64'h3000_0000_0000_0001 + beat,
                64'h3000_0000_0000_0000 + beat
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
        .s_axis_preview_tdata0(s_axis_adc_tdata),
        .s_axis_preview_tdata1(s_axis_adc_tdata),
        .s_axis_preview_tdata2(s_axis_adc_tdata),
        .s_axis_preview_tdata3(s_axis_adc_tdata),
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
        .tx_link_status_flags(32'h0000_0002),
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
        begin
            word0 = 64'd0;
            word1 = 64'd0;
            word5 = 64'd0;
            seen = 0;
            timeout = 0;
            while ((seen < 6) && (timeout < 2200)) begin
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
                    `TB_CHECK_EQ(word0, 64'h0002_1000_0000_0002, "top TIME frame dst/src MAC")
                end else begin
                    `TB_CHECK_EQ(word0, 64'h0002_0a00_0000_0002, "top SPEC frame dst/src MAC")
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
            `TB_CHECK_EQ(rd, EXPECTED_PACKET_SAMPLE0[31:0], "top captured SPEC sample0 low")
            axi_read(16'h03a4, rd);
            `TB_CHECK_EQ(rd, EXPECTED_PACKET_SAMPLE0[63:32], "top captured SPEC sample0 high")
            axi_read(16'h03b8, rd);
            `TB_CHECK_EQ(rd, 32'h0008_0000, "top captured SPEC layout word7 low")
            axi_read(16'h03bc, rd);
            `TB_CHECK_EQ(rd, 32'h0040_0004, "top captured SPEC layout word7 high")
            axi_read(16'h0904, rd);
            `TB_CHECK(rd[1], "top PFB config valid")
            axi_read(16'hb004, rd);
            `TB_CHECK(rd[1], "top TX dry-run active")
            `TB_CHECK_EQ(rd[0], 1'b0, "top TX link remains down in preflight")
            axi_read(16'hb040, rd);
            `TB_CHECK_EQ(rd, 32'h0000_0002, "top captured frame word0 low")
            axi_read(16'hb044, rd);
            `TB_CHECK_EQ(rd, 32'h0002_0a00, "top captured frame word0 high")
            axi_read(16'h07a0, rd);
            `TB_CHECK_EQ(rd, EXPECTED_PACKET_SAMPLE0[31:0], "top witness SPEC sample0 low")
            axi_read(16'h07a4, rd);
            `TB_CHECK_EQ(rd, EXPECTED_PACKET_SAMPLE0[63:32], "top witness SPEC sample0 high")
            axi_read(16'h07c0, rd);
            `TB_CHECK_EQ(rd, 32'd8192, "top witness payload bytes")
            axi_read(16'hd000, rd);
            `TB_CHECK_EQ(rd, 32'h0002_0080, "top witness buffer word0 low")
            axi_read(16'hd004, rd);
            `TB_CHECK_EQ(rd, 32'h5435_3130, "top witness buffer word0 high")
        end
    endtask

    initial begin
        check_default_waits_without_pps();
        run_mode(2'd0, 0, 1'b1);
        run_spec_header_capture();
        run_mode(2'd1, 1, 1'b1);
        run_mode(2'd2, 0, 1'b1);
        run_mode(2'd3, 0, 1'b0);
        `TB_PASS("tb_t510_fengine_top_smoke")
    end

endmodule
