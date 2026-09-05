`ifdef T510_SIM_FFT_MODEL
module t510_fengine_xfft_4096_sim_model (
    input  wire         aclk,
    input  wire         aresetn,
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
        if (!aresetn) begin
            bin_idx <= 12'd0;
            m_axis_data_tdata <= 256'd0;
            m_axis_data_tuser <= 24'd0;
            m_axis_data_tvalid <= 1'b0;
            m_axis_data_tlast <= 1'b0;
            m_axis_status_tdata <= 8'd0;
            m_axis_status_tvalid <= 1'b0;
            event_frame_started <= 1'b0;
            event_tlast_unexpected <= 1'b0;
            event_tlast_missing <= 1'b0;
            event_fft_overflow <= 1'b0;
            event_status_channel_halt <= 1'b0;
            event_data_in_channel_halt <= 1'b0;
            event_data_out_channel_halt <= 1'b0;
        end else begin
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
    end
endmodule
`endif

module t510_fengine_xfft_4096_8lane_streaming (
    input  wire         aclk,
    input  wire         aresetn,
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
    wire [7:0]  lane_frame_started;
    wire [7:0]  lane_tlast_unexpected;
    wire [7:0]  lane_tlast_missing;
    wire [7:0]  lane_fft_overflow;
    wire [7:0]  lane_data_in_halt;
    wire [7:0]  lane_m_axis_tvalid;
    wire [7:0]  lane_m_axis_tlast;
    wire [191:0] lane_m_axis_tuser;
    wire [7:0]  lane_m_axis_ovflo;
    logic [7:0] lane_cfg_done = 8'd0;
    logic       lane_cfg_seen_valid = 1'b0;
    wire [7:0] lane_cfg_tvalid;
    wire [7:0] lane_cfg_fire;
    wire [7:0] lane_cfg_done_next;
    wire       lane_cfg_new_transaction = s_axis_config_tvalid && !lane_cfg_seen_valid;
    wire [7:0] lane_cfg_done_base = lane_cfg_new_transaction ? 8'd0 : lane_cfg_done;
    wire all_lane_data_valid = &lane_m_axis_tvalid;
    wire all_lane_status_valid = &lane_status_tvalid;

    assign lane_cfg_tvalid = {8{s_axis_config_tvalid}} & ~lane_cfg_done_base;
    assign lane_cfg_fire = lane_cfg_tvalid & lane_cfg_tready;
    assign lane_cfg_done_next = lane_cfg_done_base | lane_cfg_fire;
    assign s_axis_config_tready = s_axis_config_tvalid && (&lane_cfg_done_next);
    assign config_done_debug = lane_cfg_done_next;
    assign config_ready_debug = lane_cfg_tready;
    assign s_axis_data_tready = &lane_data_tready;
    assign lane_data_tvalid = {8{s_axis_data_tvalid && s_axis_data_tready}};
    assign lane_data_tlast = {8{s_axis_data_tlast}};

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            lane_cfg_seen_valid <= 1'b0;
            lane_cfg_done <= 8'd0;
        end else if (!s_axis_config_tvalid) begin
            lane_cfg_seen_valid <= 1'b0;
        end else begin
            lane_cfg_seen_valid <= 1'b1;
            lane_cfg_done <= lane_cfg_done_next;
        end
    end

    genvar lane;
    generate
        for (lane = 0; lane < 8; lane = lane + 1) begin : gen_lane_xfft
            wire [11:0] lane_scale_schedule =
                s_axis_config_tdata[(8 + lane*12) +: 12];
            wire [15:0] lane_config_tdata = {
                3'd0,
                lane_scale_schedule,
                s_axis_config_tdata[lane]
            };
            wire [23:0] lane_tuser;

            t510_fengine_xfft_4096_lane u_lane_xfft (
                .aclk(aclk),
                .aresetn(aresetn),
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
                .m_axis_data_tlast(lane_m_axis_tlast[lane]),
                .m_axis_status_tdata(lane_status_tdata[lane*8 +: 8]),
                .m_axis_status_tvalid(lane_status_tvalid[lane]),
                .event_frame_started(lane_frame_started[lane]),
                .event_tlast_unexpected(lane_tlast_unexpected[lane]),
                .event_tlast_missing(lane_tlast_missing[lane]),
                .event_fft_overflow(lane_fft_overflow[lane]),
                .event_data_in_channel_halt(lane_data_in_halt[lane])
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
        lane_status_tdata[7*8 +: 8],
        lane_status_tdata[6*8 +: 8],
        lane_status_tdata[5*8 +: 8],
        lane_status_tdata[4*8 +: 8],
        lane_status_tdata[3*8 +: 8],
        lane_status_tdata[2*8 +: 8],
        lane_status_tdata[1*8 +: 8],
        lane_status_tdata[0*8 +: 8]
    };
    assign event_frame_started = lane_frame_started[0];
    assign event_tlast_unexpected = |lane_tlast_unexpected;
    assign event_tlast_missing = |lane_tlast_missing;
    assign event_fft_overflow = |lane_fft_overflow;
    // Realtime XFFT lanes have no output/status TREADY ports.  Capacity is
    // reserved before a frame enters the XFFT, so these wrapper-level events
    // are assertions that the surrounding elastic storage stayed available.
    assign event_status_channel_halt = m_axis_status_tvalid && !m_axis_status_tready;
    assign event_data_in_channel_halt = |lane_data_in_halt;
    assign event_data_out_channel_halt = m_axis_data_tvalid && !m_axis_data_tready;

endmodule

// Fixed 8-tap PFB multiplier pipeline and streaming channelizer.
module t510_pfb_mult_16x18_pipe2 (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                ce,
    input  wire signed [15:0]  sample,
    input  wire signed [17:0]  coeff,
    output wire signed [35:0]  product
);

    wire [29:0] dsp_a = {{14{sample[15]}}, sample};
    wire [47:0] dsp_p;

    DSP48E2 #(
        .ACASCREG(1),
        .ADREG(0),
        .ALUMODEREG(0),
        .AREG(1),
        .BCASCREG(1),
        .BREG(1),
        .CARRYINREG(0),
        .CARRYINSELREG(0),
        .CREG(0),
        .DREG(0),
        .INMODEREG(0),
        .MREG(0),
        .OPMODEREG(0),
        .PREG(1),
        .USE_MULT("MULTIPLY"),
        .USE_SIMD("ONE48")
    ) u_dsp48e2 (
        .ACOUT(),
        .BCOUT(),
        .CARRYCASCOUT(),
        .CARRYOUT(),
        .MULTSIGNOUT(),
        .OVERFLOW(),
        .P(dsp_p),
        .PATTERNBDETECT(),
        .PATTERNDETECT(),
        .PCOUT(),
        .UNDERFLOW(),
        .XOROUT(),
        .A(dsp_a),
        .ACIN(30'd0),
        .ALUMODE(4'b0000),
        .B(coeff),
        .BCIN(18'd0),
        .C(48'd0),
        .CARRYCASCIN(1'b0),
        .CARRYIN(1'b0),
        .CARRYINSEL(3'b000),
        .CEA1(ce),
        .CEA2(ce),
        .CEAD(1'b0),
        .CEALUMODE(1'b0),
        .CEB1(ce),
        .CEB2(ce),
        .CEC(1'b0),
        .CECARRYIN(1'b0),
        .CECTRL(1'b0),
        .CED(1'b0),
        .CEINMODE(1'b0),
        .CEM(1'b0),
        .CEP(ce),
        .CLK(clk),
        .D(27'd0),
        .INMODE(5'b00000),
        .MULTSIGNIN(1'b0),
        .OPMODE(9'b000000101),
        .PCIN(48'd0),
        // Data is qualified by the explicitly reset valid pipeline.  Keeping
        // the DSP data registers out of reset removes a CMAC-domain reset tree
        // from every PFB multiplier without exposing unqualified samples.
        .RSTA(1'b0),
        .RSTALLCARRYIN(1'b0),
        .RSTALUMODE(1'b0),
        .RSTB(1'b0),
        .RSTC(1'b0),
        .RSTCTRL(1'b0),
        .RSTD(1'b0),
        .RSTINMODE(1'b0),
        .RSTM(1'b0),
        .RSTP(1'b0)
    );

    assign product = dsp_p[35:0];

endmodule

module feng_channelizer_4096_streaming #(
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
    input  wire                 coeff_load_start,
    input  wire                 coeff_commit,
    input  wire                 coeff_abort,
    input  wire                 coeff_write,
    input  wire [3:0]           coeff_requested_taps,
    input  wire [14:0]          coeff_index,
    input  wire signed [17:0]   coeff_data,
    input  wire [31:0]          coeff_id,
    output wire [31:0]          coeff_status,
    output logic [31:0]         coeff_loaded_count,
    output logic [31:0]         coeff_active_id,
    output logic [31:0]         coeff_active_checksum,
    output logic [31:0]         coeff_error_count,
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
    input  wire [31:0]          output_fifo_level,
    output logic [31:0]         peak_chan,
    output logic [31:0]         peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

    localparam integer CELL_W = NINPUT * 32;
    localparam integer PFB_TAPS = 8;
    localparam integer PFB_COEFF_COUNT = NCHAN * PFB_TAPS;
    localparam integer CELLS_PER_BEAT = DATA_W / CELL_W;
    localparam integer PACK_IDX_W = (CELLS_PER_BEAT <= 1) ? 1 : $clog2(CELLS_PER_BEAT);
    localparam integer FRAME_FIFO_DEPTH = 16;
    localparam integer FRAME_FIFO_AW = 4;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_DEPTH_COUNT = FRAME_FIFO_DEPTH;
    localparam [FRAME_FIFO_AW:0] FRAME_FIFO_ZERO_COUNT = {(FRAME_FIFO_AW+1){1'b0}};
    localparam integer OUTPUT_FIFO_DEPTH = 4096;
    localparam integer OUTPUT_BEATS_PER_FRAME = NCHAN / CELLS_PER_BEAT;
    localparam integer OUTPUT_FIFO_HEADROOM = 64;
    localparam integer OUTPUT_RESERVATION_LIMIT =
        OUTPUT_FIFO_DEPTH - OUTPUT_BEATS_PER_FRAME - OUTPUT_FIFO_HEADROOM;

    logic [3:0] xfft_reset_count;
    wire xfft_reset_active = (xfft_reset_count != 4'd0);
    // A scheduled observation can clear the science pipeline at the target
    // PPS and intentionally wait until first_sample0 before enabling SPEC.
    // Keep the realtime XFFT lanes in reset throughout that disabled window,
    // matching the reset-to-enable ordering of the proven immediate-start
    // path.  A clear while enabled still receives the existing 15-clock reset
    // stretch from xfft_reset_count.
    wire xfft_aresetn = rst_n && enable && !xfft_reset_active;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n || clear) begin
            xfft_reset_count <= 4'hf;
        end else if (xfft_reset_count != 4'd0) begin
            xfft_reset_count <= xfft_reset_count - 4'd1;
        end
    end

    logic [DATA_W-1:0] fill_word;
    logic [63:0]       fill_frame_sample0;
    logic [PACK_IDX_W-1:0] fill_subidx;
    logic              fill_word_valid;
    logic [DATA_W-1:0] prefetch_word;
    logic [63:0]       prefetch_sample0;
    logic              prefetch_word_valid;
    logic [2:0]        fill_buf;
    logic [11:0]       fill_bin_idx;
    logic [3:0]        valid_frame_count;
    logic [2:0]        win_buf [0:PFB_TAPS-1];
    logic [2:0]        new_frame_buf;
    logic              new_frame_ready;
    logic              shift_pending;
    logic [63:0]       frame_sample0_buf [0:PFB_TAPS-1];

    logic              feed_active;
    logic [12:0]       feed_read_addr;
    logic [63:0]       feed_sample0;
    (* max_fanout = 64 *) logic read_cmd_valid;
    (* max_fanout = 64 *) logic [11:0] read_cmd_idx;
    logic              read_valid;
    logic [11:0]       read_idx;
    logic              read_dout_valid;
    logic [11:0]       read_dout_idx;
    logic [CELL_W-1:0] xfft_q_head_data;
    logic [CELL_W-1:0] xfft_q_tail_data;
    logic [11:0]       xfft_q_head_idx;
    logic [11:0]       xfft_q_tail_idx;
    (* max_fanout = 64 *) logic [1:0] xfft_q_count;
    localparam integer PFB_COMPONENTS = NINPUT * 2;
    logic              pfb_r0_valid;
    logic [11:0]       pfb_r0_idx;
    logic [CELL_W-1:0] pfb_r0_dout [0:PFB_TAPS-1];
    logic signed [17:0] pfb_r0_coeff [0:PFB_TAPS-1];
    logic              pfb_s0_valid;
    logic              pfb_mul_valid;
    logic              pfb_s1_valid;
    logic              pfb_s2_valid;
    logic              pfb_s3_valid;
    logic              pfb_s4_valid;
    logic              pfb_s5_valid;
    logic              pfb_s6_valid;
    logic [11:0]       pfb_s0_idx;
    logic [11:0]       pfb_mul_idx;
    logic [11:0]       pfb_s1_idx;
    logic [11:0]       pfb_s2_idx;
    logic [11:0]       pfb_s3_idx;
    logic [11:0]       pfb_s4_idx;
    logic [11:0]       pfb_s5_idx;
    logic [11:0]       pfb_s6_idx;
    logic [CELL_W-1:0] pfb_s0_data [0:PFB_TAPS-1];
    logic signed [17:0] pfb_s0_coeff [0:PFB_TAPS-1];
    wire signed [35:0] pfb_s1_prod [0:PFB_COMPONENTS-1][0:PFB_TAPS-1];
    logic signed [36:0] pfb_s2_pair [0:PFB_COMPONENTS-1][0:3];
    logic signed [37:0] pfb_s3_quad [0:PFB_COMPONENTS-1][0:1];
    logic signed [38:0] pfb_s4_acc [0:PFB_COMPONENTS-1];
    logic [23:0]       pfb_s5_magnitude [0:PFB_COMPONENTS-1];
    logic              pfb_s5_negative [0:PFB_COMPONENTS-1];
    logic [CELL_W-1:0] pfb_s6_cell;
    logic [12:0]       reserved_output_beats;
    logic              output_capacity_available;

    wire [CELL_W-1:0] fill_cell = fill_word[fill_subidx*CELL_W +: CELL_W];
    wire input_word_fire = s_axis_tvalid && s_axis_tready;
    wire fill_last_cell = (fill_subidx == (CELLS_PER_BEAT - 1));
    wire fill_last_frame_cell = fill_word_valid && fill_last_cell && (fill_bin_idx == 12'd4095);
    // Do not prefetch across the 4096-cell frame boundary.  The next frame can
    // require a different backing buffer, and that ownership change is made
    // only when the current frame's final cell is committed.
    wire fill_last_word_of_frame =
        fill_word_valid && (fill_bin_idx >= (NCHAN - CELLS_PER_BEAT));
    wire input_buffer_available =
        (valid_frame_count < 4'd8) ||
        feed_active ||
        shift_pending;

    logic [255:0] xfft_config_tdata;
    logic         xfft_config_tvalid;
    wire          xfft_config_tready;
    logic         xfft_configured;
    wire [11:0]  xfft_scale_schedule = cfg_fft_shift[11:0];

    logic [CELL_W-1:0] frame_dout [0:PFB_TAPS-1];

    logic signed [17:0] coeff_dout [0:1][0:PFB_TAPS-1];
    logic       active_bank;
    logic       shadow_bank;
    logic       coeff_loading;
    logic       coeff_shadow_full;
    logic       coeff_load_sequence_error;
    logic       coeff_active_valid;
    logic       coeff_commit_pending;
    logic       coeff_command_error;
    logic [3:0] coeff_active_taps;
    logic [31:0] coeff_shadow_checksum;
    logic [31:0] coeff_shadow_id;
    wire [2:0] coeff_write_tap = coeff_index[14:12];
    wire [11:0] coeff_write_phase = coeff_index[11:0];
    wire coeff_write_accept = coeff_write && coeff_loading &&
                              (coeff_requested_taps == 4'd8) &&
                              (coeff_loaded_count < PFB_COEFF_COUNT) &&
                              (coeff_index == coeff_loaded_count[14:0]);

    wire config_valid =
        (DATA_W >= CELL_W) &&
        ((DATA_W % CELL_W) == 0) &&
        (CELLS_PER_BEAT == 4) &&
        (NINPUT == 8) &&
        (NCHAN == 4096) &&
        (cfg_taps == 16'd8) &&
        coeff_active_valid &&
        (coeff_active_taps == 4'd8) &&
        (cfg_chan0 == 32'd0) &&
        (cfg_chan_count == 16'd256) &&
        (cfg_time_count == 16'd1);
    wire science_valid = config_valid && xfft_configured;

    // current needs one 1024-bit word every four PFB clocks.  Keep one word
    // active while a second word is prefetched, so the serializer can switch
    // words without the former fifth (load-only) cycle.
    assign s_axis_tready = enable && config_valid && xfft_configured &&
                           !prefetch_word_valid && input_buffer_available &&
                           !new_frame_ready && !fill_last_word_of_frame;

    wire [255:0] xfft_m_axis_tdata;
    wire [23:0]  xfft_m_axis_tuser;
    wire         xfft_m_axis_tvalid;
    wire         xfft_m_axis_tready;
    wire         xfft_m_axis_tlast;
    wire [7:0]   xfft_m_axis_status_tdata;
    wire         xfft_m_axis_status_tvalid;
    wire         xfft_m_axis_status_tready;
    wire         xfft_s_axis_tvalid;
    wire         xfft_s_axis_tready;
    wire         xfft_s_axis_tlast;
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
    wire [PACK_IDX_W-1:0] pack_slot = xfft_bin[PACK_IDX_W-1:0];
    wire output_fire = output_valid && m_axis_tready;
    // Realtime XFFT output cannot be throttled.  A complete frame is reserved
    // in the existing 4096-beat output CDC FIFO before feed starts, so the
    // packer is guaranteed to hand off every fourth cell without a stall.
    assign xfft_m_axis_tready = 1'b1;
    assign xfft_m_axis_status_tready = 1'b1;
    wire xfft_output_fire = xfft_m_axis_tvalid;
    wire xfft_q_empty = (xfft_q_count == 2'd0);
    wire xfft_q_full = (xfft_q_count == 2'd2);
    (* max_fanout = 64 *) wire pfb_pipe_advance = !xfft_q_full;
    wire xfft_data_valid = !xfft_q_empty;
    wire [CELL_W-1:0] xfft_data = xfft_q_head_data;
    wire [11:0] xfft_data_idx = xfft_q_head_idx;
    wire xfft_q_push = pfb_pipe_advance && pfb_s6_valid;
    wire read_issue = feed_active && pfb_pipe_advance && (feed_read_addr < 13'd4096);
    wire feed_last_read_issue = read_issue && (feed_read_addr == 13'd4095);
    assign xfft_s_axis_tvalid = enable && config_valid && xfft_configured && xfft_data_valid;
    assign xfft_s_axis_tlast = (xfft_data_idx == 12'd4095);
    wire xfft_input_fire = xfft_s_axis_tvalid && xfft_s_axis_tready;
    wire xfft_q_pop = xfft_input_fire;
    wire feed_done = xfft_input_fire && (xfft_data_idx == 12'd4095);
    wire pfb_pipe_busy = read_cmd_valid ||
                         read_valid ||
                         read_dout_valid ||
                         pfb_r0_valid ||
                         pfb_s0_valid ||
                         pfb_mul_valid ||
                         pfb_s1_valid ||
                         pfb_s2_valid ||
                         pfb_s3_valid ||
                         pfb_s4_valid ||
                         pfb_s5_valid ||
                         pfb_s6_valid;
    wire start_feed = enable && config_valid && xfft_configured &&
                      !feed_active && !pfb_pipe_busy && !xfft_data_valid &&
                      !new_frame_ready && !shift_pending &&
                      output_capacity_available &&
                      (valid_frame_count == 4'd8);
    wire pack_first_cell = (pack_slot == {PACK_IDX_W{1'b0}});
    wire pack_last_cell = (pack_slot == (CELLS_PER_BEAT - 1));
    wire pack_slot_mismatch = xfft_output_fire && (pack_slot != pack_subidx);

    (* ram_style = "distributed" *) logic [63:0] frame_sample0_fifo [0:FRAME_FIFO_DEPTH-1];
    logic [FRAME_FIFO_AW-1:0] frame_fifo_wr_ptr;
    logic [FRAME_FIFO_AW-1:0] frame_fifo_rd_ptr;
    logic [FRAME_FIFO_AW:0]   frame_fifo_count;
    wire frame_fifo_empty = (frame_fifo_count == FRAME_FIFO_ZERO_COUNT);
    wire frame_fifo_full = (frame_fifo_count == FRAME_FIFO_DEPTH_COUNT);
    wire frame_sample0_enqueue = xfft_input_fire && (xfft_data_idx == 12'd0);
    wire frame_sample0_dequeue = xfft_output_fire && xfft_m_axis_tlast;
    wire frame_sample0_push = frame_sample0_enqueue && (!frame_fifo_full || frame_sample0_dequeue);
    wire frame_sample0_pop = frame_sample0_dequeue && !frame_fifo_empty;
    wire [63:0] current_output_frame_sample0 =
        !frame_fifo_empty ? frame_sample0_fifo[frame_fifo_rd_ptr] : feed_sample0;

    wire feng_busy =
        fill_word_valid ||
        prefetch_word_valid ||
        (fill_bin_idx != 12'd0) ||
        feed_active ||
        read_cmd_valid ||
        read_valid ||
        read_dout_valid ||
        pfb_r0_valid ||
        pfb_s0_valid ||
        pfb_mul_valid ||
        pfb_s1_valid ||
        pfb_s2_valid ||
        pfb_s3_valid ||
        pfb_s4_valid ||
        pfb_s5_valid ||
        pfb_s6_valid ||
        xfft_data_valid ||
        (valid_frame_count != 4'd0) ||
        output_valid ||
        (pack_subidx != {PACK_IDX_W{1'b0}}) ||
        xfft_config_tvalid;

    assign m_axis_tdata = output_word;
    assign m_axis_sample0 = output_sample0;
    assign m_axis_tvalid = output_valid;
    assign packet_chan0 = packet_chan0_reg;
    assign packet_chan_count = 16'd256;
    assign packet_time_count = 16'd1;
    assign input_fifo_level = {
        13'd0,
        prefetch_word_valid,
        new_frame_ready,
        shift_pending,
        valid_frame_count,
        fill_bin_idx
    };
    assign coeff_status = {
        20'd0,
        coeff_active_taps,
        shadow_bank,
        active_bank,
        coeff_command_error,
        coeff_loading || coeff_commit_pending,
        coeff_commit_pending,
        coeff_shadow_full,
        coeff_loading,
        coeff_active_valid
    };

    // Stage 36: coefficients remain Q1.17; divide the accumulator by 2^16
    // to preserve an extra fractional bit before IQ16 rounding (gain 2).
    // Split symmetric rounding and saturation across two registers.  The old
    // single function synthesized as an 11-level carry path at 322 MHz.
    function automatic [23:0] round_magnitude_q16_39(input logic signed [38:0] acc);
        logic [39:0] extended;
        logic [39:0] magnitude;
        logic [39:0] biased;
        begin
            extended = {acc[38], acc};
            magnitude = acc[38] ? (~extended + 40'd1) : extended;
            biased = magnitude + 40'd32768;
            round_magnitude_q16_39 = biased[39:16];
        end
    endfunction

    function automatic signed [15:0] saturate_signed_magnitude(
        input logic negative,
        input logic [23:0] magnitude
    );
        logic signed [15:0] positive_value;
        begin
            positive_value = $signed({1'b0, magnitude[14:0]});
            if (negative && (magnitude >= 24'd32768)) begin
                saturate_signed_magnitude = -16'sd32768;
            end else if (!negative && (magnitude > 24'd32767)) begin
                saturate_signed_magnitude = 16'sd32767;
            end else if (negative) begin
                saturate_signed_magnitude = -positive_value;
            end else begin
                saturate_signed_magnitude = positive_value;
            end
        end
    endfunction

    // Reference helper retained for directed simulation checks only.  The RTL
    // datapath uses the two registered functions above.
    function automatic signed [15:0] round_sat_q16_39(input logic signed [38:0] acc);
        begin
            round_sat_q16_39 = saturate_signed_magnitude(
                acc[38], round_magnitude_q16_39(acc)
            );
        end
    endfunction

    function automatic logic magnitude_saturates(
        input logic negative,
        input logic [23:0] magnitude
    );
        begin
            magnitude_saturates = negative ? (magnitude >= 24'd32768)
                                           : (magnitude > 24'd32767);
        end
    endfunction

    // IEEE/zlib reflected CRC32 over one little-endian 32-bit coefficient
    // word.  The public CRC value is kept in its finalized (xor-out) form so
    // reset value zero matches zlib.crc32(data) with no prior bytes.
    function automatic [31:0] crc32_coeff_word(
        input logic [31:0] crc_in,
        input logic [31:0] coeff_word
    );
        logic [31:0] crc;
        integer bit_idx;
        begin
            crc = crc_in ^ 32'hffff_ffff;
            for (bit_idx = 0; bit_idx < 32; bit_idx = bit_idx + 1) begin
                if (crc[0] ^ coeff_word[bit_idx]) begin
                    crc = (crc >> 1) ^ 32'hedb8_8320;
                end else begin
                    crc = crc >> 1;
                end
            end
            crc32_coeff_word = crc ^ 32'hffff_ffff;
        end
    endfunction

    function automatic signed [15:0] pfb_component(
        input logic [CELL_W-1:0] sample_cell,
        input integer comp_idx
    );
        integer bit_lsb;
        begin
            bit_lsb = (comp_idx / 2) * 32 + (comp_idx % 2) * 16;
            pfb_component = sample_cell[bit_lsb +: 16];
        end
    endfunction

    integer pfb_comp_idx;
    integer pfb_lane_idx;
    integer pfb_tap_idx;
    integer pfb_sat_idx;
    logic pfb_s5_any_saturation;

    always_comb begin
        pfb_s5_any_saturation = 1'b0;
        for (pfb_sat_idx = 0; pfb_sat_idx < PFB_COMPONENTS; pfb_sat_idx = pfb_sat_idx + 1) begin
            pfb_s5_any_saturation = pfb_s5_any_saturation |
                magnitude_saturates(pfb_s5_negative[pfb_sat_idx],
                                    pfb_s5_magnitude[pfb_sat_idx]);
        end
    end

    always_comb begin
        xfft_config_tdata = 256'd0;
        xfft_config_tdata[7:0] = 8'hff;
        xfft_config_tdata[19:8] = xfft_scale_schedule;
        xfft_config_tdata[31:20] = xfft_scale_schedule;
        xfft_config_tdata[43:32] = xfft_scale_schedule;
        xfft_config_tdata[55:44] = xfft_scale_schedule;
        xfft_config_tdata[67:56] = xfft_scale_schedule;
        xfft_config_tdata[79:68] = xfft_scale_schedule;
        xfft_config_tdata[91:80] = xfft_scale_schedule;
        xfft_config_tdata[103:92] = xfft_scale_schedule;
    end

    always_comb begin
        pack_word_next = pack_first_cell ? {DATA_W{1'b0}} : pack_word;
        case (pack_slot)
            2'd0: pack_word_next[0*CELL_W +: CELL_W] = xfft_m_axis_tdata;
            2'd1: pack_word_next[1*CELL_W +: CELL_W] = xfft_m_axis_tdata;
            2'd2: pack_word_next[2*CELL_W +: CELL_W] = xfft_m_axis_tdata;
            default: pack_word_next[3*CELL_W +: CELL_W] = xfft_m_axis_tdata;
        endcase
    end

    genvar frame_mem_idx;
    generate
        for (frame_mem_idx = 0; frame_mem_idx < PFB_TAPS; frame_mem_idx = frame_mem_idx + 1) begin : gen_frame_mem
            wire frame_we = fill_word_valid && (fill_buf == frame_mem_idx[2:0]);
            xpm_memory_sdpram #(
                .ADDR_WIDTH_A(12),
                .ADDR_WIDTH_B(12),
                .AUTO_SLEEP_TIME(0),
                .BYTE_WRITE_WIDTH_A(CELL_W),
                .CASCADE_HEIGHT(0),
                .CLOCKING_MODE("common_clock"),
                .ECC_MODE("no_ecc"),
                .MEMORY_INIT_FILE("none"),
                .MEMORY_INIT_PARAM("0"),
                .MEMORY_OPTIMIZATION("true"),
                .MEMORY_PRIMITIVE("block"),
                .MEMORY_SIZE(NCHAN * CELL_W),
                .MESSAGE_CONTROL(0),
                .READ_DATA_WIDTH_B(CELL_W),
                .READ_LATENCY_B(2),
                .READ_RESET_VALUE_B("0"),
                .RST_MODE_A("SYNC"),
                .RST_MODE_B("SYNC"),
                .USE_EMBEDDED_CONSTRAINT(0),
                .USE_MEM_INIT(0),
                .WAKEUP_TIME("disable_sleep"),
                .WRITE_DATA_WIDTH_A(CELL_W),
                .WRITE_MODE_B("read_first")
            ) u_frame_mem (
                .dbiterrb(),
                .doutb(frame_dout[frame_mem_idx]),
                .sbiterrb(),
                .addra(fill_bin_idx),
                .addrb(read_cmd_idx),
                .clka(clk),
                .clkb(clk),
                .dina(fill_cell),
                .ena(1'b1),
                .enb(read_cmd_valid && pfb_pipe_advance),
                .injectdbiterra(1'b0),
                .injectsbiterra(1'b0),
                .regceb(pfb_pipe_advance),
                .rstb(!rst_n),
                .sleep(1'b0),
                .wea(frame_we)
            );
        end
    endgenerate

    genvar coeff_bank_idx;
    genvar coeff_tap_idx;
    generate
        for (coeff_bank_idx = 0; coeff_bank_idx < 2; coeff_bank_idx = coeff_bank_idx + 1) begin : gen_coeff_bank
            for (coeff_tap_idx = 0; coeff_tap_idx < PFB_TAPS; coeff_tap_idx = coeff_tap_idx + 1) begin : gen_coeff_tap
                wire coeff_we = coeff_write_accept &&
                                (shadow_bank == coeff_bank_idx[0]) &&
                                (coeff_write_tap == coeff_tap_idx[2:0]);
                xpm_memory_sdpram #(
                    .ADDR_WIDTH_A(12),
                    .ADDR_WIDTH_B(12),
                    .AUTO_SLEEP_TIME(0),
                    .BYTE_WRITE_WIDTH_A(18),
                    .CASCADE_HEIGHT(0),
                    .CLOCKING_MODE("common_clock"),
                    .ECC_MODE("no_ecc"),
                    .MEMORY_INIT_FILE("none"),
                    .MEMORY_INIT_PARAM("0"),
                    .MEMORY_OPTIMIZATION("true"),
                    .MEMORY_PRIMITIVE("block"),
                    .MEMORY_SIZE(NCHAN * 18),
                    .MESSAGE_CONTROL(0),
                    .READ_DATA_WIDTH_B(18),
                    .READ_LATENCY_B(2),
                    .READ_RESET_VALUE_B("0"),
                    .RST_MODE_A("SYNC"),
                    .RST_MODE_B("SYNC"),
                    .USE_EMBEDDED_CONSTRAINT(0),
                    .USE_MEM_INIT(0),
                    .WAKEUP_TIME("disable_sleep"),
                    .WRITE_DATA_WIDTH_A(18),
                    .WRITE_MODE_B("read_first")
                ) u_coeff_mem (
                    .dbiterrb(),
                    .doutb(coeff_dout[coeff_bank_idx][coeff_tap_idx]),
                    .sbiterrb(),
                    .addra(coeff_write_phase),
                    .addrb(read_cmd_idx),
                    .clka(clk),
                    .clkb(clk),
                    .dina(coeff_data),
                    .ena(1'b1),
                    .enb(read_cmd_valid && pfb_pipe_advance),
                    .injectdbiterra(1'b0),
                    .injectsbiterra(1'b0),
                    .regceb(pfb_pipe_advance),
                    .rstb(!rst_n),
                    .sleep(1'b0),
                    .wea(coeff_we)
                );
            end
        end
    endgenerate

    genvar pfb_mul_comp_idx;
    genvar pfb_mul_tap_idx;
    generate
        for (pfb_mul_comp_idx = 0;
             pfb_mul_comp_idx < PFB_COMPONENTS;
             pfb_mul_comp_idx = pfb_mul_comp_idx + 1) begin : gen_pfb_mul_comp
            localparam integer SAMPLE_LSB =
                (pfb_mul_comp_idx / 2) * 32 + (pfb_mul_comp_idx % 2) * 16;
            for (pfb_mul_tap_idx = 0;
                 pfb_mul_tap_idx < PFB_TAPS;
                 pfb_mul_tap_idx = pfb_mul_tap_idx + 1) begin : gen_pfb_mul_tap
                wire signed [15:0] mul_sample =
                    $signed(pfb_s0_data[pfb_mul_tap_idx][SAMPLE_LSB +: 16]);
                wire signed [17:0] mul_coeff = pfb_s0_coeff[pfb_mul_tap_idx];

                t510_pfb_mult_16x18_pipe2 u_pfb_mult (
                    .clk(clk),
                    .rst_n(rst_n),
                    .ce(pfb_pipe_advance),
                    .sample(mul_sample),
                    .coeff(mul_coeff),
                    .product(pfb_s1_prod[pfb_mul_comp_idx][pfb_mul_tap_idx])
                );
            end
        end
    endgenerate

`ifdef T510_SIM_FFT_MODEL
    t510_fengine_xfft_4096_sim_model u_fengine_xfft_4096 (
        .aclk(clk),
        .aresetn(xfft_aresetn),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(xfft_data),
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
        .aresetn(xfft_aresetn),
        .s_axis_config_tdata(xfft_config_tdata),
        .s_axis_config_tvalid(xfft_config_tvalid),
        .s_axis_config_tready(xfft_config_tready),
        .s_axis_data_tdata(xfft_data),
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
            frame_sample0_fifo[frame_fifo_wr_ptr] <= feed_sample0;
        end
    end

    wire [13:0] output_occupancy_reserved =
        {1'b0, output_fifo_level[12:0]} + {1'b0, reserved_output_beats};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reserved_output_beats <= 13'd0;
            output_capacity_available <= 1'b0;
        end else if (clear || !enable || !config_valid) begin
            reserved_output_beats <= 13'd0;
            output_capacity_available <= 1'b0;
        end else begin
            output_capacity_available <=
                (output_occupancy_reserved <= OUTPUT_RESERVATION_LIMIT);
            unique case ({start_feed, output_fire})
                2'b10: reserved_output_beats <=
                    reserved_output_beats + OUTPUT_BEATS_PER_FRAME;
                2'b01: if (reserved_output_beats != 13'd0) begin
                    reserved_output_beats <= reserved_output_beats - 13'd1;
                end
                2'b11: reserved_output_beats <=
                    reserved_output_beats + OUTPUT_BEATS_PER_FRAME - 13'd1;
                default: reserved_output_beats <= reserved_output_beats;
            endcase
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fill_word <= {DATA_W{1'b0}};
            fill_frame_sample0 <= 64'd0;
            fill_subidx <= {PACK_IDX_W{1'b0}};
            fill_word_valid <= 1'b0;
            prefetch_word <= {DATA_W{1'b0}};
            prefetch_sample0 <= 64'd0;
            prefetch_word_valid <= 1'b0;
            fill_buf <= 3'd0;
            fill_bin_idx <= 12'd0;
            valid_frame_count <= 4'd0;
            for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
                win_buf[pfb_tap_idx] <= pfb_tap_idx[2:0];
            end
            new_frame_buf <= 3'd0;
            new_frame_ready <= 1'b0;
            shift_pending <= 1'b0;
            for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
                frame_sample0_buf[pfb_tap_idx] <= 64'd0;
            end
            feed_active <= 1'b0;
            feed_read_addr <= 13'd0;
            feed_sample0 <= 64'd0;
            read_cmd_valid <= 1'b0;
            read_cmd_idx <= 12'd0;
            read_valid <= 1'b0;
            read_idx <= 12'd0;
            read_dout_valid <= 1'b0;
            read_dout_idx <= 12'd0;
            pfb_r0_valid <= 1'b0;
            pfb_r0_idx <= 12'd0;
            for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
                pfb_r0_dout[pfb_tap_idx] <= {CELL_W{1'b0}};
                pfb_r0_coeff[pfb_tap_idx] <= 18'sd0;
            end
            pfb_s0_valid <= 1'b0;
            pfb_mul_valid <= 1'b0;
            pfb_s1_valid <= 1'b0;
            pfb_s2_valid <= 1'b0;
            pfb_s3_valid <= 1'b0;
            pfb_s4_valid <= 1'b0;
            pfb_s5_valid <= 1'b0;
            pfb_s6_valid <= 1'b0;
            pfb_s0_idx <= 12'd0;
            pfb_mul_idx <= 12'd0;
            pfb_s1_idx <= 12'd0;
            pfb_s2_idx <= 12'd0;
            pfb_s3_idx <= 12'd0;
            pfb_s4_idx <= 12'd0;
            pfb_s5_idx <= 12'd0;
            pfb_s6_idx <= 12'd0;
            for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
                pfb_s0_data[pfb_tap_idx] <= {CELL_W{1'b0}};
                pfb_s0_coeff[pfb_tap_idx] <= 18'sd0;
            end
            pfb_s6_cell <= {CELL_W{1'b0}};
            xfft_q_head_data <= {CELL_W{1'b0}};
            xfft_q_tail_data <= {CELL_W{1'b0}};
            xfft_q_head_idx <= 12'd0;
            xfft_q_tail_idx <= 12'd0;
            xfft_q_count <= 2'd0;
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
            active_bank <= 1'b0;
            shadow_bank <= 1'b1;
            coeff_loading <= 1'b0;
            coeff_shadow_full <= 1'b0;
            coeff_load_sequence_error <= 1'b0;
            coeff_active_valid <= 1'b0;
            coeff_commit_pending <= 1'b0;
            coeff_command_error <= 1'b0;
            coeff_active_taps <= 4'd0;
            coeff_loaded_count <= 32'd0;
            coeff_shadow_checksum <= 32'd0;
            coeff_shadow_id <= 32'd0;
            coeff_active_id <= 32'd0;
            coeff_active_checksum <= 32'd0;
            coeff_error_count <= 32'd0;
        end else begin
            if (coeff_load_start) begin
                if (enable || (coeff_requested_taps != 4'd8)) begin
                    coeff_command_error <= 1'b1;
                    coeff_error_count <= coeff_error_count + 32'd1;
                end else begin
                    coeff_loading <= 1'b1;
                    coeff_shadow_full <= 1'b0;
                    coeff_load_sequence_error <= 1'b0;
                    coeff_commit_pending <= 1'b0;
                    coeff_command_error <= 1'b0;
                    shadow_bank <= ~active_bank;
                    coeff_loaded_count <= 32'd0;
                    coeff_shadow_checksum <= 32'd0;
                    coeff_shadow_id <= coeff_id;
                end
            end
            if (coeff_abort) begin
                coeff_loading <= 1'b0;
                coeff_shadow_full <= 1'b0;
                coeff_load_sequence_error <= 1'b0;
                coeff_commit_pending <= 1'b0;
            end
            if (coeff_write) begin
                if (!coeff_write_accept) begin
                    coeff_command_error <= 1'b1;
                    coeff_error_count <= coeff_error_count + 32'd1;
                    coeff_load_sequence_error <= 1'b1;
                    coeff_shadow_full <= 1'b0;
                end else begin
                    coeff_loaded_count <= coeff_loaded_count + 32'd1;
                    coeff_shadow_checksum <= crc32_coeff_word(
                        coeff_shadow_checksum, {14'd0, coeff_data[17:0]}
                    );
                    if ((coeff_loaded_count == (PFB_COEFF_COUNT - 1)) &&
                        !coeff_load_sequence_error) begin
                        coeff_shadow_full <= 1'b1;
                    end
                end
            end
            if (coeff_commit) begin
                if (enable || !coeff_shadow_full) begin
                    coeff_commit_pending <= enable;
                    coeff_command_error <= 1'b1;
                    coeff_error_count <= coeff_error_count + 32'd1;
                end else begin
                    active_bank <= shadow_bank;
                    coeff_active_valid <= 1'b1;
                    coeff_active_taps <= 4'd8;
                    coeff_active_id <= coeff_shadow_id;
                    coeff_active_checksum <= coeff_shadow_checksum;
                    coeff_loading <= 1'b0;
                    coeff_shadow_full <= 1'b0;
                    coeff_commit_pending <= 1'b0;
                    coeff_command_error <= 1'b0;
                end
            end

            if (!config_valid) begin
                fill_word_valid <= 1'b0;
                prefetch_word_valid <= 1'b0;
                fill_subidx <= {PACK_IDX_W{1'b0}};
                fill_bin_idx <= 12'd0;
                valid_frame_count <= 4'd0;
                feed_active <= 1'b0;
                feed_read_addr <= 13'd0;
                read_cmd_valid <= 1'b0;
                read_cmd_idx <= 12'd0;
                read_valid <= 1'b0;
                read_dout_valid <= 1'b0;
                pfb_r0_valid <= 1'b0;
                pfb_s0_valid <= 1'b0;
                pfb_mul_valid <= 1'b0;
                pfb_s1_valid <= 1'b0;
                pfb_s2_valid <= 1'b0;
                pfb_s3_valid <= 1'b0;
                pfb_s4_valid <= 1'b0;
                pfb_s5_valid <= 1'b0;
                pfb_s6_valid <= 1'b0;
                xfft_q_count <= 2'd0;
                xfft_config_tvalid <= 1'b0;
                xfft_configured <= 1'b0;
                pack_subidx <= {PACK_IDX_W{1'b0}};
                pack_word <= {DATA_W{1'b0}};
                output_valid <= 1'b0;
                frame_fifo_wr_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_rd_ptr <= {FRAME_FIFO_AW{1'b0}};
                frame_fifo_count <= FRAME_FIFO_ZERO_COUNT;
            end else begin
                if (xfft_reset_active || !enable) begin
                    xfft_config_tvalid <= 1'b0;
                    xfft_configured <= 1'b0;
                end else begin
                    // Configure only after enable releases the realtime XFFT
                    // lanes from reset.  The input CDC FIFO absorbs the few
                    // configuration clocks before s_axis_tready rises.
                    if (!xfft_configured && !xfft_config_tvalid
                        && enable
                    ) begin
                        xfft_config_tvalid <= 1'b1;
                    end
                    if (xfft_config_tvalid && xfft_config_tready) begin
                        xfft_config_tvalid <= 1'b0;
                        xfft_configured <= 1'b1;
                    end
                end

                if (clear || !enable) begin
                    fill_word_valid <= 1'b0;
                    prefetch_word_valid <= 1'b0;
                    fill_subidx <= {PACK_IDX_W{1'b0}};
                    fill_bin_idx <= 12'd0;
                    valid_frame_count <= 4'd0;
                    fill_buf <= 3'd0;
                    for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
                        win_buf[pfb_tap_idx] <= pfb_tap_idx[2:0];
                    end
                    new_frame_ready <= 1'b0;
                    shift_pending <= 1'b0;
                    feed_active <= 1'b0;
                    feed_read_addr <= 13'd0;
                    read_cmd_valid <= 1'b0;
                    read_cmd_idx <= 12'd0;
                    read_valid <= 1'b0;
                    read_dout_valid <= 1'b0;
                    pfb_r0_valid <= 1'b0;
                    pfb_s0_valid <= 1'b0;
                    pfb_mul_valid <= 1'b0;
                    pfb_s1_valid <= 1'b0;
                    pfb_s2_valid <= 1'b0;
                    pfb_s3_valid <= 1'b0;
                    pfb_s4_valid <= 1'b0;
                    pfb_s5_valid <= 1'b0;
                    pfb_s6_valid <= 1'b0;
                    xfft_q_count <= 2'd0;
                    pack_subidx <= {PACK_IDX_W{1'b0}};
                    pack_word <= {DATA_W{1'b0}};
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
                    if (start_feed) begin
                        feed_active <= 1'b1;
                        feed_sample0 <= frame_sample0_buf[win_buf[0]];
                        feed_read_addr <= 13'd0;
                        fill_buf <= win_buf[0];
                    end else if (read_issue) begin
                        feed_read_addr <= feed_read_addr + 13'd1;
                        if (feed_last_read_issue) begin
                            feed_active <= 1'b0;
                        end
                    end

                    if (output_fire && !(xfft_output_fire && pack_last_cell)) begin
                        output_valid <= 1'b0;
                    end

                    if (fill_word_valid) begin
                        if (fill_last_frame_cell) begin
                            frame_sample0_buf[fill_buf] <= fill_frame_sample0;
                            fill_bin_idx <= 12'd0;
                            fill_subidx <= {PACK_IDX_W{1'b0}};
                            fill_word_valid <= 1'b0;
                            prefetch_word_valid <= 1'b0;
                            if (valid_frame_count < 4'd8) begin
                                win_buf[valid_frame_count[2:0]] <= fill_buf;
                                valid_frame_count <= valid_frame_count + 4'd1;
                                fill_buf <= fill_buf + 3'd1;
                            end else if (shift_pending) begin
                                for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS-1; pfb_tap_idx = pfb_tap_idx + 1) begin
                                    win_buf[pfb_tap_idx] <= win_buf[pfb_tap_idx + 1];
                                end
                                win_buf[PFB_TAPS-1] <= fill_buf;
                                shift_pending <= 1'b0;
                                new_frame_ready <= 1'b0;
                            end else begin
                                new_frame_buf <= fill_buf;
                                new_frame_ready <= 1'b1;
                            end
                        end else begin
                            fill_bin_idx <= fill_bin_idx + 12'd1;
                            if (fill_last_cell) begin
                                fill_subidx <= {PACK_IDX_W{1'b0}};
                                if (prefetch_word_valid) begin
                                    fill_word <= prefetch_word;
                                    fill_word_valid <= 1'b1;
                                    prefetch_word_valid <= 1'b0;
                                    if ((fill_bin_idx + 12'd1) == 12'd0) begin
                                        fill_frame_sample0 <= prefetch_sample0;
                                    end
                                end else if (input_word_fire) begin
                                    // Simultaneous consume/replace is the
                                    // empty-prefetch fall-through case.
                                    fill_word <= s_axis_tdata;
                                    fill_word_valid <= 1'b1;
                                    if ((fill_bin_idx + 12'd1) == 12'd0) begin
                                        fill_frame_sample0 <= s_axis_sample0;
                                    end
                                end else begin
                                    fill_word_valid <= 1'b0;
                                end
                            end else begin
                                fill_subidx <= fill_subidx + {{(PACK_IDX_W-1){1'b0}}, 1'b1};
                                if (input_word_fire) begin
                                    prefetch_word <= s_axis_tdata;
                                    prefetch_sample0 <= s_axis_sample0;
                                    prefetch_word_valid <= 1'b1;
                                end
                            end
                        end
                    end else if (input_word_fire) begin
                        fill_word <= s_axis_tdata;
                        fill_word_valid <= 1'b1;
                        fill_subidx <= {PACK_IDX_W{1'b0}};
                        if (fill_bin_idx == 12'd0) begin
                            fill_frame_sample0 <= s_axis_sample0;
                        end
                    end

	                    unique case ({xfft_q_push, xfft_q_pop})
	                        2'b10: begin
	                            if (xfft_q_empty) begin
	                                xfft_q_head_data <= pfb_s6_cell;
	                                xfft_q_head_idx <= pfb_s6_idx;
	                            end else begin
	                                xfft_q_tail_data <= pfb_s6_cell;
	                                xfft_q_tail_idx <= pfb_s6_idx;
	                            end
	                            xfft_q_count <= xfft_q_count + 2'd1;
	                        end
	                        2'b01: begin
	                            if (xfft_q_full) begin
	                                xfft_q_head_data <= xfft_q_tail_data;
	                                xfft_q_head_idx <= xfft_q_tail_idx;
	                            end
	                            xfft_q_count <= xfft_q_count - 2'd1;
	                        end
	                        2'b11: begin
	                            xfft_q_head_data <= pfb_s6_cell;
	                            xfft_q_head_idx <= pfb_s6_idx;
	                        end
	                        default: xfft_q_count <= xfft_q_count;
	                    endcase

	                    if (pfb_pipe_advance) begin
	                        read_cmd_valid <= read_issue;
	                        if (read_issue) begin
	                            read_cmd_idx <= feed_read_addr[11:0];
	                        end
	                        read_valid <= read_cmd_valid;
	                        read_idx <= read_cmd_idx;
	                        read_dout_valid <= read_valid;
	                        read_dout_idx <= read_idx;

	                        pfb_r0_valid <= read_dout_valid;
	                        pfb_r0_idx <= read_dout_idx;
	                        for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
	                            pfb_r0_dout[pfb_tap_idx] <= frame_dout[pfb_tap_idx];
	                            pfb_r0_coeff[pfb_tap_idx] <= active_bank
	                                ? coeff_dout[1][pfb_tap_idx[2:0] - win_buf[0]]
	                                : coeff_dout[0][pfb_tap_idx[2:0] - win_buf[0]];
	                        end

	                        pfb_s0_valid <= pfb_r0_valid;
	                        pfb_s0_idx <= pfb_r0_idx;
	                        for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS; pfb_tap_idx = pfb_tap_idx + 1) begin
	                            // Sum order is independent of tap identity.  Pair
	                            // each physical frame RAM directly with the tap
	                            // selected by the oldest-buffer pointer.  This
	                            // moves the rotating 8:1 mux from 256-bit sample
	                            // cells to 18-bit coefficients and avoids a large
	                            // high-fanout datapath at 322.265625 MHz.
	                            pfb_s0_data[pfb_tap_idx] <= pfb_r0_dout[pfb_tap_idx];
	                            pfb_s0_coeff[pfb_tap_idx] <= pfb_r0_coeff[pfb_tap_idx];
	                        end

	                        pfb_mul_valid <= pfb_s0_valid;
	                        pfb_mul_idx <= pfb_s0_idx;

	                        pfb_s1_valid <= pfb_mul_valid;
	                        pfb_s1_idx <= pfb_mul_idx;

	                        pfb_s2_valid <= pfb_s1_valid;
	                        pfb_s2_idx <= pfb_s1_idx;
	                        for (pfb_comp_idx = 0; pfb_comp_idx < PFB_COMPONENTS; pfb_comp_idx = pfb_comp_idx + 1) begin
	                            pfb_s2_pair[pfb_comp_idx][0] <=
	                                $signed({pfb_s1_prod[pfb_comp_idx][0][35], pfb_s1_prod[pfb_comp_idx][0]}) +
	                                $signed({pfb_s1_prod[pfb_comp_idx][1][35], pfb_s1_prod[pfb_comp_idx][1]});
	                            pfb_s2_pair[pfb_comp_idx][1] <=
	                                $signed({pfb_s1_prod[pfb_comp_idx][2][35], pfb_s1_prod[pfb_comp_idx][2]}) +
	                                $signed({pfb_s1_prod[pfb_comp_idx][3][35], pfb_s1_prod[pfb_comp_idx][3]});
	                            pfb_s2_pair[pfb_comp_idx][2] <=
	                                $signed({pfb_s1_prod[pfb_comp_idx][4][35], pfb_s1_prod[pfb_comp_idx][4]}) +
	                                $signed({pfb_s1_prod[pfb_comp_idx][5][35], pfb_s1_prod[pfb_comp_idx][5]});
	                            pfb_s2_pair[pfb_comp_idx][3] <=
	                                $signed({pfb_s1_prod[pfb_comp_idx][6][35], pfb_s1_prod[pfb_comp_idx][6]}) +
	                                $signed({pfb_s1_prod[pfb_comp_idx][7][35], pfb_s1_prod[pfb_comp_idx][7]});
	                        end

	                        pfb_s3_valid <= pfb_s2_valid;
	                        pfb_s3_idx <= pfb_s2_idx;
	                        for (pfb_comp_idx = 0; pfb_comp_idx < PFB_COMPONENTS; pfb_comp_idx = pfb_comp_idx + 1) begin
	                            pfb_s3_quad[pfb_comp_idx][0] <=
	                                $signed({pfb_s2_pair[pfb_comp_idx][0][36], pfb_s2_pair[pfb_comp_idx][0]}) +
	                                $signed({pfb_s2_pair[pfb_comp_idx][1][36], pfb_s2_pair[pfb_comp_idx][1]});
	                            pfb_s3_quad[pfb_comp_idx][1] <=
	                                $signed({pfb_s2_pair[pfb_comp_idx][2][36], pfb_s2_pair[pfb_comp_idx][2]}) +
	                                $signed({pfb_s2_pair[pfb_comp_idx][3][36], pfb_s2_pair[pfb_comp_idx][3]});
	                        end

	                        pfb_s4_valid <= pfb_s3_valid;
	                        pfb_s4_idx <= pfb_s3_idx;
	                        for (pfb_comp_idx = 0; pfb_comp_idx < PFB_COMPONENTS; pfb_comp_idx = pfb_comp_idx + 1) begin
	                            pfb_s4_acc[pfb_comp_idx] <=
	                                $signed({pfb_s3_quad[pfb_comp_idx][0][37], pfb_s3_quad[pfb_comp_idx][0]}) +
	                                $signed({pfb_s3_quad[pfb_comp_idx][1][37], pfb_s3_quad[pfb_comp_idx][1]});
	                        end

	                        pfb_s5_valid <= pfb_s4_valid;
	                        pfb_s5_idx <= pfb_s4_idx;
	                        for (pfb_comp_idx = 0; pfb_comp_idx < PFB_COMPONENTS; pfb_comp_idx = pfb_comp_idx + 1) begin
	                            pfb_s5_magnitude[pfb_comp_idx] <=
	                                round_magnitude_q16_39(pfb_s4_acc[pfb_comp_idx]);
	                            pfb_s5_negative[pfb_comp_idx] <= pfb_s4_acc[pfb_comp_idx][38];
	                        end

	                        pfb_s6_valid <= pfb_s5_valid;
	                        pfb_s6_idx <= pfb_s5_idx;
	                        for (pfb_lane_idx = 0; pfb_lane_idx < NINPUT; pfb_lane_idx = pfb_lane_idx + 1) begin
	                            pfb_s6_cell[pfb_lane_idx*32 +: 16] <=
	                                saturate_signed_magnitude(
	                                    pfb_s5_negative[pfb_lane_idx*2],
	                                    pfb_s5_magnitude[pfb_lane_idx*2]
	                                );
	                            pfb_s6_cell[pfb_lane_idx*32 + 16 +: 16] <=
	                                saturate_signed_magnitude(
	                                    pfb_s5_negative[pfb_lane_idx*2 + 1],
	                                    pfb_s5_magnitude[pfb_lane_idx*2 + 1]
	                                );
	                        end
	                        if (pfb_s5_valid && pfb_s5_any_saturation) begin
	                            tile_overflow_count <= tile_overflow_count + 32'd1;
	                        end

	                    end

                    if (feed_done) begin
                        if (new_frame_ready) begin
                            for (pfb_tap_idx = 0; pfb_tap_idx < PFB_TAPS-1; pfb_tap_idx = pfb_tap_idx + 1) begin
                                win_buf[pfb_tap_idx] <= win_buf[pfb_tap_idx + 1];
                            end
                            win_buf[PFB_TAPS-1] <= new_frame_buf;
                            new_frame_ready <= 1'b0;
                            shift_pending <= 1'b0;
                        end else begin
                            shift_pending <= 1'b1;
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
                            pack_subidx <= pack_slot + {{(PACK_IDX_W-1){1'b0}}, 1'b1};
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
                        pack_slot_mismatch ||
                        (frame_sample0_enqueue && !frame_sample0_push)) begin
                        overflow_count <= overflow_count + 32'd1;
                    end
                    if (xfft_event_tlast_unexpected ||
                        xfft_event_tlast_missing ||
                        xfft_event_fft_overflow ||
                        pack_slot_mismatch) begin
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
        1'b0,
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
    input  wire                 coeff_load_start,
    input  wire                 coeff_commit,
    input  wire                 coeff_abort,
    input  wire                 coeff_write,
    input  wire [3:0]           coeff_requested_taps,
    input  wire [14:0]          coeff_index,
    input  wire signed [17:0]   coeff_data,
    input  wire [31:0]          coeff_id,
    output wire [31:0]          coeff_status,
    output wire [31:0]          coeff_loaded_count,
    output wire [31:0]          coeff_active_id,
    output wire [31:0]          coeff_active_checksum,
    output wire [31:0]          coeff_error_count,
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
    input  wire [31:0]          output_fifo_level,
    output wire [31:0]          peak_chan,
    output wire [31:0]          peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

    feng_channelizer_4096_streaming #(
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
        .coeff_load_start(coeff_load_start),
        .coeff_commit(coeff_commit),
        .coeff_abort(coeff_abort),
        .coeff_write(coeff_write),
        .coeff_requested_taps(coeff_requested_taps),
        .coeff_index(coeff_index),
        .coeff_data(coeff_data),
        .coeff_id(coeff_id),
        .coeff_status(coeff_status),
        .coeff_loaded_count(coeff_loaded_count),
        .coeff_active_id(coeff_active_id),
        .coeff_active_checksum(coeff_active_checksum),
        .coeff_error_count(coeff_error_count),
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
        .output_fifo_level(output_fifo_level),
        .peak_chan(peak_chan),
        .peak_power(peak_power),
        .packet_chan0(packet_chan0),
        .packet_chan_count(packet_chan_count),
        .packet_time_count(packet_time_count)
    );


endmodule
