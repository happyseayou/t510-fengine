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
    integer spectral_i [0:15];
    integer spectral_q [0:15];
    real spectral_power [0:15];

    localparam real PI = 3.14159265358979323846;
    localparam real SPUR_POWER_RATIO_85DBC = 3.162277660168379e-9;
    localparam real DC_POWER_RATIO_75DBC = 3.162277660168379e-8;

    always #5 clk = ~clk;

    function automatic signed [15:0] s16(input [15:0] value);
        begin
            s16 = value;
        end
    endfunction

    task automatic check_ch0_quadrature(input string label);
        begin
            `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, {label, " i0 positive full scale"})
            `TB_CHECK(s16(s00_axis_tdata[31:16]) > -16'sd16 && s16(s00_axis_tdata[31:16]) < 16'sd16, {label, " q0 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[47:32]) > -16'sd16 && s16(s00_axis_tdata[47:32]) < 16'sd16, {label, " i1 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[63:48]) > 16'sd4070, {label, " q1 positive full scale"})
            `TB_CHECK(s16(s00_axis_tdata[79:64]) < -16'sd4070, {label, " i2 negative full scale"})
            `TB_CHECK(s16(s00_axis_tdata[95:80]) > -16'sd16 && s16(s00_axis_tdata[95:80]) < 16'sd16, {label, " q2 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[111:96]) > -16'sd16 && s16(s00_axis_tdata[111:96]) < 16'sd16, {label, " i3 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[127:112]) < -16'sd4070, {label, " q3 negative full scale"})
        end
    endtask

    task automatic check_ch0_negative_quadrature(input string label);
        begin
            `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, {label, " i0 positive full scale"})
            `TB_CHECK(s16(s00_axis_tdata[31:16]) > -16'sd16 && s16(s00_axis_tdata[31:16]) < 16'sd16, {label, " q0 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[47:32]) > -16'sd16 && s16(s00_axis_tdata[47:32]) < 16'sd16, {label, " i1 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[63:48]) < -16'sd4070, {label, " q1 negative full scale"})
            `TB_CHECK(s16(s00_axis_tdata[79:64]) < -16'sd4070, {label, " i2 negative full scale"})
            `TB_CHECK(s16(s00_axis_tdata[95:80]) > -16'sd16 && s16(s00_axis_tdata[95:80]) < 16'sd16, {label, " q2 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[111:96]) > -16'sd16 && s16(s00_axis_tdata[111:96]) < 16'sd16, {label, " i3 near zero"})
            `TB_CHECK(s16(s00_axis_tdata[127:112]) > 16'sd4070, {label, " q3 positive full scale"})
        end
    endtask

    task automatic capture_ch0_word(input integer base_sample);
        begin
            spectral_i[base_sample + 0] = s16(s00_axis_tdata[15:0]);
            spectral_q[base_sample + 0] = s16(s00_axis_tdata[31:16]);
            spectral_i[base_sample + 1] = s16(s00_axis_tdata[47:32]);
            spectral_q[base_sample + 1] = s16(s00_axis_tdata[63:48]);
            spectral_i[base_sample + 2] = s16(s00_axis_tdata[79:64]);
            spectral_q[base_sample + 2] = s16(s00_axis_tdata[95:80]);
            spectral_i[base_sample + 3] = s16(s00_axis_tdata[111:96]);
            spectral_q[base_sample + 3] = s16(s00_axis_tdata[127:112]);
        end
    endtask

    task automatic check_stage33_spectrum;
        integer k;
        integer n;
        real angle;
        real bin_re;
        real bin_im;
        real reference_power;
        real worst_spur_ratio;
        begin
            // DFT convention: X[k] = sum(x[n] * exp(-j*2*pi*k*n/16)).
            // Mode 2 intentionally contains the +/-60 MHz pair used to
            // predistort the measured RFDC Q path.  DC is checked separately
            // because the signed amplitude truncation is not part of this LUT
            // correction.  Every other bin is an unintended 20 MHz tooth.
            for (k = 0; k < 16; k = k + 1) begin
                bin_re = 0.0;
                bin_im = 0.0;
                for (n = 0; n < 16; n = n + 1) begin
                    angle = 2.0 * PI * k * n / 16.0;
                    bin_re = bin_re
                        + spectral_i[n] * $cos(angle)
                        + spectral_q[n] * $sin(angle);
                    bin_im = bin_im
                        + spectral_q[n] * $cos(angle)
                        - spectral_i[n] * $sin(angle);
                end
                spectral_power[k] = bin_re * bin_re + bin_im * bin_im;
            end

            reference_power = spectral_power[3];
            if (spectral_power[13] > reference_power) begin
                reference_power = spectral_power[13];
            end
            `TB_CHECK(reference_power > 0.0, "Stage 33 spectrum has a nonzero reference tone")
            `TB_CHECK(spectral_power[0] < reference_power * DC_POWER_RATIO_75DBC,
                "Stage 33 signed-truncation DC remains below -75 dBc")

            worst_spur_ratio = 0.0;
            for (k = 0; k < 16; k = k + 1) begin
                if ((k != 0) && (k != 3) && (k != 13)) begin
                    if ((spectral_power[k] / reference_power) > worst_spur_ratio) begin
                        worst_spur_ratio = spectral_power[k] / reference_power;
                    end
                    if (spectral_power[k] >= reference_power * SPUR_POWER_RATIO_85DBC) begin
                        $display("    unexpected 20 MHz tooth: bin=%0d ratio=%0e", k,
                            spectral_power[k] / reference_power);
                        `TB_CHECK(1'b0, "Stage 33 unintended 20 MHz tooth exceeds -85 dBc")
                    end
                end
            end
            $display("    Stage 33 worst unintended 20 MHz tooth = %0.2f dBc",
                10.0 * $ln(worst_spur_ratio) / $ln(10.0));
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
        .all_dac_ready(all_dac_ready)
    );

    initial begin
        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        #1;
        `TB_CHECK(all_dac_ready, "all DAC ready when tready high")
        `TB_CHECK(s00_axis_tvalid && s02_axis_tvalid && s32_axis_tvalid, "all DAC valid high")
        check_ch0_quadrature("positive Fs/4 complex rotation");

        @(posedge clk);
        #1;
        check_ch0_quadrature("quarter-cycle word wraps once per AXIS beat");

        tone_phase_step_vec[31:0] = 32'h1000_0000;
        tone_phase_epoch <= 32'd1;
        @(posedge clk);
        @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > -16'sd16 && s16(s00_axis_tdata[15:0]) < 16'sd16, "phase advances I to quadrature after four samples")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > 16'sd4070, "positive phase step advances Q positive")

        repeat (3) @(posedge clk);
        tone_phase_step_vec[31:0] = 32'h4000_0000;
        tone_phase_epoch <= 32'd2;
        @(posedge clk);
        #1;
        check_ch0_quadrature("epoch reset");

        tone_mode_vec[1:0] = 2'd1;
        tone_phase_step_vec[31:0] = 32'd0;
        tone_phase0_vec[31:0] = 32'd0;
        tone_phase_epoch <= 32'd3;
        repeat (2) @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, "constant phasor phase0=0 is positive I")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > -16'sd16 && s16(s00_axis_tdata[31:16]) < 16'sd16, "constant phasor phase0=0 has Q near zero")
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
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > -16'sd16 && s16(s00_axis_tdata[15:0]) < 16'sd16, "constant phasor phase0=90 has I near zero")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > 16'sd4070, "constant phasor phase0=90 is positive Q")

        tone_mode_vec[1:0] = 2'd0;
        tone_phase0_vec[31:0] = 32'd0;
        tone_phase_step_vec[31:0] = 32'hc000_0000;
        tone_phase_epoch <= 32'd5;
        @(posedge clk);
        #1;
        check_ch0_negative_quadrature("negative Fs/4 complex rotation");

        tone_mode_vec[1:0] = 2'd2;
        tone_phase_step_vec[31:0] = 32'h4000_0000;
        tone_phase_epoch <= 32'd6;
        @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, "Stage 33 Q-advance keeps i0 at positive full scale")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) < -16'sd4070, "Stage 33 Q-advance shifts q0 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[63:48]) > -16'sd16 && s16(s00_axis_tdata[63:48]) < 16'sd16, "Stage 33 Q-advance shifts q1 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[95:80]) > 16'sd4070, "Stage 33 Q-advance shifts q2 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[127:112]) > -16'sd16 && s16(s00_axis_tdata[127:112]) < 16'sd16, "Stage 33 Q-advance shifts q3 by exactly one sample")

        tone_mode_vec[1:0] = 2'd3;
        tone_phase_epoch <= 32'd7;
        @(posedge clk);
        #1;
        `TB_CHECK(s16(s00_axis_tdata[15:0]) > 16'sd4070, "Stage 33 Q-retard keeps i0 at positive full scale")
        `TB_CHECK(s16(s00_axis_tdata[31:16]) > 16'sd4070, "Stage 33 Q-retard shifts q0 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[63:48]) > -16'sd16 && s16(s00_axis_tdata[63:48]) < 16'sd16, "Stage 33 Q-retard shifts q1 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[95:80]) < -16'sd4070, "Stage 33 Q-retard shifts q2 by exactly one sample")
        `TB_CHECK(s16(s00_axis_tdata[127:112]) > -16'sd16 && s16(s00_axis_tdata[127:112]) < 16'sd16, "Stage 33 Q-retard shifts q3 by exactly one sample")

        // At 320 MS/s, -60 MHz is phase step -3/16 = 0xd0000000.
        // Four AXIS beats contain the complete 16-sample period whose errors
        // can only land on the observed 20 MHz comb grid.
        tone_mode_vec[1:0] = 2'd2;
        tone_amplitude_vec[15:0] = 16'd8192;
        tone_phase_step_vec[31:0] = 32'hd000_0000;
        tone_phase0_vec[31:0] = 32'd0;
        tone_phase_epoch <= 32'd8;
        @(posedge clk);
        #1;
        capture_ch0_word(0);
        @(posedge clk);
        #1;
        capture_ch0_word(4);
        @(posedge clk);
        #1;
        capture_ch0_word(8);
        @(posedge clk);
        #1;
        capture_ch0_word(12);
        check_stage33_spectrum();

        tone_enable_mask = 8'hff;
        tone_amplitude_vec = {8{16'd4096}};
        tone_phase_step_vec = {8{32'h4000_0000}};
        tone_phase0_vec = 256'd0;
        tone_mode_vec = 16'd0;
        tone_phase_epoch <= 32'd9;
        @(posedge clk);
        #1;
        check_ch0_quadrature("eight-channel synchronized positive sequence");
        `TB_CHECK_EQ(s02_axis_tdata, s00_axis_tdata, "channel 1 phase synchronized")
        `TB_CHECK_EQ(s10_axis_tdata, s00_axis_tdata, "channel 2 phase synchronized")
        `TB_CHECK_EQ(s12_axis_tdata, s00_axis_tdata, "channel 3 phase synchronized")
        `TB_CHECK_EQ(s20_axis_tdata, s00_axis_tdata, "channel 4 phase synchronized")
        `TB_CHECK_EQ(s22_axis_tdata, s00_axis_tdata, "channel 5 phase synchronized")
        `TB_CHECK_EQ(s30_axis_tdata, s00_axis_tdata, "channel 6 phase synchronized")
        `TB_CHECK_EQ(s32_axis_tdata, s00_axis_tdata, "channel 7 phase synchronized")

        tone_enable_mask = 8'ha5;
        #1;
        `TB_CHECK(s00_axis_tdata != 128'd0 && s10_axis_tdata != 128'd0 && s22_axis_tdata != 128'd0 && s32_axis_tdata != 128'd0, "enabled DAC channels keep data")
        `TB_CHECK_EQ(s02_axis_tdata, 128'd0, "disabled DAC channel 1 drives zero")
        `TB_CHECK_EQ(s12_axis_tdata, 128'd0, "disabled DAC channel 3 drives zero")
        `TB_CHECK_EQ(s20_axis_tdata, 128'd0, "disabled DAC channel 4 drives zero")
        `TB_CHECK_EQ(s30_axis_tdata, 128'd0, "disabled DAC channel 6 drives zero")

        tone_enable_mask = 8'h00;
        repeat (2) @(posedge clk);
        #1;
        `TB_CHECK_EQ(s00_axis_tdata, 128'd0, "disabled DAC channel drives zero")
        `TB_PASS("tb_t510_dac_loopback_source")
    end

endmodule
