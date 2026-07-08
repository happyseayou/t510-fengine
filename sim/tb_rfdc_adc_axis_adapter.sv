`include "tb_common.svh"

module tb_rfdc_adc_axis_adapter;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [63:0] d [0:15];
    logic [15:0] valid = 16'h0000;
    logic [15:0] active_mask = 16'hffff;
    logic diag_force_zero = 1'b0;
    logic diag_force_hold = 1'b0;
    logic [7:0] diag_channel_mask = 8'hff;
    wire [15:0] ready;
    wire [1023:0] m_axis_tdata;
    wire [31:0] m_axis_tuser;
    wire [63:0] m_axis_sample0;
    wire m_axis_tvalid;
    wire m_axis_tlast;
    logic m_axis_tready = 1'b1;
    wire [255:0] preview_tdata0;
    wire [255:0] preview_tdata1;
    wire [255:0] preview_tdata2;
    wire [255:0] preview_tdata3;
    wire [63:0] preview_sample0;
    wire preview_tvalid;
    wire [255:0] raw_preview_tdata0;
    wire [255:0] raw_preview_tdata1;
    wire [255:0] raw_preview_tdata2;
    wire [255:0] raw_preview_tdata3;
    wire [63:0] raw_preview_sample0;
    wire raw_preview_tvalid;
    wire all_adc_valid;
    wire [15:0] current_valid_mask;
    wire [15:0] seen_valid_mask;
    wire [63:0] sample_count;
    wire [31:0] dropped_count;
    logic [31:0] fire_count = 32'd0;
    logic [1023:0] last_fire_tdata = 1024'd0;
    logic [31:0] last_fire_tuser = 32'd0;
    logic last_fire_tlast = 1'b0;

    always #5 clk = ~clk;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            fire_count <= 32'd0;
            last_fire_tdata <= 1024'd0;
            last_fire_tuser <= 32'd0;
            last_fire_tlast <= 1'b0;
        end else if (m_axis_tvalid && m_axis_tready) begin
            fire_count <= fire_count + 32'd1;
            last_fire_tdata <= m_axis_tdata;
            last_fire_tuser <= m_axis_tuser;
            last_fire_tlast <= m_axis_tlast;
        end
    end

    rfdc_adc_axis_adapter dut (
        .clk(clk),
        .rst_n(rst_n),
        .m00_axis_tdata(d[0]),
        .m00_axis_tready(ready[0]),
        .m00_axis_tvalid(valid[0]),
        .m01_axis_tdata(d[1]),
        .m01_axis_tready(ready[1]),
        .m01_axis_tvalid(valid[1]),
        .m02_axis_tdata(d[2]),
        .m02_axis_tready(ready[2]),
        .m02_axis_tvalid(valid[2]),
        .m03_axis_tdata(d[3]),
        .m03_axis_tready(ready[3]),
        .m03_axis_tvalid(valid[3]),
        .m10_axis_tdata(d[4]),
        .m10_axis_tready(ready[4]),
        .m10_axis_tvalid(valid[4]),
        .m11_axis_tdata(d[5]),
        .m11_axis_tready(ready[5]),
        .m11_axis_tvalid(valid[5]),
        .m12_axis_tdata(d[6]),
        .m12_axis_tready(ready[6]),
        .m12_axis_tvalid(valid[6]),
        .m13_axis_tdata(d[7]),
        .m13_axis_tready(ready[7]),
        .m13_axis_tvalid(valid[7]),
        .m20_axis_tdata(d[8]),
        .m20_axis_tready(ready[8]),
        .m20_axis_tvalid(valid[8]),
        .m21_axis_tdata(d[9]),
        .m21_axis_tready(ready[9]),
        .m21_axis_tvalid(valid[9]),
        .m22_axis_tdata(d[10]),
        .m22_axis_tready(ready[10]),
        .m22_axis_tvalid(valid[10]),
        .m23_axis_tdata(d[11]),
        .m23_axis_tready(ready[11]),
        .m23_axis_tvalid(valid[11]),
        .m30_axis_tdata(d[12]),
        .m30_axis_tready(ready[12]),
        .m30_axis_tvalid(valid[12]),
        .m31_axis_tdata(d[13]),
        .m31_axis_tready(ready[13]),
        .m31_axis_tvalid(valid[13]),
        .m32_axis_tdata(d[14]),
        .m32_axis_tready(ready[14]),
        .m32_axis_tvalid(valid[14]),
        .m33_axis_tdata(d[15]),
        .m33_axis_tready(ready[15]),
        .m33_axis_tvalid(valid[15]),
        .active_port_mask(active_mask),
        .diag_force_zero(diag_force_zero),
        .diag_force_hold(diag_force_hold),
        .diag_channel_mask(diag_channel_mask),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tuser(m_axis_tuser),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready),
        .m_preview_tdata0(preview_tdata0),
        .m_preview_tdata1(preview_tdata1),
        .m_preview_tdata2(preview_tdata2),
        .m_preview_tdata3(preview_tdata3),
        .m_preview_sample0(preview_sample0),
        .m_preview_tvalid(preview_tvalid),
        .m_raw_preview_tdata0(raw_preview_tdata0),
        .m_raw_preview_tdata1(raw_preview_tdata1),
        .m_raw_preview_tdata2(raw_preview_tdata2),
        .m_raw_preview_tdata3(raw_preview_tdata3),
        .m_raw_preview_sample0(raw_preview_sample0),
        .m_raw_preview_tvalid(raw_preview_tvalid),
        .all_adc_valid(all_adc_valid),
        .current_valid_mask(current_valid_mask),
        .seen_valid_mask(seen_valid_mask),
        .sample_count(sample_count),
        .dropped_count(dropped_count)
    );

    task automatic set_low_words(input int base);
        integer i;
        logic [15:0] word0;
        logic [15:0] word1;
        logic [15:0] word2;
        logic [15:0] word3;
        begin
            for (i = 0; i < 16; i = i + 1) begin
                word0 = base + i;
                word1 = base + 16'h0100 + i;
                word2 = base + 16'h0200 + i;
                word3 = base + 16'h0300 + i;
                d[i] = {word3, word2, word1, word0};
            end
        end
    endtask

    initial begin
        int fire_before;

        set_low_words(16'h1000);
        repeat (4) @(posedge clk);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);

        `TB_CHECK_EQ(ready, 16'hffff, "adapter keeps all RFDC ports ready")
        `TB_CHECK_EQ(seen_valid_mask, 16'h0000, "seen valid mask clears on reset")
        valid <= 16'hfffe;
        @(posedge clk);
        #1;
        `TB_CHECK(!all_adc_valid, "adapter waits for all RFDC valid bits")
        `TB_CHECK(!m_axis_tvalid, "adapter output invalid when one RFDC port is invalid")
        `TB_CHECK_EQ(current_valid_mask, 16'hfffe, "current valid mask reports partial valid")
        `TB_CHECK_EQ(sample_count, 64'd0, "sample count unchanged on partial valid")
        `TB_CHECK_EQ(fire_count, 32'd0, "no output fire on partial valid")
        `TB_CHECK_EQ(seen_valid_mask, 16'hfffe, "seen valid mask accumulates partial valid")

        valid <= 16'hffff;
        @(posedge clk);
        #1;
        `TB_CHECK(all_adc_valid, "all ADC valid asserted")
        `TB_CHECK(m_axis_tvalid, "adapter emits beat when downstream ready")
        `TB_CHECK(preview_tvalid, "adapter emits full-rate preview beat")
        `TB_CHECK_EQ(fire_count, 32'd1, "first output fire count")
        `TB_CHECK_EQ(last_fire_tdata[255:0], 256'h100f_100e_100d_100c_100b_100a_1009_1008_1007_1006_1005_1004_1003_1002_1001_1000, "adapter sub0 I/Q lane packing")
        `TB_CHECK_EQ(last_fire_tdata[511:256], 256'h110f_110e_110d_110c_110b_110a_1109_1108_1107_1106_1105_1104_1103_1102_1101_1100, "adapter sub1 I/Q lane packing")
        `TB_CHECK_EQ(last_fire_tdata[767:512], 256'h120f_120e_120d_120c_120b_120a_1209_1208_1207_1206_1205_1204_1203_1202_1201_1200, "adapter sub2 I/Q lane packing")
        `TB_CHECK_EQ(last_fire_tdata[1023:768], 256'h130f_130e_130d_130c_130b_130a_1309_1308_1307_1306_1305_1304_1303_1302_1301_1300, "adapter sub3 I/Q lane packing")
        `TB_CHECK_EQ(last_fire_tuser, 32'd0, "first tuser sample count")
        `TB_CHECK_EQ(m_axis_sample0, 64'd4, "axis sample0 full-rate output advances after first beat")
        `TB_CHECK_EQ(preview_sample0, 64'd4, "preview sample0 continuous output advances after first beat")
        `TB_CHECK_EQ(preview_tdata0[31:0], 32'h1001_1000, "preview ADC0 sample lane0 I/Q")
        `TB_CHECK_EQ(preview_tdata1[31:0], 32'h1101_1100, "preview ADC0 sample lane1 I/Q")
        `TB_CHECK_EQ(seen_valid_mask, 16'hffff, "seen valid mask accumulates all valid")
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(sample_count, 64'd2, "sample count increments while valid")

        m_axis_tready <= 1'b0;
        @(posedge clk);
        #1;
        `TB_CHECK(!m_axis_tvalid, "adapter drops output when downstream not ready")
        `TB_CHECK(!m_axis_tlast, "adapter does not emit tlast on dropped output")
        `TB_CHECK_EQ(dropped_count, 32'd1, "drop count increments")
        `TB_CHECK_EQ(ready, 16'hffff, "RFDC ports still ready during drop")

        m_axis_tready <= 1'b1;
        repeat (253) @(posedge clk);
        #1;
        `TB_CHECK(m_axis_tvalid, "adapter emits beat at 256-beat boundary")
        `TB_CHECK_EQ(last_fire_tuser, 32'd255, "tlast beat sample index")
        `TB_CHECK(last_fire_tlast, "tlast asserted at 256-beat boundary")

        rst_n <= 1'b0;
        valid <= 16'h0000;
        active_mask <= 16'h0001;
        m_axis_tready <= 1'b1;
        repeat (4) @(posedge clk);
        set_low_words(16'h2000);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);
        fire_before = fire_count;
        valid <= 16'h0001;
        @(posedge clk);
        #1;
        `TB_CHECK(all_adc_valid, "single ADC0 active mask accepts m00 only")
        `TB_CHECK_EQ(fire_count, fire_before + 1, "single ADC0 mask emits output")
        `TB_CHECK_EQ(last_fire_tdata[31:0], 32'h0000_2000, "single ADC0 mask keeps sub0 I and zeros Q")
        `TB_CHECK_EQ(last_fire_tdata[287:256], 32'h0000_2100, "single ADC0 mask keeps sub1 I and zeros Q")
        `TB_CHECK_EQ(last_fire_tdata[543:512], 32'h0000_2200, "single ADC0 mask keeps sub2 I and zeros Q")
        `TB_CHECK_EQ(last_fire_tdata[799:768], 32'h0000_2300, "single ADC0 mask keeps sub3 I and zeros Q")
        `TB_CHECK_EQ(last_fire_tdata[255:32], 224'd0, "single ADC0 mask zeros inactive sub0 lanes")
        `TB_CHECK_EQ(last_fire_tdata[511:288], 224'd0, "single ADC0 mask zeros inactive sub1 lanes")
        `TB_CHECK_EQ(last_fire_tdata[767:544], 224'd0, "single ADC0 mask zeros inactive sub2 lanes")
        `TB_CHECK_EQ(last_fire_tdata[1023:800], 224'd0, "single ADC0 mask zeros inactive sub3 lanes")
        `TB_CHECK_EQ(current_valid_mask, 16'h0001, "single ADC0 current valid mask")

        active_mask <= 16'h0003;
        valid <= 16'h0001;
        @(posedge clk);
        #1;
        `TB_CHECK(!all_adc_valid, "complex ch0 mask waits for m00 and m01")
        valid <= 16'h0003;
        @(posedge clk);
        #1;
        `TB_CHECK(all_adc_valid, "complex ch0 mask accepts m00 and m01")
        `TB_CHECK_EQ(last_fire_tdata[31:0], 32'h2001_2000, "complex ch0 lower I/Q packing")
        `TB_CHECK_EQ(last_fire_tdata[287:256], 32'h2101_2100, "complex ch0 sub1 I/Q packing")

        active_mask <= 16'hffff;
        valid <= 16'hffff;
        diag_channel_mask <= 8'h01;
        set_low_words(16'h3000);
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(last_fire_tdata[31:0], 32'h3001_3000, "diagnostic channel mask keeps CH0")
        `TB_CHECK_EQ(last_fire_tdata[255:32], 224'd0, "diagnostic channel mask zeros CH1..CH7 in sub0")
        `TB_CHECK_EQ(last_fire_tdata[287:256], 32'h3101_3100, "diagnostic channel mask keeps CH0 in sub1")
        `TB_CHECK_EQ(last_fire_tdata[511:288], 224'd0, "diagnostic channel mask zeros CH1..CH7 in sub1")
        `TB_CHECK_EQ(last_fire_tdata[543:512], 32'h3201_3200, "diagnostic channel mask keeps CH0 in sub2")
        `TB_CHECK_EQ(last_fire_tdata[767:544], 224'd0, "diagnostic channel mask zeros CH1..CH7 in sub2")
        `TB_CHECK_EQ(last_fire_tdata[799:768], 32'h3301_3300, "diagnostic channel mask keeps CH0 in sub3")
        `TB_CHECK_EQ(last_fire_tdata[1023:800], 224'd0, "diagnostic channel mask zeros CH1..CH7 in sub3")
        `TB_CHECK_EQ(raw_preview_tdata0[255:224], 32'h300f_300e, "raw preview ignores diagnostic channel mask")
        `TB_CHECK_EQ(raw_preview_tdata3[255:224], 32'h330f_330e, "raw preview sub3 ignores diagnostic channel mask")

        diag_channel_mask <= 8'hff;
        diag_force_zero <= 1'b1;
        set_low_words(16'h4000);
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(last_fire_tdata, 1024'd0, "diagnostic force-zero zeros adapter output without stopping valid")
        `TB_CHECK(m_axis_tvalid, "diagnostic force-zero preserves full-rate valid")
        `TB_CHECK_EQ(raw_preview_tdata0[31:0], 32'h4001_4000, "raw preview ignores diagnostic force-zero")

        diag_force_zero <= 1'b0;
        set_low_words(16'h5000);
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(last_fire_tdata[31:0], 32'h5001_5000, "diagnostic hold seed sample")
        diag_force_hold <= 1'b1;
        set_low_words(16'h6000);
        @(posedge clk);
        #1;
        `TB_CHECK_EQ(last_fire_tdata[31:0], 32'h5001_5000, "diagnostic force-hold repeats held data")
        `TB_CHECK_EQ(raw_preview_tdata0[31:0], 32'h6001_6000, "raw preview ignores diagnostic force-hold")
        diag_force_hold <= 1'b0;
        diag_channel_mask <= 8'hff;

        `TB_PASS("tb_rfdc_adc_axis_adapter")
    end

endmodule
