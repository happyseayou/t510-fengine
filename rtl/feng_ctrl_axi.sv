module feng_ctrl_axi #(
    parameter integer AXI_ADDR_W = 32,
    parameter integer AXI_DATA_W = 32,
    parameter integer NINPUT     = 8
) (
    input  wire                         s_axi_aclk,
    input  wire                         s_axi_aresetn,
    input  wire [AXI_ADDR_W-1:0]        s_axi_awaddr,
    input  wire                         s_axi_awvalid,
    output logic                        s_axi_awready,
    input  wire [AXI_DATA_W-1:0]        s_axi_wdata,
    input  wire [AXI_DATA_W/8-1:0]      s_axi_wstrb,
    input  wire                         s_axi_wvalid,
    output logic                        s_axi_wready,
    output logic [1:0]                  s_axi_bresp,
    output logic                        s_axi_bvalid,
    input  wire                         s_axi_bready,
    input  wire [AXI_ADDR_W-1:0]        s_axi_araddr,
    input  wire                         s_axi_arvalid,
    output logic                        s_axi_arready,
    output logic [AXI_DATA_W-1:0]       s_axi_rdata,
    output logic [1:0]                  s_axi_rresp,
    output logic                        s_axi_rvalid,
    input  wire                         s_axi_rready,
    input  wire [3:0]                   fsm_state,
    input  wire                         streaming,
    input  wire                         armed,
    input  wire [1:0]                   active_sync_mode,
    input  wire                         waiting_for_epoch,
    input  wire                         pps_seen,
    input  wire                         ref_locked,
    input  wire [31:0]                  error_flags,
    input  wire [31:0]                  monitor_sample_count,
    input  wire [NINPUT*32-1:0]         clip_counts,
    input  wire [NINPUT*32-1:0]         mean_mags,
    input  wire [31:0]                  spec_packet_count,
    input  wire [31:0]                  spec_udp_byte_count,
    input  wire [31:0]                  time_packet_count,
    input  wire [31:0]                  time_udp_byte_count,
    input  wire [31:0]                  time_dropped_count,
    input  wire [31:0]                  spec_seq_no,
    input  wire [31:0]                  time_seq_no,
    input  wire [63:0]                  time_sample0,
    input  wire [63:0]                  time_frame_id,
    input  wire [63:0]                  spec_frame_id,
    input  wire [31:0]                  spec_chan0,
    input  wire [31:0]                  rfdc_status_flags,
    input  wire [63:0]                  rfdc_sample_count,
    input  wire [31:0]                  rfdc_dropped_count,
    input  wire [15:0]                  rfdc_current_valid_mask,
    input  wire [15:0]                  rfdc_seen_valid_mask,
    input  wire [31:0]                  tx_link_status_flags,
    input  wire [31:0]                  tx_dry_run_packet_count,
    input  wire [31:0]                  tx_dry_run_byte_count,
    input  wire [31:0]                  tx_fifo_level_words,
    input  wire [31:0]                  tx_fifo_high_water_words,
    input  wire [31:0]                  tx_fifo_backpressure_cycles,
    input  wire [31:0]                  tx_preflight_status_flags,
    input  wire [31:0]                  tx_frame_built_count,
    input  wire [31:0]                  tx_frame_sent_count,
    input  wire [31:0]                  tx_frame_dropped_count,
    input  wire [31:0]                  tx_frame_byte_count,
    input  wire [31:0]                  tx_route_miss_count,
    input  wire [31:0]                  tx_route_error_count,
    input  wire [2:0]                   tx_selected_endpoint_id,
    input  wire [2:0]                   tx_selected_route_id,
    input  wire                         tx_selected_route_is_time,
    input  wire                         tx_header_capture_armed,
    input  wire                         tx_header_capture_valid,
    input  wire [4:0]                   tx_header_capture_word_count,
    input  wire [31:0]                  tx_header_capture_rd_data,
    input  wire                         tx_frame_capture_armed,
    input  wire                         tx_frame_capture_valid,
    input  wire [4:0]                   tx_frame_capture_word_count,
    input  wire [31:0]                  tx_frame_capture_rd_data,
    input  wire                         tx_payload_witness_armed,
    input  wire                         tx_payload_witness_valid,
    input  wire                         tx_payload_witness_capturing,
    input  wire [10:0]                  tx_payload_witness_word_count,
    input  wire [15:0]                  tx_payload_witness_stream_type,
    input  wire [63:0]                  tx_payload_witness_sample0,
    input  wire [63:0]                  tx_payload_witness_frame_id,
    input  wire [31:0]                  tx_payload_witness_seq_no,
    input  wire [31:0]                  tx_payload_witness_chan0,
    input  wire [63:0]                  tx_payload_witness_layout_word,
    input  wire [31:0]                  tx_payload_witness_payload_bytes,
    input  wire [31:0]                  tx_payload_witness_route_meta,
    input  wire [31:0]                  tx_payload_witness_rfdc_flags,
    input  wire [63:0]                  tx_payload_witness_rfdc_sample_count,
    input  wire [31:0]                  tx_payload_witness_dac_phase_epoch,
    input  wire                         tx_payload_witness_overflow,
    input  wire                         tx_payload_witness_filter_mismatch,
    input  wire [31:0]                  tx_payload_witness_rd_data,
    input  wire                         dac_tx_witness_armed,
    input  wire                         dac_tx_witness_valid,
    input  wire                         dac_tx_witness_capturing,
    input  wire                         dac_tx_witness_overflow,
    input  wire                         dac_tx_witness_tvalid_seen,
    input  wire                         dac_tx_witness_tready_seen,
    input  wire                         dac_tx_witness_ready_gap_seen,
    input  wire [8:0]                   dac_tx_witness_word_count,
    input  wire [31:0]                  dac_tx_witness_phase_epoch,
    input  wire [31:0]                  dac_tx_witness_phase_acc,
    input  wire [31:0]                  dac_tx_witness_phase_step,
    input  wire [31:0]                  dac_tx_witness_phase0,
    input  wire [31:0]                  dac_tx_witness_mode,
    input  wire [31:0]                  dac_tx_witness_ready_gap_count,
    input  wire [31:0]                  dac_tx_witness_rd_data,
    input  wire [NINPUT*32-1:0]         tx_spec_route_hit_counts,
    input  wire [NINPUT*32-1:0]         tx_time_route_hit_counts,
    input  wire [31:0]                  pfb_status,
    input  wire [31:0]                  pfb_frame_count,
    input  wire [31:0]                  pfb_overflow_count,
    input  wire [31:0]                  pfb_peak_chan,
    input  wire [31:0]                  pfb_peak_power,
    input  wire                         debug_busy,
    input  wire                         debug_done,
    input  wire                         debug_error,
    input  wire [31:0]                  debug_capture_count,
    input  wire [31:0]                  debug_peak_bin,
    input  wire [31:0]                  debug_peak_power,
    input  wire [31:0]                  debug_time_rd_data,
    input  wire [31:0]                  debug_fft_rd_data,
    input  wire                         preview_busy,
    input  wire                         preview_done,
    input  wire                         preview_error,
    input  wire [31:0]                  preview_capture_count,
    input  wire [63:0]                  preview_sample0,
    input  wire [31:0]                  preview_rd_data,
    input  wire [31:0]                  preview_event_rd_data,
    input  wire [31:0]                  preview_audit_status,
    input  wire [31:0]                  preview_audit_start_count,
    input  wire [31:0]                  preview_audit_first_count,
    input  wire [31:0]                  preview_audit_done_count,
    input  wire [63:0]                  preview_audit_start_sample0,
    input  wire [63:0]                  preview_audit_first_sample0,
    input  wire [63:0]                  preview_audit_done_sample0,
    input  wire [31:0]                  preview_audit_start_to_first_latency,
    input  wire [31:0]                  preview_audit_capture_beats,
    input  wire [31:0]                  preview_audit_valid_gap_count,
    input  wire [31:0]                  preview_audit_sample0_error_count,
    input  wire [63:0]                  preview_event_sample0,
    input  wire [31:0]                  preview_event_max_code,
    input  wire [31:0]                  preview_event_info,
    input  wire [31:0]                  preview_event_rfdc_flags,
    input  wire [31:0]                  preview_event_dac_phase_epoch,
    input  wire [31:0]                  dac_audit_phase_epoch_seen,
    input  wire [31:0]                  dac_audit_ch0_phase_acc,
    input  wire [31:0]                  dac_audit_ch0_phase_step,
    input  wire [31:0]                  dac_audit_ch0_phase0,
    input  wire [31:0]                  dac_audit_ch0_mode,
    output logic [15:0]                 board_id,
    output logic [1:0]                  mode,
    output logic                        arm_latched,
    output logic                        soft_epoch_pulse,
    output logic                        stop_pulse,
    output logic                        soft_reset_pulse,
    output logic [1:0]                  sync_mode,
    output logic [1:0]                  clock_ref,
    output logic [31:0]                 sample_rate_hz,
    output logic [15:0]                 quant_mode,
    output logic [15:0]                 scale_mode,
    output logic [31:0]                 scale_id,
    output logic [15:0]                 time_payload_nsamp,
    output logic [15:0]                 spec_time_count,
    output logic [15:0]                 spec_chan_count,
    output logic                        pfb_enable,
    output logic                        pfb_clear_pulse,
    output logic [15:0]                 pfb_taps,
    output logic [15:0]                 pfb_fft_shift,
    output logic [31:0]                 pfb_chan0,
    output logic [15:0]                 pfb_chan_count,
    output logic [15:0]                 pfb_time_count,
    output logic [31:0]                 chan_split,
    output logic [31:0]                 src_ip,
    output logic [31:0]                 dgx_a_ip,
    output logic [31:0]                 dgx_b_ip,
    output logic [31:0]                 time_dst_ip,
    output logic [47:0]                 src_mac,
    output logic [47:0]                 dgx_a_mac,
    output logic [47:0]                 dgx_b_mac,
    output logic [15:0]                 src_udp_port,
    output logic [15:0]                 dgx_a_udp_port,
    output logic [15:0]                 dgx_b_udp_port,
    output logic [15:0]                 time_udp_port,
    output logic [31:0]                 tx_control,
    output logic                        tx_clear_pulse,
    output logic [NINPUT-1:0]           tx_endpoint_enable,
    output logic [NINPUT*32-1:0]        tx_endpoint_ip_vec,
    output logic [NINPUT*48-1:0]        tx_endpoint_mac_vec,
    output logic [NINPUT*16-1:0]        tx_endpoint_src_port_vec,
    output logic [NINPUT*16-1:0]        tx_endpoint_dst_port_vec,
    output logic [NINPUT-1:0]           tx_spec_route_enable,
    output logic [NINPUT*32-1:0]        tx_spec_route_chan0_vec,
    output logic [NINPUT*16-1:0]        tx_spec_route_chan_count_vec,
    output logic [NINPUT*3-1:0]         tx_spec_route_endpoint_vec,
    output logic [NINPUT-1:0]           tx_time_route_enable,
    output logic [NINPUT*16-1:0]        tx_time_route_input_mask_vec,
    output logic [NINPUT*3-1:0]         tx_time_route_endpoint_vec,
    output logic [15:0]                 rfdc_active_mask,
    output logic                        debug_capture_start_pulse,
    output logic                        debug_capture_clear_pulse,
    output logic [9:0]                  debug_time_rd_addr,
    output logic [9:0]                  debug_fft_rd_addr,
    output logic                        dac_tone_enable,
    output logic [15:0]                 dac_tone_amplitude,
    output logic [31:0]                 dac_tone_phase_step,
    output logic [7:0]                  dac_enable_mask,
    output logic [NINPUT*16-1:0]        dac_tone_amplitude_vec,
    output logic [NINPUT*32-1:0]        dac_tone_phase_step_vec,
    output logic [NINPUT*32-1:0]        dac_tone_phase0_vec,
    output logic [NINPUT*32-1:0]        dac_tone_phase_inject_vec,
    output logic [NINPUT*2-1:0]         dac_tone_mode_vec,
    output logic [31:0]                 dac_phase_epoch,
    output logic                        preview_capture_start_pulse,
    output logic                        preview_capture_clear_pulse,
    output logic [NINPUT-1:0]           preview_input_mask,
    output logic [2:0]                  preview_rd_input,
    output logic [9:0]                  preview_rd_addr,
    output logic                        preview_audit_clear_pulse,
    output logic [1:0]                  preview_audit_source_select,
    output logic                        preview_audit_event_enable,
    output logic                        preview_audit_freeze_on_event,
    output logic [15:0]                 preview_audit_event_threshold,
    output logic [7:0]                  preview_event_rd_addr,
    output logic                        tx_header_capture_arm_pulse,
    output logic [4:0]                  tx_header_capture_rd_word,
    output logic                        tx_frame_capture_arm_pulse,
    output logic [4:0]                  tx_frame_capture_rd_word,
    output logic                        tx_payload_witness_arm_pulse,
    output logic                        tx_payload_witness_clear_pulse,
    output logic [1:0]                  tx_payload_witness_stream_filter,
    output logic [10:0]                 tx_payload_witness_capture_words,
    output logic [11:0]                 tx_payload_witness_rd_word,
    output logic                        dac_tx_witness_arm_pulse,
    output logic                        dac_tx_witness_clear_pulse,
    output logic [8:0]                  dac_tx_witness_capture_words,
    output logic [9:0]                  dac_tx_witness_rd_word,
    output logic [63:0]                 unix_seconds
);

    localparam [31:0] CORE_VERSION = 32'h0001_000e;
    localparam [31:0] DEBUG_NFFT = 32'd1024;
    localparam [31:0] DEBUG_OBS_SAMPLE_RATE_HZ = 32'd61_440_000;
    localparam [31:0] PREVIEW_SAMPLE_RATE_HZ = 32'd245_760_000;
    localparam [31:0] PREVIEW_AXIS_BEAT_RATE_HZ = 32'd61_440_000;
    localparam [31:0] PREVIEW_MODE_FULLRATE_IQ = 32'd1;
    localparam [1:0]  SYNC_EXTERNAL_PPS   = 2'd0;
    localparam [1:0]  SYNC_SOFTWARE_EPOCH = 2'd1;
    localparam [1:0]  SYNC_FREE_RUN       = 2'd2;
    localparam [1:0]  CLOCK_REF_EXTERNAL  = 2'd0;
    localparam [1:0]  CLOCK_REF_TCXO      = 2'd1;
    localparam [1:0]  CLOCK_REF_GPS       = 2'd2;

    wire [63:0] tx_payload_witness_source_sample0 = tx_payload_witness_rfdc_sample_count << 2;
    wire [63:0] tx_payload_witness_preview_delta = tx_payload_witness_sample0 - preview_sample0;

    logic [AXI_ADDR_W-1:0] awaddr_latched;
    logic                  awaddr_valid;
    logic [31:0]           wdata_latched;
    logic [3:0]            wstrb_latched;
    logic                  wdata_valid;
    logic [AXI_ADDR_W-1:0] araddr_latched;
    logic                  read_pending;
    logic [15:0]           write_addr;
    logic [15:0]           read_addr;

    function automatic [31:0] lane_word(
        input [NINPUT*32-1:0] bus,
        input integer lane_idx
    );
        begin
            lane_word = bus[lane_idx*32 +: 32];
        end
    endfunction

    task automatic apply_wstrb(
        inout logic [31:0] reg_value,
        input logic [31:0] wdata,
        input logic [3:0]  wstrb
    );
        integer byte_idx;
        begin
            for (byte_idx = 0; byte_idx < 4; byte_idx = byte_idx + 1) begin
                if (wstrb[byte_idx]) begin
                    reg_value[byte_idx*8 +: 8] = wdata[byte_idx*8 +: 8];
                end
            end
        end
    endtask

    integer lane_idx;
    integer write_idx;
    logic [31:0] read_data_next;
    wire         aw_accept;
    wire         w_accept;
    wire         ar_accept;
    wire         have_write_addr;
    wire         have_write_data;

    assign aw_accept       = s_axi_awready && s_axi_awvalid && !s_axi_bvalid;
    assign w_accept        = s_axi_wready && s_axi_wvalid && !s_axi_bvalid;
    assign ar_accept       = s_axi_arready && s_axi_arvalid && !s_axi_rvalid;
    assign have_write_addr = awaddr_valid || aw_accept;
    assign have_write_data = wdata_valid || w_accept;

    function automatic [15:0] local_addr(input [AXI_ADDR_W-1:0] addr);
        begin
            local_addr = addr[15:0];
        end
    endfunction

    always_ff @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
        if (!s_axi_aresetn) begin
            s_axi_awready      <= 1'b1;
            s_axi_wready       <= 1'b1;
            s_axi_bresp        <= 2'b00;
            s_axi_bvalid       <= 1'b0;
            s_axi_arready      <= 1'b1;
            s_axi_rresp        <= 2'b00;
            s_axi_rvalid       <= 1'b0;
            s_axi_rdata        <= 32'd0;
            awaddr_latched     <= {AXI_ADDR_W{1'b0}};
            awaddr_valid       <= 1'b0;
            wdata_latched      <= 32'd0;
            wstrb_latched      <= 4'd0;
            wdata_valid        <= 1'b0;
            araddr_latched     <= {AXI_ADDR_W{1'b0}};
            read_pending       <= 1'b0;
            board_id           <= 16'd0;
            mode               <= 2'd0;
            arm_latched        <= 1'b0;
            soft_epoch_pulse   <= 1'b0;
            stop_pulse         <= 1'b0;
            soft_reset_pulse   <= 1'b0;
            debug_capture_start_pulse <= 1'b0;
            debug_capture_clear_pulse <= 1'b0;
            preview_capture_start_pulse <= 1'b0;
            preview_capture_clear_pulse <= 1'b0;
            preview_audit_clear_pulse <= 1'b0;
            tx_header_capture_arm_pulse <= 1'b0;
            tx_frame_capture_arm_pulse <= 1'b0;
            tx_payload_witness_arm_pulse <= 1'b0;
            tx_payload_witness_clear_pulse <= 1'b0;
            tx_payload_witness_stream_filter <= 2'd0;
            tx_payload_witness_capture_words <= 11'd1040;
            dac_tx_witness_arm_pulse <= 1'b0;
            dac_tx_witness_clear_pulse <= 1'b0;
            dac_tx_witness_capture_words <= 9'd256;
            tx_clear_pulse     <= 1'b0;
            pfb_clear_pulse    <= 1'b0;
            sync_mode          <= SYNC_EXTERNAL_PPS;
            clock_ref          <= CLOCK_REF_EXTERNAL;
            sample_rate_hz     <= 32'd100_000_000;
            quant_mode         <= 16'd0;
            scale_mode         <= 16'd0;
            scale_id           <= 32'd0;
            time_payload_nsamp <= 16'd256;
            spec_time_count    <= 16'd4;
            spec_chan_count    <= 16'd64;
            pfb_enable         <= 1'b1;
            pfb_taps           <= 16'd4;
            pfb_fft_shift      <= 16'd0;
            pfb_chan0          <= 32'd0;
            pfb_chan_count     <= 16'd64;
            pfb_time_count     <= 16'd4;
            chan_split         <= 32'd2048;
            src_ip             <= 32'h0a00_0101;
            dgx_a_ip           <= 32'h0a00_010a;
            dgx_b_ip           <= 32'h0a00_010b;
            time_dst_ip        <= 32'h0a00_0110;
            src_mac            <= 48'h0200_0000_0001;
            dgx_a_mac          <= 48'h0200_0000_000a;
            dgx_b_mac          <= 48'h0200_0000_000b;
            src_udp_port       <= 16'd4000;
            dgx_a_udp_port     <= 16'd4100;
            dgx_b_udp_port     <= 16'd4200;
            time_udp_port      <= 16'd4300;
            tx_control         <= 32'h0000_000d;
            tx_endpoint_enable <= 8'h07;
            tx_endpoint_ip_vec <= {
                32'd0, 32'd0, 32'd0, 32'd0, 32'd0,
                32'h0a00_0110, 32'h0a00_010b, 32'h0a00_010a
            };
            tx_endpoint_mac_vec <= {
                48'd0, 48'd0, 48'd0, 48'd0, 48'd0,
                48'h0200_0000_0010, 48'h0200_0000_000b, 48'h0200_0000_000a
            };
            tx_endpoint_src_port_vec <= {NINPUT{16'd4000}};
            tx_endpoint_dst_port_vec <= {
                16'd0, 16'd0, 16'd0, 16'd0, 16'd0,
                16'd4300, 16'd4200, 16'd4100
            };
            tx_spec_route_enable <= 8'h03;
            tx_spec_route_chan0_vec <= {
                32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd0, 32'd2048, 32'd0
            };
            tx_spec_route_chan_count_vec <= {
                16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd2048, 16'd2048
            };
            tx_spec_route_endpoint_vec <= {
                3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd1, 3'd0
            };
            tx_time_route_enable <= 8'h01;
            tx_time_route_input_mask_vec <= {
                16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'h00ff
            };
            tx_time_route_endpoint_vec <= {
                3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd0, 3'd2
            };
            rfdc_active_mask    <= 16'hffff;
            dac_tone_enable     <= 1'b1;
            dac_tone_amplitude  <= 16'd2048;
            dac_tone_phase_step <= 32'h0080_0000;
            dac_enable_mask <= 8'hff;
            dac_tone_amplitude_vec <= {NINPUT{16'd2048}};
            dac_tone_phase_step_vec <= {NINPUT{32'h0080_0000}};
            dac_tone_phase0_vec <= {NINPUT{32'd0}};
            dac_tone_phase_inject_vec <= {NINPUT{32'd0}};
            dac_tone_mode_vec <= {NINPUT{2'd0}};
            dac_phase_epoch <= 32'd0;
            preview_input_mask <= {{NINPUT-1{1'b0}}, 1'b1};
            preview_audit_source_select <= 2'd0;
            preview_audit_event_enable <= 1'b0;
            preview_audit_freeze_on_event <= 1'b1;
            preview_audit_event_threshold <= 16'd28000;
            unix_seconds       <= 64'd0;
        end else begin
            soft_epoch_pulse <= 1'b0;
            stop_pulse       <= 1'b0;
            soft_reset_pulse <= 1'b0;
            debug_capture_start_pulse <= 1'b0;
            debug_capture_clear_pulse <= 1'b0;
            preview_capture_start_pulse <= 1'b0;
            preview_capture_clear_pulse <= 1'b0;
            preview_audit_clear_pulse <= 1'b0;
            tx_header_capture_arm_pulse <= 1'b0;
            tx_frame_capture_arm_pulse <= 1'b0;
            tx_payload_witness_arm_pulse <= 1'b0;
            tx_payload_witness_clear_pulse <= 1'b0;
            dac_tx_witness_arm_pulse <= 1'b0;
            dac_tx_witness_clear_pulse <= 1'b0;
            tx_clear_pulse <= 1'b0;
            pfb_clear_pulse <= 1'b0;
            s_axi_awready    <= !awaddr_valid && !s_axi_bvalid;
            s_axi_wready     <= !wdata_valid && !s_axi_bvalid;
            s_axi_arready    <= !s_axi_rvalid && !read_pending;

            if (aw_accept) begin
                awaddr_latched <= s_axi_awaddr;
                awaddr_valid   <= 1'b1;
            end

            if (w_accept) begin
                wdata_latched <= s_axi_wdata;
                wstrb_latched <= s_axi_wstrb;
                wdata_valid   <= 1'b1;
            end

            if (have_write_addr && have_write_data && !s_axi_bvalid) begin
                write_addr = local_addr(aw_accept ? s_axi_awaddr : awaddr_latched);
                case (write_addr)
                    16'h0004: board_id <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0008: mode <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h000c: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            arm_latched <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                            soft_epoch_pulse <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[2] : wdata_latched[2])) begin
                            arm_latched <= 1'b0;
                            stop_pulse  <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[3] : wdata_latched[3])) begin
                            arm_latched      <= 1'b0;
                            soft_reset_pulse <= 1'b1;
                        end
                    end
                    16'h0020: begin
                        if (!arm_latched && !armed && !streaming) begin
                            if ((w_accept ? s_axi_wstrb[0] : wstrb_latched[0])) begin
                                case ((w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]))
                                    SYNC_EXTERNAL_PPS,
                                    SYNC_SOFTWARE_EPOCH,
                                    SYNC_FREE_RUN: sync_mode <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                                    default: sync_mode <= SYNC_EXTERNAL_PPS;
                                endcase
                            end
                            if ((w_accept ? s_axi_wstrb[2] : wstrb_latched[2])) begin
                                case ((w_accept ? s_axi_wdata[17:16] : wdata_latched[17:16]))
                                    CLOCK_REF_EXTERNAL,
                                    CLOCK_REF_TCXO,
                                    CLOCK_REF_GPS: clock_ref <= (w_accept ? s_axi_wdata[17:16] : wdata_latched[17:16]);
                                    default: clock_ref <= CLOCK_REF_EXTERNAL;
                                endcase
                            end
                        end
                    end
                    16'h0108: apply_wstrb(sample_rate_hz, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                    16'h010c: quant_mode <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0110: scale_mode <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0114: time_payload_nsamp <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0118: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            spec_time_count <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            pfb_time_count  <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    16'h011c: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            spec_chan_count <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            pfb_chan_count  <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    16'h0200: apply_wstrb(src_ip, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                    16'h0204: begin
                        apply_wstrb(dgx_a_ip, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                        tx_endpoint_ip_vec[0*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0208: begin
                        apply_wstrb(dgx_b_ip, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                        tx_endpoint_ip_vec[1*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h020c: begin
                        apply_wstrb(time_dst_ip, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                        tx_endpoint_ip_vec[2*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_enable[2] <= 1'b1;
                    end
                    16'h0210: src_mac[31:0] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0214: src_mac[47:32] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0218: begin
                        dgx_a_mac[31:0] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_mac_vec[0*48 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h021c: begin
                        dgx_a_mac[47:32] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_mac_vec[0*48 + 32 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0220: begin
                        dgx_b_mac[31:0] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_mac_vec[1*48 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0224: begin
                        dgx_b_mac[47:32] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_mac_vec[1*48 + 32 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0228: src_udp_port <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h022c: begin
                        dgx_a_udp_port <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_dst_port_vec[0*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0230: begin
                        dgx_b_udp_port <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_dst_port_vec[1*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0234: begin
                        time_udp_port <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_dst_port_vec[2*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        tx_endpoint_enable[2] <= 1'b1;
                    end
                    16'h0238: apply_wstrb(chan_split, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                    16'h0240: apply_wstrb(scale_id, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                    16'h0244: unix_seconds[31:0] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0248: unix_seconds[63:32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0350: begin
                        if (!arm_latched && !armed && !streaming &&
                            (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            rfdc_active_mask <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    16'h0378: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            tx_header_capture_arm_pulse <= 1'b1;
                        end
                    end
                    16'h0790: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            tx_payload_witness_arm_pulse <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                            tx_payload_witness_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0798: begin
                        case ((w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]))
                            2'd0,
                            2'd1,
                            2'd2: tx_payload_witness_stream_filter <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                            default: tx_payload_witness_stream_filter <= 2'd0;
                        endcase
                    end
                    16'h079c: begin
                        if ((w_accept ? s_axi_wdata[10:0] : wdata_latched[10:0]) == 11'd0) begin
                            tx_payload_witness_capture_words <= 11'd1040;
                        end else if ((w_accept ? s_axi_wdata[10:0] : wdata_latched[10:0]) <= 11'd1056) begin
                            tx_payload_witness_capture_words <= (w_accept ? s_axi_wdata[10:0] : wdata_latched[10:0]);
                        end else begin
                            tx_payload_witness_capture_words <= 11'd1040;
                        end
                    end
                    16'hb600: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            dac_tx_witness_arm_pulse <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                            dac_tx_witness_clear_pulse <= 1'b1;
                        end
                    end
                    16'hb608: begin
                        if ((w_accept ? s_axi_wdata[8:0] : wdata_latched[8:0]) == 9'd0) begin
                            dac_tx_witness_capture_words <= 9'd256;
                        end else if ((w_accept ? s_axi_wdata[8:0] : wdata_latched[8:0]) <= 9'd256) begin
                            dac_tx_witness_capture_words <= (w_accept ? s_axi_wdata[8:0] : wdata_latched[8:0]);
                        end else begin
                            dac_tx_witness_capture_words <= 9'd256;
                        end
                    end
                    16'hb000: begin
                        tx_control[3:0] <= (w_accept ? s_axi_wdata[3:0] : wdata_latched[3:0]);
                        if ((w_accept ? s_axi_wdata[4] : wdata_latched[4])) begin
                            tx_clear_pulse <= 1'b1;
                        end
                    end
                    16'hb030: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            tx_frame_capture_arm_pulse <= 1'b1;
                        end
                    end
                    16'h0400: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            debug_capture_start_pulse <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                            debug_capture_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0440: begin
                        if ((w_accept ? s_axi_wstrb[0] : wstrb_latched[0])) begin
                            dac_tone_enable <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]);
                            dac_enable_mask <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]) ? 8'hff : 8'h00;
                        end
                    end
                    16'h0444: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) begin
                            dac_tone_amplitude <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            dac_tone_amplitude_vec <= {NINPUT{(w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0])}};
                        end
                    end
                    16'h0448: begin
                        apply_wstrb(dac_tone_phase_step, (w_accept ? s_axi_wdata : wdata_latched), (w_accept ? s_axi_wstrb : wstrb_latched));
                        dac_tone_phase_step_vec <= {NINPUT{(w_accept ? s_axi_wdata : wdata_latched)}};
                    end
                    16'h0600: begin
                        if ((w_accept ? s_axi_wstrb[0] : wstrb_latched[0])) begin
                            dac_enable_mask <= (w_accept ? s_axi_wdata[7:0] : wdata_latched[7:0]);
                            dac_tone_enable <= |(w_accept ? s_axi_wdata[7:0] : wdata_latched[7:0]);
                        end
                    end
                    16'h0604: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) begin
                            dac_tone_amplitude <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            dac_tone_amplitude_vec <= {NINPUT{(w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0])}};
                        end
                    end
                    16'h0608: begin
                        dac_tone_phase_step <= (w_accept ? s_axi_wdata : wdata_latched);
                        dac_tone_phase_step_vec <= {NINPUT{(w_accept ? s_axi_wdata : wdata_latched)}};
                    end
                    16'h060c: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            dac_phase_epoch <= dac_phase_epoch + 32'd1;
                        end
                    end
                    16'h0620: dac_tone_phase_step_vec[0*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0624: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[0*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0628: dac_tone_phase0_vec[0*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h062c: dac_tone_phase_inject_vec[0*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0630: dac_tone_mode_vec[0*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0638: dac_tone_phase_step_vec[1*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h063c: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[1*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0640: dac_tone_phase0_vec[1*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0644: dac_tone_phase_inject_vec[1*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0648: dac_tone_mode_vec[1*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0650: dac_tone_phase_step_vec[2*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0654: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[2*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0658: dac_tone_phase0_vec[2*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h065c: dac_tone_phase_inject_vec[2*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0660: dac_tone_mode_vec[2*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0668: dac_tone_phase_step_vec[3*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h066c: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[3*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0670: dac_tone_phase0_vec[3*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0674: dac_tone_phase_inject_vec[3*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0678: dac_tone_mode_vec[3*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0680: dac_tone_phase_step_vec[4*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0684: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[4*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0688: dac_tone_phase0_vec[4*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h068c: dac_tone_phase_inject_vec[4*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h0690: dac_tone_mode_vec[4*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0698: dac_tone_phase_step_vec[5*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h069c: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[5*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h06a0: dac_tone_phase0_vec[5*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06a4: dac_tone_phase_inject_vec[5*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06a8: dac_tone_mode_vec[5*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h06b0: dac_tone_phase_step_vec[6*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06b4: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[6*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h06b8: dac_tone_phase0_vec[6*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06bc: dac_tone_phase_inject_vec[6*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06c0: dac_tone_mode_vec[6*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h06c8: dac_tone_phase_step_vec[7*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06cc: if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) <= 16'd8192) dac_tone_amplitude_vec[7*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h06d0: dac_tone_phase0_vec[7*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06d4: dac_tone_phase_inject_vec[7*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                    16'h06d8: dac_tone_mode_vec[7*2 +: 2] <= (w_accept ? s_axi_wdata[1:0] : wdata_latched[1:0]);
                    16'h0700: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            preview_capture_start_pulse <= 1'b1;
                        end
                        if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                            preview_capture_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0708: begin
                        if ((w_accept ? s_axi_wdata[NINPUT-1:0] : wdata_latched[NINPUT-1:0]) != {NINPUT{1'b0}}) begin
                            preview_input_mask <= (w_accept ? s_axi_wdata[NINPUT-1:0] : wdata_latched[NINPUT-1:0]);
                        end
                    end
                    16'h0730: begin
                        if ((w_accept ? s_axi_wdata[0] : wdata_latched[0])) begin
                            preview_audit_clear_pulse <= 1'b1;
                        end
                        preview_audit_event_enable <= (w_accept ? s_axi_wdata[1] : wdata_latched[1]);
                        preview_audit_freeze_on_event <= (w_accept ? s_axi_wdata[2] : wdata_latched[2]);
                        case ((w_accept ? s_axi_wdata[9:8] : wdata_latched[9:8]))
                            2'd0,
                            2'd1,
                            2'd2: preview_audit_source_select <= (w_accept ? s_axi_wdata[9:8] : wdata_latched[9:8]);
                            default: preview_audit_source_select <= 2'd0;
                        endcase
                    end
                    16'h0770: preview_audit_event_threshold <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0900: begin
                        if ((w_accept ? s_axi_wstrb[0] : wstrb_latched[0])) begin
                            pfb_enable <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]);
                            if ((w_accept ? s_axi_wdata[1] : wdata_latched[1])) begin
                                pfb_clear_pulse <= 1'b1;
                            end
                        end
                    end
                    16'h090c: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            pfb_taps <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    16'h0910: pfb_fft_shift <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                    16'h0914: begin
                        if ((w_accept ? s_axi_wdata[31:0] : wdata_latched[31:0]) < 32'd4096) begin
                            pfb_chan0 <= (w_accept ? s_axi_wdata[31:0] : wdata_latched[31:0]);
                        end
                    end
                    16'h0918: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            pfb_chan_count  <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            spec_chan_count <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    16'h091c: begin
                        if ((w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]) != 16'd0) begin
                            pfb_time_count  <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                            spec_time_count <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                        end
                    end
                    default: begin
                        if ((write_addr >= 16'hb100) && (write_addr < 16'hb200)) begin
                            write_idx = (write_addr - 16'hb100) >> 5;
                            case ((write_addr - 16'hb100) & 16'h001f)
                                16'h0000: tx_endpoint_enable[write_idx] <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]);
                                16'h0004: tx_endpoint_ip_vec[write_idx*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                                16'h0008: tx_endpoint_mac_vec[write_idx*48 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                                16'h000c: tx_endpoint_mac_vec[write_idx*48 + 32 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                                16'h0010: tx_endpoint_dst_port_vec[write_idx*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                                16'h0014: tx_endpoint_src_port_vec[write_idx*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                                default: begin
                                end
                            endcase
                        end else if ((write_addr >= 16'hb300) && (write_addr < 16'hb400)) begin
                            write_idx = (write_addr - 16'hb300) >> 5;
                            case ((write_addr - 16'hb300) & 16'h001f)
                                16'h0000: begin
                                    tx_spec_route_enable[write_idx] <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]);
                                    tx_spec_route_endpoint_vec[write_idx*3 +: 3] <= (w_accept ? s_axi_wdata[10:8] : wdata_latched[10:8]);
                                end
                                16'h0004: tx_spec_route_chan0_vec[write_idx*32 +: 32] <= (w_accept ? s_axi_wdata : wdata_latched);
                                16'h0008: tx_spec_route_chan_count_vec[write_idx*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                                default: begin
                                end
                            endcase
                        end else if ((write_addr >= 16'hb500) && (write_addr < 16'hb600)) begin
                            write_idx = (write_addr - 16'hb500) >> 5;
                            case ((write_addr - 16'hb500) & 16'h001f)
                                16'h0000: begin
                                    tx_time_route_enable[write_idx] <= (w_accept ? s_axi_wdata[0] : wdata_latched[0]);
                                    tx_time_route_endpoint_vec[write_idx*3 +: 3] <= (w_accept ? s_axi_wdata[10:8] : wdata_latched[10:8]);
                                end
                                16'h0004: tx_time_route_input_mask_vec[write_idx*16 +: 16] <= (w_accept ? s_axi_wdata[15:0] : wdata_latched[15:0]);
                                default: begin
                                end
                            endcase
                        end
                    end
                endcase
                s_axi_bvalid   <= 1'b1;
                awaddr_valid   <= 1'b0;
                wdata_valid    <= 1'b0;
            end

            if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end

            if (ar_accept) begin
                araddr_latched <= s_axi_araddr;
                read_pending   <= 1'b1;
            end

            if (read_pending && !s_axi_rvalid) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rdata  <= read_data_next;
                read_pending <= 1'b0;
            end

            if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    always_comb begin
        read_addr      = local_addr((s_axi_arvalid && s_axi_arready) ? s_axi_araddr : araddr_latched);
        read_data_next = 32'd0;
        lane_idx       = 0;
        debug_time_rd_addr = 10'd0;
        debug_fft_rd_addr  = 10'd0;
        preview_rd_input = 3'd0;
        preview_rd_addr = 10'd0;
        preview_event_rd_addr = 8'd0;
        tx_header_capture_rd_word = 5'd0;
        tx_frame_capture_rd_word = 5'd0;
        tx_payload_witness_rd_word = 12'd0;
        dac_tx_witness_rd_word = 10'd0;
        if ((read_addr >= 16'h0800) && (read_addr < 16'h1800)) begin
            debug_time_rd_addr = (read_addr - 16'h0800) >> 2;
        end
        if ((read_addr >= 16'h1800) && (read_addr < 16'h2800)) begin
            debug_fft_rd_addr = (read_addr - 16'h1800) >> 2;
        end
        if ((read_addr >= 16'h2800) && (read_addr < 16'ha800)) begin
            preview_rd_input = (read_addr - 16'h2800) >> 12;
            preview_rd_addr = ((read_addr - 16'h2800) & 16'h0fff) >> 2;
        end
        if ((read_addr >= 16'ha800) && (read_addr < 16'hac00)) begin
            preview_event_rd_addr = (read_addr - 16'ha800) >> 2;
        end
        if ((read_addr >= 16'h0380) && (read_addr < 16'h0400)) begin
            tx_header_capture_rd_word = (read_addr - 16'h0380) >> 2;
        end
        if ((read_addr >= 16'hb040) && (read_addr < 16'hb0c0)) begin
            tx_frame_capture_rd_word = (read_addr - 16'hb040) >> 2;
        end
        if ((read_addr >= 16'hd000) && (read_addr < 16'hf100)) begin
            tx_payload_witness_rd_word = (read_addr - 16'hd000) >> 2;
        end
        if ((read_addr >= 16'hc000) && (read_addr < 16'hd000)) begin
            dac_tx_witness_rd_word = (read_addr - 16'hc000) >> 2;
        end

        case (read_addr)
            16'h0000: read_data_next = CORE_VERSION;
            16'h0004: read_data_next = {16'd0, board_id};
            16'h0008: read_data_next = {30'd0, mode};
            16'h000c: read_data_next = {28'd0, soft_reset_pulse, stop_pulse, soft_epoch_pulse, arm_latched};
            16'h0010: read_data_next = {20'd0, fsm_state, 3'd0, waiting_for_epoch, active_sync_mode, streaming, armed};
            16'h0014: read_data_next = {30'd0, ref_locked, pps_seen};
            16'h0018: read_data_next = {31'd0, ref_locked};
            16'h001c: read_data_next = error_flags;
            16'h0020: read_data_next = {14'd0, clock_ref, 14'd0, sync_mode};
            16'h00f0: read_data_next = (s_axi_arvalid ? s_axi_araddr[31:0] : araddr_latched[31:0]);
            16'h00f4: read_data_next = awaddr_latched[31:0];
            16'h0100: read_data_next = 32'd8;
            16'h0104: read_data_next = {13'd0, board_id, 3'b000};
            16'h0108: read_data_next = sample_rate_hz;
            16'h010c: read_data_next = {16'd0, quant_mode};
            16'h0110: read_data_next = {16'd0, scale_mode};
            16'h0114: read_data_next = {16'd0, time_payload_nsamp};
            16'h0118: read_data_next = {16'd0, spec_time_count};
            16'h011c: read_data_next = {16'd0, spec_chan_count};
            16'h0200: read_data_next = src_ip;
            16'h0204: read_data_next = dgx_a_ip;
            16'h0208: read_data_next = dgx_b_ip;
            16'h020c: read_data_next = time_dst_ip;
            16'h0210: read_data_next = src_mac[31:0];
            16'h0214: read_data_next = {16'd0, src_mac[47:32]};
            16'h0218: read_data_next = dgx_a_mac[31:0];
            16'h021c: read_data_next = {16'd0, dgx_a_mac[47:32]};
            16'h0220: read_data_next = dgx_b_mac[31:0];
            16'h0224: read_data_next = {16'd0, dgx_b_mac[47:32]};
            16'h0228: read_data_next = {16'd0, src_udp_port};
            16'h022c: read_data_next = {16'd0, dgx_a_udp_port};
            16'h0230: read_data_next = {16'd0, dgx_b_udp_port};
            16'h0234: read_data_next = {16'd0, time_udp_port};
            16'h0238: read_data_next = chan_split;
            16'h0240: read_data_next = scale_id;
            16'h0244: read_data_next = unix_seconds[31:0];
            16'h0248: read_data_next = unix_seconds[63:32];
            16'h0300: read_data_next = monitor_sample_count;
            16'h0304: read_data_next = spec_packet_count;
            16'h0308: read_data_next = spec_udp_byte_count;
            16'h030c: read_data_next = time_packet_count;
            16'h0310: read_data_next = time_udp_byte_count;
            16'h0314: read_data_next = time_dropped_count;
            16'h0318: read_data_next = spec_seq_no;
            16'h031c: read_data_next = time_seq_no;
            16'h0320: read_data_next = time_sample0[31:0];
            16'h0324: read_data_next = time_sample0[63:32];
            16'h0328: read_data_next = time_frame_id[31:0];
            16'h032c: read_data_next = time_frame_id[63:32];
            16'h0330: read_data_next = spec_frame_id[31:0];
            16'h0334: read_data_next = spec_frame_id[63:32];
            16'h0338: read_data_next = spec_chan0;
            16'h0340: read_data_next = rfdc_status_flags;
            16'h0344: read_data_next = rfdc_sample_count[31:0];
            16'h0348: read_data_next = rfdc_sample_count[63:32];
            16'h034c: read_data_next = rfdc_dropped_count;
            16'h0350: read_data_next = {16'd0, rfdc_active_mask};
            16'h0354: read_data_next = {16'd0, rfdc_current_valid_mask};
            16'h0358: read_data_next = {16'd0, rfdc_seen_valid_mask};
            16'h0360: read_data_next = tx_link_status_flags;
            16'h0364: read_data_next = tx_dry_run_packet_count;
            16'h0368: read_data_next = tx_dry_run_byte_count;
            16'h036c: read_data_next = tx_fifo_level_words;
            16'h0370: read_data_next = tx_fifo_high_water_words;
            16'h0374: read_data_next = tx_fifo_backpressure_cycles;
            16'h0378: read_data_next = 32'd0;
            16'h037c: read_data_next = {11'd0, tx_header_capture_word_count, 14'd0, tx_header_capture_valid, tx_header_capture_armed};
            16'h0790: read_data_next = 32'd0;
            16'h0794: read_data_next = {
                tx_payload_witness_stream_type[7:0],
                5'd0,
                tx_payload_witness_word_count,
                3'd0,
                tx_payload_witness_filter_mismatch,
                tx_payload_witness_overflow,
                tx_payload_witness_capturing,
                tx_payload_witness_valid,
                tx_payload_witness_armed
            };
            16'h0798: read_data_next = {30'd0, tx_payload_witness_stream_filter};
            16'h079c: read_data_next = {21'd0, tx_payload_witness_capture_words};
            16'h07a0: read_data_next = tx_payload_witness_sample0[31:0];
            16'h07a4: read_data_next = tx_payload_witness_sample0[63:32];
            16'h07a8: read_data_next = tx_payload_witness_frame_id[31:0];
            16'h07ac: read_data_next = tx_payload_witness_frame_id[63:32];
            16'h07b0: read_data_next = tx_payload_witness_seq_no;
            16'h07b4: read_data_next = tx_payload_witness_chan0;
            16'h07b8: read_data_next = tx_payload_witness_layout_word[31:0];
            16'h07bc: read_data_next = tx_payload_witness_layout_word[63:32];
            16'h07c0: read_data_next = tx_payload_witness_payload_bytes;
            16'h07c4: read_data_next = tx_payload_witness_route_meta;
            16'h07c8: read_data_next = tx_payload_witness_rfdc_flags;
            16'h07cc: read_data_next = tx_payload_witness_dac_phase_epoch;
            16'h07d0: read_data_next = tx_payload_witness_rfdc_sample_count[31:0];
            16'h07d4: read_data_next = tx_payload_witness_rfdc_sample_count[63:32];
            16'h07d8: read_data_next = {
                tx_payload_witness_stream_type[7:0],
                5'd0,
                tx_payload_witness_word_count,
                3'd0,
                tx_payload_witness_filter_mismatch,
                tx_payload_witness_overflow,
                preview_error,
                preview_done,
                tx_payload_witness_valid
            };
            16'h07dc: read_data_next = tx_payload_witness_source_sample0[31:0];
            16'h07e0: read_data_next = tx_payload_witness_source_sample0[63:32];
            16'h07e4: read_data_next = preview_sample0[31:0];
            16'h07e8: read_data_next = preview_sample0[63:32];
            16'h07ec: read_data_next = tx_payload_witness_sample0[31:0];
            16'h07f0: read_data_next = tx_payload_witness_sample0[63:32];
            16'h07f4: read_data_next = tx_payload_witness_preview_delta[31:0];
            16'h07f8: read_data_next = tx_payload_witness_preview_delta[63:32];
            16'h07fc: read_data_next = rfdc_status_flags;
            16'hb600: read_data_next = 32'd0;
            16'hb604: read_data_next = {
                15'd0,
                dac_tx_witness_word_count,
                1'b0,
                dac_tx_witness_ready_gap_seen,
                dac_tx_witness_tready_seen,
                dac_tx_witness_tvalid_seen,
                dac_tx_witness_overflow,
                dac_tx_witness_capturing,
                dac_tx_witness_valid,
                dac_tx_witness_armed
            };
            16'hb608: read_data_next = {23'd0, dac_tx_witness_capture_words};
            16'hb60c: read_data_next = 32'd256;
            16'hb610: read_data_next = dac_tx_witness_phase_epoch;
            16'hb614: read_data_next = dac_tx_witness_phase_acc;
            16'hb618: read_data_next = dac_tx_witness_phase_step;
            16'hb61c: read_data_next = dac_tx_witness_phase0;
            16'hb620: read_data_next = dac_tx_witness_mode;
            16'hb624: read_data_next = dac_tx_witness_ready_gap_count;
            16'hb000: read_data_next = {28'd0, tx_control[3:0]};
            16'hb004: read_data_next = tx_preflight_status_flags;
            16'hb008: read_data_next = tx_frame_built_count;
            16'hb00c: read_data_next = tx_frame_sent_count;
            16'hb010: read_data_next = tx_frame_dropped_count;
            16'hb014: read_data_next = tx_frame_byte_count;
            16'hb018: read_data_next = tx_route_miss_count;
            16'hb01c: read_data_next = tx_route_error_count;
            16'hb020: read_data_next = tx_dry_run_packet_count;
            16'hb024: read_data_next = tx_dry_run_byte_count;
            16'hb028: read_data_next = {29'd0, tx_selected_endpoint_id};
            16'hb02c: read_data_next = {28'd0, tx_selected_route_is_time, tx_selected_route_id};
            16'hb030: read_data_next = 32'd0;
            16'hb034: read_data_next = {11'd0, tx_frame_capture_word_count, 14'd0, tx_frame_capture_valid, tx_frame_capture_armed};
            16'h0400: read_data_next = 32'd0;
            16'h0404: read_data_next = {29'd0, debug_done, debug_error, debug_busy};
            16'h0408: read_data_next = DEBUG_NFFT;
            16'h040c: read_data_next = DEBUG_OBS_SAMPLE_RATE_HZ;
            16'h0410: read_data_next = debug_peak_bin;
            16'h0414: read_data_next = debug_peak_power;
            16'h0418: read_data_next = debug_capture_count;
            16'h0440: read_data_next = {31'd0, dac_tone_enable};
            16'h0444: read_data_next = {16'd0, dac_tone_amplitude};
            16'h0448: read_data_next = dac_tone_phase_step;
            16'h0600: read_data_next = {24'd0, dac_enable_mask};
            16'h0604: read_data_next = {16'd0, dac_tone_amplitude};
            16'h0608: read_data_next = dac_tone_phase_step;
            16'h060c: read_data_next = dac_phase_epoch;
            16'h0620: read_data_next = dac_tone_phase_step_vec[0*32 +: 32];
            16'h0624: read_data_next = {16'd0, dac_tone_amplitude_vec[0*16 +: 16]};
            16'h0628: read_data_next = dac_tone_phase0_vec[0*32 +: 32];
            16'h062c: read_data_next = dac_tone_phase_inject_vec[0*32 +: 32];
            16'h0630: read_data_next = {30'd0, dac_tone_mode_vec[0*2 +: 2]};
            16'h0638: read_data_next = dac_tone_phase_step_vec[1*32 +: 32];
            16'h063c: read_data_next = {16'd0, dac_tone_amplitude_vec[1*16 +: 16]};
            16'h0640: read_data_next = dac_tone_phase0_vec[1*32 +: 32];
            16'h0644: read_data_next = dac_tone_phase_inject_vec[1*32 +: 32];
            16'h0648: read_data_next = {30'd0, dac_tone_mode_vec[1*2 +: 2]};
            16'h0650: read_data_next = dac_tone_phase_step_vec[2*32 +: 32];
            16'h0654: read_data_next = {16'd0, dac_tone_amplitude_vec[2*16 +: 16]};
            16'h0658: read_data_next = dac_tone_phase0_vec[2*32 +: 32];
            16'h065c: read_data_next = dac_tone_phase_inject_vec[2*32 +: 32];
            16'h0660: read_data_next = {30'd0, dac_tone_mode_vec[2*2 +: 2]};
            16'h0668: read_data_next = dac_tone_phase_step_vec[3*32 +: 32];
            16'h066c: read_data_next = {16'd0, dac_tone_amplitude_vec[3*16 +: 16]};
            16'h0670: read_data_next = dac_tone_phase0_vec[3*32 +: 32];
            16'h0674: read_data_next = dac_tone_phase_inject_vec[3*32 +: 32];
            16'h0678: read_data_next = {30'd0, dac_tone_mode_vec[3*2 +: 2]};
            16'h0680: read_data_next = dac_tone_phase_step_vec[4*32 +: 32];
            16'h0684: read_data_next = {16'd0, dac_tone_amplitude_vec[4*16 +: 16]};
            16'h0688: read_data_next = dac_tone_phase0_vec[4*32 +: 32];
            16'h068c: read_data_next = dac_tone_phase_inject_vec[4*32 +: 32];
            16'h0690: read_data_next = {30'd0, dac_tone_mode_vec[4*2 +: 2]};
            16'h0698: read_data_next = dac_tone_phase_step_vec[5*32 +: 32];
            16'h069c: read_data_next = {16'd0, dac_tone_amplitude_vec[5*16 +: 16]};
            16'h06a0: read_data_next = dac_tone_phase0_vec[5*32 +: 32];
            16'h06a4: read_data_next = dac_tone_phase_inject_vec[5*32 +: 32];
            16'h06a8: read_data_next = {30'd0, dac_tone_mode_vec[5*2 +: 2]};
            16'h06b0: read_data_next = dac_tone_phase_step_vec[6*32 +: 32];
            16'h06b4: read_data_next = {16'd0, dac_tone_amplitude_vec[6*16 +: 16]};
            16'h06b8: read_data_next = dac_tone_phase0_vec[6*32 +: 32];
            16'h06bc: read_data_next = dac_tone_phase_inject_vec[6*32 +: 32];
            16'h06c0: read_data_next = {30'd0, dac_tone_mode_vec[6*2 +: 2]};
            16'h06c8: read_data_next = dac_tone_phase_step_vec[7*32 +: 32];
            16'h06cc: read_data_next = {16'd0, dac_tone_amplitude_vec[7*16 +: 16]};
            16'h06d0: read_data_next = dac_tone_phase0_vec[7*32 +: 32];
            16'h06d4: read_data_next = dac_tone_phase_inject_vec[7*32 +: 32];
            16'h06d8: read_data_next = {30'd0, dac_tone_mode_vec[7*2 +: 2]};
            16'h06e0: read_data_next = dac_audit_phase_epoch_seen;
            16'h06e4: read_data_next = dac_audit_ch0_phase_acc;
            16'h06e8: read_data_next = dac_audit_ch0_phase_step;
            16'h06ec: read_data_next = dac_audit_ch0_phase0;
            16'h06f0: read_data_next = dac_audit_ch0_mode;
            16'h0700: read_data_next = 32'd0;
            16'h0704: read_data_next = {29'd0, preview_done, preview_error, preview_busy};
            16'h0708: read_data_next = {{(32-NINPUT){1'b0}}, preview_input_mask};
            16'h070c: read_data_next = preview_capture_count;
            16'h0710: read_data_next = preview_sample0[31:0];
            16'h0714: read_data_next = preview_sample0[63:32];
            16'h0718: read_data_next = 32'd1024;
            16'h071c: read_data_next = PREVIEW_SAMPLE_RATE_HZ;
            16'h0720: read_data_next = PREVIEW_AXIS_BEAT_RATE_HZ;
            16'h0724: read_data_next = PREVIEW_MODE_FULLRATE_IQ;
            16'h0730: read_data_next = {22'd0, preview_audit_source_select, 5'd0, preview_audit_freeze_on_event, preview_audit_event_enable, 1'b0};
            16'h0734: read_data_next = preview_audit_status;
            16'h0738: read_data_next = preview_audit_start_count;
            16'h073c: read_data_next = preview_audit_first_count;
            16'h0740: read_data_next = preview_audit_done_count;
            16'h0744: read_data_next = preview_audit_start_sample0[31:0];
            16'h0748: read_data_next = preview_audit_start_sample0[63:32];
            16'h074c: read_data_next = preview_audit_first_sample0[31:0];
            16'h0750: read_data_next = preview_audit_first_sample0[63:32];
            16'h0754: read_data_next = preview_audit_done_sample0[31:0];
            16'h0758: read_data_next = preview_audit_done_sample0[63:32];
            16'h075c: read_data_next = preview_audit_start_to_first_latency;
            16'h0760: read_data_next = preview_audit_capture_beats;
            16'h0764: read_data_next = preview_audit_valid_gap_count;
            16'h0768: read_data_next = preview_audit_sample0_error_count;
            16'h076c: read_data_next = 32'd0;
            16'h0770: read_data_next = {16'd0, preview_audit_event_threshold};
            16'h0774: read_data_next = preview_event_sample0[31:0];
            16'h0778: read_data_next = preview_event_sample0[63:32];
            16'h077c: read_data_next = preview_event_max_code;
            16'h0780: read_data_next = preview_event_info;
            16'h0784: read_data_next = preview_event_rfdc_flags;
            16'h0788: read_data_next = preview_event_dac_phase_epoch;
            16'h078c: read_data_next = 32'd256;
            16'h0900: read_data_next = {31'd0, pfb_enable};
            16'h0904: read_data_next = pfb_status;
            16'h0908: read_data_next = 32'd4096;
            16'h090c: read_data_next = {16'd0, pfb_taps};
            16'h0910: read_data_next = {16'd0, pfb_fft_shift};
            16'h0914: read_data_next = pfb_chan0;
            16'h0918: read_data_next = {16'd0, pfb_chan_count};
            16'h091c: read_data_next = {16'd0, pfb_time_count};
            16'h0920: read_data_next = pfb_frame_count;
            16'h0924: read_data_next = pfb_overflow_count;
            16'h0928: read_data_next = pfb_peak_chan;
            16'h092c: read_data_next = pfb_peak_power;
            default: begin
                if ((read_addr >= 16'h0500) && (read_addr < 16'h0520)) begin
                    lane_idx = (read_addr - 16'h0500) >> 2;
                    read_data_next = lane_word(clip_counts, lane_idx);
                end else if ((read_addr >= 16'h0520) && (read_addr < 16'h0540)) begin
                    lane_idx = (read_addr - 16'h0520) >> 2;
                    read_data_next = lane_word(mean_mags, lane_idx);
                end else if ((read_addr >= 16'h0380) && (read_addr < 16'h0400)) begin
                    read_data_next = tx_header_capture_rd_data;
                end else if ((read_addr >= 16'hb040) && (read_addr < 16'hb0c0)) begin
                    read_data_next = tx_frame_capture_rd_data;
                end else if ((read_addr >= 16'hb100) && (read_addr < 16'hb200)) begin
                    lane_idx = (read_addr - 16'hb100) >> 5;
                    case ((read_addr - 16'hb100) & 16'h001f)
                        16'h0000: read_data_next = {31'd0, tx_endpoint_enable[lane_idx]};
                        16'h0004: read_data_next = tx_endpoint_ip_vec[lane_idx*32 +: 32];
                        16'h0008: read_data_next = tx_endpoint_mac_vec[lane_idx*48 +: 32];
                        16'h000c: read_data_next = {16'd0, tx_endpoint_mac_vec[lane_idx*48 + 32 +: 16]};
                        16'h0010: read_data_next = {16'd0, tx_endpoint_dst_port_vec[lane_idx*16 +: 16]};
                        16'h0014: read_data_next = {16'd0, tx_endpoint_src_port_vec[lane_idx*16 +: 16]};
                        default: read_data_next = 32'd0;
                    endcase
                end else if ((read_addr >= 16'hb300) && (read_addr < 16'hb400)) begin
                    lane_idx = (read_addr - 16'hb300) >> 5;
                    case ((read_addr - 16'hb300) & 16'h001f)
                        16'h0000: read_data_next = {21'd0, tx_spec_route_endpoint_vec[lane_idx*3 +: 3], 7'd0, tx_spec_route_enable[lane_idx]};
                        16'h0004: read_data_next = tx_spec_route_chan0_vec[lane_idx*32 +: 32];
                        16'h0008: read_data_next = {16'd0, tx_spec_route_chan_count_vec[lane_idx*16 +: 16]};
                        16'h000c: read_data_next = tx_spec_route_hit_counts[lane_idx*32 +: 32];
                        default: read_data_next = 32'd0;
                    endcase
                end else if ((read_addr >= 16'hb500) && (read_addr < 16'hb600)) begin
                    lane_idx = (read_addr - 16'hb500) >> 5;
                    case ((read_addr - 16'hb500) & 16'h001f)
                        16'h0000: read_data_next = {21'd0, tx_time_route_endpoint_vec[lane_idx*3 +: 3], 7'd0, tx_time_route_enable[lane_idx]};
                        16'h0004: read_data_next = {16'd0, tx_time_route_input_mask_vec[lane_idx*16 +: 16]};
                        16'h000c: read_data_next = tx_time_route_hit_counts[lane_idx*32 +: 32];
                        default: read_data_next = 32'd0;
                    endcase
                end else if ((read_addr >= 16'h0800) && (read_addr < 16'h1800)) begin
                    read_data_next = debug_time_rd_data;
                end else if ((read_addr >= 16'h1800) && (read_addr < 16'h2800)) begin
                    read_data_next = debug_fft_rd_data;
                end else if ((read_addr >= 16'h2800) && (read_addr < 16'ha800)) begin
                    read_data_next = preview_rd_data;
                end else if ((read_addr >= 16'ha800) && (read_addr < 16'hac00)) begin
                    read_data_next = preview_event_rd_data;
                end else if ((read_addr >= 16'hd000) && (read_addr < 16'hf100)) begin
                    read_data_next = tx_payload_witness_rd_data;
                end else if ((read_addr >= 16'hc000) && (read_addr < 16'hd000)) begin
                    read_data_next = dac_tx_witness_rd_data;
                end else begin
                    read_data_next = 32'd0;
                end
            end
        endcase
    end

endmodule
