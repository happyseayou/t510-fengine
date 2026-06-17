module requantizer #(
    parameter integer DATA_W = 256,
    parameter integer LANE_W = 16
) (
    input  wire [DATA_W-1:0] in_tdata,
    input  wire              in_tvalid,
    input  wire [15:0]       quant_mode,
    output logic [DATA_W-1:0] out_tdata,
    output logic              clip_any
);

    integer idx;
    logic signed [LANE_W-1:0] sample_word;
    logic signed [7:0]        q8_word;

    always_comb begin
        out_tdata = in_tdata;
        clip_any  = 1'b0;

        if (in_tvalid && quant_mode == 16'd1) begin
            for (idx = 0; idx < DATA_W / LANE_W; idx = idx + 1) begin
                sample_word = in_tdata[idx*LANE_W +: LANE_W];
                if (sample_word > 16'sd127) begin
                    q8_word  = 8'sd127;
                    clip_any = 1'b1;
                end else if (sample_word < -16'sd128) begin
                    q8_word  = -8'sd128;
                    clip_any = 1'b1;
                end else begin
                    q8_word = sample_word[7:0];
                end
                out_tdata[idx*LANE_W +: LANE_W] = {{8{q8_word[7]}}, q8_word};
            end
        end
    end

endmodule
