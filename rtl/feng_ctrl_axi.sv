module feng_ctrl_axi #(
    parameter integer AXI_ADDR_W = 32,
    parameter integer AXI_DATA_W = 32,
    parameter integer NINPUT     = 8,
    parameter integer N_TX_ENDPOINTS = 72,
    parameter integer N_SPEC_ROUTES  = 64,
    parameter integer N_TIME_ROUTES  = 8,
    parameter bit     PRODUCTION_27H = 1'b0,
    parameter bit     PRODUCTION_27J_PFB = 1'b0,
    parameter bit     RAW_WITNESS_DIAGNOSTIC = 1'b0
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
    input  wire [63:0]                  pps_count,
    input  wire                         ref_locked,
    input  wire [31:0]                  error_flags,
    input  wire [31:0]                  stage31_sync_status,
    input  wire [31:0]                  stage31_sync_error,
    input  wire [63:0]                  stage31_active_generation,
    input  wire [63:0]                  stage31_actual_commit_pps_count,
    input  wire [63:0]                  stage31_actual_epoch_raw_sample0,
    input  wire [63:0]                  stage31_actual_first_time_sample0,
    input  wire [63:0]                  stage31_actual_first_spec_sample0,
    input  wire [31:0]                  monitor_sample_count,
    input  wire [NINPUT*32-1:0]         clip_counts,
    input  wire [NINPUT*32-1:0]         mean_mags,
    input  wire [31:0]                  spec_packet_count,
    input  wire [31:0]                  spec_udp_byte_count,
    input  wire [31:0]                  time_packet_count,
    input  wire [31:0]                  time_udp_byte_count,
    input  wire [31:0]                  time_dropped_count,
    input  wire [31:0]                  spec_dropped_count,
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
    input  wire [31:0]                  science_dropped_beat_count,
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
    input  wire [31:0]                  tx_cmac_source_status,
    input  wire [7:0]                   tx_selected_endpoint_id,
    input  wire [5:0]                   tx_selected_route_id,
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
    input  wire                         rfdc_axis_raw_witness_armed,
    input  wire                         rfdc_axis_raw_witness_valid,
    input  wire                         rfdc_axis_raw_witness_capturing,
    input  wire                         rfdc_axis_raw_witness_overflow,
    input  wire                         rfdc_axis_raw_witness_tvalid_seen,
    input  wire [8:0]                   rfdc_axis_raw_witness_beat_count,
    input  wire [2:0]                   rfdc_axis_raw_witness_channel_select,
    input  wire [63:0]                  rfdc_axis_raw_witness_sample0,
    input  wire [31:0]                  rfdc_axis_raw_witness_rfdc_flags,
    input  wire [15:0]                  rfdc_axis_raw_witness_valid_mask,
    input  wire [31:0]                  rfdc_axis_raw_witness_rd_data,
    input  wire [N_SPEC_ROUTES*32-1:0]  tx_spec_route_hit_counts,
    input  wire [N_TIME_ROUTES*32-1:0]  tx_time_route_hit_counts,
    input  wire [31:0]                  pfb_status,
    input  wire [31:0]                  pfb_frame_count,
    input  wire [31:0]                  pfb_overflow_count,
    input  wire [31:0]                  pfb_data_halt_count,
    input  wire [31:0]                  pfb_xfft_event_count,
    input  wire [31:0]                  pfb_tile_overflow_count,
    input  wire [31:0]                  pfb_xfft_tlast_unexpected_count,
    input  wire [31:0]                  pfb_xfft_tlast_missing_count,
    input  wire [31:0]                  pfb_xfft_fft_overflow_count,
    input  wire [31:0]                  pfb_xfft_data_out_halt_count,
    input  wire [31:0]                  pfb_xfft_status_halt_count,
    input  wire [31:0]                  pfb_capture_backpressure_count,
    input  wire [31:0]                  pfb_frame_sample0_overflow_count,
    input  wire [31:0]                  pfb_input_fifo_level,
    input  wire [31:0]                  pfb_peak_chan,
    input  wire [31:0]                  pfb_peak_power,
    input  wire [31:0]                  pfb_coeff_status,
    input  wire [31:0]                  pfb_coeff_loaded_count,
    input  wire [31:0]                  pfb_coeff_active_id,
    input  wire [31:0]                  pfb_coeff_active_checksum,
    input  wire [31:0]                  pfb_coeff_error_count,
    input  wire                         science_aa100_active,
    input  wire                         science_aa100_primed,
    input  wire [31:0]                  science_aa100_coeff_version,
    input  wire [31:0]                  time_ddr_ring_status,
    input  wire [31:0]                  time_ddr_ring_occupancy,
    input  wire [31:0]                  time_ddr_ring_write_count,
    input  wire [31:0]                  time_ddr_ring_read_count,
    input  wire [31:0]                  time_ddr_ring_drop_count,
    input  wire [31:0]                  time_ddr_ring_error_count,
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
    output logic                        stage31_prepare_pulse,
    output logic                        stage31_arm_pulse,
    output logic                        stage31_abort_pulse,
    output logic                        stage31_clear_status_pulse,
    output logic [63:0]                 stage31_generation,
    output logic [63:0]                 stage31_target_pps_count,
    output logic [63:0]                 stage31_epoch_tai_seconds,
    output logic [63:0]                 stage31_first_sample0,
    output logic [63:0]                 stage31_observation_tag,
    output logic [31:0]                 stage31_signal_chain_tag,
    output logic [31:0]                 stage31_schedule_tag,
    output logic [31:0]                 stage31_mts_result_id,
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
    output logic                        pfb_coeff_load_start_pulse,
    output logic                        pfb_coeff_commit_pulse,
    output logic                        pfb_coeff_abort_pulse,
    output logic                        pfb_coeff_write_pulse,
    output logic [3:0]                  pfb_coeff_requested_taps,
    output logic [13:0]                 pfb_coeff_index,
    output logic signed [17:0]          pfb_coeff_data,
    output logic [31:0]                 pfb_coeff_id,
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
    output logic [N_TX_ENDPOINTS-1:0]   tx_endpoint_enable,
    output logic [N_TX_ENDPOINTS*32-1:0] tx_endpoint_ip_vec,
    output logic [N_TX_ENDPOINTS*48-1:0] tx_endpoint_mac_vec,
    output logic [N_TX_ENDPOINTS*16-1:0] tx_endpoint_src_port_vec,
    output logic [N_TX_ENDPOINTS*16-1:0] tx_endpoint_dst_port_vec,
    output logic [31:0]                 qsfp_test_interval_cycles,
    output logic [N_SPEC_ROUTES-1:0]    tx_spec_route_enable,
    output logic [N_SPEC_ROUTES*32-1:0] tx_spec_route_chan0_vec,
    output logic [N_SPEC_ROUTES*16-1:0] tx_spec_route_chan_count_vec,
    output logic [N_SPEC_ROUTES*8-1:0]  tx_spec_route_endpoint_vec,
    output logic [N_TIME_ROUTES-1:0]    tx_time_route_enable,
    output logic [N_TIME_ROUTES*16-1:0] tx_time_route_input_mask_vec,
    output logic [N_TIME_ROUTES*8-1:0]  tx_time_route_endpoint_vec,
    output logic [15:0]                 rfdc_active_mask,
    output logic                        diag_adc_force_zero,
    output logic                        diag_adc_force_hold,
    output logic [7:0]                  diag_adc_channel_mask,
    output logic                        diag_dac_gate,
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
    output logic                        rfdc_axis_raw_witness_arm_pulse,
    output logic                        rfdc_axis_raw_witness_clear_pulse,
    output logic [2:0]                  rfdc_axis_raw_witness_channel_select_ctrl,
    output logic [8:0]                  rfdc_axis_raw_witness_capture_beats,
    output logic [9:0]                  rfdc_axis_raw_witness_rd_word,
    output logic [63:0]                 unix_seconds,
    output logic [31:0]                 time_live_interval_beats,
    output logic                        time_ddr_ring_enable,
    output logic                        time_ddr_ring_clear_pulse,
    output logic [63:0]                 time_ddr_ring_base_addr,
    output logic [15:0]                 time_ddr_ring_slots,
    output logic                        time_multiflow_enable,
    output logic [2:0]                  time_multiflow_base_endpoint,
    output logic [3:0]                  time_multiflow_count,
    output wire [1:0]                   science_bandwidth_mode_cfg,
    output wire [2:0]                   science_output_mode_cfg
);

`ifdef T510_STAGE27J_PFB
    localparam [31:0] CORE_VERSION = 32'h0001_0031;
`elsif T510_STAGE27I_ANTI_ALIAS
    localparam [31:0] CORE_VERSION = 32'h0001_002B;
`elsif T510_STAGE27I_RAW_WITNESS
    localparam [31:0] CORE_VERSION = 32'h0001_002A;
`else
    localparam [31:0] CORE_VERSION = 32'h0001_0029;
