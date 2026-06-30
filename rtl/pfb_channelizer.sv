`ifdef T510_SIM_FFT_MODEL
module t510_fengine_xfft_4096_sim_model (
    input  wire         aclk,
    input  wire [255:0] s_axis_config_tdata,
    input  wire         s_axis_config_tvalid,
    output wire         s_axis_config_tready,
    input  wire [255:0] s_axis_data_tdata,
    input  wire         s_axis_data_tvalid,
    output wire         s_axis_data_tready,
    input  wire         s_axis_data_tlast,
    output logic [255:0] m_axis_data_tdata,
    output logic [23:0]  m_axis_data_tuser,
    output logic         m_axis_data_tvalid,
    input  wire          m_axis_data_tready,
    output logic         m_axis_data_tlast,
    output logic [7:0]   m_axis_status_tdata,
    output logic         m_axis_status_tvalid,
    input  wire          m_axis_status_tready,
    output logic         event_frame_started,
    output logic         event_tlast_unexpected,
    output logic         event_tlast_missing,
    output logic         event_fft_overflow,
    output logic         event_status_channel_halt,
    output logic         event_data_in_channel_halt,
    output logic         event_data_out_channel_halt
);

    logic [11:0] bin_idx = 12'd0;
    wire data_output_ready = !m_axis_data_tvalid || m_axis_data_tready;
    wire status_output_ready = !m_axis_status_tvalid || m_axis_status_tready;

    assign s_axis_config_tready = status_output_ready;
    assign s_axis_data_tready = data_output_ready;

    initial begin
        m_axis_data_tdata = 256'd0;
        m_axis_data_tuser = 24'd0;
        m_axis_data_tvalid = 1'b0;
        m_axis_data_tlast = 1'b0;
        m_axis_status_tdata = 8'd0;
        m_axis_status_tvalid = 1'b0;
        event_frame_started = 1'b0;
        event_tlast_unexpected = 1'b0;
        event_tlast_missing = 1'b0;
        event_fft_overflow = 1'b0;
        event_status_channel_halt = 1'b0;
        event_data_in_channel_halt = 1'b0;
        event_data_out_channel_halt = 1'b0;
    end

    function automatic [31:0] rotate_by_bin(
        input signed [15:0] i_value,
        input signed [15:0] q_value,
        input [11:0] bin
    );
        logic signed [15:0] out_i;
        logic signed [15:0] out_q;
        begin
            case (bin[1:0])
                2'd0: begin out_i = i_value;  out_q = q_value;  end
                2'd1: begin out_i = -q_value; out_q = i_value;  end
                2'd2: begin out_i = -i_value; out_q = -q_value; end
                default: begin out_i = q_value; out_q = -i_value; end
            endcase
            rotate_by_bin = {out_q[15:0], out_i[15:0]};
        end
    endfunction

    function automatic [255:0] model_fft_word(input [255:0] value, input [11:0] bin);
        integer lane;
        logic [255:0] out;
        logic signed [15:0] i_word;
        logic signed [15:0] q_word;
        begin
            out = 256'd0;
            for (lane = 0; lane < 8; lane = lane + 1) begin
                i_word = value[lane*32 +: 16];
                q_word = value[lane*32 + 16 +: 16];
                out[lane*32 +: 32] = rotate_by_bin(i_word, q_word, bin + lane[11:0]);
            end
            model_fft_word = out;
        end
    endfunction

    always @(posedge aclk) begin
        event_frame_started <= 1'b0;
        event_tlast_unexpected <= 1'b0;
        event_tlast_missing <= 1'b0;
        event_fft_overflow <= 1'b0;
        event_status_channel_halt <= !status_output_ready;
        event_data_in_channel_halt <= 1'b0;
        event_data_out_channel_halt <= !data_output_ready;

        if (status_output_ready) begin
            m_axis_status_tvalid <= 1'b0;
            if (s_axis_config_tvalid) begin
                m_axis_status_tdata <= s_axis_config_tdata[7:0];
                m_axis_status_tvalid <= 1'b1;
            end
        end

        if (data_output_ready) begin
            m_axis_data_tvalid <= 1'b0;
            m_axis_data_tlast <= 1'b0;
            if (s_axis_data_tvalid) begin
                m_axis_data_tdata <= model_fft_word(s_axis_data_tdata, bin_idx);
                m_axis_data_tuser <= {4'd0, 8'd0, bin_idx};
                m_axis_data_tvalid <= 1'b1;
                m_axis_data_tlast <= (bin_idx == 12'd4095);
                event_frame_started <= (bin_idx == 12'd0);
                if (s_axis_data_tlast != (bin_idx == 12'd4095)) begin
                    event_tlast_unexpected <= s_axis_data_tlast;
                    event_tlast_missing <= !s_axis_data_tlast && (bin_idx == 12'd4095);
                end
                bin_idx <= (bin_idx == 12'd4095) ? 12'd0 : (bin_idx + 12'd1);
            end
        end
    end
endmodule
`endif

`ifndef T510_SIM_FFT_MODEL
`ifdef T510_STAGE27H_PRODUCTION_ONLY
module t510_fengine_xfft_4096_8lane_streaming (
    input  wire         aclk,
    input  wire [255:0] s_axis_config_tdata,
    input  wire         s_axis_config_tvalid,
    output wire         s_axis_config_tready,
    input  wire [255:0] s_axis_data_tdata,
    input  wire         s_axis_data_tvalid,
    output wire         s_axis_data_tready,
    input  wire         s_axis_data_tlast,
    output wire [255:0] m_axis_data_tdata,
    output wire [23:0]  m_axis_data_tuser,
    output wire         m_axis_data_tvalid,
    input  wire         m_axis_data_tready,
    output wire         m_axis_data_tlast,
    output wire [7:0]   m_axis_status_tdata,
    output wire         m_axis_status_tvalid,
    input  wire         m_axis_status_tready,
    output wire         event_frame_started,
    output wire         event_tlast_unexpected,
    output wire         event_tlast_missing,
    output wire         event_fft_overflow,
    output wire         event_status_channel_halt,
    output wire         event_data_in_channel_halt,
    output wire         event_data_out_channel_halt,
    output wire [7:0]   config_done_debug,
    output wire [7:0]   config_ready_debug
);

    wire [7:0]  lane_cfg_tready;
    wire [7:0]  lane_data_tready;
    wire [7:0]  lane_data_tvalid;
    wire [7:0]  lane_data_tlast;
    wire [7:0]  lane_status_tvalid;
    wire [63:0] lane_status_tdata;
    wire [7:0]  lane_status_halt;
    wire [7:0]  lane_data_out_halt;
    wire [7:0]  lane_frame_started;
    wire [7:0]  lane_tlast_unexpected;
    wire [7:0]  lane_tlast_missing;
    wire [7:0]  lane_fft_overflow;
    wire [7:0]  lane_data_in_halt;
    wire [7:0]  lane_m_axis_tvalid;
    wire [7:0]  lane_m_axis_tready;
    wire [7:0]  lane_m_axis_tlast;
    wire [7:0]  lane_m_axis_status_tready;
    wire [191:0] lane_m_axis_tuser;
    wire [7:0]  lane_m_axis_ovflo;
    logic [7:0] lane_cfg_done = 8'd0;
    wire [7:0] lane_cfg_tvalid;
    wire [7:0] lane_cfg_fire;
    wire [7:0] lane_cfg_done_next;
    wire all_lane_data_valid = &lane_m_axis_tvalid;
    wire all_lane_status_valid = &lane_status_tvalid;

    assign lane_cfg_tvalid = {8{s_axis_config_tvalid}} & ~lane_cfg_done;
    assign lane_cfg_fire = lane_cfg_tvalid & lane_cfg_tready;
    assign lane_cfg_done_next = lane_cfg_done | lane_cfg_fire;
    assign s_axis_config_tready = s_axis_config_tvalid && (&lane_cfg_done_next);
    assign config_done_debug = lane_cfg_done_next;
    assign config_ready_debug = lane_cfg_tready;
    assign s_axis_data_tready = &lane_data_tready;
    assign lane_data_tvalid = {8{s_axis_data_tvalid && s_axis_data_tready}};
    assign lane_data_tlast = {8{s_axis_data_tlast}};
    assign lane_m_axis_tready = {8{all_lane_data_valid && m_axis_data_tready}};
    assign lane_m_axis_status_tready = {8{all_lane_status_valid && m_axis_status_tready}};

    always_ff @(posedge aclk) begin
        if (!s_axis_config_tvalid) begin
            lane_cfg_done <= 8'd0;
        end else begin
            lane_cfg_done <= lane_cfg_done_next;
        end
    end

    genvar lane;
    generate
        for (lane = 0; lane < 8; lane = lane + 1) begin : gen_lane_xfft
            wire [23:0] lane_scale_schedule =
                s_axis_config_tdata[(8 + lane*24) +: 24];
            wire [15:0] lane_config_tdata = {
                3'd0,
                lane_scale_schedule[11:0],
                s_axis_config_tdata[lane]
            };
            wire [23:0] lane_tuser;

            t510_fengine_xfft_4096_lane u_lane_xfft (
                .aclk(aclk),
                .s_axis_config_tdata(lane_config_tdata),
                .s_axis_config_tvalid(lane_cfg_tvalid[lane]),
                .s_axis_config_tready(lane_cfg_tready[lane]),
                .s_axis_data_tdata(s_axis_data_tdata[lane*32 +: 32]),
                .s_axis_data_tvalid(lane_data_tvalid[lane]),
                .s_axis_data_tready(lane_data_tready[lane]),
                .s_axis_data_tlast(lane_data_tlast[lane]),
                .m_axis_data_tdata(m_axis_data_tdata[lane*32 +: 32]),
                .m_axis_data_tuser(lane_tuser),
                .m_axis_data_tvalid(lane_m_axis_tvalid[lane]),
                .m_axis_data_tready(lane_m_axis_tready[lane]),
                .m_axis_data_tlast(lane_m_axis_tlast[lane]),
                .m_axis_status_tdata(lane_status_tdata[lane*8 +: 8]),
                .m_axis_status_tvalid(lane_status_tvalid[lane]),
                .m_axis_status_tready(lane_m_axis_status_tready[lane]),
                .event_frame_started(lane_frame_started[lane]),
                .event_tlast_unexpected(lane_tlast_unexpected[lane]),
                .event_tlast_missing(lane_tlast_missing[lane]),
                .event_fft_overflow(lane_fft_overflow[lane]),
                .event_status_channel_halt(lane_status_halt[lane]),
                .event_data_in_channel_halt(lane_data_in_halt[lane]),
                .event_data_out_channel_halt(lane_data_out_halt[lane])
            );

            assign lane_m_axis_tuser[lane*24 +: 24] = lane_tuser;
            assign lane_m_axis_ovflo[lane] = lane_tuser[16];
        end
    endgenerate

    assign m_axis_data_tvalid = all_lane_data_valid;
    assign m_axis_data_tlast = lane_m_axis_tlast[0] && (&lane_m_axis_tlast);
    assign m_axis_data_tuser = {
        lane_m_axis_ovflo,
        4'd0,
        lane_m_axis_tuser[11:0]
    };
    assign m_axis_status_tvalid = all_lane_status_valid;
    assign m_axis_status_tdata = {
        lane_status_tdata[7*8],
        lane_status_tdata[6*8],
        lane_status_tdata[5*8],
        lane_status_tdata[4*8],
        lane_status_tdata[3*8],
        lane_status_tdata[2*8],
        lane_status_tdata[1*8],
        lane_status_tdata[0]
    };
    assign event_frame_started = lane_frame_started[0];
    assign event_tlast_unexpected = |lane_tlast_unexpected;
    assign event_tlast_missing = |lane_tlast_missing;
    assign event_fft_overflow = |lane_fft_overflow;
    assign event_status_channel_halt = |lane_status_halt;
    assign event_data_in_channel_halt = |lane_data_in_halt;
    assign event_data_out_channel_halt = |lane_data_out_halt;

