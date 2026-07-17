`timescale 1ns/1ps
`include "tb_common.svh"

module t510_fengine_xfft_4096_lane (
    input  wire        aclk,
    input  wire        aresetn,
    input  wire [15:0] s_axis_config_tdata,
    input  wire        s_axis_config_tvalid,
    output wire        s_axis_config_tready,
    input  wire [31:0] s_axis_data_tdata,
    input  wire        s_axis_data_tvalid,
    output wire        s_axis_data_tready,
    input  wire        s_axis_data_tlast,
    output wire [31:0] m_axis_data_tdata,
    output wire [23:0] m_axis_data_tuser,
    output wire        m_axis_data_tvalid,
    input  wire        m_axis_data_tready,
    output wire        m_axis_data_tlast,
    output wire [7:0]  m_axis_status_tdata,
    output wire        m_axis_status_tvalid,
    input  wire        m_axis_status_tready,
    output wire        event_frame_started,
    output wire        event_tlast_unexpected,
    output wire        event_tlast_missing,
    output wire        event_fft_overflow,
    output wire        event_status_channel_halt,
    output wire        event_data_in_channel_halt,
    output wire        event_data_out_channel_halt
);
    logic config_valid_seen = 1'b0;
    logic config_ready_reg = 1'b0;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            config_valid_seen <= 1'b0;
            config_ready_reg <= 1'b0;
        end else if (!s_axis_config_tvalid) begin
            config_valid_seen <= 1'b0;
            config_ready_reg <= 1'b0;
        end else begin
            config_ready_reg <= config_valid_seen;
            config_valid_seen <= 1'b1;
        end
    end

    assign s_axis_config_tready = config_ready_reg;
    assign s_axis_data_tready = 1'b1;
    assign m_axis_data_tdata = s_axis_data_tdata;
    assign m_axis_data_tuser = 24'd0;
    assign m_axis_data_tvalid = s_axis_data_tvalid;
    assign m_axis_data_tlast = s_axis_data_tlast;
    assign m_axis_status_tdata = s_axis_config_tdata[7:0];
    assign m_axis_status_tvalid = s_axis_config_tvalid && s_axis_config_tready;
    assign event_frame_started = s_axis_data_tvalid && s_axis_data_tready;
    assign event_tlast_unexpected = 1'b0;
    assign event_tlast_missing = 1'b0;
    assign event_fft_overflow = 1'b0;
    assign event_status_channel_halt = m_axis_status_tvalid && !m_axis_status_tready;
    assign event_data_in_channel_halt = 1'b0;
    assign event_data_out_channel_halt = m_axis_data_tvalid && !m_axis_data_tready;
endmodule

module tb_xfft_8lane_config_wrapper;
    logic clk = 1'b0;
    always #1.538 clk = ~clk;

    logic [255:0] cfg_data = 256'd0;
    logic         cfg_valid = 1'b0;
    wire          cfg_ready;
    logic [255:0] s_data = 256'd0;
    logic         s_valid = 1'b0;
    wire          s_ready;
    logic         s_last = 1'b0;
    wire [255:0] m_data;
    wire [23:0]  m_user;
    wire         m_valid;
    wire         m_last;
    wire [7:0]   m_status_data;
    wire         m_status_valid;
    wire         event_frame_started;
    wire         event_tlast_unexpected;
    wire         event_tlast_missing;
    wire         event_fft_overflow;
    wire         event_status_channel_halt;
    wire         event_data_in_channel_halt;
    wire         event_data_out_channel_halt;
    integer lane_idx;

    t510_fengine_xfft_4096_8lane_streaming dut (
        .aclk(clk),
        .aresetn(1'b1),
        .s_axis_config_tdata(cfg_data),
        .s_axis_config_tvalid(cfg_valid),
        .s_axis_config_tready(cfg_ready),
        .s_axis_data_tdata(s_data),
        .s_axis_data_tvalid(s_valid),
        .s_axis_data_tready(s_ready),
        .s_axis_data_tlast(s_last),
        .m_axis_data_tdata(m_data),
        .m_axis_data_tuser(m_user),
        .m_axis_data_tvalid(m_valid),
        .m_axis_data_tready(1'b1),
        .m_axis_data_tlast(m_last),
        .m_axis_status_tdata(m_status_data),
        .m_axis_status_tvalid(m_status_valid),
        .m_axis_status_tready(1'b1),
        .event_frame_started(event_frame_started),
        .event_tlast_unexpected(event_tlast_unexpected),
        .event_tlast_missing(event_tlast_missing),
        .event_fft_overflow(event_fft_overflow),
        .event_status_channel_halt(event_status_channel_halt),
        .event_data_in_channel_halt(event_data_in_channel_halt),
        .event_data_out_channel_halt(event_data_out_channel_halt)
    );

    initial begin
        repeat (4) @(posedge clk);
        cfg_data[7:0] = 8'hff;
        for (lane_idx = 0; lane_idx < 8; lane_idx = lane_idx + 1) begin
            cfg_data[(8 + lane_idx*12) +: 12] = 12'h550 + lane_idx[11:0];
        end
        cfg_valid = 1'b1;
        #1;
        `TB_CHECK_EQ(cfg_data[19:8], 12'h550, "wrapper test drives lane0 12-bit scale schedule")
        `TB_CHECK_EQ(cfg_data[103:92], 12'h557, "wrapper test drives lane7 12-bit scale schedule")
        `TB_CHECK_EQ(dut.gen_lane_xfft[0].lane_config_tdata[12:1], 12'h550, "lane0 wrapper uses 12-bit scale schedule")
        `TB_CHECK_EQ(dut.gen_lane_xfft[7].lane_config_tdata[12:1], 12'h557, "lane7 wrapper uses 12-bit scale schedule")
        @(posedge clk);
        `TB_CHECK(!cfg_ready, "8-lane XFFT wrapper holds config valid through delayed lane ready")
        repeat (8) begin
            @(posedge clk);
            if (cfg_ready) begin
                cfg_valid = 1'b0;
                break;
            end
        end
        `TB_CHECK(cfg_ready, "8-lane XFFT config handshake completes when lane ready depends on valid");
        repeat (2) @(posedge clk);
        s_data = {8{32'h0001_ffff}};
        s_last = 1'b1;
        s_valid = 1'b1;
        @(posedge clk);
        `TB_CHECK(s_ready, "8-lane XFFT data ready after config");
        `TB_CHECK(m_valid, "8-lane XFFT output valid follows lane outputs");
        `TB_CHECK(m_last, "8-lane XFFT output last follows lane outputs");
        s_valid = 1'b0;
        s_last = 1'b0;
        repeat (2) @(posedge clk);
        $display("CHECK PASSED tb_xfft_8lane_config_wrapper");
        $finish;
    end
endmodule
