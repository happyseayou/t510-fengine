module tx_header_capture #(
    parameter integer DATA_W       = 64,
    parameter integer HEADER_WORDS = 16
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 ctrl_clk,
    input  wire                 ctrl_rst_n,
    input  wire                 arm_pulse_ctrl,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire                 s_axis_tvalid,
    input  wire                 s_axis_tlast,
    input  wire                 s_axis_tready,
    input  wire [4:0]           ctrl_rd_word,
    output wire [31:0]          ctrl_rd_data,
    output wire                 ctrl_armed,
    output wire                 ctrl_valid,
    output wire [4:0]           ctrl_word_count
);

    localparam integer BUS_W = DATA_W * HEADER_WORDS;

    logic arm_toggle_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0] arm_toggle_sync;
    logic arm_toggle_seen;
    wire  arm_pulse_data = arm_toggle_sync[2] ^ arm_toggle_seen;

    logic armed_data;
    logic valid_data;
    logic capturing_data;
    logic in_packet_data;
    logic [4:0] word_count_data;
    logic [DATA_W-1:0] header_words_data [0:HEADER_WORDS-1];
    logic [BUS_W-1:0] header_words_bus_data;
    wire [BUS_W-1:0] header_words_bus_ctrl;
    wire fire = s_axis_tvalid && s_axis_tready;
    wire packet_start = fire && !in_packet_data;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            arm_toggle_ctrl <= 1'b0;
        end else if (arm_pulse_ctrl) begin
            arm_toggle_ctrl <= ~arm_toggle_ctrl;
        end
    end

    integer pack_idx;
    always_comb begin
        for (pack_idx = 0; pack_idx < HEADER_WORDS; pack_idx = pack_idx + 1) begin
            header_words_bus_data[pack_idx*DATA_W +: DATA_W] = header_words_data[pack_idx];
        end
    end

    integer clear_idx;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_toggle_sync <= 3'b000;
            arm_toggle_seen <= 1'b0;
            armed_data      <= 1'b0;
            valid_data      <= 1'b0;
            capturing_data  <= 1'b0;
            in_packet_data  <= 1'b0;
            word_count_data <= 5'd0;
            for (clear_idx = 0; clear_idx < HEADER_WORDS; clear_idx = clear_idx + 1) begin
                header_words_data[clear_idx] <= {DATA_W{1'b0}};
            end
        end else begin
            arm_toggle_sync <= {arm_toggle_sync[1:0], arm_toggle_ctrl};
            arm_toggle_seen <= arm_toggle_sync[2];

            if (arm_pulse_data) begin
                armed_data      <= 1'b1;
                valid_data      <= 1'b0;
                capturing_data  <= 1'b0;
                word_count_data <= 5'd0;
            end

            if (fire) begin
                if (packet_start && armed_data && !valid_data) begin
                    header_words_data[0] <= s_axis_tdata;
                    capturing_data       <= 1'b1;
                    word_count_data      <= 5'd1;
                end else if (capturing_data && !valid_data) begin
                    header_words_data[word_count_data] <= s_axis_tdata;
                    word_count_data <= word_count_data + 5'd1;
                    if (word_count_data == HEADER_WORDS - 1) begin
                        capturing_data <= 1'b0;
                        armed_data     <= 1'b0;
                        valid_data     <= 1'b1;
                    end
                end

                in_packet_data <= !s_axis_tlast;
            end
        end
    end

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_armed_cdc (
        .src_clk(clk),
        .src_in(armed_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_armed)
    );

    xpm_cdc_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1)
    ) u_valid_cdc (
        .src_clk(clk),
        .src_in(valid_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_valid)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(5)
    ) u_count_cdc (
        .src_clk(clk),
        .src_in(word_count_data),
        .dest_clk(ctrl_clk),
        .dest_out(ctrl_word_count)
    );

    xpm_cdc_array_single #(
        .DEST_SYNC_FF(3),
        .INIT_SYNC_FF(0),
        .SIM_ASSERT_CHK(0),
        .SRC_INPUT_REG(1),
        .WIDTH(BUS_W)
    ) u_header_bus_cdc (
        .src_clk(clk),
        .src_in(header_words_bus_data),
        .dest_clk(ctrl_clk),
        .dest_out(header_words_bus_ctrl)
    );

    wire [63:0] selected_word = header_words_bus_ctrl[ctrl_rd_word[4:1]*DATA_W +: DATA_W];
    assign ctrl_rd_data = ctrl_rd_word[0] ? selected_word[63:32] : selected_word[31:0];

endmodule
