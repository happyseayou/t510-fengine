`include "tb_common.svh"

module tb_t510_dac_loopback_source;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [7:0] tone_enable_mask = 8'h01;
    logic [127:0] tone_amplitude_vec = {{7{16'd0}}, 16'd4096};
    logic [255:0] tone_phase_step_vec = {{7{32'd0}}, 32'h4000_0000};
    logic [255:0] tone_phase0_vec = 256'd0;
    logic [255:0] tone_phase_inject_vec = 256'd0;
    logic [15:0] tone_mode_vec = 16'd0;
    logic [31:0] tone_phase_epoch = 32'd0;
    wire [127:0] s00_axis_tdata;
    wire [127:0] s02_axis_tdata;
    wire [127:0] s10_axis_tdata;
    wire [127:0] s12_axis_tdata;
    wire [127:0] s20_axis_tdata;
    wire [127:0] s22_axis_tdata;
    wire [127:0] s30_axis_tdata;
    wire [127:0] s32_axis_tdata;
    wire s00_axis_tvalid;
    wire s02_axis_tvalid;
    wire s10_axis_tvalid;
    wire s12_axis_tvalid;
    wire s20_axis_tvalid;
    wire s22_axis_tvalid;
    wire s30_axis_tvalid;
    wire s32_axis_tvalid;
    wire all_dac_ready;
    wire [31:0] audit_phase_epoch_seen;
    wire [31:0] audit_ch0_phase_acc;
    wire [31:0] audit_ch0_phase_step;
    wire [31:0] audit_ch0_phase0;
    wire [31:0] audit_ch0_mode;

    always #5 clk = ~clk;

    function automatic signed [15:0] s16(input [15:0] value);
        begin
            s16 = value;
        end
    endfunction

    task automatic check_ch0_quadrature(input string label);
        begin
            `TB_CHECK(s16(s00_axis_tdata[15:0]) > -16'sd16 && s16(s00_axis_tdata[15:0]) < 16'sd16, {label, " i0 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[31:16]) > 16'sd4070, {label, " q0 positive full scale"})
            `TB_CHECK(s16(s00_axis_tdata[47:32]) > 16'sd4070, {label, " i1 positive full scale"})
            `TB_CHECK(s16(s00_axis_tdata[63:48]) > -16'sd16 && s16(s00_axis_tdata[63:48]) < 16'sd16, {label, " q1 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[79:64]) > -16'sd16 && s16(s00_axis_tdata[79:64]) < 16'sd16, {label, " i2 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[95:80]) < -16'sd4070, {label, " q2 negative full scale"})
            `TB_CHECK(s16(s00_axis_tdata[111:96]) < -16'sd4070, {label, " i3 negative full scale"})
            `TB_CHECK(s16(s00_axis_tdata[127:112]) > -16'sd16 && s16(s00_axis_tdata[127:112]) < 16'sd16, {label, " q3 near zero"})
        end
    endtask

    t510_dac_loopback_source dut (
        .clk(clk),
        .rst_n(rst_n),
        .tone_enable_mask(tone_enable_mask),
        .tone_amplitude_vec(tone_amplitude_vec),
        .tone_phase_step_vec(tone_phase_step_vec),
        .tone_phase0_vec(tone_phase0_vec),
        .tone_phase_inject_vec(tone_phase_inject_vec),
        .tone_mode_vec(tone_mode_vec),
        .tone_phase_epoch(tone_phase_epoch),
        .s00_axis_tdata(s00_axis_tdata),
        .s00_axis_tready(1'b1),
        .s00_axis_tvalid(s00_axis_tvalid),
        .s02_axis_tdata(s02_axis_tdata),
        .s02_axis_tready(1'b1),
        .s02_axis_tvalid(s02_axis_tvalid),
        .s10_axis_tdata(s10_axis_tdata),
        .s10_axis_tready(1'b1),
        .s10_axis_tvalid(s10_axis_tvalid),
        .s12_axis_tdata(s12_axis_tdata),
        .s12_axis_tready(1'b1),
        .s12_axis_tvalid(s12_axis_tvalid),
        .s20_axis_tdata(s20_axis_tdata),
        .s20_axis_tready(1'b1),
        .s20_axis_tvalid(s20_axis_tvalid),
        .s22_axis_tdata(s22_axis_tdata),
        .s22_axis_tready(1'b1),
        .s22_axis_tvalid(s22_axis_tvalid),
        .s30_axis_tdata(s30_axis_tdata),
        .s30_axis_tready(1'b1),
        .s30_axis_tvalid(s30_axis_tvalid),
        .s32_axis_tdata(s32_axis_tdata),
        .s32_axis_tready(1'b1),
        .s32_axis_tvalid(s32_axis_tvalid),
        .all_dac_ready(all_dac_ready),
        .audit_phase_epoch_seen(audit_phase_epoch_seen),
        .audit_ch0_phase_acc(audit_ch0_phase_acc),
        .audit_ch0_phase_step(audit_ch0_phase_step),
        .audit_ch0_phase0(audit_ch0_phase0),
        .audit_ch0_mode(audit_ch0_mode)
    );

    initial begin
        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        #1;
        `TB_CHECK(all_dac_ready, "all DAC ready when tready high")
        `TB_CHECK(s00_axis_tvalid && s02_axis_tvalid && s32_axis_tvalid, "all DAC valid high")
        `TB_CHECK_EQ(audit_phase_epoch_seen, 32'd0, "DAC audit epoch reset")
        `TB_CHECK_EQ(audit_ch0_phase_step, 32'h4000_0000, "DAC audit phase step")
        check_ch0_quadrature("reset phase");

        @(posedge clk);
        #1;
        check_ch0_quadrature("quarter-cycle word wraps once per AXIS beat");

        tone_phase_step_vec[31:0] = 32'h1000_0000;
        tone_phase_epoch <= 32'd1;
        @(posedge clk);
        @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, "phase advances by four samples per AXIS beat")

        repeat (3) @(posedge clk);
        tone_phase_step_vec[31:0] = 32'h4000_0000;
        tone_phase_epoch <= 32'd2;
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(audit_phase_epoch_seen, 32'd2, "DAC audit epoch follows reset")
        check_ch0_quadrature("epoch reset");

        tone_mode_vec[1:0] = 2'd1;
        tone_phase_step_vec[31:0] = 32'd0;
        tone_phase0_vec[31:0] = 32'd0;
        tone_phase_epoch <= 32'd3;
        repeat (2) @(posedge clk);
        #1;
        `TB_CHECK_EQ(audit_ch0_mode, 32'd1, "DAC audit mode readback")
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > -16'sd16 && s16(s00_axis_tdata[15:0]) < 16'sd16, "constant phasor i0 near zero")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > 16'sd4070, "constant phasor q0 positive")
        `TB_CHECK_EQ(s00_axis_tdata[47:32], s00_axis_tdata[15:0], "constant phasor i1 equals i0")
        `TB_CHECK_EQ(s00_axis_tdata[63:48], s00_axis_tdata[31:16], "constant phasor q1 equals q0")
        `TB_CHECK_EQ(s00_axis_tdata[79:64], s00_axis_tdata[15:0], "constant phasor i2 equals i0")
        `TB_CHECK_EQ(s00_axis_tdata[95:80], s00_axis_tdata[31:16], "constant phasor q2 equals q0")
        `TB_CHECK_EQ(s00_axis_tdata[111:96], s00_axis_tdata[15:0], "constant phasor i3 equals i0")
        `TB_CHECK_EQ(s00_axis_tdata[127:112], s00_axis_tdata[31:16], "constant phasor q3 equals q0")

        tone_phase0_vec[31:0] = 32'h4000_0000;
        tone_phase_epoch <= 32'd4;
        @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, "constant phasor phase0 moves I positive")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > -16'sd16 && s16(s00_axis_tdata[31:16]) < 16'sd16, "constant phasor phase0 moves Q near zero")

        tone_enable_mask = 8'h00;
        repeat (2) @(posedge clk);
        #1;
        `TB_CHECK_EQ(s00_axis_tdata, 128'd0, "disabled DAC channel drives zero")
        `TB_PASS("tb_t510_dac_loopback_source")
    end

endmodule