`endif
    localparam [31:0] DEBUG_NFFT = 32'd1024;
    localparam [31:0] DEBUG_OBS_SAMPLE_RATE_HZ = 32'd61_440_000;
    localparam [31:0] PREVIEW_SAMPLE_RATE_HZ = 32'd245_760_000;
    localparam [31:0] PREVIEW_AXIS_BEAT_RATE_HZ = 32'd61_440_000;
    localparam [31:0] PREVIEW_MODE_FULLRATE_IQ = 32'd1;
    localparam [31:0] SCIENCE_CAPABILITY_WORD = 32'h0000_0707;
    localparam [2:0]  SCIENCE_MODE_OFF              = 3'd0;
    localparam [2:0]  SCIENCE_MODE_TIME_ONLY        = 3'd1;
    localparam [2:0]  SCIENCE_MODE_SPEC_ONLY        = 3'd2;
    localparam [2:0]  SCIENCE_MODE_TIME_SPEC        = 3'd3;
    localparam [2:0]  SCIENCE_MODE_TIME_MONITOR_SPEC = 3'd4;
    localparam [15:0] FFT_ONLY_DEFAULT_SHIFT = 16'h0556;
    localparam [1:0]  SYNC_EXTERNAL_PPS   = 2'd0;
    localparam [1:0]  SYNC_SOFTWARE_EPOCH = 2'd1;
    localparam [1:0]  SYNC_FREE_RUN       = 2'd2;
    localparam [1:0]  CLOCK_REF_EXTERNAL  = 2'd0;
    localparam [1:0]  CLOCK_REF_TCXO      = 2'd1;
    localparam [1:0]  CLOCK_REF_GPS       = 2'd2;

    wire [63:0] tx_payload_witness_source_sample0 = tx_payload_witness_rfdc_sample_count << 2;
    wire [63:0] tx_payload_witness_preview_delta = tx_payload_witness_sample0 - preview_sample0;
    logic [31:0] science_control;
    logic [1:0]  science_bandwidth_mode;
    logic [2:0]  science_output_mode;
    wire         science_live_requested;
    wire         science_time_enabled;
    wire         science_spec_enabled;
    wire         science_time_spec_rejected;
    wire         science_cmac_live_ready;
    wire         fengine_science_valid;
    wire         fengine_overflow_seen;
    wire         science_rate_drop_seen;
    wire [31:0] science_block_reason;
    wire [31:0] science_status_word;

    logic [AXI_ADDR_W-1:0] awaddr_latched;
    logic                  awaddr_valid;
    logic [31:0]           wdata_latched;
    logic [3:0]            wstrb_latched;
    logic                  wdata_valid;
    logic [AXI_ADDR_W-1:0] araddr_latched;
    logic                  read_pending;
    logic [1:0]            read_wait_cycles;
    logic [31:0]           read_data_stage;
    logic [17:0]           read_addr;
    logic                  write_exec_valid;
    logic [17:0]           write_exec_addr;
    logic [31:0]           write_exec_data;
    logic [3:0]            write_exec_strb;
    logic [6:0]            tx_endpoint_indirect_index;
    logic [5:0]            tx_spec_route_indirect_index;
    logic [2:0]            tx_time_route_indirect_index;

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
    integer reset_idx;
    logic pfb_coeff_auto_increment;
    logic [13:0] pfb_coeff_next_index;
    logic [31:0] read_data_next;
    wire         aw_accept;
    wire         w_accept;
    wire         ar_accept;
    wire         have_write_addr;
    wire         have_write_data;
    wire         tx_endpoint_indirect_valid;
    wire         tx_spec_route_indirect_valid;
    wire         tx_time_route_indirect_valid;
    wire [17:0] ar_accept_addr;
    localparam [3:0] READ_BANK_CORE          = 4'd0;
    localparam [3:0] READ_BANK_STREAM        = 4'd1;
    localparam [3:0] READ_BANK_DAC           = 4'd2;
    localparam [3:0] READ_BANK_PREVIEW_CTRL  = 4'd3;
    localparam [3:0] READ_BANK_FENGINE       = 4'd4;
    localparam [3:0] READ_BANK_TX            = 4'd5;
    localparam [3:0] READ_BANK_TX_INDIRECT   = 4'd6;
    localparam [3:0] READ_BANK_SCIENCE       = 4'd7;
    localparam [3:0] READ_BANK_PREVIEW_BUF   = 4'd8;
    localparam [3:0] READ_BANK_PREVIEW_EVENT = 4'd9;
    localparam [3:0] READ_BANK_LANE_MON      = 4'd10;
    localparam [3:0] READ_BANK_RAW_WITNESS   = 4'd11;
    localparam [3:0] READ_BANK_STAGE31_SYNC   = 4'd12;
    localparam [3:0] READ_BANK_ZERO          = 4'd15;
    logic [3:0]            read_bank_latched;

    assign aw_accept       = s_axi_awready && s_axi_awvalid && !s_axi_bvalid && !write_exec_valid;
    assign w_accept        = s_axi_wready && s_axi_wvalid && !s_axi_bvalid && !write_exec_valid;
    assign ar_accept       = s_axi_arready && s_axi_arvalid && !s_axi_rvalid && !read_pending;
    assign ar_accept_addr  = local_addr(s_axi_araddr);
    assign have_write_addr = awaddr_valid || aw_accept;
    assign have_write_data = wdata_valid || w_accept;
    assign tx_endpoint_indirect_valid = ({25'd0, tx_endpoint_indirect_index} < N_TX_ENDPOINTS);
    assign tx_spec_route_indirect_valid = ({26'd0, tx_spec_route_indirect_index} < N_SPEC_ROUTES);
    assign tx_time_route_indirect_valid = ({29'd0, tx_time_route_indirect_index} < N_TIME_ROUTES);
    assign science_live_requested = science_control[1] && !science_control[0];
    assign science_bandwidth_mode_cfg = science_bandwidth_mode;
    assign science_output_mode_cfg = science_output_mode;
    assign science_time_enabled =
        (science_output_mode == SCIENCE_MODE_TIME_ONLY) ||
        (science_output_mode == SCIENCE_MODE_TIME_SPEC) ||
        (science_output_mode == SCIENCE_MODE_TIME_MONITOR_SPEC);
    assign science_spec_enabled =
        (science_output_mode == SCIENCE_MODE_SPEC_ONLY) ||
        (science_output_mode == SCIENCE_MODE_TIME_SPEC);
    assign science_time_spec_rejected =
        (science_bandwidth_mode == 2'd2) &&
        (science_output_mode == SCIENCE_MODE_TIME_SPEC);
    assign science_cmac_live_ready =
        tx_link_status_flags[0] &&
        tx_link_status_flags[2] &&
        tx_link_status_flags[3] &&
        tx_link_status_flags[4] &&
        !tx_link_status_flags[5] &&
        !tx_link_status_flags[6] &&
        !tx_link_status_flags[1];
    assign fengine_science_valid = pfb_status[5];
    assign fengine_overflow_seen = (pfb_overflow_count != 32'd0) || pfb_status[3];
    assign science_rate_drop_seen = (science_dropped_beat_count != 32'd0);
    assign science_block_reason = {
        20'd0,
        science_rate_drop_seen,
        1'b0,
        science_spec_enabled && fengine_overflow_seen,
        science_spec_enabled && !fengine_science_valid,
        science_spec_enabled && fengine_science_valid,
        science_control[0],
        science_live_requested && !science_cmac_live_ready,
        1'b0,
        1'b0,
        1'b0,
        1'b0,
        science_time_spec_rejected
    };
    assign science_status_word = {
        16'd0,
        science_output_mode,
        1'b0,
        science_aa100_primed,
        science_aa100_active,
        science_bandwidth_mode,
        2'd0,
        science_cmac_live_ready,
        1'b1,
        fengine_science_valid,
        science_time_spec_rejected,
        science_spec_enabled,
        science_time_enabled
    };

    function automatic [17:0] local_addr(input [AXI_ADDR_W-1:0] addr);
        begin
            local_addr = addr[17:0];
        end
    endfunction

    function automatic logic stage27h_archived_ctrl_addr(input logic [17:0] addr);
        begin
            stage27h_archived_ctrl_addr =
                ((addr >= 18'h00400) && (addr < 18'h00440)) ||
                ((addr >= 18'h00790) && (addr < 18'h00800)) ||
                ((addr >= 18'h00800) && (addr < 18'h00900)) ||
                (((addr >= 18'h0095c) && (addr < 18'h02800)) &&
                 !(PRODUCTION_27J_PFB && (addr >= 18'h00960) && (addr < 18'h00980))) ||
                (addr == 18'h00378) || (addr == 18'h0037c) ||
                ((addr >= 18'h00380) && (addr < 18'h00400)) ||
                ((addr >= 18'h0b030) && (addr < 18'h0b0c0)) ||
                ((addr >= 18'h0b600) && (addr < 18'h0b628)) ||
                ((addr >= 18'h0b700) && (addr < 18'h0b704)) ||
                ((addr >= 18'h0c000) && (addr < 18'h0d000)) ||
                (!RAW_WITNESS_DIAGNOSTIC && ((addr >= 18'h0e200) && (addr < 18'h0e228))) ||
                (!RAW_WITNESS_DIAGNOSTIC && ((addr >= 18'h0e800) && (addr < 18'h0f800))) ||
                ((addr >= 18'h10000) && (addr < 18'h12100)) ||
                ((addr >= 18'h13000) && (addr < 18'h14900));
        end
    endfunction

    function automatic [3:0] stage27h_read_bank(input logic [17:0] addr);
        begin
            if (((addr >= 18'h00000) && (addr < 18'h00300)) ||
                ((addr >= 18'h0340) && (addr < 18'h0364))) begin
                stage27h_read_bank = READ_BANK_CORE;
            end else if ((addr >= 18'h00300) && (addr < 18'h00380)) begin
                stage27h_read_bank = READ_BANK_STREAM;
            end else if (((addr >= 18'h00440) && (addr < 18'h0044c)) ||
                         ((addr >= 18'h00600) && (addr < 18'h006f4))) begin
                stage27h_read_bank = READ_BANK_DAC;
            end else if ((addr >= 18'h00500) && (addr < 18'h00540)) begin
                stage27h_read_bank = READ_BANK_LANE_MON;
            end else if ((addr >= 18'h00700) && (addr < 18'h00790)) begin
                stage27h_read_bank = READ_BANK_PREVIEW_CTRL;
            end else if ((addr >= 18'h02800) && (addr < 18'h0a800)) begin
                stage27h_read_bank = READ_BANK_PREVIEW_BUF;
            end else if ((addr >= 18'h0a800) && (addr < 18'h0ac00)) begin
                stage27h_read_bank = READ_BANK_PREVIEW_EVENT;
            end else if ((addr >= 18'h0ac00) && (addr < 18'h0ad00)) begin
                stage27h_read_bank = READ_BANK_STAGE31_SYNC;
            end else if ((addr >= 18'h00900) &&
                         (addr < (PRODUCTION_27J_PFB ? 18'h00980 : 18'h0095c))) begin
                stage27h_read_bank = READ_BANK_FENGINE;
            end else if (((addr >= 18'h0b000) && (addr < 18'h0b030)) ||
                         (addr == 18'h0b700) || (addr == 18'h0b704)) begin
                stage27h_read_bank = READ_BANK_TX;
            end else if ((addr >= 18'h0b100) && (addr < 18'h0b160)) begin
                stage27h_read_bank = READ_BANK_TX_INDIRECT;
            end else if (((addr >= 18'h0d000) && (addr < 18'h0d05c)) ||
                         (addr == 18'h0d060)) begin
                stage27h_read_bank = READ_BANK_SCIENCE;
            end else if (RAW_WITNESS_DIAGNOSTIC &&
                         (((addr >= 18'h0e200) && (addr < 18'h0e228)) ||
                          ((addr >= 18'h0e800) && (addr < 18'h0f800)))) begin
                stage27h_read_bank = READ_BANK_RAW_WITNESS;
            end else begin
                stage27h_read_bank = READ_BANK_ZERO;
            end
        end
    endfunction

    function automatic [31:0] endpoint_ip_word(input logic [6:0] idx);
        integer fn_idx;
        begin
            endpoint_ip_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TX_ENDPOINTS; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[6:0]) begin
                    endpoint_ip_word = tx_endpoint_ip_vec[fn_idx*32 +: 32];
                end
            end
        end
    endfunction

    function automatic [31:0] endpoint_mac_lo_word(input logic [6:0] idx);
        integer fn_idx;
        begin
            endpoint_mac_lo_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TX_ENDPOINTS; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[6:0]) begin
                    endpoint_mac_lo_word = tx_endpoint_mac_vec[fn_idx*48 +: 32];
                end
            end
        end
    endfunction

    function automatic [31:0] endpoint_mac_hi_word(input logic [6:0] idx);
        integer fn_idx;
        begin
            endpoint_mac_hi_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TX_ENDPOINTS; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[6:0]) begin
                    endpoint_mac_hi_word = {16'd0, tx_endpoint_mac_vec[fn_idx*48 + 32 +: 16]};
                end
            end
        end
    endfunction

    function automatic [31:0] endpoint_dst_port_word(input logic [6:0] idx);
        integer fn_idx;
        begin
            endpoint_dst_port_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TX_ENDPOINTS; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[6:0]) begin
                    endpoint_dst_port_word = {16'd0, tx_endpoint_dst_port_vec[fn_idx*16 +: 16]};
                end
            end
        end
    endfunction

    function automatic [31:0] endpoint_src_port_word(input logic [6:0] idx);
        integer fn_idx;
        begin
            endpoint_src_port_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TX_ENDPOINTS; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[6:0]) begin
                    endpoint_src_port_word = {16'd0, tx_endpoint_src_port_vec[fn_idx*16 +: 16]};
                end
            end
        end
    endfunction

    function automatic [31:0] spec_route_ctrl_word(input logic [5:0] idx);
        integer fn_idx;
        begin
            spec_route_ctrl_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_SPEC_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[5:0]) begin
                    spec_route_ctrl_word = {16'd0, tx_spec_route_endpoint_vec[fn_idx*8 +: 8], 7'd0, tx_spec_route_enable[fn_idx]};
                end
            end
        end
    endfunction

    function automatic [31:0] spec_route_chan0_word(input logic [5:0] idx);
        integer fn_idx;
        begin
            spec_route_chan0_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_SPEC_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[5:0]) begin
                    spec_route_chan0_word = tx_spec_route_chan0_vec[fn_idx*32 +: 32];
                end
            end
        end
    endfunction

    function automatic [31:0] spec_route_chan_count_word(input logic [5:0] idx);
        integer fn_idx;
        begin
            spec_route_chan_count_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_SPEC_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[5:0]) begin
                    spec_route_chan_count_word = {16'd0, tx_spec_route_chan_count_vec[fn_idx*16 +: 16]};
                end
            end
        end
    endfunction

    function automatic [31:0] spec_route_hit_word(input logic [5:0] idx);
        integer fn_idx;
        begin
            spec_route_hit_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_SPEC_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[5:0]) begin
                    spec_route_hit_word = tx_spec_route_hit_counts[fn_idx*32 +: 32];
                end
            end
        end
    endfunction

    function automatic [31:0] time_route_ctrl_word(input logic [2:0] idx);
        integer fn_idx;
        begin
            time_route_ctrl_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TIME_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[2:0]) begin
                    time_route_ctrl_word = {16'd0, tx_time_route_endpoint_vec[fn_idx*8 +: 8], 7'd0, tx_time_route_enable[fn_idx]};
                end
            end
        end
    endfunction

    function automatic [31:0] time_route_mask_word(input logic [2:0] idx);
        integer fn_idx;
        begin
            time_route_mask_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TIME_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[2:0]) begin
                    time_route_mask_word = {16'd0, tx_time_route_input_mask_vec[fn_idx*16 +: 16]};
                end
            end
        end
    endfunction

    function automatic [31:0] time_route_hit_word(input logic [2:0] idx);
        integer fn_idx;
        begin
            time_route_hit_word = 32'd0;
            for (fn_idx = 0; fn_idx < N_TIME_ROUTES; fn_idx = fn_idx + 1) begin
                if (idx == fn_idx[2:0]) begin
                    time_route_hit_word = tx_time_route_hit_counts[fn_idx*32 +: 32];
                end
            end
        end
    endfunction

    function automatic [31:0] science_sample_rate_hz(input logic [1:0] bw_mode);
        begin
            case (bw_mode)
                2'd0: science_sample_rate_hz = 32'd30_720_000;
                2'd1: science_sample_rate_hz = 32'd122_880_000;
                2'd2: science_sample_rate_hz = 32'd245_760_000;
                default: science_sample_rate_hz = 32'd30_720_000;
            endcase
        end
    endfunction

    function automatic [31:0] science_decim_factor(input logic [1:0] bw_mode);
        begin
            case (bw_mode)
                2'd0: science_decim_factor = 32'd8;
                2'd1: science_decim_factor = 32'd2;
                2'd2: science_decim_factor = 32'd1;
                default: science_decim_factor = 32'd8;
            endcase
        end
    endfunction

    function automatic [31:0] science_single_stream_mbps(input logic [1:0] bw_mode);
        begin
            case (bw_mode)
                2'd0: science_single_stream_mbps = 32'd7_864;
                2'd1: science_single_stream_mbps = 32'd31_457;
                2'd2: science_single_stream_mbps = 32'd62_915;
                default: science_single_stream_mbps = 32'd7_864;
            endcase
        end
    endfunction

    function automatic [31:0] science_monitor_spec_mbps(input logic [1:0] bw_mode);
        begin
            case (bw_mode)
                2'd0: science_monitor_spec_mbps = 32'd123;
                2'd1: science_monitor_spec_mbps = 32'd491;
                2'd2: science_monitor_spec_mbps = 32'd983;
                default: science_monitor_spec_mbps = 32'd123;
            endcase
        end
    endfunction

    function automatic [31:0] science_payload_rate_mbps(
        input logic [1:0] bw_mode,
        input logic [2:0] out_mode
    );
        begin
            case (out_mode)
                SCIENCE_MODE_TIME_ONLY,
                SCIENCE_MODE_SPEC_ONLY: science_payload_rate_mbps = science_single_stream_mbps(bw_mode);
                SCIENCE_MODE_TIME_SPEC: science_payload_rate_mbps = science_single_stream_mbps(bw_mode) << 1;
                SCIENCE_MODE_TIME_MONITOR_SPEC: science_payload_rate_mbps =
                    science_single_stream_mbps(bw_mode) + science_monitor_spec_mbps(bw_mode);
                default: science_payload_rate_mbps = 32'd0;
            endcase
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
            read_bank_latched  <= READ_BANK_ZERO;
            read_pending       <= 1'b0;
            read_wait_cycles   <= 2'd0;
            read_data_stage    <= 32'd0;
            debug_time_rd_addr <= 10'd0;
            debug_fft_rd_addr <= 10'd0;
            preview_rd_input <= 3'd0;
            preview_rd_addr <= 10'd0;
            preview_event_rd_addr <= 8'd0;
            tx_header_capture_rd_word <= 5'd0;
            tx_frame_capture_rd_word <= 5'd0;
            tx_payload_witness_rd_word <= 12'd0;
            dac_tx_witness_rd_word <= 10'd0;
            rfdc_axis_raw_witness_rd_word <= 10'd0;
            write_exec_valid   <= 1'b0;
            write_exec_addr    <= 18'd0;
            write_exec_data    <= 32'd0;
            write_exec_strb    <= 4'd0;
            board_id           <= 16'd0;
            mode               <= 2'd0;
            arm_latched        <= 1'b0;
            soft_epoch_pulse   <= 1'b0;
            stop_pulse         <= 1'b0;
            soft_reset_pulse   <= 1'b0;
            stage31_prepare_pulse <= 1'b0;
            stage31_arm_pulse <= 1'b0;
            stage31_abort_pulse <= 1'b0;
            stage31_clear_status_pulse <= 1'b0;
            stage31_generation <= 64'd0;
            stage31_target_pps_count <= 64'd0;
            stage31_epoch_tai_seconds <= 64'd0;
            stage31_first_sample0 <= 64'd32788;
            stage31_observation_tag <= 64'd0;
            stage31_signal_chain_tag <= 32'd0;
            stage31_schedule_tag <= 32'd0;
            stage31_mts_result_id <= 32'd0;
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
            rfdc_axis_raw_witness_arm_pulse <= 1'b0;
            rfdc_axis_raw_witness_clear_pulse <= 1'b0;
            rfdc_axis_raw_witness_channel_select_ctrl <= 3'd0;
            rfdc_axis_raw_witness_capture_beats <= 9'd256;
            tx_clear_pulse     <= 1'b0;
            pfb_clear_pulse    <= 1'b0;
            pfb_coeff_load_start_pulse <= 1'b0;
            pfb_coeff_commit_pulse <= 1'b0;
            pfb_coeff_abort_pulse <= 1'b0;
            pfb_coeff_write_pulse <= 1'b0;
            sync_mode          <= SYNC_EXTERNAL_PPS;
            clock_ref          <= CLOCK_REF_EXTERNAL;
            sample_rate_hz     <= 32'd100_000_000;
            quant_mode         <= 16'd0;
            scale_mode         <= 16'd0;
            scale_id           <= 32'd0;
            time_payload_nsamp <= 16'd256;
            spec_time_count    <= 16'd1;
            spec_chan_count    <= 16'd256;
            pfb_enable         <= 1'b1;
            pfb_taps           <= PRODUCTION_27J_PFB ? 16'd4 : 16'd0;
            pfb_fft_shift      <= PRODUCTION_27H ? FFT_ONLY_DEFAULT_SHIFT : 16'd0;
            pfb_chan0          <= 32'd0;
            pfb_chan_count     <= 16'd256;
            pfb_time_count     <= 16'd1;
            pfb_coeff_requested_taps <= 4'd4;
            pfb_coeff_index    <= 14'd0;
            pfb_coeff_next_index <= 14'd0;
            pfb_coeff_data     <= 18'sd0;
            pfb_coeff_id       <= 32'h27a4_0001;
            pfb_coeff_auto_increment <= 1'b0;
            science_control    <= 32'h0000_0001;
            science_bandwidth_mode <= 2'd1;
            science_output_mode <= SCIENCE_MODE_OFF;
            time_live_interval_beats <= 32'd7680;
            time_ddr_ring_enable <= 1'b0;
            time_ddr_ring_clear_pulse <= 1'b0;
            time_ddr_ring_base_addr <= 64'h0000_0008_0000_0000;
            time_ddr_ring_slots <= 16'd64;
            time_multiflow_enable <= 1'b0;
            time_multiflow_base_endpoint <= 3'd0;
            time_multiflow_count <= 4'd1;
            tx_endpoint_indirect_index <= 7'd0;
            tx_spec_route_indirect_index <= 6'd0;
            tx_time_route_indirect_index <= 3'd0;
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
            tx_endpoint_enable <= {N_TX_ENDPOINTS{1'b1}};
            tx_endpoint_ip_vec <= {N_TX_ENDPOINTS{32'h0a00_0110}};
            tx_endpoint_mac_vec <= {N_TX_ENDPOINTS{48'h08c0_ebd5_95b2}};
            tx_endpoint_src_port_vec <= {N_TX_ENDPOINTS{16'd4000}};
            tx_endpoint_dst_port_vec <= {N_TX_ENDPOINTS{16'd4300}};
            for (reset_idx = 0; reset_idx < N_TX_ENDPOINTS; reset_idx = reset_idx + 1) begin
                tx_endpoint_enable[reset_idx] <= 1'b1;
                tx_endpoint_ip_vec[reset_idx*32 +: 32] <= 32'h0a00_0110;
                tx_endpoint_mac_vec[reset_idx*48 +: 48] <= 48'h08c0_ebd5_95b2;
                tx_endpoint_src_port_vec[reset_idx*16 +: 16] <= 16'd4000 + reset_idx;
                tx_endpoint_dst_port_vec[reset_idx*16 +: 16] <= 16'd4300 + reset_idx;
            end
            tx_spec_route_enable <= {N_SPEC_ROUTES{1'b0}};
            tx_spec_route_chan0_vec <= {N_SPEC_ROUTES{32'd0}};
            tx_spec_route_chan_count_vec <= {N_SPEC_ROUTES{16'd0}};
            tx_spec_route_endpoint_vec <= {N_SPEC_ROUTES{8'd8}};
            for (reset_idx = 0; reset_idx < N_SPEC_ROUTES; reset_idx = reset_idx + 1) begin
                tx_spec_route_enable[reset_idx] <= (reset_idx < 16);
                tx_spec_route_chan0_vec[reset_idx*32 +: 32] <= (reset_idx < 16) ? (reset_idx * 32'd256) : 32'd0;
                tx_spec_route_chan_count_vec[reset_idx*16 +: 16] <= (reset_idx < 16) ? 16'd256 : 16'd0;
                tx_spec_route_endpoint_vec[reset_idx*8 +: 8] <= 8'd8 + reset_idx[7:0];
            end
            tx_time_route_enable <= 8'h01;
            tx_time_route_input_mask_vec <= {
                16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'd0, 16'h00ff
            };
            tx_time_route_endpoint_vec <= {N_TIME_ROUTES{8'd0}};
            tx_time_route_endpoint_vec[0 +: 8] <= 8'd0;
            qsfp_test_interval_cycles <= 32'd322_266;
            rfdc_active_mask    <= 16'hffff;
            diag_adc_force_zero <= 1'b0;
            diag_adc_force_hold <= 1'b0;
            diag_adc_channel_mask <= 8'hff;
            diag_dac_gate <= 1'b0;
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
            stage31_prepare_pulse <= 1'b0;
            stage31_arm_pulse <= 1'b0;
            stage31_abort_pulse <= 1'b0;
            stage31_clear_status_pulse <= 1'b0;
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
            rfdc_axis_raw_witness_arm_pulse <= 1'b0;
            rfdc_axis_raw_witness_clear_pulse <= 1'b0;
            tx_clear_pulse <= 1'b0;
            time_ddr_ring_clear_pulse <= 1'b0;
            pfb_clear_pulse <= 1'b0;
            pfb_coeff_load_start_pulse <= 1'b0;
            pfb_coeff_commit_pulse <= 1'b0;
            pfb_coeff_abort_pulse <= 1'b0;
            pfb_coeff_write_pulse <= 1'b0;
            s_axi_awready    <= !awaddr_valid && !s_axi_bvalid && !write_exec_valid;
            s_axi_wready     <= !wdata_valid && !s_axi_bvalid && !write_exec_valid;
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

            if (have_write_addr && have_write_data && !s_axi_bvalid && !write_exec_valid) begin
                write_exec_valid <= 1'b1;
                write_exec_addr  <= local_addr(aw_accept ? s_axi_awaddr : awaddr_latched);
                write_exec_data  <= w_accept ? s_axi_wdata : wdata_latched;
                write_exec_strb  <= w_accept ? s_axi_wstrb : wstrb_latched;
                awaddr_valid     <= 1'b0;
                wdata_valid      <= 1'b0;
            end

            if (write_exec_valid && !s_axi_bvalid) begin
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(write_exec_addr))) begin
                    case (write_exec_addr)
                    16'h0004: board_id <= write_exec_data[15:0];
                    16'h0008: mode <= write_exec_data[1:0];
                    16'h000c: begin
                        if (write_exec_data[0]) begin
                            arm_latched <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            soft_epoch_pulse <= 1'b1;
                        end
                        if (write_exec_data[2]) begin
                            arm_latched <= 1'b0;
                            stop_pulse  <= 1'b1;
                        end
                        if (write_exec_data[3]) begin
                            arm_latched      <= 1'b0;
                            soft_reset_pulse <= 1'b1;
                        end
                    end
                    16'h0020: begin
                        if (!arm_latched && !armed && !streaming) begin
                            if (write_exec_strb[0]) begin
                                case (write_exec_data[1:0])
                                    SYNC_EXTERNAL_PPS,
                                    SYNC_SOFTWARE_EPOCH,
                                    SYNC_FREE_RUN: sync_mode <= write_exec_data[1:0];
                                    default: sync_mode <= SYNC_EXTERNAL_PPS;
                                endcase
                            end
                            if (write_exec_strb[2]) begin
                                case (write_exec_data[17:16])
                                    CLOCK_REF_EXTERNAL,
                                    CLOCK_REF_TCXO,
                                    CLOCK_REF_GPS: clock_ref <= write_exec_data[17:16];
                                    default: clock_ref <= CLOCK_REF_EXTERNAL;
                                endcase
                            end
                        end
                    end
                    16'h0108: apply_wstrb(sample_rate_hz, write_exec_data, write_exec_strb);
                    16'h010c: quant_mode <= write_exec_data[15:0];
                    16'h0110: scale_mode <= write_exec_data[15:0];
                    16'h0114: time_payload_nsamp <= write_exec_data[15:0];
                    16'h0118: begin
                        if (PRODUCTION_27H) begin
                            spec_time_count <= 16'd1;
                            pfb_time_count  <= 16'd1;
                        end else if (write_exec_data[15:0] != 16'd0) begin
                            spec_time_count <= write_exec_data[15:0];
                            pfb_time_count  <= write_exec_data[15:0];
                        end
                    end
                    16'h011c: begin
                        if (PRODUCTION_27H) begin
                            spec_chan_count <= 16'd256;
                            pfb_chan_count  <= 16'd256;
                        end else if (write_exec_data[15:0] != 16'd0) begin
                            spec_chan_count <= write_exec_data[15:0];
                            pfb_chan_count  <= write_exec_data[15:0];
                        end
                    end
                    16'h0200: apply_wstrb(src_ip, write_exec_data, write_exec_strb);
                    16'h0204: begin
                        apply_wstrb(dgx_a_ip, write_exec_data, write_exec_strb);
                        tx_endpoint_ip_vec[0*32 +: 32] <= write_exec_data;
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0208: begin
                        apply_wstrb(dgx_b_ip, write_exec_data, write_exec_strb);
                        tx_endpoint_ip_vec[1*32 +: 32] <= write_exec_data;
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h020c: begin
                        apply_wstrb(time_dst_ip, write_exec_data, write_exec_strb);
                        tx_endpoint_ip_vec[2*32 +: 32] <= write_exec_data;
                        tx_endpoint_enable[2] <= 1'b1;
                    end
                    16'h0210: src_mac[31:0] <= write_exec_data;
                    16'h0214: src_mac[47:32] <= write_exec_data[15:0];
                    16'h0218: begin
                        dgx_a_mac[31:0] <= write_exec_data;
                        tx_endpoint_mac_vec[0*48 +: 32] <= write_exec_data;
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h021c: begin
                        dgx_a_mac[47:32] <= write_exec_data[15:0];
                        tx_endpoint_mac_vec[0*48 + 32 +: 16] <= write_exec_data[15:0];
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0220: begin
                        dgx_b_mac[31:0] <= write_exec_data;
                        tx_endpoint_mac_vec[1*48 +: 32] <= write_exec_data;
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0224: begin
                        dgx_b_mac[47:32] <= write_exec_data[15:0];
                        tx_endpoint_mac_vec[1*48 + 32 +: 16] <= write_exec_data[15:0];
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0228: src_udp_port <= write_exec_data[15:0];
                    16'h022c: begin
                        dgx_a_udp_port <= write_exec_data[15:0];
                        tx_endpoint_dst_port_vec[0*16 +: 16] <= write_exec_data[15:0];
                        tx_endpoint_enable[0] <= 1'b1;
                    end
                    16'h0230: begin
                        dgx_b_udp_port <= write_exec_data[15:0];
                        tx_endpoint_dst_port_vec[1*16 +: 16] <= write_exec_data[15:0];
                        tx_endpoint_enable[1] <= 1'b1;
                    end
                    16'h0234: begin
                        time_udp_port <= write_exec_data[15:0];
                        tx_endpoint_dst_port_vec[2*16 +: 16] <= write_exec_data[15:0];
                        tx_endpoint_enable[2] <= 1'b1;
                    end
                    16'h0238: apply_wstrb(chan_split, write_exec_data, write_exec_strb);
                    16'h0240: apply_wstrb(scale_id, write_exec_data, write_exec_strb);
                    16'h0244: unix_seconds[31:0] <= write_exec_data;
                    16'h0248: unix_seconds[63:32] <= write_exec_data;
                    16'h0350: begin
                        if (!arm_latched && !armed && !streaming &&
                            write_exec_data[15:0] != 16'd0) begin
                            rfdc_active_mask <= write_exec_data[15:0];
                        end
                    end
                    16'h0378: begin
                        if (write_exec_data[0]) begin
                            tx_header_capture_arm_pulse <= 1'b1;
                        end
                    end
                    16'h0790: begin
                        if (write_exec_data[0]) begin
                            tx_payload_witness_arm_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            tx_payload_witness_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0798: begin
                        case (write_exec_data[1:0])
                            2'd0,
                            2'd1,
                            2'd2: tx_payload_witness_stream_filter <= write_exec_data[1:0];
                            default: tx_payload_witness_stream_filter <= 2'd0;
                        endcase
                    end
                    16'h079c: begin
                        if (write_exec_data[10:0] == 11'd0) begin
                            tx_payload_witness_capture_words <= 11'd1040;
                        end else if (write_exec_data[10:0] <= 11'd1056) begin
                            tx_payload_witness_capture_words <= write_exec_data[10:0];
                        end else begin
                            tx_payload_witness_capture_words <= 11'd1040;
                        end
                    end
                    16'hb600: begin
                        if (write_exec_data[0]) begin
                            dac_tx_witness_arm_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            dac_tx_witness_clear_pulse <= 1'b1;
                        end
                    end
                    16'hb608: begin
                        if (write_exec_data[8:0] == 9'd0) begin
                            dac_tx_witness_capture_words <= 9'd256;
                        end else if (write_exec_data[8:0] <= 9'd256) begin
                            dac_tx_witness_capture_words <= write_exec_data[8:0];
                        end else begin
                            dac_tx_witness_capture_words <= 9'd256;
                        end
                    end
                    16'he200: begin
                        if (write_exec_data[0]) begin
                            rfdc_axis_raw_witness_arm_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            rfdc_axis_raw_witness_clear_pulse <= 1'b1;
                        end
                    end
                    16'he208: begin
                        rfdc_axis_raw_witness_channel_select_ctrl <= write_exec_data[2:0];
                    end
                    16'he20c: begin
                        if (write_exec_data[8:0] == 9'd0) begin
                            rfdc_axis_raw_witness_capture_beats <= 9'd256;
                        end else if (write_exec_data[8:0] <= 9'd256) begin
                            rfdc_axis_raw_witness_capture_beats <= write_exec_data[8:0];
                        end else begin
                            rfdc_axis_raw_witness_capture_beats <= 9'd256;
                        end
                    end
                    16'hb000: begin
                        tx_control[4:0] <= write_exec_data[4:0];
                        if (write_exec_data[5]) begin
                            tx_clear_pulse <= 1'b1;
                        end
                    end
                    16'hb030: begin
                        if (write_exec_data[0]) begin
                            tx_frame_capture_arm_pulse <= 1'b1;
                        end
                    end
                    16'hb100: tx_endpoint_indirect_index <= write_exec_data[6:0];
                    16'hb104: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_enable[write_idx] <= write_exec_data[0];
                            end
                        end
                    end
                    16'hb108: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_ip_vec[write_idx*32 +: 32] <= write_exec_data;
                            end
                        end
                    end
                    16'hb10c: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_mac_vec[write_idx*48 +: 32] <= write_exec_data;
                            end
                        end
                    end
                    16'hb110: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_mac_vec[write_idx*48 + 32 +: 16] <= write_exec_data[15:0];
                            end
                        end
                    end
                    16'hb114: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_dst_port_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                            end
                        end
                    end
                    16'hb118: begin
                        for (write_idx = 0; write_idx < N_TX_ENDPOINTS; write_idx = write_idx + 1) begin
                            if (tx_endpoint_indirect_index == write_idx[6:0]) begin
                                tx_endpoint_src_port_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                            end
                        end
                    end
                    16'hb130: tx_spec_route_indirect_index <= write_exec_data[5:0];
                    16'hb134: begin
                        for (write_idx = 0; write_idx < N_SPEC_ROUTES; write_idx = write_idx + 1) begin
                            if (tx_spec_route_indirect_index == write_idx[5:0]) begin
                                tx_spec_route_enable[write_idx] <= write_exec_data[0];
                                tx_spec_route_endpoint_vec[write_idx*8 +: 8] <= write_exec_data[15:8];
                            end
                        end
                    end
                    16'hb138: begin
                        for (write_idx = 0; write_idx < N_SPEC_ROUTES; write_idx = write_idx + 1) begin
                            if (tx_spec_route_indirect_index == write_idx[5:0]) begin
                                tx_spec_route_chan0_vec[write_idx*32 +: 32] <= write_exec_data;
                            end
                        end
                    end
                    16'hb13c: begin
                        for (write_idx = 0; write_idx < N_SPEC_ROUTES; write_idx = write_idx + 1) begin
                            if (tx_spec_route_indirect_index == write_idx[5:0]) begin
                                tx_spec_route_chan_count_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                            end
                        end
                    end
                    16'hb150: tx_time_route_indirect_index <= write_exec_data[2:0];
                    16'hb154: begin
                        for (write_idx = 0; write_idx < N_TIME_ROUTES; write_idx = write_idx + 1) begin
                            if (tx_time_route_indirect_index == write_idx[2:0]) begin
                                tx_time_route_enable[write_idx] <= write_exec_data[0];
                                tx_time_route_endpoint_vec[write_idx*8 +: 8] <= write_exec_data[15:8];
                            end
                        end
                    end
                    16'hb158: begin
                        for (write_idx = 0; write_idx < N_TIME_ROUTES; write_idx = write_idx + 1) begin
                            if (tx_time_route_indirect_index == write_idx[2:0]) begin
                                tx_time_route_input_mask_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                            end
                        end
                    end
                    16'h0400: begin
                        if (write_exec_data[0]) begin
                            debug_capture_start_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            debug_capture_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0440: begin
                        if (write_exec_strb[0]) begin
                            dac_tone_enable <= write_exec_data[0];
                            dac_enable_mask <= write_exec_data[0] ? 8'hff : 8'h00;
                        end
                    end
                    16'h0444: begin
                        if (write_exec_data[15:0] <= 16'd8192) begin
                            dac_tone_amplitude <= write_exec_data[15:0];
                            dac_tone_amplitude_vec <= {NINPUT{write_exec_data[15:0]}};
                        end
                    end
                    16'h0448: begin
                        apply_wstrb(dac_tone_phase_step, write_exec_data, write_exec_strb);
                        dac_tone_phase_step_vec <= {NINPUT{write_exec_data}};
                    end
                    16'h0600: begin
                        if (write_exec_strb[0]) begin
                            dac_enable_mask <= write_exec_data[7:0];
                            dac_tone_enable <= |write_exec_data[7:0];
                        end
                    end
                    16'h0604: begin
                        if (write_exec_data[15:0] <= 16'd8192) begin
                            dac_tone_amplitude <= write_exec_data[15:0];
                            dac_tone_amplitude_vec <= {NINPUT{write_exec_data[15:0]}};
                        end
                    end
                    16'h0608: begin
                        dac_tone_phase_step <= write_exec_data;
                        dac_tone_phase_step_vec <= {NINPUT{write_exec_data}};
                    end
                    16'h060c: begin
                        if (write_exec_data[0]) begin
                            dac_phase_epoch <= dac_phase_epoch + 32'd1;
                        end
                    end
                    16'h0620: dac_tone_phase_step_vec[0*32 +: 32] <= write_exec_data;
                    16'h0624: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[0*16 +: 16] <= write_exec_data[15:0];
                    16'h0628: dac_tone_phase0_vec[0*32 +: 32] <= write_exec_data;
                    16'h062c: dac_tone_phase_inject_vec[0*32 +: 32] <= write_exec_data;
                    16'h0630: dac_tone_mode_vec[0*2 +: 2] <= write_exec_data[1:0];
                    16'h0638: dac_tone_phase_step_vec[1*32 +: 32] <= write_exec_data;
                    16'h063c: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[1*16 +: 16] <= write_exec_data[15:0];
                    16'h0640: dac_tone_phase0_vec[1*32 +: 32] <= write_exec_data;
                    16'h0644: dac_tone_phase_inject_vec[1*32 +: 32] <= write_exec_data;
                    16'h0648: dac_tone_mode_vec[1*2 +: 2] <= write_exec_data[1:0];
                    16'h0650: dac_tone_phase_step_vec[2*32 +: 32] <= write_exec_data;
                    16'h0654: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[2*16 +: 16] <= write_exec_data[15:0];
                    16'h0658: dac_tone_phase0_vec[2*32 +: 32] <= write_exec_data;
                    16'h065c: dac_tone_phase_inject_vec[2*32 +: 32] <= write_exec_data;
                    16'h0660: dac_tone_mode_vec[2*2 +: 2] <= write_exec_data[1:0];
                    16'h0668: dac_tone_phase_step_vec[3*32 +: 32] <= write_exec_data;
                    16'h066c: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[3*16 +: 16] <= write_exec_data[15:0];
                    16'h0670: dac_tone_phase0_vec[3*32 +: 32] <= write_exec_data;
                    16'h0674: dac_tone_phase_inject_vec[3*32 +: 32] <= write_exec_data;
                    16'h0678: dac_tone_mode_vec[3*2 +: 2] <= write_exec_data[1:0];
                    16'h0680: dac_tone_phase_step_vec[4*32 +: 32] <= write_exec_data;
                    16'h0684: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[4*16 +: 16] <= write_exec_data[15:0];
                    16'h0688: dac_tone_phase0_vec[4*32 +: 32] <= write_exec_data;
                    16'h068c: dac_tone_phase_inject_vec[4*32 +: 32] <= write_exec_data;
                    16'h0690: dac_tone_mode_vec[4*2 +: 2] <= write_exec_data[1:0];
                    16'h0698: dac_tone_phase_step_vec[5*32 +: 32] <= write_exec_data;
                    16'h069c: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[5*16 +: 16] <= write_exec_data[15:0];
                    16'h06a0: dac_tone_phase0_vec[5*32 +: 32] <= write_exec_data;
                    16'h06a4: dac_tone_phase_inject_vec[5*32 +: 32] <= write_exec_data;
                    16'h06a8: dac_tone_mode_vec[5*2 +: 2] <= write_exec_data[1:0];
                    16'h06b0: dac_tone_phase_step_vec[6*32 +: 32] <= write_exec_data;
                    16'h06b4: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[6*16 +: 16] <= write_exec_data[15:0];
                    16'h06b8: dac_tone_phase0_vec[6*32 +: 32] <= write_exec_data;
                    16'h06bc: dac_tone_phase_inject_vec[6*32 +: 32] <= write_exec_data;
                    16'h06c0: dac_tone_mode_vec[6*2 +: 2] <= write_exec_data[1:0];
                    16'h06c8: dac_tone_phase_step_vec[7*32 +: 32] <= write_exec_data;
                    16'h06cc: if (write_exec_data[15:0] <= 16'd8192) dac_tone_amplitude_vec[7*16 +: 16] <= write_exec_data[15:0];
                    16'h06d0: dac_tone_phase0_vec[7*32 +: 32] <= write_exec_data;
                    16'h06d4: dac_tone_phase_inject_vec[7*32 +: 32] <= write_exec_data;
                    16'h06d8: dac_tone_mode_vec[7*2 +: 2] <= write_exec_data[1:0];
                    16'h0700: begin
                        if (write_exec_data[0]) begin
                            preview_capture_start_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            preview_capture_clear_pulse <= 1'b1;
                        end
                    end
                    16'h0708: begin
                        if (write_exec_data[NINPUT-1:0] != {NINPUT{1'b0}}) begin
                            preview_input_mask <= write_exec_data[NINPUT-1:0];
                        end
                    end
                    16'h0730: begin
                        if (write_exec_data[0]) begin
                            preview_audit_clear_pulse <= 1'b1;
                        end
                        preview_audit_event_enable <= write_exec_data[1];
                        preview_audit_freeze_on_event <= write_exec_data[2];
                        case (write_exec_data[9:8])
                            2'd0,
                            2'd1,
                            2'd2: preview_audit_source_select <= write_exec_data[9:8];
                            default: preview_audit_source_select <= 2'd0;
                        endcase
                    end
                    16'h0770: preview_audit_event_threshold <= write_exec_data[15:0];
                    16'h0900: begin
                        if (write_exec_strb[0]) begin
                            pfb_enable <= write_exec_data[0];
                            if (write_exec_data[1]) begin
                                pfb_clear_pulse <= 1'b1;
                            end
                        end
                    end
                    16'h090c: begin
                        if (PRODUCTION_27J_PFB) begin
                            pfb_taps <= 16'd4;
                        end else if (PRODUCTION_27H) begin
                            pfb_taps <= 16'd0;
                        end else begin
                            pfb_taps <= write_exec_data[15:0];
                        end
                    end
                    16'h0910: pfb_fft_shift <= PRODUCTION_27H ? {4'd0, write_exec_data[11:0]} : write_exec_data[15:0];
                    16'h0914: begin
                        if (PRODUCTION_27H) begin
                            pfb_chan0 <= 32'd0;
                        end else if (write_exec_data[31:0] < 32'd4096) begin
                            pfb_chan0 <= write_exec_data[31:0];
                        end
                    end
                    16'h0918: begin
                        if (PRODUCTION_27H) begin
                            pfb_chan_count  <= 16'd256;
                            spec_chan_count <= 16'd256;
                        end else if (write_exec_data[15:0] != 16'd0) begin
                            pfb_chan_count  <= write_exec_data[15:0];
                            spec_chan_count <= write_exec_data[15:0];
                        end
                    end
                    16'h091c: begin
                        if (PRODUCTION_27H) begin
                            pfb_time_count  <= 16'd1;
                            spec_time_count <= 16'd1;
                        end else if (write_exec_data[15:0] != 16'd0) begin
                            pfb_time_count  <= write_exec_data[15:0];
                            spec_time_count <= write_exec_data[15:0];
                        end
                    end
                    16'h0960: begin
                        if (PRODUCTION_27J_PFB) begin
                            pfb_coeff_requested_taps <= write_exec_data[7:4];
                            pfb_coeff_auto_increment <= write_exec_data[3];
                            if (write_exec_data[0]) begin
                                pfb_coeff_load_start_pulse <= 1'b1;
                            end
                            if (write_exec_data[1]) begin
                                pfb_coeff_commit_pulse <= 1'b1;
                            end
                            if (write_exec_data[2]) begin
                                pfb_coeff_abort_pulse <= 1'b1;
                            end
                        end
                    end
                    16'h0968: begin
                        if (PRODUCTION_27J_PFB) begin
                            pfb_coeff_index <= write_exec_data[13:0];
                            pfb_coeff_next_index <= write_exec_data[13:0];
                        end
                    end
                    16'h096c: begin
                        if (PRODUCTION_27J_PFB) begin
                            pfb_coeff_index <= pfb_coeff_next_index;
                            pfb_coeff_data <= write_exec_data[17:0];
                            pfb_coeff_write_pulse <= 1'b1;
                            if (pfb_coeff_auto_increment) begin
                                pfb_coeff_next_index <= pfb_coeff_next_index + 14'd1;
                            end
                        end
                    end
                    16'h0974: begin
                        if (PRODUCTION_27J_PFB) begin
                            pfb_coeff_id <= write_exec_data;
                        end
                    end
                    16'hd000: begin
                        apply_wstrb(science_control, write_exec_data, write_exec_strb);
                    end
                    16'hd008: begin
                        case (write_exec_data[1:0])
                            2'd0,
                            2'd1,
                            2'd2: science_bandwidth_mode <= write_exec_data[1:0];
                            default: science_bandwidth_mode <= 2'd1;
                        endcase
                    end
                    16'hd00c: begin
                        case (write_exec_data[2:0])
                            SCIENCE_MODE_OFF,
                            SCIENCE_MODE_TIME_ONLY,
                            SCIENCE_MODE_SPEC_ONLY,
                            SCIENCE_MODE_TIME_SPEC,
                            SCIENCE_MODE_TIME_MONITOR_SPEC: science_output_mode <= write_exec_data[2:0];
                            default: science_output_mode <= SCIENCE_MODE_OFF;
                        endcase
                    end
                    16'hd024: begin
                        if (write_exec_data[31:0] == 32'd0) begin
                            time_live_interval_beats <= 32'd0;
                        end else if (write_exec_data[31:0] < 32'd16) begin
                            time_live_interval_beats <= 32'd16;
                        end else begin
                            time_live_interval_beats <= write_exec_data[31:0];
                        end
                    end
                    16'hd028: begin
                        time_ddr_ring_enable <= write_exec_data[0];
                        if (write_exec_data[1]) begin
                            time_ddr_ring_clear_pulse <= 1'b1;
                        end
                    end
                    16'hd02c: time_ddr_ring_base_addr[31:0] <= write_exec_data;
                    16'hd030: time_ddr_ring_base_addr[63:32] <= write_exec_data;
                    16'hd034: begin
                        if (write_exec_data[15:0] != 16'd0) begin
                            time_ddr_ring_slots <= write_exec_data[15:0];
                        end
                    end
                    16'hd050: begin
                        time_multiflow_enable <= write_exec_data[0];
                        time_multiflow_base_endpoint <= write_exec_data[10:8];
                        if (write_exec_data[19:16] == 4'd0) begin
                            time_multiflow_count <= 4'd1;
                        end else if (write_exec_data[19:16] > 4'd8) begin
                            time_multiflow_count <= 4'd8;
                        end else begin
                            time_multiflow_count <= write_exec_data[19:16];
                        end
                    end
                    16'hd060: begin
                        if (write_exec_strb[0]) begin
                            diag_adc_force_zero <= write_exec_data[0];
                            diag_adc_force_hold <= write_exec_data[1];
                        end
                        if (write_exec_strb[1]) begin
                            diag_adc_channel_mask <= write_exec_data[15:8];
                        end
                        if (write_exec_strb[2]) begin
                            diag_dac_gate <= write_exec_data[16];
                        end
                    end
                    16'hac04: begin
                        if (write_exec_data[0]) begin
                            stage31_prepare_pulse <= 1'b1;
                        end
                        if (write_exec_data[1]) begin
                            stage31_arm_pulse <= 1'b1;
                        end
                        if (write_exec_data[2]) begin
                            stage31_abort_pulse <= 1'b1;
                        end
                        if (write_exec_data[3]) begin
                            stage31_clear_status_pulse <= 1'b1;
                        end
                    end
                    16'hac10: stage31_generation[31:0] <= write_exec_data;
                    16'hac14: stage31_generation[63:32] <= write_exec_data;
                    16'hac18: stage31_target_pps_count[31:0] <= write_exec_data;
                    16'hac1c: stage31_target_pps_count[63:32] <= write_exec_data;
                    16'hac20: stage31_epoch_tai_seconds[31:0] <= write_exec_data;
                    16'hac24: stage31_epoch_tai_seconds[63:32] <= write_exec_data;
                    16'hac28: stage31_first_sample0[31:0] <= write_exec_data;
                    16'hac2c: stage31_first_sample0[63:32] <= write_exec_data;
                    16'hac30: stage31_observation_tag[31:0] <= write_exec_data;
                    16'hac34: stage31_observation_tag[63:32] <= write_exec_data;
                    16'hac38: stage31_signal_chain_tag <= write_exec_data;
                    16'hac3c: stage31_schedule_tag <= write_exec_data;
                    16'hac40: stage31_mts_result_id <= write_exec_data;
                    16'hb700: begin
                        if (write_exec_data[31:0] >= 32'd1024) begin
                            qsfp_test_interval_cycles <= write_exec_data[31:0];
                        end
                    end
                    default: begin
                        if (!PRODUCTION_27H && (write_exec_addr >= 18'h13000) && (write_exec_addr < 18'h13900)) begin
                            write_idx = (write_exec_addr - 18'h13000) >> 5;
                            if (write_idx < N_TX_ENDPOINTS) begin
                                case ((write_exec_addr - 18'h13000) & 18'h0001f)
                                    16'h0000: tx_endpoint_enable[write_idx] <= write_exec_data[0];
                                    16'h0004: tx_endpoint_ip_vec[write_idx*32 +: 32] <= write_exec_data;
                                    16'h0008: tx_endpoint_mac_vec[write_idx*48 +: 32] <= write_exec_data;
                                    16'h000c: tx_endpoint_mac_vec[write_idx*48 + 32 +: 16] <= write_exec_data[15:0];
                                    16'h0010: tx_endpoint_dst_port_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                                    16'h0014: tx_endpoint_src_port_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                                    default: begin
                                    end
                                endcase
                            end
                        end else if (!PRODUCTION_27H && (write_exec_addr >= 18'h14000) && (write_exec_addr < 18'h14800)) begin
                            write_idx = (write_exec_addr - 18'h14000) >> 5;
                            if (write_idx < N_SPEC_ROUTES) begin
                                case ((write_exec_addr - 18'h14000) & 18'h0001f)
                                    16'h0000: begin
                                        tx_spec_route_enable[write_idx] <= write_exec_data[0];
                                        tx_spec_route_endpoint_vec[write_idx*8 +: 8] <= write_exec_data[15:8];
                                    end
                                    16'h0004: tx_spec_route_chan0_vec[write_idx*32 +: 32] <= write_exec_data;
                                    16'h0008: tx_spec_route_chan_count_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                                    default: begin
                                    end
                                endcase
                            end
                        end else if (!PRODUCTION_27H && (write_exec_addr >= 18'h14800) && (write_exec_addr < 18'h14900)) begin
                            write_idx = (write_exec_addr - 18'h14800) >> 5;
                            if (write_idx < N_TIME_ROUTES) begin
                                case ((write_exec_addr - 18'h14800) & 18'h0001f)
                                    16'h0000: begin
                                        tx_time_route_enable[write_idx] <= write_exec_data[0];
                                        tx_time_route_endpoint_vec[write_idx*8 +: 8] <= write_exec_data[15:8];
                                    end
                                    16'h0004: tx_time_route_input_mask_vec[write_idx*16 +: 16] <= write_exec_data[15:0];
                                    default: begin
                                    end
                                endcase
                            end
                        end
                    end
                    endcase
                end
                write_exec_valid <= 1'b0;
                s_axi_bvalid     <= 1'b1;
            end

            if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end

            if (ar_accept) begin
                araddr_latched <= s_axi_araddr;
                read_bank_latched <= stage27h_read_bank(ar_accept_addr);
                read_pending   <= 1'b1;
                read_wait_cycles <= 2'd2;
                debug_time_rd_addr <= 10'd0;
                debug_fft_rd_addr <= 10'd0;
                preview_rd_input <= 3'd0;
                preview_rd_addr <= 10'd0;
                preview_event_rd_addr <= 8'd0;
                tx_header_capture_rd_word <= 5'd0;
                tx_frame_capture_rd_word <= 5'd0;
                tx_payload_witness_rd_word <= 12'd0;
                dac_tx_witness_rd_word <= 10'd0;
                rfdc_axis_raw_witness_rd_word <= 10'd0;
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h00800) && (ar_accept_addr < 18'h01800)) begin
                    debug_time_rd_addr <= (ar_accept_addr - 18'h00800) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h01800) && (ar_accept_addr < 18'h02800)) begin
                    debug_fft_rd_addr <= (ar_accept_addr - 18'h01800) >> 2;
                end
                if ((ar_accept_addr >= 18'h02800) && (ar_accept_addr < 18'h0a800)) begin
                    preview_rd_input <= (ar_accept_addr - 18'h02800) >> 12;
                    preview_rd_addr <= ((ar_accept_addr - 18'h02800) & 18'h00fff) >> 2;
                end
                if ((ar_accept_addr >= 18'h0a800) && (ar_accept_addr < 18'h0ac00)) begin
                    preview_event_rd_addr <= (ar_accept_addr - 18'h0a800) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h00380) && (ar_accept_addr < 18'h00400)) begin
                    tx_header_capture_rd_word <= (ar_accept_addr - 18'h00380) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h0b040) && (ar_accept_addr < 18'h0b0c0)) begin
                    tx_frame_capture_rd_word <= (ar_accept_addr - 18'h0b040) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h10000) && (ar_accept_addr < 18'h12100)) begin
                    tx_payload_witness_rd_word <= (ar_accept_addr - 18'h10000) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h0c000) && (ar_accept_addr < 18'h0d000)) begin
                    dac_tx_witness_rd_word <= (ar_accept_addr - 18'h0c000) >> 2;
                end
                if (!(PRODUCTION_27H && stage27h_archived_ctrl_addr(ar_accept_addr)) &&
                    (ar_accept_addr >= 18'h0e800) && (ar_accept_addr < 18'h0f800)) begin
                    rfdc_axis_raw_witness_rd_word <= (ar_accept_addr - 18'h0e800) >> 2;
                end
            end

            if (read_pending && !s_axi_rvalid) begin
                if (read_wait_cycles == 2'd0) begin
                    s_axi_rvalid     <= 1'b1;
                    s_axi_rdata      <= read_data_stage;
                    read_pending     <= 1'b0;
                end else if (read_wait_cycles == 2'd1) begin
                    read_data_stage  <= read_data_next;
                    read_wait_cycles <= 2'd0;
                end else if (read_wait_cycles != 2'd0) begin
                    read_wait_cycles <= read_wait_cycles - 2'd1;
                end
            end

            if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    always_comb begin
        read_addr      = local_addr(araddr_latched);
        read_data_next = 32'd0;
        lane_idx       = 0;

        if (PRODUCTION_27H) begin
            case (read_bank_latched)
                READ_BANK_CORE: begin
                    case (read_addr)
                        16'h0000: read_data_next = CORE_VERSION;
                        16'h0004: read_data_next = {16'd0, board_id};
                        16'h0008: read_data_next = {30'd0, mode};
                        16'h000c: read_data_next = {28'd0, soft_reset_pulse, stop_pulse, soft_epoch_pulse, arm_latched};
                        16'h0010: read_data_next = {20'd0, fsm_state, 3'd0, waiting_for_epoch, active_sync_mode, streaming, armed};
                        16'h0014: read_data_next = {29'd0, (pps_count != 64'd0), ref_locked, pps_seen};
                        16'h0018: read_data_next = {31'd0, ref_locked};
                        16'h001c: read_data_next = error_flags;
                        16'h0020: read_data_next = {14'd0, clock_ref, 14'd0, sync_mode};
                        16'h0024: read_data_next = pps_count[31:0];
                        16'h0028: read_data_next = pps_count[63:32];
                        16'h00f0: read_data_next = araddr_latched[31:0];
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
                        16'h0340: read_data_next = rfdc_status_flags;
                        16'h0344: read_data_next = rfdc_sample_count[31:0];
                        16'h0348: read_data_next = rfdc_sample_count[63:32];
                        16'h034c: read_data_next = rfdc_dropped_count;
                        16'h0350: read_data_next = {16'd0, rfdc_active_mask};
                        16'h0354: read_data_next = {16'd0, rfdc_current_valid_mask};
                        16'h0358: read_data_next = {16'd0, rfdc_seen_valid_mask};
                        16'h035c: read_data_next = science_dropped_beat_count;
                        16'h0360: read_data_next = tx_link_status_flags;
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_STREAM: begin
                    case (read_addr)
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
                        16'h033c: read_data_next = spec_dropped_count;
                        16'h0364: read_data_next = 32'd0;
                        16'h0368: read_data_next = 32'd0;
                        16'h036c: read_data_next = tx_fifo_level_words;
                        16'h0370: read_data_next = tx_fifo_high_water_words;
                        16'h0374: read_data_next = tx_fifo_backpressure_cycles;
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_DAC: begin
                    case (read_addr)
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
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_LANE_MON: begin
                    if ((read_addr >= 18'h00500) && (read_addr < 18'h00520)) begin
                        lane_idx = (read_addr - 18'h00500) >> 2;
                        read_data_next = lane_word(clip_counts, lane_idx);
                    end else if ((read_addr >= 18'h00520) && (read_addr < 18'h00540)) begin
                        lane_idx = (read_addr - 18'h00520) >> 2;
                        read_data_next = lane_word(mean_mags, lane_idx);
                    end
                end
                READ_BANK_PREVIEW_CTRL: begin
                    case (read_addr)
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
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_PREVIEW_BUF: begin
                    read_data_next = preview_rd_data;
                end
                READ_BANK_PREVIEW_EVENT: begin
                    read_data_next = preview_event_rd_data;
                end
                READ_BANK_STAGE31_SYNC: begin
                    case (read_addr)
                        16'hac00: read_data_next = 32'h0102_021f;
                        16'hac04: read_data_next = 32'd0;
                        16'hac08: read_data_next = stage31_sync_status;
                        16'hac0c: read_data_next = stage31_sync_error;
                        16'hac10: read_data_next = stage31_generation[31:0];
                        16'hac14: read_data_next = stage31_generation[63:32];
                        16'hac18: read_data_next = stage31_target_pps_count[31:0];
                        16'hac1c: read_data_next = stage31_target_pps_count[63:32];
                        16'hac20: read_data_next = stage31_epoch_tai_seconds[31:0];
                        16'hac24: read_data_next = stage31_epoch_tai_seconds[63:32];
                        16'hac28: read_data_next = stage31_first_sample0[31:0];
                        16'hac2c: read_data_next = stage31_first_sample0[63:32];
                        16'hac30: read_data_next = stage31_observation_tag[31:0];
                        16'hac34: read_data_next = stage31_observation_tag[63:32];
                        16'hac38: read_data_next = stage31_signal_chain_tag;
                        16'hac3c: read_data_next = stage31_schedule_tag;
                        16'hac40: read_data_next = stage31_mts_result_id;
                        16'hac44: read_data_next = stage31_active_generation[31:0];
                        16'hac48: read_data_next = stage31_active_generation[63:32];
                        16'hac4c: read_data_next = stage31_actual_commit_pps_count[31:0];
                        16'hac50: read_data_next = stage31_actual_commit_pps_count[63:32];
                        16'hac54: read_data_next = stage31_actual_epoch_raw_sample0[31:0];
                        16'hac58: read_data_next = stage31_actual_epoch_raw_sample0[63:32];
                        16'hac5c: read_data_next = stage31_actual_first_time_sample0[31:0];
                        16'hac60: read_data_next = stage31_actual_first_time_sample0[63:32];
                        16'hac64: read_data_next = stage31_actual_first_spec_sample0[31:0];
                        16'hac68: read_data_next = stage31_actual_first_spec_sample0[63:32];
                        16'hac6c: read_data_next = pps_count[31:0];
                        16'hac70: read_data_next = pps_count[63:32];
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_FENGINE: begin
                    case (read_addr)
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
                        16'h0930: read_data_next = pfb_data_halt_count;
                        16'h0934: read_data_next = pfb_xfft_event_count;
                        16'h0938: read_data_next = pfb_tile_overflow_count;
                        16'h093c: read_data_next = pfb_input_fifo_level;
                        16'h0940: read_data_next = pfb_xfft_tlast_unexpected_count;
                        16'h0944: read_data_next = pfb_xfft_tlast_missing_count;
                        16'h0948: read_data_next = pfb_xfft_fft_overflow_count;
                        16'h094c: read_data_next = pfb_xfft_data_out_halt_count;
                        16'h0950: read_data_next = pfb_xfft_status_halt_count;
                        16'h0954: read_data_next = pfb_capture_backpressure_count;
                        16'h0958: read_data_next = pfb_frame_sample0_overflow_count;
                        16'h0960: read_data_next = {24'd0, pfb_coeff_requested_taps, pfb_coeff_auto_increment, 3'd0};
                        16'h0964: read_data_next = pfb_coeff_status;
                        16'h0968: read_data_next = {18'd0, pfb_coeff_next_index};
                        16'h096c: read_data_next = {{14{pfb_coeff_data[17]}}, pfb_coeff_data};
                        16'h0970: read_data_next = pfb_coeff_loaded_count;
                        16'h0974: read_data_next = pfb_coeff_active_id;
                        16'h0978: read_data_next = pfb_coeff_active_checksum;
                        16'h097c: read_data_next = pfb_coeff_error_count;
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_TX: begin
                    case (read_addr)
                        16'hb000: read_data_next = {27'd0, tx_control[4:0]};
                        16'hb004: read_data_next = tx_preflight_status_flags;
                        16'hb008: read_data_next = tx_frame_built_count;
                        16'hb00c: read_data_next = tx_frame_sent_count;
                        16'hb010: read_data_next = tx_frame_dropped_count;
                        16'hb014: read_data_next = tx_frame_byte_count;
                        16'hb018: read_data_next = tx_route_miss_count;
                        16'hb01c: read_data_next = tx_route_error_count;
                        16'hb020: read_data_next = 32'd0;
                        16'hb024: read_data_next = 32'd0;
                        16'hb028: read_data_next = {24'd0, tx_selected_endpoint_id};
                        16'hb02c: read_data_next = {25'd0, tx_selected_route_is_time, tx_selected_route_id};
                        16'hb700: read_data_next = qsfp_test_interval_cycles;
                        16'hb704: read_data_next = tx_cmac_source_status;
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_TX_INDIRECT: begin
                    case (read_addr)
                        16'hb100: read_data_next = {25'd0, tx_endpoint_indirect_index};
                        16'hb104: if (tx_endpoint_indirect_valid) read_data_next = {31'd0, tx_endpoint_enable[tx_endpoint_indirect_index]};
                        16'hb108: if (tx_endpoint_indirect_valid) read_data_next = endpoint_ip_word(tx_endpoint_indirect_index);
                        16'hb10c: if (tx_endpoint_indirect_valid) read_data_next = endpoint_mac_lo_word(tx_endpoint_indirect_index);
                        16'hb110: if (tx_endpoint_indirect_valid) read_data_next = endpoint_mac_hi_word(tx_endpoint_indirect_index);
                        16'hb114: if (tx_endpoint_indirect_valid) read_data_next = endpoint_dst_port_word(tx_endpoint_indirect_index);
                        16'hb118: if (tx_endpoint_indirect_valid) read_data_next = endpoint_src_port_word(tx_endpoint_indirect_index);
                        16'hb130: read_data_next = {26'd0, tx_spec_route_indirect_index};
                        16'hb134: if (tx_spec_route_indirect_valid) read_data_next = spec_route_ctrl_word(tx_spec_route_indirect_index);
                        16'hb138: if (tx_spec_route_indirect_valid) read_data_next = spec_route_chan0_word(tx_spec_route_indirect_index);
                        16'hb13c: if (tx_spec_route_indirect_valid) read_data_next = spec_route_chan_count_word(tx_spec_route_indirect_index);
                        16'hb140: if (tx_spec_route_indirect_valid) read_data_next = spec_route_hit_word(tx_spec_route_indirect_index);
                        16'hb150: read_data_next = {29'd0, tx_time_route_indirect_index};
                        16'hb154: if (tx_time_route_indirect_valid) read_data_next = time_route_ctrl_word(tx_time_route_indirect_index);
                        16'hb158: if (tx_time_route_indirect_valid) read_data_next = time_route_mask_word(tx_time_route_indirect_index);
                        16'hb15c: if (tx_time_route_indirect_valid) read_data_next = time_route_hit_word(tx_time_route_indirect_index);
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_SCIENCE: begin
                    case (read_addr)
                        16'hd000: read_data_next = science_control;
                        16'hd004: read_data_next = science_status_word;
                        16'hd008: read_data_next = {30'd0, science_bandwidth_mode};
                        16'hd00c: read_data_next = {29'd0, science_output_mode};
                        16'hd010: read_data_next = science_sample_rate_hz(science_bandwidth_mode);
                        16'hd014: read_data_next = science_decim_factor(science_bandwidth_mode);
                        16'hd018: read_data_next = science_payload_rate_mbps(science_bandwidth_mode, science_output_mode);
                        16'hd01c: read_data_next = science_block_reason;
                        16'hd020: read_data_next = SCIENCE_CAPABILITY_WORD;
                        16'hd024: read_data_next = time_live_interval_beats;
                        16'hd028: read_data_next = {30'd0, time_ddr_ring_clear_pulse, time_ddr_ring_enable};
                        16'hd02c: read_data_next = time_ddr_ring_base_addr[31:0];
                        16'hd030: read_data_next = time_ddr_ring_base_addr[63:32];
                        16'hd034: read_data_next = {16'd0, time_ddr_ring_slots};
                        16'hd038: read_data_next = time_ddr_ring_status;
                        16'hd03c: read_data_next = time_ddr_ring_occupancy;
                        16'hd040: read_data_next = time_ddr_ring_write_count;
                        16'hd044: read_data_next = time_ddr_ring_read_count;
                        16'hd048: read_data_next = time_ddr_ring_drop_count;
                        16'hd04c: read_data_next = time_ddr_ring_error_count;
                        16'hd050: read_data_next = {12'd0, time_multiflow_count, 5'd0, time_multiflow_base_endpoint, 7'd0, time_multiflow_enable};
                        16'hd054: read_data_next = {
                            22'd0,
                            science_aa100_primed,
                            science_aa100_active,
                            8'd41
                        };
                        16'hd058: read_data_next = science_aa100_coeff_version;
                        16'hd060: read_data_next = {15'd0, diag_dac_gate, diag_adc_channel_mask, 6'd0, diag_adc_force_hold, diag_adc_force_zero};
                        default: read_data_next = 32'd0;
                    endcase
                end
                READ_BANK_RAW_WITNESS: begin
                    case (read_addr)
                        16'he200: read_data_next = 32'd0;
                        16'he204: read_data_next = {
                            5'd0,
                            rfdc_axis_raw_witness_channel_select,
                            7'd0,
                            rfdc_axis_raw_witness_beat_count,
                            3'd0,
                            rfdc_axis_raw_witness_tvalid_seen,
                            rfdc_axis_raw_witness_overflow,
                            rfdc_axis_raw_witness_capturing,
                            rfdc_axis_raw_witness_valid,
                            rfdc_axis_raw_witness_armed
                        };
                        16'he208: read_data_next = {29'd0, rfdc_axis_raw_witness_channel_select_ctrl};
                        16'he20c: read_data_next = {23'd0, rfdc_axis_raw_witness_capture_beats};
                        16'he210: read_data_next = rfdc_axis_raw_witness_sample0[31:0];
                        16'he214: read_data_next = rfdc_axis_raw_witness_sample0[63:32];
                        16'he218: read_data_next = rfdc_axis_raw_witness_rfdc_flags;
                        16'he21c: read_data_next = {21'd0, rfdc_axis_raw_witness_beat_count, 2'b00};
                        16'he220: read_data_next = 32'd1024;
                        16'he224: read_data_next = {16'd0, rfdc_axis_raw_witness_valid_mask};
                        default: begin
                            if ((read_addr >= 18'h0e800) && (read_addr < 18'h0f800)) begin
                                read_data_next = rfdc_axis_raw_witness_rd_data;
                            end else begin
                                read_data_next = 32'd0;
                            end
                        end
                    endcase
                end
                default: begin
                    read_data_next = 32'd0;
                end
            endcase
        end else begin
        case (read_addr)
            16'h0000: read_data_next = CORE_VERSION;
            16'h0004: read_data_next = {16'd0, board_id};
            16'h0008: read_data_next = {30'd0, mode};
            16'h000c: read_data_next = {28'd0, soft_reset_pulse, stop_pulse, soft_epoch_pulse, arm_latched};
            16'h0010: read_data_next = {20'd0, fsm_state, 3'd0, waiting_for_epoch, active_sync_mode, streaming, armed};
            16'h0014: read_data_next = {29'd0, (pps_count != 64'd0), ref_locked, pps_seen};
            16'h0018: read_data_next = {31'd0, ref_locked};
            16'h001c: read_data_next = error_flags;
            16'h0020: read_data_next = {14'd0, clock_ref, 14'd0, sync_mode};
            16'h0024: read_data_next = pps_count[31:0];
            16'h0028: read_data_next = pps_count[63:32];
            16'h00f0: read_data_next = araddr_latched[31:0];
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
            16'h033c: read_data_next = spec_dropped_count;
            16'h0340: read_data_next = rfdc_status_flags;
            16'h0344: read_data_next = rfdc_sample_count[31:0];
            16'h0348: read_data_next = rfdc_sample_count[63:32];
            16'h034c: read_data_next = rfdc_dropped_count;
            16'h0350: read_data_next = {16'd0, rfdc_active_mask};
            16'h0354: read_data_next = {16'd0, rfdc_current_valid_mask};
            16'h0358: read_data_next = {16'd0, rfdc_seen_valid_mask};
            16'h035c: read_data_next = science_dropped_beat_count;
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
            16'he200: read_data_next = 32'd0;
            16'he204: read_data_next = {
                5'd0,
                rfdc_axis_raw_witness_channel_select,
                7'd0,
                rfdc_axis_raw_witness_beat_count,
                3'd0,
                rfdc_axis_raw_witness_tvalid_seen,
                rfdc_axis_raw_witness_overflow,
                rfdc_axis_raw_witness_capturing,
                rfdc_axis_raw_witness_valid,
                rfdc_axis_raw_witness_armed
            };
            16'he208: read_data_next = {29'd0, rfdc_axis_raw_witness_channel_select_ctrl};
            16'he20c: read_data_next = {23'd0, rfdc_axis_raw_witness_capture_beats};
            16'he210: read_data_next = rfdc_axis_raw_witness_sample0[31:0];
            16'he214: read_data_next = rfdc_axis_raw_witness_sample0[63:32];
            16'he218: read_data_next = rfdc_axis_raw_witness_rfdc_flags;
            16'he21c: read_data_next = {21'd0, rfdc_axis_raw_witness_beat_count, 2'b00};
            16'he220: read_data_next = 32'd1024;
            16'he224: read_data_next = {16'd0, rfdc_axis_raw_witness_valid_mask};
            16'hb000: read_data_next = {27'd0, tx_control[4:0]};
            16'hb004: read_data_next = tx_preflight_status_flags;
            16'hb008: read_data_next = tx_frame_built_count;
            16'hb00c: read_data_next = tx_frame_sent_count;
            16'hb010: read_data_next = tx_frame_dropped_count;
            16'hb014: read_data_next = tx_frame_byte_count;
            16'hb018: read_data_next = tx_route_miss_count;
            16'hb01c: read_data_next = tx_route_error_count;
            16'hb020: read_data_next = tx_dry_run_packet_count;
            16'hb024: read_data_next = tx_dry_run_byte_count;
            16'hb028: read_data_next = {24'd0, tx_selected_endpoint_id};
            16'hb02c: read_data_next = {25'd0, tx_selected_route_is_time, tx_selected_route_id};
            16'hb030: read_data_next = 32'd0;
            16'hb034: read_data_next = {11'd0, tx_frame_capture_word_count, 14'd0, tx_frame_capture_valid, tx_frame_capture_armed};
            16'hb100: read_data_next = {25'd0, tx_endpoint_indirect_index};
            16'hb104: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = {31'd0, tx_endpoint_enable[tx_endpoint_indirect_index]};
                end
            end
            16'hb108: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = endpoint_ip_word(tx_endpoint_indirect_index);
                end
            end
            16'hb10c: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = endpoint_mac_lo_word(tx_endpoint_indirect_index);
                end
            end
            16'hb110: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = endpoint_mac_hi_word(tx_endpoint_indirect_index);
                end
            end
            16'hb114: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = endpoint_dst_port_word(tx_endpoint_indirect_index);
                end
            end
            16'hb118: begin
                if (tx_endpoint_indirect_valid) begin
                    read_data_next = endpoint_src_port_word(tx_endpoint_indirect_index);
                end
            end
            16'hb130: read_data_next = {26'd0, tx_spec_route_indirect_index};
            16'hb134: begin
                if (tx_spec_route_indirect_valid) begin
                    read_data_next = spec_route_ctrl_word(tx_spec_route_indirect_index);
                end
            end
            16'hb138: begin
                if (tx_spec_route_indirect_valid) begin
                    read_data_next = spec_route_chan0_word(tx_spec_route_indirect_index);
                end
            end
            16'hb13c: begin
                if (tx_spec_route_indirect_valid) begin
                    read_data_next = spec_route_chan_count_word(tx_spec_route_indirect_index);
                end
            end
            16'hb140: begin
                if (tx_spec_route_indirect_valid) begin
                    read_data_next = spec_route_hit_word(tx_spec_route_indirect_index);
                end
            end
            16'hb150: read_data_next = {29'd0, tx_time_route_indirect_index};
            16'hb154: begin
                if (tx_time_route_indirect_valid) begin
                    read_data_next = time_route_ctrl_word(tx_time_route_indirect_index);
                end
            end
            16'hb158: begin
                if (tx_time_route_indirect_valid) begin
                    read_data_next = time_route_mask_word(tx_time_route_indirect_index);
                end
            end
            16'hb15c: begin
                if (tx_time_route_indirect_valid) begin
                    read_data_next = time_route_hit_word(tx_time_route_indirect_index);
                end
            end
            16'hb700: read_data_next = qsfp_test_interval_cycles;
            16'hb704: read_data_next = tx_cmac_source_status;
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
            16'h0930: read_data_next = pfb_data_halt_count;
            16'h0934: read_data_next = pfb_xfft_event_count;
            16'h0938: read_data_next = pfb_tile_overflow_count;
            16'h093c: read_data_next = pfb_input_fifo_level;
            16'h0940: read_data_next = pfb_xfft_tlast_unexpected_count;
            16'h0944: read_data_next = pfb_xfft_tlast_missing_count;
            16'h0948: read_data_next = pfb_xfft_fft_overflow_count;
            16'h094c: read_data_next = pfb_xfft_data_out_halt_count;
            16'h0950: read_data_next = pfb_xfft_status_halt_count;
            16'h0954: read_data_next = pfb_capture_backpressure_count;
            16'h0958: read_data_next = pfb_frame_sample0_overflow_count;
            16'h0960: read_data_next = {24'd0, pfb_coeff_requested_taps, pfb_coeff_auto_increment, 3'd0};
            16'h0964: read_data_next = pfb_coeff_status;
            16'h0968: read_data_next = {18'd0, pfb_coeff_next_index};
            16'h096c: read_data_next = {{14{pfb_coeff_data[17]}}, pfb_coeff_data};
            16'h0970: read_data_next = pfb_coeff_loaded_count;
            16'h0974: read_data_next = pfb_coeff_active_id;
            16'h0978: read_data_next = pfb_coeff_active_checksum;
            16'h097c: read_data_next = pfb_coeff_error_count;
            16'hd000: read_data_next = science_control;
            16'hd004: read_data_next = science_status_word;
            16'hd008: read_data_next = {30'd0, science_bandwidth_mode};
            16'hd00c: read_data_next = {29'd0, science_output_mode};
            16'hd010: read_data_next = science_sample_rate_hz(science_bandwidth_mode);
            16'hd014: read_data_next = science_decim_factor(science_bandwidth_mode);
            16'hd018: read_data_next = science_payload_rate_mbps(science_bandwidth_mode, science_output_mode);
            16'hd01c: read_data_next = science_block_reason;
            16'hd020: read_data_next = SCIENCE_CAPABILITY_WORD;
            16'hd024: read_data_next = time_live_interval_beats;
            16'hd028: read_data_next = {30'd0, time_ddr_ring_clear_pulse, time_ddr_ring_enable};
            16'hd02c: read_data_next = time_ddr_ring_base_addr[31:0];
            16'hd030: read_data_next = time_ddr_ring_base_addr[63:32];
            16'hd034: read_data_next = {16'd0, time_ddr_ring_slots};
            16'hd038: read_data_next = time_ddr_ring_status;
            16'hd03c: read_data_next = time_ddr_ring_occupancy;
            16'hd040: read_data_next = time_ddr_ring_write_count;
            16'hd044: read_data_next = time_ddr_ring_read_count;
            16'hd048: read_data_next = time_ddr_ring_drop_count;
            16'hd04c: read_data_next = time_ddr_ring_error_count;
            16'hd050: read_data_next = {12'd0, time_multiflow_count, 5'd0, time_multiflow_base_endpoint, 7'd0, time_multiflow_enable};
            16'hd054: read_data_next = {
                22'd0,
                science_aa100_primed,
                science_aa100_active,
                8'd41
            };
            16'hd058: read_data_next = science_aa100_coeff_version;
            16'hd060: read_data_next = {15'd0, diag_dac_gate, diag_adc_channel_mask, 6'd0, diag_adc_force_hold, diag_adc_force_zero};
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
                end else if (!PRODUCTION_27H && (read_addr >= 18'h13000) && (read_addr < 18'h13900)) begin
                    lane_idx = (read_addr - 18'h13000) >> 5;
                    if (lane_idx < N_TX_ENDPOINTS) begin
                        case ((read_addr - 18'h13000) & 18'h0001f)
                            16'h0000: read_data_next = {31'd0, tx_endpoint_enable[lane_idx]};
                            16'h0004: read_data_next = tx_endpoint_ip_vec[lane_idx*32 +: 32];
                            16'h0008: read_data_next = tx_endpoint_mac_vec[lane_idx*48 +: 32];
                            16'h000c: read_data_next = {16'd0, tx_endpoint_mac_vec[lane_idx*48 + 32 +: 16]};
                            16'h0010: read_data_next = {16'd0, tx_endpoint_dst_port_vec[lane_idx*16 +: 16]};
                            16'h0014: read_data_next = {16'd0, tx_endpoint_src_port_vec[lane_idx*16 +: 16]};
                            default: read_data_next = 32'd0;
                        endcase
                    end
                end else if (!PRODUCTION_27H && (read_addr >= 18'h14000) && (read_addr < 18'h14800)) begin
                    lane_idx = (read_addr - 18'h14000) >> 5;
                    if (lane_idx < N_SPEC_ROUTES) begin
                        case ((read_addr - 18'h14000) & 18'h0001f)
                            16'h0000: read_data_next = {16'd0, tx_spec_route_endpoint_vec[lane_idx*8 +: 8], 7'd0, tx_spec_route_enable[lane_idx]};
                            16'h0004: read_data_next = tx_spec_route_chan0_vec[lane_idx*32 +: 32];
                            16'h0008: read_data_next = {16'd0, tx_spec_route_chan_count_vec[lane_idx*16 +: 16]};
                            16'h000c: read_data_next = tx_spec_route_hit_counts[lane_idx*32 +: 32];
                            default: read_data_next = 32'd0;
                        endcase
                    end
                end else if (!PRODUCTION_27H && (read_addr >= 18'h14800) && (read_addr < 18'h14900)) begin
                    lane_idx = (read_addr - 18'h14800) >> 5;
                    if (lane_idx < N_TIME_ROUTES) begin
                        case ((read_addr - 18'h14800) & 18'h0001f)
                            16'h0000: read_data_next = {16'd0, tx_time_route_endpoint_vec[lane_idx*8 +: 8], 7'd0, tx_time_route_enable[lane_idx]};
                            16'h0004: read_data_next = {16'd0, tx_time_route_input_mask_vec[lane_idx*16 +: 16]};
                            16'h000c: read_data_next = tx_time_route_hit_counts[lane_idx*32 +: 32];
                            default: read_data_next = 32'd0;
                        endcase
                    end
                end else if (!PRODUCTION_27H && (read_addr >= 16'h0800) && (read_addr < 16'h1800)) begin
                    read_data_next = debug_time_rd_data;
                end else if (!PRODUCTION_27H && (read_addr >= 16'h1800) && (read_addr < 16'h2800)) begin
                    read_data_next = debug_fft_rd_data;
                end else if ((read_addr >= 16'h2800) && (read_addr < 16'ha800)) begin
                    read_data_next = preview_rd_data;
                end else if ((read_addr >= 16'ha800) && (read_addr < 16'hac00)) begin
                    read_data_next = preview_event_rd_data;
                end else if (!PRODUCTION_27H && (read_addr >= 18'h10000) && (read_addr < 18'h12100)) begin
                    read_data_next = tx_payload_witness_rd_data;
                end else if (!PRODUCTION_27H && (read_addr >= 16'hc000) && (read_addr < 16'hd000)) begin
                    read_data_next = dac_tx_witness_rd_data;
                end else if (!PRODUCTION_27H && (read_addr >= 16'he800) && (read_addr < 16'hf800)) begin
                    read_data_next = rfdc_axis_raw_witness_rd_data;
                end else begin
                    read_data_next = 32'd0;
                end
            end
        endcase
        end
    end

endmodule
