module monitor_counters #(
    parameter integer NINPUT  = 8,
    parameter integer IQ_W    = 16,
    parameter integer PAIR_W  = 32
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         clear,
    input  wire                         sample_valid,
    input  wire [NINPUT*PAIR_W-1:0]     sample_tdata,
    output logic [31:0]                 sample_count,
    output logic [NINPUT*32-1:0]        clip_counts,
    output logic [NINPUT*32-1:0]        mean_mags
);

    integer lane;
    logic [31:0] clip_count_arr [0:NINPUT-1];
    logic [31:0] mean_mag_arr   [0:NINPUT-1];

    function automatic [15:0] abs_word(input logic signed [IQ_W-1:0] word);
        begin
            abs_word = word[IQ_W-1] ? (~word + 1'b1) : word;
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sample_count <= 32'd0;
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                clip_count_arr[lane] <= 32'd0;
                mean_mag_arr[lane]   <= 32'd0;
            end
        end else if (clear) begin
            sample_count <= 32'd0;
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                clip_count_arr[lane] <= 32'd0;
                mean_mag_arr[lane]   <= 32'd0;
            end
        end else if (sample_valid) begin
            sample_count <= sample_count + 32'd1;
            for (lane = 0; lane < NINPUT; lane = lane + 1) begin
                mean_mag_arr[lane] <= mean_mag_arr[lane] +
                    {16'd0, abs_word(sample_tdata[lane*PAIR_W +: IQ_W])} +
                    {16'd0, abs_word(sample_tdata[lane*PAIR_W + IQ_W +: IQ_W])};

                if (($signed(sample_tdata[lane*PAIR_W +: IQ_W]) == 16'sh7fff) ||
                    ($signed(sample_tdata[lane*PAIR_W +: IQ_W]) == -16'sh8000) ||
                    ($signed(sample_tdata[lane*PAIR_W + IQ_W +: IQ_W]) == 16'sh7fff) ||
                    ($signed(sample_tdata[lane*PAIR_W + IQ_W +: IQ_W]) == -16'sh8000)) begin
                    clip_count_arr[lane] <= clip_count_arr[lane] + 32'd1;
                end
            end
        end
    end

    genvar g;
    generate
        for (g = 0; g < NINPUT; g = g + 1) begin : GEN_FLATTEN
            assign clip_counts[g*32 +: 32] = clip_count_arr[g];
            assign mean_mags[g*32 +: 32]   = mean_mag_arr[g];
        end
    endgenerate

endmodule