endmodule
`endif
`endif

module feng_channelizer_4096 #(
    parameter integer DATA_W = 1024,
    parameter integer NINPUT = 8,
    parameter integer NCHAN  = 4096
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 clear,
    input  wire [15:0]          cfg_taps,
    input  wire [15:0]          cfg_fft_shift,
    input  wire [31:0]          cfg_chan0,
    input  wire [15:0]          cfg_chan_count,
    input  wire [15:0]          cfg_time_count,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [63:0]          s_axis_sample0,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [63:0]          m_axis_sample0,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire [31:0]          status,
    output logic [31:0]         frame_count,
    output logic [31:0]         overflow_count,
    output logic [31:0]         data_halt_count,
    output logic [31:0]         xfft_event_count,
    output logic [31:0]         tile_overflow_count,
    output logic [31:0]         xfft_tlast_unexpected_count,
    output logic [31:0]         xfft_tlast_missing_count,
    output logic [31:0]         xfft_fft_overflow_count,
    output logic [31:0]         xfft_data_out_halt_count,
    output logic [31:0]         xfft_status_halt_count,
    output logic [31:0]         capture_backpressure_count,
    output logic [31:0]         frame_sample0_overflow_count,
    output wire [31:0]          input_fifo_level,
    output logic [31:0]         peak_chan,
    output logic [31:0]         peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

    localparam integer CELL_W = NINPUT * 32;
    localparam integer CELLS_PER_BEAT = DATA_W / CELL_W;
    localparam integer PACK_IDX_W = (CELLS_PER_BEAT <= 1) ? 1 : $clog2(CELLS_PER_BEAT);
    localparam [15:0] CELLS_PER_BEAT_U16 = CELLS_PER_BEAT;
    localparam [31:0] PAYLOAD_CELLS = 32'd256;
    localparam [31:0] LOCAL_NCHAN = NCHAN;
    localparam integer TILE_FRAMES = 1;
    localparam integer TILE_BUFFERS = 2;
    localparam integer BLOCK_CHANS = 256;
    localparam integer BLOCK_BEATS = BLOCK_CHANS / CELLS_PER_BEAT;
    localparam integer BLOCK_COUNT = NCHAN / BLOCK_CHANS;
    localparam [5:0] BLOCK_BEAT_LAST_U6 = BLOCK_BEATS - 1;
    localparam [2:0] TILE_FRAME_COUNT_U3 = TILE_FRAMES;
    localparam [1:0] TILE_FRAME_COUNT_U2 = TILE_FRAMES;
    localparam [2:0] TILE_FRAME_LAST_U3 = TILE_FRAME_COUNT_U3 - 3'd1;
    localparam [1:0] TILE_FRAME_LAST_U2 = TILE_FRAME_COUNT_U2 - 2'd1;
    localparam [5:0] BLOCK_LAST_U6 = BLOCK_COUNT - 1;
    localparam integer TILE_CELLS = TILE_FRAMES * NCHAN;
    localparam integer TILE_BEATS = TILE_CELLS / CELLS_PER_BEAT;
    localparam integer TILE_CELL_AW = (TILE_CELLS <= 1) ? 1 : $clog2(TILE_CELLS);
    localparam integer TILE_BEAT_AW = (TILE_BEATS <= 1) ? 1 : $clog2(TILE_BEATS);
    localparam integer TILE_TOTAL_CELLS = TILE_BUFFERS * TILE_CELLS;
    localparam integer TILE_TOTAL_BEATS = TILE_BUFFERS * TILE_BEATS;
    localparam integer TILE_TOTAL_CELL_AW = (TILE_TOTAL_CELLS <= 1) ? 1 : $clog2(TILE_TOTAL_CELLS);
    localparam integer TILE_TOTAL_BEAT_AW = (TILE_TOTAL_BEATS <= 1) ? 1 : $clog2(TILE_TOTAL_BEATS);
    localparam integer FRAME_FIFO_DEPTH = 16;
    localparam integer FRAME_FIFO_AW = 4;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_DEPTH_COUNT = FRAME_FIFO_DEPTH;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_ZERO_COUNT = {(FRAME_FIFO_AW+1){1'b0}};
    localparam integer INPUT_BEATS_PER_FRAME = NCHAN / CELLS_PER_BEAT;
    localparam integer INPUT_FIFO_DEPTH = 2048;
    localparam integer INPUT_FIFO_COUNT_W = 12;
    localparam integer INPUT_FIFO_W = DATA_W + 64;

    logic [DATA_W-1:0] input_word;
    logic [63:0]       input_sample0;
    logic [PACK_IDX_W-1:0] input_subidx;
    logic              input_valid;
    logic [11:0]       input_bin_idx;

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    wire config_valid =
        (DATA_W >= CELL_W) &&
        ((DATA_W % CELL_W) == 0) &&
        (CELLS_PER_BEAT == 4) &&
        (NINPUT == 8) &&
        (NCHAN == 4096) &&
        (cfg_taps == 16'd0) &&
        (cfg_chan0 == 32'd0) &&
        (cfg_chan_count == 16'd256) &&
        (cfg_time_count == 16'd1);
    wire science_valid = config_valid;
`else
    wire [31:0] window_cells = cfg_chan_count * cfg_time_count;
    wire [31:0] chan_end = cfg_chan0 + {16'd0, cfg_chan_count};
    wire config_valid =
        (DATA_W >= CELL_W) &&
        ((DATA_W % CELL_W) == 0) &&
        (CELLS_PER_BEAT == 4) &&
        (NINPUT == 8) &&
        (cfg_chan_count != 16'd0) &&
        (cfg_time_count != 16'd0) &&
        (cfg_chan_count >= CELLS_PER_BEAT_U16) &&
        ((cfg_chan_count % CELLS_PER_BEAT_U16) == 16'd0) &&
        (cfg_chan0 < LOCAL_NCHAN) &&
        (chan_end <= LOCAL_NCHAN) &&
        (window_cells == PAYLOAD_CELLS);
    wire science_valid =
        config_valid &&
        (cfg_taps == 16'd0) &&
        (cfg_chan_count == 16'd256) &&
        (cfg_time_count == 16'd1) &&
        (LOCAL_NCHAN == 32'd4096);
`endif

    logic [255:0] xfft_config_tdata;
    logic         xfft_config_tvalid;
    wire          xfft_config_tready;
    logic         xfft_configured;

    wire [CELL_W-1:0] selected_input_cell =
        input_word[input_subidx*CELL_W +: CELL_W];
    wire [63:0] selected_input_sample0 =
        input_sample0 + {{(64-PACK_IDX_W){1'b0}}, input_subidx};
    wire [23:0] xfft_scale_schedule = (cfg_fft_shift == 16'd0) ? 24'd0 : {8'h55, cfg_fft_shift};
    logic [2:0] input_frame_count;
    logic [TILE_BUFFERS-1:0] tile_valid;
    logic                    capture_buf_sel;
    logic                    emit_buf_sel;
    wire                     capture_buffer_free = !tile_valid[capture_buf_sel];
    wire                     emit_buffer_valid = tile_valid[emit_buf_sel];
    wire                     other_emit_buffer_valid = tile_valid[~emit_buf_sel];
    wire input_tile_open = (input_frame_count < TILE_FRAME_COUNT_U3) && capture_buffer_free;
    wire input_frame_active = input_valid || (input_bin_idx != 12'd0);
    wire input_frame_can_start =
        !input_frame_active &&
        (input_fifo_level >= INPUT_BEATS_PER_FRAME);
    wire xfft_s_axis_tvalid = enable && config_valid && xfft_configured &&
                              input_valid && input_tile_open;
    wire xfft_s_axis_tready;
    wire xfft_s_axis_tlast = (input_bin_idx == 12'd4095);
    wire xfft_input_fire = xfft_s_axis_tvalid && xfft_s_axis_tready;
    wire input_last_cell_fire = xfft_input_fire && (input_subidx == (CELLS_PER_BEAT - 1));
    wire input_tile_closing =
        xfft_input_fire &&
        xfft_s_axis_tlast &&
        (input_frame_count == TILE_FRAME_LAST_U3);
    wire input_fifo_rst = !rst_n || clear || !enable || !config_valid;
    wire input_fifo_full;
    wire input_fifo_empty;
    wire input_fifo_wr_rst_busy;
    wire input_fifo_rd_rst_busy;
    wire [INPUT_FIFO_COUNT_W-1:0] input_fifo_data_count;
    wire [INPUT_FIFO_W-1:0] input_fifo_dout;
    wire input_fifo_wr_en;
    wire input_fifo_rd_en;

    wire can_load_input = enable && config_valid && xfft_configured &&
                          input_tile_open &&
                          !input_tile_closing &&
                          !input_fifo_rd_rst_busy &&
                          !input_fifo_empty &&
                          (input_frame_active || input_frame_can_start) &&
                          (!input_valid || input_last_cell_fire);
    wire load_input = input_fifo_rd_en;
    assign s_axis_tready = enable && config_valid && xfft_configured &&
                           !input_fifo_wr_rst_busy &&
                           !input_fifo_rd_rst_busy &&
                           !input_fifo_full;
    assign input_fifo_wr_en = s_axis_tvalid && s_axis_tready;
    assign input_fifo_rd_en = can_load_input;
    assign input_fifo_level = {{(32-INPUT_FIFO_COUNT_W){1'b0}}, input_fifo_data_count};

    wire [255:0] xfft_m_axis_tdata;
    wire [23:0]  xfft_m_axis_tuser;
    wire         xfft_m_axis_tvalid;
    wire         xfft_m_axis_tready;
    wire         xfft_m_axis_tlast;
    wire [7:0]   xfft_m_axis_status_tdata;
    wire         xfft_m_axis_status_tvalid;
    wire         xfft_m_axis_status_tready;
    wire         xfft_event_frame_started;
    wire         xfft_event_tlast_unexpected;
    wire         xfft_event_tlast_missing;
    wire         xfft_event_fft_overflow;
    wire         xfft_event_status_channel_halt;
    wire         xfft_event_data_in_channel_halt;
    wire         xfft_event_data_out_channel_halt;
    wire [7:0]   xfft_config_done_debug;
    wire [7:0]   xfft_config_ready_debug;

    wire [11:0] xfft_bin = xfft_m_axis_tuser[11:0];
    wire [31:0] xfft_bin_ext = {20'd0, xfft_bin};

    logic [1:0] tile_capture_time_idx;
    logic       tile_capture_armed;
    logic [63:0] tile_sample0 [0:TILE_BUFFERS-1][0:TILE_FRAMES-1];
    logic [TILE_TOTAL_BEAT_AW-1:0] tile_rd_addr;
    wire [DATA_W-1:0] tile_rd_data;
    wire xfft_output_fire = xfft_m_axis_tvalid && xfft_m_axis_tready;
    wire accept_xfft_output = xfft_output_fire && tile_capture_armed;
    wire capture_backpressure = xfft_m_axis_tvalid && tile_capture_armed && !capture_buffer_free;
    wire capture_overflow = xfft_output_fire && tile_capture_armed && !capture_buffer_free;
    wire tile_wr_en = accept_xfft_output && capture_buffer_free;
    wire [TILE_TOTAL_CELL_AW-1:0] tile_wr_addr = {capture_buf_sel, xfft_bin};

    assign xfft_m_axis_tready = capture_buffer_free;
    assign xfft_m_axis_status_tready = 1'b1;

    logic [5:0] emit_block_idx;
    logic [5:0] emit_beat_idx;
    logic       emit_read_wait;
    logic       emit_read_load;
    logic [DATA_W-1:0] output_word;
    logic [63:0] output_sample0;
    logic output_valid;
    logic [31:0] packet_chan0_reg;
    logic [15:0] packet_chan_count_reg;
    logic [15:0] packet_time_count_reg;

    (* ram_style = "distributed" *) logic [63:0] frame_sample0_fifo [0:FRAME_FIFO_DEPTH-1];
    logic [FRAME_FIFO_AW-1:0] frame_fifo_wr_ptr;
    logic [FRAME_FIFO_AW-1:0] frame_fifo_rd_ptr;
    logic [FRAME_FIFO_AW:0]   frame_fifo_count;
    wire frame_fifo_empty = (frame_fifo_count == FRAME_FIFO_ZERO_COUNT);
    wire frame_fifo_full = (frame_fifo_count == FRAME_FIFO_DEPTH_COUNT);
    wire frame_sample0_enqueue;
    wire frame_sample0_dequeue;
    wire frame_sample0_push = frame_sample0_enqueue && (!frame_fifo_full || frame_sample0_dequeue);
    wire frame_sample0_pop = frame_sample0_dequeue && !frame_fifo_empty;
    wire [63:0] current_output_frame_sample0 =
        !frame_fifo_empty ?
        frame_sample0_fifo[frame_fifo_rd_ptr] : selected_input_sample0;

    assign m_axis_tdata = output_word;
    assign m_axis_sample0 = output_sample0;
    assign m_axis_tvalid = output_valid;
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign packet_chan0 = packet_chan0_reg;
    assign packet_chan_count = 16'd256;
    assign packet_time_count = 16'd1;
`else
    assign packet_chan0 = (packet_chan_count_reg != 16'd0) ? packet_chan0_reg : cfg_chan0;
    assign packet_chan_count = (packet_chan_count_reg != 16'd0) ? packet_chan_count_reg : cfg_chan_count;
    assign packet_time_count = (packet_time_count_reg != 16'd0) ? packet_time_count_reg : cfg_time_count;
`endif

`ifndef T510_STAGE27H_PRODUCTION_ONLY
    function automatic [15:0] abs16(input logic signed [15:0] value);
        begin
            if (value == -16'sd32768) begin
                abs16 = 16'h8000;
            end else if (value < 0) begin
                abs16 = -value;
            end else begin
                abs16 = value[15:0];
            end
        end
    endfunction

    function automatic [31:0] cell_metric(input logic [CELL_W-1:0] data);
        integer word_idx;
        logic signed [15:0] i_word;
        logic signed [15:0] q_word;
        logic [31:0] sum;
        begin
            sum = 32'd0;
            for (word_idx = 0; word_idx < CELL_W / 32; word_idx = word_idx + 1) begin
                i_word = data[word_idx*32 +: 16];
                q_word = data[word_idx*32 + 16 +: 16];
                sum = sum + {16'd0, abs16(i_word)} + {16'd0, abs16(q_word)};
            end
            cell_metric = sum;
        end
    endfunction
`endif

    always_comb begin
        xfft_config_tdata = 256'd0;
        xfft_config_tdata[7:0] = 8'hff;
        xfft_config_tdata[31:8] = xfft_scale_schedule;
        xfft_config_tdata[55:32] = xfft_scale_schedule;
        xfft_config_tdata[79:56] = xfft_scale_schedule;
        xfft_config_tdata[103:80] = xfft_scale_schedule;
        xfft_config_tdata[127:104] = xfft_scale_schedule;
        xfft_config_tdata[151:128] = xfft_scale_schedule;
        xfft_config_tdata[175:152] = xfft_scale_schedule;
        xfft_config_tdata[199:176] = xfft_scale_schedule;
    end

`ifdef T510_SIM_FFT_MODEL
    t510_fengine_xfft_4096_sim_model u_fengine_xfft_4096 (
        .aclk(clk),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(selected_input_cell),
        .s_axis_data_tvalid(xfft_s_axis_tvalid),
        .s_axis_data_tready(xfft_s_axis_tready),
        .s_axis_data_tlast(xfft_s_axis_tlast),
        .m_axis_data_tdata(xfft_m_axis_tdata),
        .m_axis_data_tuser(xfft_m_axis_tuser),
        .m_axis_data_tvalid(xfft_m_axis_tvalid),
        .m_axis_data_tready(xfft_m_axis_tready),
        .m_axis_data_tlast(xfft_m_axis_tlast),
        .m_axis_status_tdata(xfft_m_axis_status_tdata),
        .m_axis_status_tvalid(xfft_m_axis_status_tvalid),
        .m_axis_status_tready(xfft_m_axis_status_tready),
        .event_frame_started(xfft_event_frame_started),
        .event_tlast_unexpected(xfft_event_tlast_unexpected),
        .event_tlast_missing(xfft_event_tlast_missing),
        .event_fft_overflow(xfft_event_fft_overflow),
        .event_status_channel_halt(xfft_event_status_channel_halt),
        .event_data_in_channel_halt(xfft_event_data_in_channel_halt),
        .event_data_out_channel_halt(xfft_event_data_out_channel_halt)
    );
    assign xfft_config_done_debug = xfft_configured ? 8'hff : 8'h00;
    assign xfft_config_ready_debug = {8{xfft_config_tready}};
`elsif T510_STAGE27H_PRODUCTION_ONLY
    t510_fengine_xfft_4096_8lane_streaming u_fengine_xfft_4096 (
        .aclk(clk),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(selected_input_cell),
        .s_axis_data_tvalid(xfft_s_axis_tvalid),
        .s_axis_data_tready(xfft_s_axis_tready),
        .s_axis_data_tlast(xfft_s_axis_tlast),
        .m_axis_data_tdata(xfft_m_axis_tdata),
        .m_axis_data_tuser(xfft_m_axis_tuser),
        .m_axis_data_tvalid(xfft_m_axis_tvalid),
        .m_axis_data_tready(xfft_m_axis_tready),
        .m_axis_data_tlast(xfft_m_axis_tlast),
        .m_axis_status_tdata(xfft_m_axis_status_tdata),
        .m_axis_status_tvalid(xfft_m_axis_status_tvalid),
        .m_axis_status_tready(xfft_m_axis_status_tready),
        .event_frame_started(xfft_event_frame_started),
        .event_tlast_unexpected(xfft_event_tlast_unexpected),
        .event_tlast_missing(xfft_event_tlast_missing),
        .event_fft_overflow(xfft_event_fft_overflow),
        .event_status_channel_halt(xfft_event_status_channel_halt),
        .event_data_in_channel_halt(xfft_event_data_in_channel_halt),
        .event_data_out_channel_halt(xfft_event_data_out_channel_halt),
        .config_done_debug(xfft_config_done_debug),
        .config_ready_debug(xfft_config_ready_debug)
    );
`else
    t510_fengine_xfft_4096 u_fengine_xfft_4096 (
        .aclk(clk),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(selected_input_cell),
        .s_axis_data_tvalid(xfft_s_axis_tvalid),
        .s_axis_data_tready(xfft_s_axis_tready),
        .s_axis_data_tlast(xfft_s_axis_tlast),
        .m_axis_data_tdata(xfft_m_axis_tdata),
        .m_axis_data_tuser(xfft_m_axis_tuser),
        .m_axis_data_tvalid(xfft_m_axis_tvalid),
        .m_axis_data_tready(xfft_m_axis_tready),
        .m_axis_data_tlast(xfft_m_axis_tlast),
        .m_axis_status_tdata(xfft_m_axis_status_tdata),
        .m_axis_status_tvalid(xfft_m_axis_status_tvalid),
        .m_axis_status_tready(xfft_m_axis_status_tready),
        .event_frame_started(xfft_event_frame_started),
        .event_tlast_unexpected(xfft_event_tlast_unexpected),
        .event_tlast_missing(xfft_event_tlast_missing),
        .event_fft_overflow(xfft_event_fft_overflow),
        .event_status_channel_halt(xfft_event_status_channel_halt),
        .event_data_in_channel_halt(xfft_event_data_in_channel_halt),
        .event_data_out_channel_halt(xfft_event_data_out_channel_halt)
    );
    assign xfft_config_done_debug = xfft_configured ? 8'hff : 8'h00;
    assign xfft_config_ready_debug = {8{xfft_config_tready}};
`endif

    xpm_memory_sdpram #(
        .ADDR_WIDTH_A(TILE_TOTAL_CELL_AW),
        .ADDR_WIDTH_B(TILE_TOTAL_BEAT_AW),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(CELL_W),
        .CASCADE_HEIGHT(0),
        .CLOCKING_MODE("common_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"),
        .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE("block"),
        .MEMORY_SIZE(TILE_TOTAL_CELLS * CELL_W),
        .MESSAGE_CONTROL(0),
        .READ_DATA_WIDTH_B(DATA_W),
        .READ_LATENCY_B(1),
        .READ_RESET_VALUE_B("0"),
        .RST_MODE_A("SYNC"),
        .RST_MODE_B("SYNC"),
        .USE_EMBEDDED_CONSTRAINT(0),
        .USE_MEM_INIT(0),
        .WAKEUP_TIME("disable_sleep"),
        .WRITE_DATA_WIDTH_A(CELL_W),
        .WRITE_MODE_B("read_first")
    ) u_tile_bram (
        .dbiterrb(),
        .doutb(tile_rd_data),
        .sbiterrb(),
        .addra(tile_wr_addr),
        .addrb(tile_rd_addr),
        .clka(clk),
        .clkb(clk),
        .dina(xfft_m_axis_tdata),
        .ena(1'b1),
        .enb(1'b1),
        .injectdbiterra(1'b0),
        .injectsbiterra(1'b0),
        .regceb(1'b1),
        .rstb(!rst_n),
        .sleep(1'b0),
        .wea(tile_wr_en)
    );

    xpm_fifo_sync #(
        .CASCADE_HEIGHT(0),
        .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"),
        .FIFO_MEMORY_TYPE("block"),
        .FIFO_READ_LATENCY(1),
        .FIFO_WRITE_DEPTH(INPUT_FIFO_DEPTH),
        .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10),
        .PROG_FULL_THRESH(INPUT_FIFO_DEPTH - 10),
        .RD_DATA_COUNT_WIDTH(INPUT_FIFO_COUNT_W),
        .READ_DATA_WIDTH(INPUT_FIFO_W),
        .READ_MODE("fwft"),
        .SIM_ASSERT_CHK(0),
        .USE_ADV_FEATURES("0707"),
        .WAKEUP_TIME(0),
        .WRITE_DATA_WIDTH(INPUT_FIFO_W),
        .WR_DATA_COUNT_WIDTH(INPUT_FIFO_COUNT_W)
    ) u_input_fifo (
        .almost_empty(),
        .almost_full(),
        .data_valid(),
        .dbiterr(),
        .dout(input_fifo_dout),
        .empty(input_fifo_empty),
        .full(input_fifo_full),
        .overflow(),
        .prog_empty(),
        .prog_full(),
        .rd_data_count(input_fifo_data_count),
        .rd_rst_busy(input_fifo_rd_rst_busy),
        .sbiterr(),
        .underflow(),
        .wr_ack(),
        .wr_data_count(),
        .wr_rst_busy(input_fifo_wr_rst_busy),
        .din({s_axis_sample0, s_axis_tdata}),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .rd_en(input_fifo_rd_en),
        .rst(input_fifo_rst),
        .sleep(1'b0),
        .wr_clk(clk),
        .wr_en(input_fifo_wr_en)
    );

    integer reset_buf;
    integer reset_frame;
    wire output_fire = output_valid && m_axis_tready;
    wire emit_packet_last_beat =
        (emit_beat_idx == BLOCK_BEAT_LAST_U6);
    wire emit_tile_last_beat =
        emit_packet_last_beat &&
        (emit_block_idx == BLOCK_LAST_U6);
    wire [TILE_BEAT_AW-1:0] emit_tile_beat_addr = {emit_block_idx[3:0], emit_beat_idx};
    wire emit_can_issue_read =
        emit_buffer_valid &&
        !emit_read_wait &&
        !emit_read_load &&
        !output_valid;
    wire feng_busy =
        input_valid ||
        (input_frame_count != 3'd0) ||
        tile_capture_armed ||
        (tile_capture_time_idx != 2'd0) ||
        (tile_valid != {TILE_BUFFERS{1'b0}}) ||
        emit_read_wait ||
        emit_read_load ||
        output_valid;
    assign frame_sample0_enqueue = xfft_input_fire && (input_bin_idx == 12'd0);
    assign frame_sample0_dequeue = accept_xfft_output && xfft_m_axis_tlast;

    always_ff @(posedge clk) begin
        if (frame_sample0_push) begin
            frame_sample0_fifo[frame_fifo_wr_ptr] <= selected_input_sample0;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            input_word <= {DATA_W{1'b0}};
            input_sample0 <= 64'd0;
            input_subidx <= {PACK_IDX_W{1'b0}};
            input_valid <= 1'b0;
            input_bin_idx <= 12'd0;
            input_frame_count <= 3'd0;
            xfft_config_tvalid <= 1'b0;
            xfft_configured <= 1'b0;
            tile_capture_time_idx <= 2'd0;
            tile_capture_armed <= 1'b0;
            tile_valid <= {TILE_BUFFERS{1'b0}};
            capture_buf_sel <= 1'b0;
            emit_buf_sel <= 1'b0;
            tile_rd_addr <= {TILE_TOTAL_BEAT_AW{1'b0}};
            emit_block_idx <= 6'd0;
            emit_beat_idx <= 6'd0;
            emit_read_wait <= 1'b0;
            emit_read_load <= 1'b0;
            output_word <= {DATA_W{1'b0}};
            output_sample0 <= 64'd0;
            output_valid <= 1'b0;
            packet_chan0_reg <= 32'd0;
            packet_chan_count_reg <= 16'd0;
            packet_time_count_reg <= 16'd0;
            frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
            frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
            frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
            frame_count <= 32'd0;
            overflow_count <= 32'd0;
            data_halt_count <= 32'd0;
            xfft_event_count <= 32'd0;
            tile_overflow_count <= 32'd0;
            xfft_tlast_unexpected_count <= 32'd0;
            xfft_tlast_missing_count <= 32'd0;
            xfft_fft_overflow_count <= 32'd0;
            xfft_data_out_halt_count <= 32'd0;
            xfft_status_halt_count <= 32'd0;
            capture_backpressure_count <= 32'd0;
            frame_sample0_overflow_count <= 32'd0;
            peak_chan <= 32'd0;
            peak_power <= 32'd0;
            for (reset_buf = 0; reset_buf < TILE_BUFFERS; reset_buf = reset_buf + 1) begin
                for (reset_frame = 0; reset_frame < TILE_FRAMES; reset_frame = reset_frame + 1) begin
                    tile_sample0[reset_buf][reset_frame] <= 64'd0;
                end
            end
        end else begin
            if (!config_valid) begin
                input_valid <= 1'b0;
                input_subidx <= {PACK_IDX_W{1'b0}};
                input_bin_idx <= 12'd0;
                input_frame_count <= 3'd0;
                xfft_config_tvalid <= 1'b0;
                xfft_configured <= 1'b0;
                tile_capture_time_idx <= 2'd0;
                tile_capture_armed <= 1'b0;
                tile_valid <= {TILE_BUFFERS{1'b0}};
                capture_buf_sel <= 1'b0;
                emit_buf_sel <= 1'b0;
                tile_rd_addr <= {TILE_TOTAL_BEAT_AW{1'b0}};
                emit_block_idx <= 6'd0;
                emit_beat_idx <= 6'd0;
                emit_read_wait <= 1'b0;
                emit_read_load <= 1'b0;
                output_valid <= 1'b0;
                packet_chan_count_reg <= 16'd0;
                packet_time_count_reg <= 16'd0;
                frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
                if (clear) begin
                    frame_count <= 32'd0;
                    overflow_count <= 32'd0;
                    data_halt_count <= 32'd0;
                    xfft_event_count <= 32'd0;
                    tile_overflow_count <= 32'd0;
                    xfft_tlast_unexpected_count <= 32'd0;
                    xfft_tlast_missing_count <= 32'd0;
                    xfft_fft_overflow_count <= 32'd0;
                    xfft_data_out_halt_count <= 32'd0;
                    xfft_status_halt_count <= 32'd0;
                    capture_backpressure_count <= 32'd0;
                    frame_sample0_overflow_count <= 32'd0;
                    peak_chan <= 32'd0;
                    peak_power <= 32'd0;
                    for (reset_buf = 0; reset_buf < TILE_BUFFERS; reset_buf = reset_buf + 1) begin
                        for (reset_frame = 0; reset_frame < TILE_FRAMES; reset_frame = reset_frame + 1) begin
                            tile_sample0[reset_buf][reset_frame] <= 64'd0;
                        end
                    end
                end
            end else begin
                if (!xfft_configured && !xfft_config_tvalid) begin
                    xfft_config_tvalid <= 1'b1;
                end
                if (xfft_config_tvalid && xfft_config_tready) begin
                    xfft_config_tvalid <= 1'b0;
                    xfft_configured <= 1'b1;
                end

                if (clear || !enable) begin
                    input_valid <= 1'b0;
                    input_subidx <= {PACK_IDX_W{1'b0}};
                    input_bin_idx <= 12'd0;
                    input_frame_count <= 3'd0;
                    tile_capture_time_idx <= 2'd0;
                    tile_capture_armed <= 1'b0;
                    tile_valid <= {TILE_BUFFERS{1'b0}};
                    capture_buf_sel <= 1'b0;
                    emit_buf_sel <= 1'b0;
                    tile_rd_addr <= {TILE_TOTAL_BEAT_AW{1'b0}};
                    emit_block_idx <= 6'd0;
                    emit_beat_idx <= 6'd0;
                    emit_read_wait <= 1'b0;
                    emit_read_load <= 1'b0;
                    output_valid <= 1'b0;
                    packet_chan_count_reg <= 16'd0;
                    packet_time_count_reg <= 16'd0;
                    frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
                    frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
                    frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
                    if (clear) begin
                        frame_count <= 32'd0;
                        overflow_count <= 32'd0;
                        data_halt_count <= 32'd0;
                        xfft_event_count <= 32'd0;
                        tile_overflow_count <= 32'd0;
                        xfft_tlast_unexpected_count <= 32'd0;
                        xfft_tlast_missing_count <= 32'd0;
                        xfft_fft_overflow_count <= 32'd0;
                        xfft_data_out_halt_count <= 32'd0;
                        xfft_status_halt_count <= 32'd0;
                        capture_backpressure_count <= 32'd0;
                        frame_sample0_overflow_count <= 32'd0;
                        peak_chan <= 32'd0;
                        peak_power <= 32'd0;
                        for (reset_buf = 0; reset_buf < TILE_BUFFERS; reset_buf = reset_buf + 1) begin
                            for (reset_frame = 0; reset_frame < TILE_FRAMES; reset_frame = reset_frame + 1) begin
                                tile_sample0[reset_buf][reset_frame] <= 64'd0;
                            end
                        end
                    end
                end else begin
                if (output_fire) begin
                    output_valid <= 1'b0;
                    if (emit_tile_last_beat) begin
                        tile_valid[emit_buf_sel] <= 1'b0;
                        emit_block_idx <= 6'd0;
                        emit_beat_idx <= 6'd0;
                        frame_count <= frame_count + 32'd1;
                        if (other_emit_buffer_valid) begin
                            emit_buf_sel <= ~emit_buf_sel;
                        end
                        if ((input_frame_count == TILE_FRAME_COUNT_U3) &&
                            tile_valid[capture_buf_sel] &&
                            (emit_buf_sel != capture_buf_sel)) begin
                            capture_buf_sel <= emit_buf_sel;
                            input_frame_count <= 3'd0;
                            tile_capture_time_idx <= 2'd0;
                            tile_capture_armed <= 1'b0;
                        end
                    end else if (emit_packet_last_beat) begin
                        emit_beat_idx <= 6'd0;
                        emit_block_idx <= emit_block_idx + 6'd1;
                    end else begin
                        emit_beat_idx <= emit_beat_idx + 6'd1;
                    end
                end

                if (load_input) begin
                    input_word <= input_fifo_dout[0 +: DATA_W];
                    input_sample0 <= input_fifo_dout[DATA_W +: 64];
                    input_valid <= 1'b1;
                    input_subidx <= {PACK_IDX_W{1'b0}};
                end else if (input_last_cell_fire) begin
                    input_valid <= 1'b0;
                    input_subidx <= {PACK_IDX_W{1'b0}};
                end else if (xfft_input_fire) begin
                    input_subidx <= input_subidx + {{(PACK_IDX_W-1){1'b0}}, 1'b1};
                end

                if (xfft_input_fire) begin
                    tile_capture_armed <= 1'b1;
                    if (input_bin_idx == 12'd4095) begin
                        input_bin_idx <= 12'd0;
                        if (input_frame_count != TILE_FRAME_COUNT_U3) begin
                            input_frame_count <= input_frame_count + 3'd1;
                        end
                    end else begin
                        input_bin_idx <= input_bin_idx + 12'd1;
                    end
                end

                if (frame_sample0_push) begin
                    frame_fifo_wr_ptr <= frame_fifo_wr_ptr + {{(FRAME_FIFO_AW-1){1'b0}}, 1'b1};
                end
                if (frame_sample0_pop) begin
                    frame_fifo_rd_ptr <= frame_fifo_rd_ptr + {{(FRAME_FIFO_AW-1){1'b0}}, 1'b1};
                end
                case ({frame_sample0_push, frame_sample0_pop})
                    2'b10: if (frame_fifo_count != FRAME_FIFO_DEPTH_COUNT) begin
                        frame_fifo_count <= frame_fifo_count + {{FRAME_FIFO_AW{1'b0}}, 1'b1};
                    end
                    2'b01: if (frame_fifo_count != FRAME_FIFO_ZERO_COUNT) begin
                        frame_fifo_count <= frame_fifo_count - {{FRAME_FIFO_AW{1'b0}}, 1'b1};
                    end
                    default: frame_fifo_count <= frame_fifo_count;
                endcase

                if (accept_xfft_output) begin
                    if (!capture_buffer_free) begin
                        tile_overflow_count <= tile_overflow_count + 32'd1;
                    end
                    if (xfft_bin == 12'd0) begin
                        tile_sample0[capture_buf_sel][tile_capture_time_idx] <= current_output_frame_sample0;
                    end
`ifndef T510_STAGE27H_PRODUCTION_ONLY
                    if (cell_metric(xfft_m_axis_tdata) >= peak_power) begin
                        peak_power <= cell_metric(xfft_m_axis_tdata);
                        peak_chan <= xfft_bin_ext;
                    end
`endif
                    if (xfft_m_axis_tlast && capture_buffer_free) begin
                        if (tile_capture_time_idx == TILE_FRAME_LAST_U2) begin
                            tile_valid[capture_buf_sel] <= 1'b1;
                            if (!tile_valid[~capture_buf_sel]) begin
                                capture_buf_sel <= ~capture_buf_sel;
                                input_frame_count <= 3'd0;
                                tile_capture_time_idx <= 2'd0;
                                tile_capture_armed <= 1'b0;
                            end
                        end else begin
                            tile_capture_time_idx <= tile_capture_time_idx + 2'd1;
                        end
                    end
                end

                if (emit_read_load) begin
                    emit_read_load <= 1'b0;
                    output_word <= tile_rd_data;
                    output_sample0 <= tile_sample0[emit_buf_sel][0];
                    output_valid <= 1'b1;
                    packet_chan0_reg <= {22'd0, emit_block_idx[3:0], 8'd0};
                    packet_chan_count_reg <= 16'd256;
                    packet_time_count_reg <= 16'd1;
                end else if (emit_read_wait) begin
                    emit_read_wait <= 1'b0;
                    emit_read_load <= 1'b1;
                end else if (emit_can_issue_read) begin
                    tile_rd_addr <= {emit_buf_sel, emit_tile_beat_addr};
                    emit_read_wait <= 1'b1;
                end else if (!emit_buffer_valid && other_emit_buffer_valid &&
                             !emit_read_wait && !emit_read_load && !output_valid) begin
                    emit_buf_sel <= ~emit_buf_sel;
                end

                if (xfft_event_tlast_unexpected ||
                    xfft_event_tlast_missing ||
                    xfft_event_fft_overflow ||
                    capture_overflow ||
                    (frame_sample0_enqueue && !frame_sample0_push)) begin
                    overflow_count <= overflow_count + 32'd1;
                end
                if (xfft_event_tlast_unexpected ||
                    xfft_event_tlast_missing ||
                    xfft_event_fft_overflow) begin
                    xfft_event_count <= xfft_event_count + 32'd1;
                end
                if (xfft_event_data_in_channel_halt) begin
                    data_halt_count <= data_halt_count + 32'd1;
                end
                if (xfft_event_tlast_unexpected) begin
                    xfft_tlast_unexpected_count <= xfft_tlast_unexpected_count + 32'd1;
                end
                if (xfft_event_tlast_missing) begin
                    xfft_tlast_missing_count <= xfft_tlast_missing_count + 32'd1;
                end
                if (xfft_event_fft_overflow) begin
                    xfft_fft_overflow_count <= xfft_fft_overflow_count + 32'd1;
                end
                if (xfft_event_data_out_channel_halt) begin
                    xfft_data_out_halt_count <= xfft_data_out_halt_count + 32'd1;
                end
                if (xfft_event_status_channel_halt) begin
                    xfft_status_halt_count <= xfft_status_halt_count + 32'd1;
                end
                if (capture_backpressure) begin
                    capture_backpressure_count <= capture_backpressure_count + 32'd1;
                end
                if (capture_overflow || (frame_sample0_enqueue && !frame_sample0_push)) begin
                    tile_overflow_count <= tile_overflow_count + 32'd1;
                end
                if (frame_sample0_enqueue && !frame_sample0_push) begin
                    frame_sample0_overflow_count <= frame_sample0_overflow_count + 32'd1;
                end
                end
            end
        end
    end

    assign status = {
        xfft_config_ready_debug,
        xfft_config_done_debug,
        cfg_fft_shift[3:0],
        xfft_config_tready,
        xfft_config_tvalid,
        xfft_configured,
        1'b1,
        (data_halt_count != 32'd0),
        (input_fifo_level >= INPUT_BEATS_PER_FRAME),
        science_valid && xfft_configured,
        feng_busy,
        (overflow_count != 32'd0),
        output_valid,
        config_valid,
        enable
    };

endmodule

`ifdef T510_STAGE27H_PRODUCTION_ONLY
module feng_channelizer_4096_streaming_27h #(
    parameter integer DATA_W = 1024,
    parameter integer NINPUT = 8,
    parameter integer NCHAN  = 4096
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 clear,
    input  wire [15:0]          cfg_taps,
    input  wire [15:0]          cfg_fft_shift,
    input  wire [31:0]          cfg_chan0,
    input  wire [15:0]          cfg_chan_count,
    input  wire [15:0]          cfg_time_count,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [63:0]          s_axis_sample0,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [63:0]          m_axis_sample0,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire [31:0]          status,
    output logic [31:0]         frame_count,
    output logic [31:0]         overflow_count,
    output logic [31:0]         data_halt_count,
    output logic [31:0]         xfft_event_count,
    output logic [31:0]         tile_overflow_count,
    output logic [31:0]         xfft_tlast_unexpected_count,
    output logic [31:0]         xfft_tlast_missing_count,
    output logic [31:0]         xfft_fft_overflow_count,
    output logic [31:0]         xfft_data_out_halt_count,
    output logic [31:0]         xfft_status_halt_count,
    output logic [31:0]         capture_backpressure_count,
    output logic [31:0]         frame_sample0_overflow_count,
    output wire [31:0]          input_fifo_level,
    output logic [31:0]         peak_chan,
    output logic [31:0]         peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

    localparam integer CELL_W = NINPUT * 32;
    localparam integer CELLS_PER_BEAT = DATA_W / CELL_W;
    localparam integer PACK_IDX_W = (CELLS_PER_BEAT <= 1) ? 1 : $clog2(CELLS_PER_BEAT);
    localparam integer FRAME_FIFO_DEPTH = 16;
    localparam integer FRAME_FIFO_AW = 4;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_DEPTH_COUNT = FRAME_FIFO_DEPTH;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_ZERO_COUNT = {(FRAME_FIFO_AW+1){1'b0}};

    logic [DATA_W-1:0] input_word;
    logic [63:0]       input_sample0;
    logic [PACK_IDX_W-1:0] input_subidx;
    logic              input_valid;
    logic [11:0]       input_bin_idx;

    wire [CELL_W-1:0] selected_input_cell =
        input_word[input_subidx*CELL_W +: CELL_W];
    wire [63:0] selected_input_sample0 =
        input_sample0 + {{(64-PACK_IDX_W){1'b0}}, input_subidx};
    wire [23:0] xfft_scale_schedule = (cfg_fft_shift == 16'd0) ? 24'd0 : {8'h55, cfg_fft_shift};

    logic [255:0] xfft_config_tdata;
    logic         xfft_config_tvalid;
    wire          xfft_config_tready;
    logic         xfft_configured;

    wire config_valid =
        (DATA_W >= CELL_W) &&
        ((DATA_W % CELL_W) == 0) &&
        (CELLS_PER_BEAT == 4) &&
        (NINPUT == 8) &&
        (NCHAN == 4096) &&
        (cfg_taps == 16'd0) &&
        (cfg_chan0 == 32'd0) &&
        (cfg_chan_count == 16'd256) &&
        (cfg_time_count == 16'd1);
    wire science_valid = config_valid && xfft_configured;

    wire xfft_s_axis_tvalid = enable && config_valid && xfft_configured && input_valid;
    wire xfft_s_axis_tready;
    wire xfft_s_axis_tlast = (input_bin_idx == 12'd4095);
    wire xfft_input_fire = xfft_s_axis_tvalid && xfft_s_axis_tready;
    wire input_last_cell_fire = xfft_input_fire && (input_subidx == (CELLS_PER_BEAT - 1));
    wire input_word_fire = s_axis_tvalid && s_axis_tready;

    assign s_axis_tready = enable && config_valid && xfft_configured &&
                           (!input_valid || input_last_cell_fire);

    wire [255:0] xfft_m_axis_tdata;
    wire [23:0]  xfft_m_axis_tuser;
    wire         xfft_m_axis_tvalid;
    wire         xfft_m_axis_tready;
    wire         xfft_m_axis_tlast;
    wire [7:0]   xfft_m_axis_status_tdata;
    wire         xfft_m_axis_status_tvalid;
    wire         xfft_m_axis_status_tready;
    wire         xfft_event_frame_started;
    wire         xfft_event_tlast_unexpected;
    wire         xfft_event_tlast_missing;
    wire         xfft_event_fft_overflow;
    wire         xfft_event_status_channel_halt;
    wire         xfft_event_data_in_channel_halt;
    wire         xfft_event_data_out_channel_halt;
    wire [7:0]   xfft_config_done_debug;
    wire [7:0]   xfft_config_ready_debug;

    logic [DATA_W-1:0] pack_word;
    logic [DATA_W-1:0] pack_word_next;
    logic [PACK_IDX_W-1:0] pack_subidx;
    logic [DATA_W-1:0] output_word;
    logic [63:0]       output_sample0;
    logic              output_valid;
    logic [31:0]       packet_chan0_reg;

    wire [11:0] xfft_bin = xfft_m_axis_tuser[11:0];
    wire output_fire = output_valid && m_axis_tready;
    wire output_slot_ready = !output_valid || m_axis_tready;
    assign xfft_m_axis_tready = output_slot_ready;
    assign xfft_m_axis_status_tready = 1'b1;
    wire xfft_output_fire = xfft_m_axis_tvalid && xfft_m_axis_tready;
    wire pack_last_cell = (xfft_bin[1:0] == 2'd3);

    (* ram_style = "distributed" *) logic [63:0] frame_sample0_fifo [0:FRAME_FIFO_DEPTH-1];
    logic [FRAME_FIFO_AW-1:0] frame_fifo_wr_ptr;
    logic [FRAME_FIFO_AW-1:0] frame_fifo_rd_ptr;
    logic [FRAME_FIFO_AW:0]   frame_fifo_count;
    wire frame_fifo_empty = (frame_fifo_count == FRAME_FIFO_ZERO_COUNT);
    wire frame_fifo_full = (frame_fifo_count == FRAME_FIFO_DEPTH_COUNT);
    wire frame_sample0_enqueue = xfft_input_fire && (input_bin_idx == 12'd0);
    wire frame_sample0_dequeue = xfft_output_fire && xfft_m_axis_tlast;
    wire frame_sample0_push = frame_sample0_enqueue && (!frame_fifo_full || frame_sample0_dequeue);
    wire frame_sample0_pop = frame_sample0_dequeue && !frame_fifo_empty;
    wire [63:0] current_output_frame_sample0 =
        !frame_fifo_empty ? frame_sample0_fifo[frame_fifo_rd_ptr] : selected_input_sample0;

    wire feng_busy =
        input_valid ||
        (input_bin_idx != 12'd0) ||
        output_valid ||
        (pack_subidx != {PACK_IDX_W{1'b0}}) ||
        xfft_config_tvalid;

    assign m_axis_tdata = output_word;
    assign m_axis_sample0 = output_sample0;
    assign m_axis_tvalid = output_valid;
    assign packet_chan0 = packet_chan0_reg;
    assign packet_chan_count = 16'd256;
    assign packet_time_count = 16'd1;
    assign input_fifo_level = 32'd0;

    always_comb begin
        xfft_config_tdata = 256'd0;
        xfft_config_tdata[7:0] = 8'hff;
        xfft_config_tdata[31:8] = xfft_scale_schedule;
        xfft_config_tdata[55:32] = xfft_scale_schedule;
        xfft_config_tdata[79:56] = xfft_scale_schedule;
        xfft_config_tdata[103:80] = xfft_scale_schedule;
        xfft_config_tdata[127:104] = xfft_scale_schedule;
        xfft_config_tdata[151:128] = xfft_scale_schedule;
        xfft_config_tdata[175:152] = xfft_scale_schedule;
        xfft_config_tdata[199:176] = xfft_scale_schedule;
    end

    always_comb begin
        pack_word_next = pack_word;
        pack_word_next[pack_subidx*CELL_W +: CELL_W] = xfft_m_axis_tdata;
    end

`ifdef T510_SIM_FFT_MODEL
    t510_fengine_xfft_4096_sim_model u_fengine_xfft_4096 (
        .aclk(clk),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(selected_input_cell),
        .s_axis_data_tvalid(xfft_s_axis_tvalid),
        .s_axis_data_tready(xfft_s_axis_tready),
        .s_axis_data_tlast(xfft_s_axis_tlast),
        .m_axis_data_tdata(xfft_m_axis_tdata),
        .m_axis_data_tuser(xfft_m_axis_tuser),
        .m_axis_data_tvalid(xfft_m_axis_tvalid),
        .m_axis_data_tready(xfft_m_axis_tready),
        .m_axis_data_tlast(xfft_m_axis_tlast),
        .m_axis_status_tdata(xfft_m_axis_status_tdata),
        .m_axis_status_tvalid(xfft_m_axis_status_tvalid),
        .m_axis_status_tready(xfft_m_axis_status_tready),
        .event_frame_started(xfft_event_frame_started),
        .event_tlast_unexpected(xfft_event_tlast_unexpected),
        .event_tlast_missing(xfft_event_tlast_missing),
        .event_fft_overflow(xfft_event_fft_overflow),
        .event_status_channel_halt(xfft_event_status_channel_halt),
        .event_data_in_channel_halt(xfft_event_data_in_channel_halt),
        .event_data_out_channel_halt(xfft_event_data_out_channel_halt)
    );
    assign xfft_config_done_debug = xfft_configured ? 8'hff : 8'h00;
    assign xfft_config_ready_debug = {8{xfft_config_tready}};
`else
    t510_fengine_xfft_4096_8lane_streaming u_fengine_xfft_4096 (
        .aclk(clk),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(selected_input_cell),
        .s_axis_data_tvalid(xfft_s_axis_tvalid),
        .s_axis_data_tready(xfft_s_axis_tready),
        .s_axis_data_tlast(xfft_s_axis_tlast),
        .m_axis_data_tdata(xfft_m_axis_tdata),
        .m_axis_data_tuser(xfft_m_axis_tuser),
        .m_axis_data_tvalid(xfft_m_axis_tvalid),
        .m_axis_data_tready(xfft_m_axis_tready),
        .m_axis_data_tlast(xfft_m_axis_tlast),
        .m_axis_status_tdata(xfft_m_axis_status_tdata),
        .m_axis_status_tvalid(xfft_m_axis_status_tvalid),
        .m_axis_status_tready(xfft_m_axis_status_tready),
        .event_frame_started(xfft_event_frame_started),
        .event_tlast_unexpected(xfft_event_tlast_unexpected),
        .event_tlast_missing(xfft_event_tlast_missing),
        .event_fft_overflow(xfft_event_fft_overflow),
        .event_status_channel_halt(xfft_event_status_channel_halt),
        .event_data_in_channel_halt(xfft_event_data_in_channel_halt),
        .event_data_out_channel_halt(xfft_event_data_out_channel_halt),
        .config_done_debug(xfft_config_done_debug),
        .config_ready_debug(xfft_config_ready_debug)
    );
`endif

    always_ff @(posedge clk) begin
        if (frame_sample0_push) begin
            frame_sample0_fifo[frame_fifo_wr_ptr] <= selected_input_sample0;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            input_word <= {DATA_W{1'b0}};
            input_sample0 <= 64'd0;
            input_subidx <= {PACK_IDX_W{1'b0}};
            input_valid <= 1'b0;
            input_bin_idx <= 12'd0;
            xfft_config_tvalid <= 1'b0;
            xfft_configured <= 1'b0;
            pack_word <= {DATA_W{1'b0}};
            pack_subidx <= {PACK_IDX_W{1'b0}};
            output_word <= {DATA_W{1'b0}};
            output_sample0 <= 64'd0;
            output_valid <= 1'b0;
            packet_chan0_reg <= 32'd0;
            frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
            frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
            frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
            frame_count <= 32'd0;
            overflow_count <= 32'd0;
            data_halt_count <= 32'd0;
            xfft_event_count <= 32'd0;
            tile_overflow_count <= 32'd0;
            xfft_tlast_unexpected_count <= 32'd0;
            xfft_tlast_missing_count <= 32'd0;
            xfft_fft_overflow_count <= 32'd0;
            xfft_data_out_halt_count <= 32'd0;
            xfft_status_halt_count <= 32'd0;
            capture_backpressure_count <= 32'd0;
            frame_sample0_overflow_count <= 32'd0;
            peak_chan <= 32'd0;
            peak_power <= 32'd0;
        end else begin
            if (!config_valid) begin
                input_valid <= 1'b0;
                input_subidx <= {PACK_IDX_W{1'b0}};
                input_bin_idx <= 12'd0;
                xfft_config_tvalid <= 1'b0;
                xfft_configured <= 1'b0;
                pack_subidx <= {PACK_IDX_W{1'b0}};
                output_valid <= 1'b0;
                frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
                if (clear) begin
                    frame_count <= 32'd0;
                    overflow_count <= 32'd0;
                    data_halt_count <= 32'd0;
                    xfft_event_count <= 32'd0;
                    tile_overflow_count <= 32'd0;
                    xfft_tlast_unexpected_count <= 32'd0;
                    xfft_tlast_missing_count <= 32'd0;
                    xfft_fft_overflow_count <= 32'd0;
                    xfft_data_out_halt_count <= 32'd0;
                    xfft_status_halt_count <= 32'd0;
                    capture_backpressure_count <= 32'd0;
                    frame_sample0_overflow_count <= 32'd0;
                    peak_chan <= 32'd0;
                    peak_power <= 32'd0;
                end
            end else begin
                if (!xfft_configured && !xfft_config_tvalid) begin
                    xfft_config_tvalid <= 1'b1;
                end
                if (xfft_config_tvalid && xfft_config_tready) begin
                    xfft_config_tvalid <= 1'b0;
                    xfft_configured <= 1'b1;
                end

                if (clear || !enable) begin
                    input_valid <= 1'b0;
                    input_subidx <= {PACK_IDX_W{1'b0}};
                    input_bin_idx <= 12'd0;
                    pack_subidx <= {PACK_IDX_W{1'b0}};
                    output_valid <= 1'b0;
                    frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
                    frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
                    frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
                    if (clear) begin
                        frame_count <= 32'd0;
                        overflow_count <= 32'd0;
                        data_halt_count <= 32'd0;
                        xfft_event_count <= 32'd0;
                        tile_overflow_count <= 32'd0;
                        xfft_tlast_unexpected_count <= 32'd0;
                        xfft_tlast_missing_count <= 32'd0;
                        xfft_fft_overflow_count <= 32'd0;
                        xfft_data_out_halt_count <= 32'd0;
                        xfft_status_halt_count <= 32'd0;
                        capture_backpressure_count <= 32'd0;
                        frame_sample0_overflow_count <= 32'd0;
                        peak_chan <= 32'd0;
                        peak_power <= 32'd0;
                    end
                end else begin
                    if (output_fire && !(xfft_output_fire && pack_last_cell)) begin
                        output_valid <= 1'b0;
                    end

                    if (input_word_fire) begin
                        input_word <= s_axis_tdata;
                        input_sample0 <= s_axis_sample0;
                        input_valid <= 1'b1;
                        input_subidx <= {PACK_IDX_W{1'b0}};
                    end else if (input_last_cell_fire) begin
                        input_valid <= 1'b0;
                        input_subidx <= {PACK_IDX_W{1'b0}};
                    end else if (xfft_input_fire) begin
                        input_subidx <= input_subidx + {{(PACK_IDX_W-1){1'b0}}, 1'b1};
                    end

                    if (xfft_input_fire) begin
                        if (input_bin_idx == 12'd4095) begin
                            input_bin_idx <= 12'd0;
                        end else begin
                            input_bin_idx <= input_bin_idx + 12'd1;
                        end
                    end

                    if (xfft_output_fire) begin
                        pack_word <= pack_word_next;
                        if (pack_last_cell) begin
                            output_word <= pack_word_next;
                            output_sample0 <= current_output_frame_sample0;
                            output_valid <= 1'b1;
                            packet_chan0_reg <= {20'd0, xfft_bin[11:8], 8'd0};
                            pack_subidx <= {PACK_IDX_W{1'b0}};
                        end else begin
                            pack_subidx <= pack_subidx + {{(PACK_IDX_W-1){1'b0}}, 1'b1};
                        end
                        if (xfft_m_axis_tlast) begin
                            frame_count <= frame_count + 32'd1;
                        end
                    end

                    if (frame_sample0_push) begin
                        frame_fifo_wr_ptr <= frame_fifo_wr_ptr + {{(FRAME_FIFO_AW-1){1'b0}}, 1'b1};
                    end
                    if (frame_sample0_pop) begin
                        frame_fifo_rd_ptr <= frame_fifo_rd_ptr + {{(FRAME_FIFO_AW-1){1'b0}}, 1'b1};
                    end
                    case ({frame_sample0_push, frame_sample0_pop})
                        2'b10: if (frame_fifo_count != FRAME_FIFO_DEPTH_COUNT) begin
                            frame_fifo_count <= frame_fifo_count + {{FRAME_FIFO_AW{1'b0}}, 1'b1};
                        end
                        2'b01: if (frame_fifo_count != FRAME_FIFO_ZERO_COUNT) begin
                            frame_fifo_count <= frame_fifo_count - {{FRAME_FIFO_AW{1'b0}}, 1'b1};
                        end
                        default: frame_fifo_count <= frame_fifo_count;
                    endcase

                    if (xfft_event_tlast_unexpected ||
                        xfft_event_tlast_missing ||
                        xfft_event_fft_overflow ||
                        (frame_sample0_enqueue && !frame_sample0_push)) begin
                        overflow_count <= overflow_count + 32'd1;
                    end
                    if (xfft_event_tlast_unexpected ||
                        xfft_event_tlast_missing ||
                        xfft_event_fft_overflow) begin
                        xfft_event_count <= xfft_event_count + 32'd1;
                    end
                    if (xfft_event_data_in_channel_halt) begin
                        data_halt_count <= data_halt_count + 32'd1;
                    end
                    if (xfft_event_tlast_unexpected) begin
                        xfft_tlast_unexpected_count <= xfft_tlast_unexpected_count + 32'd1;
                    end
                    if (xfft_event_tlast_missing) begin
                        xfft_tlast_missing_count <= xfft_tlast_missing_count + 32'd1;
                    end
                    if (xfft_event_fft_overflow) begin
                        xfft_fft_overflow_count <= xfft_fft_overflow_count + 32'd1;
                    end
                    if (xfft_event_data_out_channel_halt) begin
                        xfft_data_out_halt_count <= xfft_data_out_halt_count + 32'd1;
                    end
                    if (xfft_event_status_channel_halt) begin
                        xfft_status_halt_count <= xfft_status_halt_count + 32'd1;
                    end
                    if (output_valid && !m_axis_tready) begin
                        capture_backpressure_count <= capture_backpressure_count + 32'd1;
                    end
                    if (frame_sample0_enqueue && !frame_sample0_push) begin
                        frame_sample0_overflow_count <= frame_sample0_overflow_count + 32'd1;
                    end
                end
            end
        end
    end

    assign status = {
        xfft_config_ready_debug,
        xfft_config_done_debug,
        cfg_fft_shift[3:0],
        xfft_config_tready,
        xfft_config_tvalid,
        xfft_configured,
        1'b1,
        (data_halt_count != 32'd0),
        s_axis_tready,
        science_valid,
        feng_busy,
        (overflow_count != 32'd0),
        output_valid,
        config_valid,
        enable
    };

endmodule
`endif

module pfb_channelizer #(
    parameter integer DATA_W = 1024,
    parameter integer NINPUT = 8,
    parameter integer NCHAN  = 4096
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 clear,
    input  wire [15:0]          cfg_taps,
    input  wire [15:0]          cfg_fft_shift,
    input  wire [31:0]          cfg_chan0,
    input  wire [15:0]          cfg_chan_count,
    input  wire [15:0]          cfg_time_count,
    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire [63:0]          s_axis_sample0,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,
    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire [63:0]          m_axis_sample0,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire [31:0]          status,
    output wire [31:0]          frame_count,
    output wire [31:0]          overflow_count,
    output wire [31:0]          data_halt_count,
    output wire [31:0]          xfft_event_count,
    output wire [31:0]          tile_overflow_count,
    output wire [31:0]          xfft_tlast_unexpected_count,
    output wire [31:0]          xfft_tlast_missing_count,
    output wire [31:0]          xfft_fft_overflow_count,
    output wire [31:0]          xfft_data_out_halt_count,
    output wire [31:0]          xfft_status_halt_count,
    output wire [31:0]          capture_backpressure_count,
    output wire [31:0]          frame_sample0_overflow_count,
    output wire [31:0]          input_fifo_level,
    output wire [31:0]          peak_chan,
    output wire [31:0]          peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    feng_channelizer_4096_streaming_27h #(
        .DATA_W(DATA_W),
        .NINPUT(NINPUT),
        .NCHAN(NCHAN)
    ) u_feng_channelizer_4096 (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .cfg_taps(cfg_taps),
        .cfg_fft_shift(cfg_fft_shift),
        .cfg_chan0(cfg_chan0),
        .cfg_chan_count(cfg_chan_count),
        .cfg_time_count(cfg_time_count),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .status(status),
        .frame_count(frame_count),
        .overflow_count(overflow_count),
        .data_halt_count(data_halt_count),
        .xfft_event_count(xfft_event_count),
        .tile_overflow_count(tile_overflow_count),
        .xfft_tlast_unexpected_count(xfft_tlast_unexpected_count),
        .xfft_tlast_missing_count(xfft_tlast_missing_count),
        .xfft_fft_overflow_count(xfft_fft_overflow_count),
        .xfft_data_out_halt_count(xfft_data_out_halt_count),
        .xfft_status_halt_count(xfft_status_halt_count),
        .capture_backpressure_count(capture_backpressure_count),
        .frame_sample0_overflow_count(frame_sample0_overflow_count),
        .input_fifo_level(input_fifo_level),
        .peak_chan(peak_chan),
        .peak_power(peak_power),
        .packet_chan0(packet_chan0),
        .packet_chan_count(packet_chan_count),
        .packet_time_count(packet_time_count)
    );
`else
    feng_channelizer_4096 #(
        .DATA_W(DATA_W),
        .NINPUT(NINPUT),
        .NCHAN(NCHAN)
    ) u_feng_channelizer_4096 (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .cfg_taps(cfg_taps),
        .cfg_fft_shift(cfg_fft_shift),
        .cfg_chan0(cfg_chan0),
        .cfg_chan_count(cfg_chan_count),
        .cfg_time_count(cfg_time_count),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_sample0(s_axis_sample0),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_sample0(m_axis_sample0),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .status(status),
        .frame_count(frame_count),
        .overflow_count(overflow_count),
        .data_halt_count(data_halt_count),
        .xfft_event_count(xfft_event_count),
        .tile_overflow_count(tile_overflow_count),
        .xfft_tlast_unexpected_count(xfft_tlast_unexpected_count),
        .xfft_tlast_missing_count(xfft_tlast_missing_count),
        .xfft_fft_overflow_count(xfft_fft_overflow_count),
        .xfft_data_out_halt_count(xfft_data_out_halt_count),
        .xfft_status_halt_count(xfft_status_halt_count),
        .capture_backpressure_count(capture_backpressure_count),
        .frame_sample0_overflow_count(frame_sample0_overflow_count),
        .input_fifo_level(input_fifo_level),
        .peak_chan(peak_chan),
        .peak_power(peak_power),
        .packet_chan0(packet_chan0),
        .packet_chan_count(packet_chan_count),
        .packet_time_count(packet_time_count)
    );
`endif

endmodule
