module pfb_channelizer #(
    parameter integer DATA_W = 256,
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
    output logic [31:0]         peak_chan,
    output logic [31:0]         peak_power,
    output wire [31:0]          packet_chan0,
    output wire [15:0]          packet_chan_count,
    output wire [15:0]          packet_time_count
);

    localparam [31:0] PAYLOAD_BEATS = 32'd256;
    localparam [31:0] LOCAL_NCHAN   = NCHAN;

    logic [15:0] channel_offset;
    logic [15:0] time_offset;
    wire [31:0] window_beats;
    wire [31:0] chan_end;
    wire        config_valid;
    wire        output_fire;
    wire [31:0] current_chan;
    wire [31:0] current_power;

    assign window_beats = cfg_chan_count * cfg_time_count;
    assign chan_end     = cfg_chan0 + {16'd0, cfg_chan_count};
    assign config_valid = (cfg_taps != 16'd0) &&
                          (cfg_chan_count != 16'd0) &&
                          (cfg_time_count != 16'd0) &&
                          (cfg_chan0 < LOCAL_NCHAN) &&
                          (chan_end <= LOCAL_NCHAN) &&
                          (window_beats == PAYLOAD_BEATS);

    assign s_axis_tready = enable && config_valid && m_axis_tready;
    assign m_axis_tdata  = s_axis_tdata;
    assign m_axis_sample0 = s_axis_sample0;
    assign m_axis_tvalid = enable && config_valid && s_axis_tvalid;
    assign output_fire   = m_axis_tvalid && m_axis_tready;

    assign packet_chan0      = cfg_chan0;
    assign packet_chan_count = cfg_chan_count;
    assign packet_time_count = cfg_time_count;
    assign current_chan      = cfg_chan0 + {16'd0, channel_offset};

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

    function automatic [31:0] beat_metric(input logic [DATA_W-1:0] data);
        integer lane_idx;
        logic signed [15:0] i_word;
        logic signed [15:0] q_word;
        logic [31:0] sum;
        begin
            sum = 32'd0;
            for (lane_idx = 0; lane_idx < NINPUT; lane_idx = lane_idx + 1) begin
                i_word = data[lane_idx*32 +: 16];
                q_word = data[lane_idx*32 + 16 +: 16];
                sum = sum + {16'd0, abs16(i_word)} + {16'd0, abs16(q_word)};
            end
            beat_metric = sum;
        end
    endfunction

    assign current_power = beat_metric(s_axis_tdata);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            channel_offset <= 16'd0;
            time_offset    <= 16'd0;
            frame_count    <= 32'd0;
            overflow_count <= 32'd0;
            peak_chan      <= 32'd0;
            peak_power     <= 32'd0;
        end else begin
            if (clear || !enable || !config_valid) begin
                channel_offset <= 16'd0;
                time_offset    <= 16'd0;
                if (clear) begin
                    frame_count    <= 32'd0;
                    overflow_count <= 32'd0;
                    peak_chan      <= 32'd0;
                    peak_power     <= 32'd0;
                end
            end else begin
                if (s_axis_tvalid && !s_axis_tready) begin
                    overflow_count <= overflow_count + 32'd1;
                end

                if (output_fire) begin
                    if (current_power >= peak_power) begin
                        peak_power <= current_power;
                        peak_chan  <= current_chan;
                    end

                    if (channel_offset == cfg_chan_count - 16'd1) begin
                        channel_offset <= 16'd0;
                        if (time_offset == cfg_time_count - 16'd1) begin
                            time_offset <= 16'd0;
                            frame_count <= frame_count + 32'd1;
                        end else begin
                            time_offset <= time_offset + 16'd1;
                        end
                    end else begin
                        channel_offset <= channel_offset + 16'd1;
                    end
                end
            end
        end
    end

    assign status = {
        16'd0,
        cfg_fft_shift[3:0],
        7'd0,
        (time_offset != 16'd0) || (channel_offset != 16'd0),
        (overflow_count != 32'd0),
        m_axis_tvalid,
        config_valid,
        enable
    };

endmodule
