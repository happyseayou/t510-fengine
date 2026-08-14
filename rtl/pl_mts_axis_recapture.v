module pl_mts_axis_recapture (
    input  wire        pl_clk,
    input  wire        adc_axis_clk,
    input  wire        dac_axis_clk,
    input  wire        pl_sysref_capture,
    output wire        user_sysref_adc,
    output wire        user_sysref_dac,
    output wire [31:0] sysref_pl_edge_count_gray,
    output wire [31:0] sysref_adc_edge_count_gray,
    output wire [31:0] sysref_dac_edge_count_gray,
    output wire [2:0]  sysref_capture_levels
);

    // The first physical-pin capture is in pl_mts_sync_clk. These registers
    // implement PG269's required recapture when PL_CLK and RFDC AXIS clocks
    // have different rates. They intentionally have no high-fanout reset.
    (* DONT_TOUCH = "TRUE", SHREG_EXTRACT = "NO" *) reg pl_sysref_level = 1'b0;
    (* DONT_TOUCH = "TRUE", SHREG_EXTRACT = "NO" *) reg adc_sysref_level = 1'b0;
    (* DONT_TOUCH = "TRUE", SHREG_EXTRACT = "NO" *) reg dac_sysref_level = 1'b0;
    reg pl_sysref_level_d = 1'b0;
    reg adc_sysref_level_d = 1'b0;
    reg dac_sysref_level_d = 1'b0;
    reg [31:0] pl_edge_count = 32'd0;
    reg [31:0] adc_edge_count = 32'd0;
    reg [31:0] dac_edge_count = 32'd0;

    always @(posedge pl_clk) begin
        pl_sysref_level <= pl_sysref_capture;
        pl_sysref_level_d <= pl_sysref_level;
        if (pl_sysref_level && !pl_sysref_level_d)
            pl_edge_count <= pl_edge_count + 32'd1;
    end

    always @(posedge adc_axis_clk) begin
        adc_sysref_level <= pl_sysref_capture;
        adc_sysref_level_d <= adc_sysref_level;
        if (adc_sysref_level && !adc_sysref_level_d)
            adc_edge_count <= adc_edge_count + 32'd1;
    end

    always @(posedge dac_axis_clk) begin
        dac_sysref_level <= pl_sysref_capture;
        dac_sysref_level_d <= dac_sysref_level;
        if (dac_sysref_level && !dac_sysref_level_d)
            dac_edge_count <= dac_edge_count + 32'd1;
    end

    assign user_sysref_adc = adc_sysref_level;
    assign user_sysref_dac = dac_sysref_level;
    assign sysref_pl_edge_count_gray = pl_edge_count ^ (pl_edge_count >> 1);
    assign sysref_adc_edge_count_gray = adc_edge_count ^ (adc_edge_count >> 1);
    assign sysref_dac_edge_count_gray = dac_edge_count ^ (dac_edge_count >> 1);
    assign sysref_capture_levels = {dac_sysref_level, adc_sysref_level, pl_sysref_level};

endmodule
