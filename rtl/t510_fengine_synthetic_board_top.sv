module t510_fengine_synthetic_board_top (
    input  wire pl_clk_p,
    input  wire pl_clk_n,
    input  wire pps_in,
    input  wire qsfp0_modprsl,
    input  wire qsfp0_intl,
    output wire qsfp0_resetl,
    output wire qsfp0_lpmode,
    output wire qsfp0_modsell,
    output wire pl_led0,
    output wire pl_led1,
    output wire pl_led2,
    output wire pl_led3
);

    wire pl_clk;

    IBUFDS u_pl_clk_ibufds (
        .I(pl_clk_p),
        .IB(pl_clk_n),
        .O(pl_clk)
    );

    logic [7:0] reset_pipe = 8'd0;
    logic [27:0] heartbeat = 28'd0;
    logic [1:0] pps_sync = 2'b00;
    logic pps_d = 1'b0;
    logic pps_seen_latched = 1'b0;
    logic [27:0] pps_age_cycles = 28'd122_880_000;
    logic [23:0] pps_blink_cycles = 24'd0;

    wire rst_n = &reset_pipe;
    wire pps_recent = pps_seen_latched && (pps_age_cycles < 28'd122_880_000);

    always_ff @(posedge pl_clk) begin
        reset_pipe <= {reset_pipe[6:0], 1'b1};
        heartbeat <= heartbeat + 28'd1;
        pps_sync <= {pps_sync[0], pps_in};
        pps_d <= pps_sync[1];
        if (pps_sync[1] && !pps_d) begin
            pps_seen_latched <= 1'b1;
            pps_age_cycles <= 28'd0;
            pps_blink_cycles <= 24'd6_144_000;
        end else begin
            if (pps_age_cycles != 28'd122_880_000) begin
                pps_age_cycles <= pps_age_cycles + 28'd1;
            end
            if (pps_blink_cycles != 24'd0) begin
                pps_blink_cycles <= pps_blink_cycles - 24'd1;
            end
        end
    end

    logic [31:0] axi_awaddr = 32'd0;
    logic axi_awvalid = 1'b0;
    wire axi_awready;
    logic [31:0] axi_wdata = 32'd0;
    logic [3:0] axi_wstrb = 4'hf;
    logic axi_wvalid = 1'b0;
    wire axi_wready;
    wire [1:0] axi_bresp;
    wire axi_bvalid;
    wire [31:0] axi_rdata;
    wire [1:0] axi_rresp;
    wire axi_arready;
    wire axi_rvalid;
    wire core_irq;

    localparam [1:0] AXI_IDLE  = 2'd0;
    localparam [1:0] AXI_ISSUE = 2'd1;
    localparam [1:0] AXI_WAIT  = 2'd2;
    localparam [1:0] AXI_DONE  = 2'd3;

    logic [1:0] axi_boot_state = AXI_IDLE;
    logic [2:0] axi_boot_index = 3'd0;

    function automatic [31:0] boot_awaddr(input [2:0] index);
        begin
            case (index)
                3'd0: boot_awaddr = 32'h0000_0004;
                3'd1: boot_awaddr = 32'h0000_0008;
                3'd2: boot_awaddr = 32'h0000_0020;
                default: boot_awaddr = 32'h0000_000c;
            endcase
        end
    endfunction

    function automatic [31:0] boot_wdata(input [2:0] index);
        begin
            case (index)
                3'd0: boot_wdata = 32'h0000_0001;
                3'd1: boot_wdata = 32'h0000_0001;
                3'd2: boot_wdata = 32'h0000_0002;
                default: boot_wdata = 32'h0000_0001;
            endcase
        end
    endfunction

    always_ff @(posedge pl_clk) begin
        if (!rst_n) begin
            axi_boot_state <= AXI_IDLE;
            axi_boot_index <= 3'd0;
            axi_awaddr <= 32'd0;
            axi_awvalid <= 1'b0;
            axi_wdata <= 32'd0;
            axi_wvalid <= 1'b0;
        end else begin
            case (axi_boot_state)
                AXI_IDLE: begin
                    axi_boot_index <= 3'd0;
                    axi_awvalid <= 1'b0;
                    axi_wvalid <= 1'b0;
                    axi_boot_state <= AXI_ISSUE;
                end

                AXI_ISSUE: begin
                    axi_awaddr <= boot_awaddr(axi_boot_index);
                    axi_wdata <= boot_wdata(axi_boot_index);
                    axi_awvalid <= 1'b1;
                    axi_wvalid <= 1'b1;
                    axi_boot_state <= AXI_WAIT;
                end

                AXI_WAIT: begin
                    // AW is a one-cycle pulse. W remains asserted until the
                    // simple AXI-Lite slave returns BVALID for this write.
                    axi_awvalid <= 1'b0;
                    if (axi_bvalid) begin
                        axi_wvalid <= 1'b0;
                        if (axi_boot_index == 3'd3) begin
                            axi_boot_state <= AXI_DONE;
                        end else begin
                            axi_boot_index <= axi_boot_index + 2'd1;
                            axi_boot_state <= AXI_ISSUE;
                        end
                    end
                end

                default: begin
                    axi_awvalid <= 1'b0;
                    axi_wvalid <= 1'b0;
                end
            endcase
        end
    end

    logic [63:0] test_sample_counter = 64'd0;
    logic [7:0] test_frame_counter = 8'd0;
    wire adc_test_tready;
    function automatic [255:0] make_preview_subsample(input [15:0] sample_base);
        begin
            make_preview_subsample = {
                sample_base + 16'd7, ~(sample_base + 16'd7),
                sample_base + 16'd6, ~(sample_base + 16'd6),
                sample_base + 16'd5, ~(sample_base + 16'd5),
                sample_base + 16'd4, ~(sample_base + 16'd4),
                sample_base + 16'd3, ~(sample_base + 16'd3),
                sample_base + 16'd2, ~(sample_base + 16'd2),
                sample_base + 16'd1, ~(sample_base + 16'd1),
                sample_base + 16'd0, ~(sample_base + 16'd0)
            };
        end
    endfunction

    wire [1023:0] adc_test_tdata = {
        make_preview_subsample(test_sample_counter[15:0] + 16'd24),
        make_preview_subsample(test_sample_counter[15:0] + 16'd16),
        make_preview_subsample(test_sample_counter[15:0] + 16'd8),
        make_preview_subsample(test_sample_counter[15:0])
    };
    wire [31:0] adc_test_tuser = test_sample_counter[31:0];
    wire adc_test_tvalid = rst_n;
    wire adc_test_tlast = (test_frame_counter == 8'hff);

    wire [63:0] core_tx_tdata;
    wire [7:0] core_tx_tkeep;
    wire core_tx_tvalid;
    wire core_tx_tlast;
    logic tx_activity_latched = 1'b0;
    logic [31:0] tx_word_count = 32'd0;
    logic [31:0] tx_packet_count = 32'd0;

    always_ff @(posedge pl_clk) begin
        if (!rst_n) begin
            test_sample_counter <= 64'd0;
            test_frame_counter <= 8'd0;
            tx_activity_latched <= 1'b0;
            tx_word_count <= 32'd0;
            tx_packet_count <= 32'd0;
        end else begin
            if (adc_test_tvalid && adc_test_tready) begin
                test_sample_counter <= test_sample_counter + 64'd1;
                test_frame_counter <= test_frame_counter + 8'd1;
            end

            if (core_tx_tvalid) begin
                tx_activity_latched <= 1'b1;
                tx_word_count <= tx_word_count + 32'd1;
                if (core_tx_tlast) begin
                    tx_packet_count <= tx_packet_count + 32'd1;
                end
            end
        end
    end

    t510_fengine_top u_core (
        .clk(pl_clk),
        .rst_n(rst_n),
        .ctrl_clk(pl_clk),
        .ctrl_rst_n(rst_n),
        .pps_in(pps_in),
        .ref_lock_in(1'b1),
        .rfdc_ready_in(1'b1),
        .s_axi_awaddr(axi_awaddr),
        .s_axi_awvalid(axi_awvalid),
        .s_axi_awready(axi_awready),
        .s_axi_wdata(axi_wdata),
        .s_axi_wstrb(axi_wstrb),
        .s_axi_wvalid(axi_wvalid),
        .s_axi_wready(axi_wready),
        .s_axi_bresp(axi_bresp),
        .s_axi_bvalid(axi_bvalid),
        .s_axi_bready(1'b1),
        .s_axi_araddr(32'd0),
        .s_axi_arvalid(1'b0),
        .s_axi_arready(axi_arready),
        .s_axi_rdata(axi_rdata),
        .s_axi_rresp(axi_rresp),
        .s_axi_rvalid(axi_rvalid),
        .s_axi_rready(1'b1),
        .s_axis_adc_tdata(adc_test_tdata),
        .s_axis_adc_tuser(adc_test_tuser),
        .s_axis_adc_sample0(test_sample_counter << 2),
        .s_axis_adc_tvalid(adc_test_tvalid),
        .s_axis_adc_tlast(adc_test_tlast),
        .s_axis_adc_tready(adc_test_tready),
        .s_axis_preview_tdata0(adc_test_tdata[255:0]),
        .s_axis_preview_tdata1(adc_test_tdata[511:256]),
        .s_axis_preview_tdata2(adc_test_tdata[767:512]),
        .s_axis_preview_tdata3(adc_test_tdata[1023:768]),
        .s_axis_preview_sample0(test_sample_counter << 2),
        .s_axis_preview_tvalid(adc_test_tvalid && adc_test_tready),
        .s_axis_raw_witness_tdata0(adc_test_tdata[255:0]),
        .s_axis_raw_witness_tdata1(adc_test_tdata[511:256]),
        .s_axis_raw_witness_tdata2(adc_test_tdata[767:512]),
        .s_axis_raw_witness_tdata3(adc_test_tdata[1023:768]),
        .s_axis_raw_witness_sample0(test_sample_counter << 2),
        .s_axis_raw_witness_tvalid(adc_test_tvalid && adc_test_tready),
        .rfdc_status_flags({25'd0, pps_recent, pps_sync[1], pps_seen_latched, rst_n, 1'b1, 1'b1, adc_test_tready}),
        .rfdc_sample_count(test_sample_counter),
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
        .m_axis_tx_tdata(core_tx_tdata),
        .m_axis_tx_tkeep(core_tx_tkeep),
        .m_axis_tx_tvalid(core_tx_tvalid),
        .m_axis_tx_tlast(core_tx_tlast),
        .m_axis_tx_tready(1'b1),
        .cmac_tx_clk(pl_clk),
        .cmac_tx_rst_n(rst_n),
        .cmac_tx_axis_tdata(),
        .cmac_tx_axis_tkeep(),
        .cmac_tx_axis_tvalid(),
        .cmac_tx_axis_tlast(),
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
        .tx_link_status_flags(32'h0000_101d),
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
        .irq(core_irq)
    );

    assign qsfp0_resetl = 1'b1;
    assign qsfp0_lpmode = 1'b0;
    assign qsfp0_modsell = 1'b0;

    assign pl_led0 = rst_n;
    assign pl_led1 = (pps_blink_cycles != 24'd0);
    assign pl_led2 = pps_recent;
    assign pl_led3 = core_irq | !pps_recent;

endmodule
