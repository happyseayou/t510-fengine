module rfdc_adc_axis_adapter (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [63:0]  m00_axis_tdata,
    output wire         m00_axis_tready,
    input  wire         m00_axis_tvalid,
    input  wire [63:0]  m01_axis_tdata,
    output wire         m01_axis_tready,
    input  wire         m01_axis_tvalid,
    input  wire [63:0]  m02_axis_tdata,
    output wire         m02_axis_tready,
    input  wire         m02_axis_tvalid,
    input  wire [63:0]  m03_axis_tdata,
    output wire         m03_axis_tready,
    input  wire         m03_axis_tvalid,
    input  wire [63:0]  m10_axis_tdata,
    output wire         m10_axis_tready,
    input  wire         m10_axis_tvalid,
    input  wire [63:0]  m11_axis_tdata,
    output wire         m11_axis_tready,
    input  wire         m11_axis_tvalid,
    input  wire [63:0]  m12_axis_tdata,
    output wire         m12_axis_tready,
    input  wire         m12_axis_tvalid,
    input  wire [63:0]  m13_axis_tdata,
    output wire         m13_axis_tready,
    input  wire         m13_axis_tvalid,
    input  wire [63:0]  m20_axis_tdata,
    output wire         m20_axis_tready,
    input  wire         m20_axis_tvalid,
    input  wire [63:0]  m21_axis_tdata,
    output wire         m21_axis_tready,
    input  wire         m21_axis_tvalid,
    input  wire [63:0]  m22_axis_tdata,
    output wire         m22_axis_tready,
    input  wire         m22_axis_tvalid,
    input  wire [63:0]  m23_axis_tdata,
    output wire         m23_axis_tready,
    input  wire         m23_axis_tvalid,
    input  wire [63:0]  m30_axis_tdata,
    output wire         m30_axis_tready,
    input  wire         m30_axis_tvalid,
    input  wire [63:0]  m31_axis_tdata,
    output wire         m31_axis_tready,
    input  wire         m31_axis_tvalid,
    input  wire [63:0]  m32_axis_tdata,
    output wire         m32_axis_tready,
    input  wire         m32_axis_tvalid,
    input  wire [63:0]  m33_axis_tdata,
    output wire         m33_axis_tready,
    input  wire         m33_axis_tvalid,
    input  wire [15:0]  active_port_mask,
    output wire [255:0] m_axis_tdata,
    output wire [31:0]  m_axis_tuser,
    output wire [63:0]  m_axis_sample0,
    output wire         m_axis_tvalid,
    output wire         m_axis_tlast,
    input  wire         m_axis_tready,
    output wire [255:0] m_preview_tdata0,
    output wire [255:0] m_preview_tdata1,
    output wire [255:0] m_preview_tdata2,
    output wire [255:0] m_preview_tdata3,
    output wire [63:0]  m_preview_sample0,
    output wire         m_preview_tvalid,
    output wire         all_adc_valid,
    output wire [15:0]  current_valid_mask,
    output logic [15:0] seen_valid_mask,
    output logic [63:0] sample_count,
    output logic [31:0] dropped_count
);

    wire [15:0] effective_active_mask = (active_port_mask == 16'd0) ? 16'hffff : active_port_mask;
    wire [15:0] port_valid_mask = {
        m33_axis_tvalid, m32_axis_tvalid, m31_axis_tvalid, m30_axis_tvalid,
        m23_axis_tvalid, m22_axis_tvalid, m21_axis_tvalid, m20_axis_tvalid,
        m13_axis_tvalid, m12_axis_tvalid, m11_axis_tvalid, m10_axis_tvalid,
        m03_axis_tvalid, m02_axis_tvalid, m01_axis_tvalid, m00_axis_tvalid
    };
    wire sample_valid = ((port_valid_mask & effective_active_mask) == effective_active_mask);

    assign all_adc_valid = sample_valid;
    assign current_valid_mask = port_valid_mask;

    // RFDC AXIS cannot be allowed to backpressure the converter in this first
    // integration. If the downstream F-engine is not ready, the beat is counted
    // as dropped and RFDC remains ready.
    assign m00_axis_tready = 1'b1;
    assign m01_axis_tready = 1'b1;
    assign m02_axis_tready = 1'b1;
    assign m03_axis_tready = 1'b1;
    assign m10_axis_tready = 1'b1;
    assign m11_axis_tready = 1'b1;
    assign m12_axis_tready = 1'b1;
    assign m13_axis_tready = 1'b1;
    assign m20_axis_tready = 1'b1;
    assign m21_axis_tready = 1'b1;
    assign m22_axis_tready = 1'b1;
    assign m23_axis_tready = 1'b1;
    assign m30_axis_tready = 1'b1;
    assign m31_axis_tready = 1'b1;
    assign m32_axis_tready = 1'b1;
    assign m33_axis_tready = 1'b1;

    assign m_axis_tdata = {
        effective_active_mask[15] ? m33_axis_tdata[15:0] : 16'd0,
        effective_active_mask[14] ? m32_axis_tdata[15:0] : 16'd0,
        effective_active_mask[13] ? m31_axis_tdata[15:0] : 16'd0,
        effective_active_mask[12] ? m30_axis_tdata[15:0] : 16'd0,
        effective_active_mask[11] ? m23_axis_tdata[15:0] : 16'd0,
        effective_active_mask[10] ? m22_axis_tdata[15:0] : 16'd0,
        effective_active_mask[9]  ? m21_axis_tdata[15:0] : 16'd0,
        effective_active_mask[8]  ? m20_axis_tdata[15:0] : 16'd0,
        effective_active_mask[7]  ? m13_axis_tdata[15:0] : 16'd0,
        effective_active_mask[6]  ? m12_axis_tdata[15:0] : 16'd0,
        effective_active_mask[5]  ? m11_axis_tdata[15:0] : 16'd0,
        effective_active_mask[4]  ? m10_axis_tdata[15:0] : 16'd0,
        effective_active_mask[3]  ? m03_axis_tdata[15:0] : 16'd0,
        effective_active_mask[2]  ? m02_axis_tdata[15:0] : 16'd0,
        effective_active_mask[1]  ? m01_axis_tdata[15:0] : 16'd0,
        effective_active_mask[0]  ? m00_axis_tdata[15:0] : 16'd0
    };
    wire output_fire = sample_valid && m_axis_tready;

    assign m_axis_tuser  = sample_count[31:0];
    assign m_axis_sample0 = sample_count << 2;
    assign m_axis_tvalid = output_fire;
    assign m_axis_tlast  = output_fire && (sample_count[7:0] == 8'hff);

    function automatic [31:0] adc_complex_word(
        input [15:0] i_sample,
        input [15:0] q_sample,
        input i_active,
        input q_active
    );
        begin
            adc_complex_word = {
                q_active ? q_sample : 16'd0,
                i_active ? i_sample : 16'd0
            };
        end
    endfunction

    assign m_preview_tdata0 = {
        adc_complex_word(m32_axis_tdata[15:0], m33_axis_tdata[15:0], effective_active_mask[14], effective_active_mask[15]),
        adc_complex_word(m30_axis_tdata[15:0], m31_axis_tdata[15:0], effective_active_mask[12], effective_active_mask[13]),
        adc_complex_word(m22_axis_tdata[15:0], m23_axis_tdata[15:0], effective_active_mask[10], effective_active_mask[11]),
        adc_complex_word(m20_axis_tdata[15:0], m21_axis_tdata[15:0], effective_active_mask[8],  effective_active_mask[9]),
        adc_complex_word(m12_axis_tdata[15:0], m13_axis_tdata[15:0], effective_active_mask[6],  effective_active_mask[7]),
        adc_complex_word(m10_axis_tdata[15:0], m11_axis_tdata[15:0], effective_active_mask[4],  effective_active_mask[5]),
        adc_complex_word(m02_axis_tdata[15:0], m03_axis_tdata[15:0], effective_active_mask[2],  effective_active_mask[3]),
        adc_complex_word(m00_axis_tdata[15:0], m01_axis_tdata[15:0], effective_active_mask[0],  effective_active_mask[1])
    };
    assign m_preview_tdata1 = {
        adc_complex_word(m32_axis_tdata[31:16], m33_axis_tdata[31:16], effective_active_mask[14], effective_active_mask[15]),
        adc_complex_word(m30_axis_tdata[31:16], m31_axis_tdata[31:16], effective_active_mask[12], effective_active_mask[13]),
        adc_complex_word(m22_axis_tdata[31:16], m23_axis_tdata[31:16], effective_active_mask[10], effective_active_mask[11]),
        adc_complex_word(m20_axis_tdata[31:16], m21_axis_tdata[31:16], effective_active_mask[8],  effective_active_mask[9]),
        adc_complex_word(m12_axis_tdata[31:16], m13_axis_tdata[31:16], effective_active_mask[6],  effective_active_mask[7]),
        adc_complex_word(m10_axis_tdata[31:16], m11_axis_tdata[31:16], effective_active_mask[4],  effective_active_mask[5]),
        adc_complex_word(m02_axis_tdata[31:16], m03_axis_tdata[31:16], effective_active_mask[2],  effective_active_mask[3]),
        adc_complex_word(m00_axis_tdata[31:16], m01_axis_tdata[31:16], effective_active_mask[0],  effective_active_mask[1])
    };
    assign m_preview_tdata2 = {
        adc_complex_word(m32_axis_tdata[47:32], m33_axis_tdata[47:32], effective_active_mask[14], effective_active_mask[15]),
        adc_complex_word(m30_axis_tdata[47:32], m31_axis_tdata[47:32], effective_active_mask[12], effective_active_mask[13]),
        adc_complex_word(m22_axis_tdata[47:32], m23_axis_tdata[47:32], effective_active_mask[10], effective_active_mask[11]),
        adc_complex_word(m20_axis_tdata[47:32], m21_axis_tdata[47:32], effective_active_mask[8],  effective_active_mask[9]),
        adc_complex_word(m12_axis_tdata[47:32], m13_axis_tdata[47:32], effective_active_mask[6],  effective_active_mask[7]),
        adc_complex_word(m10_axis_tdata[47:32], m11_axis_tdata[47:32], effective_active_mask[4],  effective_active_mask[5]),
        adc_complex_word(m02_axis_tdata[47:32], m03_axis_tdata[47:32], effective_active_mask[2],  effective_active_mask[3]),
        adc_complex_word(m00_axis_tdata[47:32], m01_axis_tdata[47:32], effective_active_mask[0],  effective_active_mask[1])
    };
    assign m_preview_tdata3 = {
        adc_complex_word(m32_axis_tdata[63:48], m33_axis_tdata[63:48], effective_active_mask[14], effective_active_mask[15]),
        adc_complex_word(m30_axis_tdata[63:48], m31_axis_tdata[63:48], effective_active_mask[12], effective_active_mask[13]),
        adc_complex_word(m22_axis_tdata[63:48], m23_axis_tdata[63:48], effective_active_mask[10], effective_active_mask[11]),
        adc_complex_word(m20_axis_tdata[63:48], m21_axis_tdata[63:48], effective_active_mask[8],  effective_active_mask[9]),
        adc_complex_word(m12_axis_tdata[63:48], m13_axis_tdata[63:48], effective_active_mask[6],  effective_active_mask[7]),
        adc_complex_word(m10_axis_tdata[63:48], m11_axis_tdata[63:48], effective_active_mask[4],  effective_active_mask[5]),
        adc_complex_word(m02_axis_tdata[63:48], m03_axis_tdata[63:48], effective_active_mask[2],  effective_active_mask[3]),
        adc_complex_word(m00_axis_tdata[63:48], m01_axis_tdata[63:48], effective_active_mask[0],  effective_active_mask[1])
    };
    assign m_preview_sample0 = m_axis_sample0;
    assign m_preview_tvalid = sample_valid;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sample_count  <= 64'd0;
            dropped_count <= 32'd0;
            seen_valid_mask <= 16'd0;
        end else if (sample_valid) begin
            sample_count <= sample_count + 64'd1;
            seen_valid_mask <= seen_valid_mask | port_valid_mask;
            if (!m_axis_tready) begin
                dropped_count <= dropped_count + 32'd1;
            end
        end else begin
            seen_valid_mask <= seen_valid_mask | port_valid_mask;
        end
    end

endmodule
