module t510_fengine_top (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         ctrl_clk,
    input  wire         ctrl_rst_n,
    input  wire         pps_in,
    input  wire         ref_lock_in,
    input  wire         rfdc_ready_in,
    input  wire [31:0]  s_axi_awaddr,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output wire [1:0]   s_axi_bresp,
    output wire         s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [31:0]  s_axi_araddr,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output wire [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output wire         s_axi_rvalid,
    input  wire         s_axi_rready,
    input  wire [1023:0] s_axis_adc_tdata,
    input  wire [31:0]  s_axis_adc_tuser,
    input  wire [63:0]  s_axis_adc_sample0,
    input  wire         s_axis_adc_tvalid,
    input  wire         s_axis_adc_tlast,
    output wire         s_axis_adc_tready,
    input  wire [255:0] s_axis_preview_tdata0,
    input  wire [255:0] s_axis_preview_tdata1,
    input  wire [255:0] s_axis_preview_tdata2,
    input  wire [255:0] s_axis_preview_tdata3,
    input  wire [63:0]  s_axis_preview_sample0,
    input  wire         s_axis_preview_tvalid,
    input  wire [31:0]  rfdc_status_flags,
    input  wire [63:0]  rfdc_sample_count,
    input  wire [31:0]  rfdc_dropped_count,
    input  wire [15:0]  rfdc_current_valid_mask,
    input  wire [15:0]  rfdc_seen_valid_mask,
    input  wire [31:0]  dac_audit_phase_epoch_seen,
    input  wire [31:0]  dac_audit_ch0_phase_acc,
    input  wire [31:0]  dac_audit_ch0_phase_step,
    input  wire [31:0]  dac_audit_ch0_phase0,
    input  wire [31:0]  dac_audit_ch0_mode,
    input  wire         dac_tx_witness_armed,
    input  wire         dac_tx_witness_valid,
    input  wire         dac_tx_witness_capturing,
    input  wire         dac_tx_witness_overflow,
    input  wire         dac_tx_witness_tvalid_seen,
    input  wire         dac_tx_witness_tready_seen,
    input  wire         dac_tx_witness_ready_gap_seen,
    input  wire [8:0]   dac_tx_witness_word_count,
    input  wire [31:0]  dac_tx_witness_phase_epoch,
    input  wire [31:0]  dac_tx_witness_phase_acc,
    input  wire [31:0]  dac_tx_witness_phase_step,
    input  wire [31:0]  dac_tx_witness_phase0,
    input  wire [31:0]  dac_tx_witness_mode,
    input  wire [31:0]  dac_tx_witness_ready_gap_count,
    input  wire [31:0]  dac_tx_witness_rd_data,
    output wire [15:0]  rfdc_active_port_mask,
    output wire [63:0]  m_axis_tx_tdata,
    output wire [7:0]   m_axis_tx_tkeep,
    output wire         m_axis_tx_tvalid,
    output wire         m_axis_tx_tlast,
    input  wire         m_axis_tx_tready,
    input  wire         cmac_tx_clk,
    input  wire         cmac_tx_rst_n,
    output wire [511:0] cmac_tx_axis_tdata,
    output wire [63:0]  cmac_tx_axis_tkeep,
    output wire         cmac_tx_axis_tvalid,
    output wire         cmac_tx_axis_tlast,
    input  wire         cmac_tx_axis_tready,
    input  wire [31:0]  tx_link_status_flags,
    input  wire [31:0]  tx_dry_run_packet_count,
    input  wire [31:0]  tx_dry_run_byte_count,
    output wire         dac_tone_enable,
    output wire [15:0]  dac_tone_amplitude,
    output wire [31:0]  dac_tone_phase_step,
    output wire [7:0]   dac_enable_mask,
    output wire [127:0] dac_tone_amplitude_vec,
    output wire [255:0] dac_tone_phase_step_vec,
    output wire [255:0] dac_tone_phase0_vec,
    output wire [255:0] dac_tone_phase_inject_vec,
    output wire [15:0]  dac_tone_mode_vec,
    output wire [31:0]  dac_phase_epoch,
    output wire         dac_tx_witness_arm_pulse,
    output wire         dac_tx_witness_clear_pulse,
    output wire [8:0]   dac_tx_witness_capture_words,
    output wire [9:0]   dac_tx_witness_rd_word,
    output wire         irq
);

    localparam [1:0] MODE_SPEC     = 2'd0;
    localparam [1:0] MODE_TIME     = 2'd1;
    localparam [1:0] MODE_DUAL     = 2'd2;
    localparam [1:0] MODE_SNAPSHOT = 2'd3;

    wire [15:0] ctrl_board_id;
    wire [1:0]  ctrl_mode;
    wire        ctrl_arm_latched;
    wire        ctrl_soft_epoch_pulse;
    wire        ctrl_stop_pulse;
    wire        ctrl_soft_reset_pulse;
    wire [1:0]  ctrl_sync_mode;
    wire [1:0]  ctrl_clock_ref;
    wire [31:0] ctrl_sample_rate_hz;
    wire [15:0] ctrl_quant_mode;
    wire [15:0] ctrl_scale_mode;
    wire [31:0] ctrl_scale_id;
    wire [15:0] ctrl_time_payload_nsamp;
    wire [15:0] ctrl_spec_time_count;
    wire [15:0] ctrl_spec_chan_count;
    wire        ctrl_pfb_enable;
    wire        ctrl_pfb_clear_pulse;
    wire [15:0] ctrl_pfb_taps;
    wire [15:0] ctrl_pfb_fft_shift;
    wire [31:0] ctrl_pfb_chan0;
    wire [15:0] ctrl_pfb_chan_count;
    wire [15:0] ctrl_pfb_time_count;
    wire [31:0] ctrl_chan_split;
    wire [31:0] ctrl_src_ip;
    wire [31:0] ctrl_dgx_a_ip;
    wire [31:0] ctrl_dgx_b_ip;
    wire [31:0] ctrl_time_dst_ip;
    wire [47:0] ctrl_src_mac;
    wire [47:0] ctrl_dgx_a_mac;
    wire [47:0] ctrl_dgx_b_mac;
    wire [15:0] ctrl_src_udp_port;
    wire [15:0] ctrl_dgx_a_udp_port;
    wire [15:0] ctrl_dgx_b_udp_port;
    wire [15:0] ctrl_time_udp_port;
    wire [31:0] ctrl_tx_control;
    wire        ctrl_tx_clear_pulse;
    wire [7:0]  ctrl_tx_endpoint_enable;
    wire [255:0] ctrl_tx_endpoint_ip_vec;
    wire [383:0] ctrl_tx_endpoint_mac_vec;
    wire [127:0] ctrl_tx_endpoint_src_port_vec;
    wire [127:0] ctrl_tx_endpoint_dst_port_vec;
    wire [31:0] ctrl_qsfp_test_interval_cycles;
    wire [7:0]  ctrl_tx_spec_route_enable;
    wire [255:0] ctrl_tx_spec_route_chan0_vec;
    wire [127:0] ctrl_tx_spec_route_chan_count_vec;
    wire [23:0] ctrl_tx_spec_route_endpoint_vec;
    wire [7:0]  ctrl_tx_time_route_enable;
    wire [127:0] ctrl_tx_time_route_input_mask_vec;
    wire [23:0] ctrl_tx_time_route_endpoint_vec;
    wire [15:0] ctrl_rfdc_active_mask;
    wire        ctrl_debug_capture_start_pulse;
    wire        ctrl_debug_capture_clear_pulse;
    wire [9:0]  ctrl_debug_time_rd_addr;
    wire [9:0]  ctrl_debug_fft_rd_addr;
    wire        ctrl_dac_tone_enable;
    wire [15:0] ctrl_dac_tone_amplitude;
    wire [31:0] ctrl_dac_tone_phase_step;
    wire [7:0]  ctrl_dac_enable_mask;
    wire [127:0] ctrl_dac_tone_amplitude_vec;
    wire [255:0] ctrl_dac_tone_phase_step_vec;
    wire [255:0] ctrl_dac_tone_phase0_vec;
    wire [255:0] ctrl_dac_tone_phase_inject_vec;
    wire [15:0]  ctrl_dac_tone_mode_vec;
    wire [31:0]  ctrl_dac_phase_epoch;
    wire        ctrl_preview_capture_start_pulse;
    wire        ctrl_preview_capture_clear_pulse;
    wire [7:0]  ctrl_preview_input_mask;
    wire [2:0]  ctrl_preview_rd_input;
    wire [9:0]  ctrl_preview_rd_addr;
    wire        ctrl_preview_audit_clear_pulse;
    wire [1:0]  ctrl_preview_audit_source_select;
    wire        ctrl_preview_audit_event_enable;
    wire        ctrl_preview_audit_freeze_on_event;
    wire [15:0] ctrl_preview_audit_event_threshold;
    wire [7:0]  ctrl_preview_event_rd_addr;
    wire        ctrl_tx_header_capture_arm_pulse;
    wire [4:0]  ctrl_tx_header_capture_rd_word;
    wire        ctrl_tx_frame_capture_arm_pulse;
    wire [4:0]  ctrl_tx_frame_capture_rd_word;
    wire        ctrl_tx_payload_witness_arm_pulse;
    wire        ctrl_tx_payload_witness_clear_pulse;
    wire [1:0]  ctrl_tx_payload_witness_stream_filter;
    wire [10:0] ctrl_tx_payload_witness_capture_words;
    wire [11:0] ctrl_tx_payload_witness_rd_word;
    wire        ctrl_rfdc_axis_raw_witness_arm_pulse;
    wire        ctrl_rfdc_axis_raw_witness_clear_pulse;
    wire [2:0]  ctrl_rfdc_axis_raw_witness_channel_select;
    wire [8:0]  ctrl_rfdc_axis_raw_witness_capture_beats;
    wire [9:0]  ctrl_rfdc_axis_raw_witness_rd_word;
    wire [63:0] ctrl_unix_seconds;

    (* ASYNC_REG = "TRUE" *) logic [15:0] board_id_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] board_id;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  mode;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sample_rate_hz_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sample_rate_hz;
    (* ASYNC_REG = "TRUE" *) logic [15:0] quant_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] quant_mode;
    (* ASYNC_REG = "TRUE" *) logic [15:0] scale_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] scale_mode;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scale_id_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scale_id;
    (* ASYNC_REG = "TRUE" *) logic [15:0] time_payload_nsamp_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] time_payload_nsamp;
    (* ASYNC_REG = "TRUE" *) logic [15:0] spec_time_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] spec_time_count;
    (* ASYNC_REG = "TRUE" *) logic [15:0] spec_chan_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] spec_chan_count;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  pfb_enable_sync;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_taps_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_taps;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift;
    (* ASYNC_REG = "TRUE" *) logic [31:0] pfb_chan0_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] pfb_chan0;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_chan_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_chan_count;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_time_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_time_count;
    (* ASYNC_REG = "TRUE" *) logic [31:0] chan_split_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] chan_split;
    (* ASYNC_REG = "TRUE" *) logic [31:0] src_ip_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] src_ip;
    (* ASYNC_REG = "TRUE" *) logic [47:0] src_mac_meta;
    (* ASYNC_REG = "TRUE" *) logic [47:0] src_mac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_control_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_control;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_endpoint_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_endpoint_enable;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_endpoint_ip_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_endpoint_ip_vec;
    (* ASYNC_REG = "TRUE" *) logic [383:0] tx_endpoint_mac_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [383:0] tx_endpoint_mac_vec;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_endpoint_src_port_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_endpoint_src_port_vec;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_endpoint_dst_port_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_endpoint_dst_port_vec;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_spec_route_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_spec_route_enable;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_spec_route_chan0_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_spec_route_chan0_vec;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_spec_route_chan_count_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_spec_route_chan_count_vec;
    (* ASYNC_REG = "TRUE" *) logic [23:0] tx_spec_route_endpoint_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [23:0] tx_spec_route_endpoint_vec;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_time_route_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_time_route_enable;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_time_route_input_mask_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_time_route_input_mask_vec;
    (* ASYNC_REG = "TRUE" *) logic [23:0] tx_time_route_endpoint_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [23:0] tx_time_route_endpoint_vec;
    (* ASYNC_REG = "TRUE" *) logic [15:0] rfdc_active_mask_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] rfdc_active_mask;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  sync_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  sync_mode;
    (* ASYNC_REG = "TRUE" *) logic [63:0] unix_seconds_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] unix_seconds;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  arm_latched_sync;
    logic        ctrl_soft_epoch_toggle;
    logic        ctrl_stop_toggle;
    logic        ctrl_soft_reset_toggle;
    logic        ctrl_pfb_clear_toggle;
    logic        ctrl_tx_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_epoch_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  stop_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_reset_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_cmac_sync;
    logic        soft_epoch_toggle_seen;
    logic        stop_toggle_seen;
    logic        soft_reset_toggle_seen;
    logic        pfb_clear_toggle_seen;
    logic        tx_clear_toggle_seen;
    logic        tx_clear_toggle_cmac_seen;
    wire         arm_latched;
    wire         soft_epoch_pulse;
    wire         stop_pulse;
    wire         soft_reset_pulse;
    wire         pfb_clear_pulse;
    wire         tx_clear_pulse;
    wire         tx_clear_pulse_cmac;
    logic [1:0]  mode_prev;
    logic [31:0] mode_switch_reset_count;
    wire         mode_change_pulse;
    wire         packet_stream_reset_pulse;

    wire [3:0]  fsm_state;
    wire        armed;
    wire        streaming;
    wire        waiting_for_epoch;
    wire        epoch_reset_pulse;
    wire        pps_seen;
    logic [63:0] pps_count;
    wire [31:0] error_flags;
    (* ASYNC_REG = "TRUE" *) logic [1:0] pps_sync;
    (* ASYNC_REG = "TRUE" *) logic       pps_seen_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic       pps_seen_ctrl;
    (* ASYNC_REG = "TRUE" *) logic       ref_lock_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic       ref_lock_ctrl;

    wire [31:0] monitor_sample_count;
    wire [255:0] clip_counts;
    wire [255:0] mean_mags;
    wire        debug_busy_ctrl;
    wire        debug_done_ctrl;
    wire        debug_error_ctrl;
    wire [31:0] debug_capture_count_ctrl;
    wire [31:0] debug_peak_bin_ctrl;
    wire [31:0] debug_peak_power_ctrl;
    wire [31:0] debug_time_rd_data_ctrl;
    wire [31:0] debug_fft_rd_data_ctrl;
    wire        preview_busy_ctrl;
    wire        preview_done_ctrl;
    wire        preview_error_ctrl;
    wire [31:0] preview_capture_count_ctrl;
    wire [63:0] preview_sample0_ctrl;
    wire [31:0] preview_rd_data_ctrl;
    wire [31:0] preview_event_rd_data_ctrl;
    wire [31:0] preview_audit_status_ctrl;
    wire [31:0] preview_audit_start_count_ctrl;
    wire [31:0] preview_audit_first_count_ctrl;
    wire [31:0] preview_audit_done_count_ctrl;
    wire [63:0] preview_audit_start_sample0_ctrl;
    wire [63:0] preview_audit_first_sample0_ctrl;
    wire [63:0] preview_audit_done_sample0_ctrl;
    wire [31:0] preview_audit_start_to_first_latency_ctrl;
    wire [31:0] preview_audit_capture_beats_ctrl;
    wire [31:0] preview_audit_valid_gap_count_ctrl;
    wire [31:0] preview_audit_sample0_error_count_ctrl;
    wire [63:0] preview_event_sample0_ctrl;
    wire [31:0] preview_event_max_code_ctrl;
    wire [31:0] preview_event_info_ctrl;
    wire [31:0] preview_event_rfdc_flags_ctrl;
    wire [31:0] preview_event_dac_phase_epoch_ctrl;
    wire        rfdc_axis_raw_witness_armed_ctrl;
    wire        rfdc_axis_raw_witness_valid_ctrl;
    wire        rfdc_axis_raw_witness_capturing_ctrl;
    wire        rfdc_axis_raw_witness_overflow_ctrl;
    wire        rfdc_axis_raw_witness_tvalid_seen_ctrl;
    wire [8:0]  rfdc_axis_raw_witness_beat_count_ctrl;
    wire [2:0]  rfdc_axis_raw_witness_channel_select_ctrl;
    wire [63:0] rfdc_axis_raw_witness_sample0_ctrl;
    wire [31:0] rfdc_axis_raw_witness_rfdc_flags_ctrl;
    wire [15:0] rfdc_axis_raw_witness_valid_mask_ctrl;
    wire [31:0] rfdc_axis_raw_witness_rd_data_ctrl;

    wire spec_enable;
    wire time_enable;
    wire snapshot_enable;
    wire monitor_enable;

    localparam integer SCIENCE_DATA_W = 1024;

    wire [SCIENCE_DATA_W-1:0] science_tdata;
    wire [31:0]  science_tuser;
    wire [63:0]  science_sample0;
    wire         science_tvalid;
    wire         science_tlast;
    wire         science_tready;
    wire [31:0]  science_output_beat_count;
    wire [31:0]  science_dropped_beat_count;

    wire [SCIENCE_DATA_W-1:0] spec_tdata;
    wire [31:0]  spec_tuser;
    wire [63:0]  spec_sample0;
    wire         spec_tvalid;
    wire         spec_tlast;
    wire         spec_tready;
    wire [SCIENCE_DATA_W-1:0] time_tdata;
    wire [31:0]  time_tuser;
    wire [63:0]  time_sample0_sideband;
    wire         time_tvalid;
    wire         time_tlast;
    wire         time_tready;
    wire [SCIENCE_DATA_W-1:0] snapshot_tdata;
    wire [31:0]  snapshot_tuser;
    wire [63:0]  snapshot_sample0;
    wire         snapshot_tvalid;
    wire         snapshot_tlast;
    wire         snapshot_tready;
    wire [SCIENCE_DATA_W-1:0] monitor_tdata;
    wire [31:0]  monitor_tuser;
    wire [63:0]  monitor_sample0;
    wire         monitor_tvalid;
    wire         monitor_tlast;
    wire         monitor_tready;

    wire [SCIENCE_DATA_W-1:0] quant_spec_tdata;
    wire         quant_clip_any;
    wire [SCIENCE_DATA_W-1:0] pfb_spec_tdata;
    wire [63:0]  pfb_spec_sample0;
    wire         pfb_spec_tvalid;
    wire         pfb_spec_tready;
    wire [31:0] pfb_status;
    wire [31:0] pfb_frame_count;
    wire [31:0] pfb_overflow_count;
    wire [31:0] pfb_peak_chan;
    wire [31:0] pfb_peak_power;
    wire [31:0] pfb_packet_chan0;
    wire [15:0] pfb_packet_chan_count;
    wire [15:0] pfb_packet_time_count;
    wire [1:0] ctrl_science_bandwidth_mode_cfg;
    wire [2:0] ctrl_science_output_mode_cfg;
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_bandwidth_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_bandwidth_mode;

    wire [63:0] spec_axis_tdata;
    wire [7:0]  spec_axis_tkeep;
    wire        spec_axis_tvalid;
    wire        spec_axis_tlast;
    wire        spec_axis_tready;

    wire [63:0] time_axis_tdata;
    wire [7:0]  time_axis_tkeep;
    wire        time_axis_tvalid;
    wire        time_axis_tlast;
    wire        time_axis_tready;

    wire [63:0] arb_tx_tdata;
    wire [7:0]  arb_tx_tkeep;
    wire        arb_tx_tvalid;
    wire        arb_tx_tlast;
    wire        arb_tx_tready;

    wire [31:0] tx_fifo_level_words;
    wire [31:0] tx_fifo_high_water_words;
    wire [31:0] tx_fifo_backpressure_cycles;
    wire [31:0] tx_header_capture_rd_data_ctrl;
    wire        tx_header_capture_armed_ctrl;
    wire        tx_header_capture_valid_ctrl;
    wire [4:0]  tx_header_capture_word_count_ctrl;
    wire [63:0] internal_tx_tdata;
    wire [7:0]  internal_tx_tkeep;
    wire        internal_tx_tvalid;
    wire        internal_tx_tlast;
    wire        internal_tx_tready;
    wire [63:0] routed_tx_tdata;
    wire [7:0]  routed_tx_tkeep;
    wire        routed_tx_tvalid;
    wire        routed_tx_tlast;
    wire        routed_tx_tready;
    wire [47:0] routed_dst_mac;
    wire [31:0] routed_dst_ip;
    wire [15:0] routed_src_udp_port;
    wire [15:0] routed_dst_udp_port;
    wire [31:0] routed_t510_payload_bytes;
    wire [15:0] routed_stream_type;
    wire [2:0]  routed_endpoint_id;
    wire [2:0]  routed_route_id;
    wire        routed_route_is_time;
    wire [31:0] tx_route_forwarded_count;
    wire [31:0] tx_route_dropped_count;
    wire [31:0] tx_route_miss_count;
    wire [31:0] tx_route_error_count;
    wire [2:0]  tx_selected_endpoint_id;
    wire [2:0]  tx_selected_route_id;
    wire        tx_selected_route_is_time;
    wire [255:0] tx_spec_route_hit_counts;
    wire [255:0] tx_time_route_hit_counts;
    wire [31:0] tx_frame_built_count;
    wire [31:0] tx_frame_byte_count;
    wire [31:0] tx_preflight_status_flags;
    wire        tx_dry_run_active;
    wire        tx_qsfp_link_up;
    wire        tx_qsfp_module_present;
    wire        tx_cmac_tx_ready;
    wire        tx_cmac_live_ready;
    wire        tx_qsfp_test_enable;
    wire [31:0] tx_count_packet_status;
    wire [31:0] tx_count_byte_status;
    wire [31:0] tx_cmac_test_packet_count;
    wire [31:0] tx_cmac_test_byte_count;
    wire [47:0] tx_qsfp_test_dst_mac;
    wire [31:0] tx_qsfp_test_dst_ip;
    wire [15:0] tx_qsfp_test_src_port;
    wire [15:0] tx_qsfp_test_dst_port;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_data_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_data;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_control_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_control_cmac;
    (* ASYNC_REG = "TRUE" *) logic [47:0] src_mac_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [47:0] src_mac_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] src_ip_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] src_ip_cmac;
    (* ASYNC_REG = "TRUE" *) logic [47:0] tx_qsfp_test_dst_mac_meta;
    (* ASYNC_REG = "TRUE" *) logic [47:0] tx_qsfp_test_dst_mac_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_qsfp_test_dst_ip_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_qsfp_test_dst_ip_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] tx_qsfp_test_src_port_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] tx_qsfp_test_src_port_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] tx_qsfp_test_dst_port_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] tx_qsfp_test_dst_port_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_qsfp_test_interval_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_qsfp_test_interval_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_link_status_flags_cmac;
    (* ASYNC_REG = "TRUE" *) logic [63:0] rfdc_sample_count_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] rfdc_sample_count_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] ctrl_board_id_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] ctrl_board_id_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_cmac_test_packet_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_cmac_test_packet_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_cmac_test_byte_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] tx_cmac_test_byte_count_ctrl;
    wire [31:0] tx_frame_capture_rd_data_ctrl;
    wire        tx_frame_capture_armed_ctrl;
    wire        tx_frame_capture_valid_ctrl;
    wire [4:0]  tx_frame_capture_word_count_ctrl;
    wire [31:0] tx_payload_witness_rd_data_ctrl;
    wire        tx_payload_witness_armed_ctrl;
    wire        tx_payload_witness_valid_ctrl;
    wire        tx_payload_witness_capturing_ctrl;
    wire [10:0] tx_payload_witness_word_count_ctrl;
    wire [15:0] tx_payload_witness_stream_type_ctrl;
    wire [63:0] tx_payload_witness_sample0_ctrl;
    wire [63:0] tx_payload_witness_frame_id_ctrl;
    wire [31:0] tx_payload_witness_seq_no_ctrl;
    wire [31:0] tx_payload_witness_chan0_ctrl;
    wire [63:0] tx_payload_witness_layout_word_ctrl;
    wire [31:0] tx_payload_witness_payload_bytes_ctrl;
    wire [31:0] tx_payload_witness_route_meta_ctrl;
    wire [31:0] tx_payload_witness_rfdc_flags_ctrl;
    wire [63:0] tx_payload_witness_rfdc_sample_count_ctrl;
    wire [31:0] tx_payload_witness_dac_phase_epoch_ctrl;
    wire        tx_payload_witness_overflow_ctrl;
    wire        tx_payload_witness_filter_mismatch_ctrl;

    wire [31:0] spec_packet_count;
    wire [31:0] spec_udp_byte_count;
    wire [31:0] spec_seq_no;
    wire [63:0] spec_frame_id;
    wire [31:0] spec_chan0;
    wire [31:0] time_packet_count;
    wire [31:0] time_dropped_count;
    wire [31:0] time_udp_byte_count;
    wire [31:0] time_seq_no;
    wire [63:0] time_sample0;
    wire [63:0] time_frame_id;
    wire [63:0] spec_input_sample0;
    wire [63:0] time_input_sample0;

    (* ASYNC_REG = "TRUE" *) logic [3:0]   fsm_state_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [3:0]   fsm_state_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  status_bits_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  status_bits_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  monitor_sample_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  monitor_sample_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [255:0] clip_counts_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] clip_counts_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [255:0] mean_mags_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] mean_mags_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_packet_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_packet_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_udp_byte_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_udp_byte_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_packet_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_packet_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_udp_byte_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_udp_byte_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_dropped_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_dropped_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_seq_no_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_seq_no_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_seq_no_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  time_seq_no_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  time_sample0_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  time_sample0_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  time_frame_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  time_frame_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  spec_frame_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  spec_frame_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_chan0_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_chan0_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_status_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_frame_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_frame_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_overflow_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_overflow_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_peak_chan_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_peak_chan_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_peak_power_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_peak_power_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  rfdc_status_flags_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  rfdc_status_flags_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  rfdc_sample_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  rfdc_sample_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  rfdc_dropped_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  rfdc_dropped_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  rfdc_current_valid_mask_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  rfdc_current_valid_mask_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  rfdc_seen_valid_mask_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0]  rfdc_seen_valid_mask_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_preflight_status_flags_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_preflight_status_flags_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_frame_built_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_frame_built_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_dropped_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_dropped_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_frame_byte_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_frame_byte_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_miss_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_miss_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_error_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_route_error_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0]   tx_selected_endpoint_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0]   tx_selected_endpoint_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0]   tx_selected_route_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0]   tx_selected_route_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic         tx_selected_route_is_time_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic         tx_selected_route_is_time_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_spec_route_hit_counts_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_spec_route_hit_counts_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_time_route_hit_counts_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [255:0] tx_time_route_hit_counts_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  dac_phase_epoch_data_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  dac_phase_epoch_data;
    wire [15:0] udp_epoch_mode;
    wire [15:0] udp_packet_flags;

    assign spec_enable     = streaming && ((mode == MODE_SPEC) || (mode == MODE_DUAL));
    assign time_enable     = streaming && ((mode == MODE_TIME) || (mode == MODE_DUAL));
    assign snapshot_enable = streaming && (mode == MODE_SNAPSHOT);
    assign monitor_enable  = armed;
    assign pps_seen        = pps_sync[1];
    assign udp_epoch_mode  = (sync_mode == 2'd0) ? 16'd0 : 16'd1;
    assign tx_qsfp_link_up = tx_link_status_flags_data[0];
    assign tx_qsfp_module_present = tx_link_status_flags_data[12];
    assign tx_cmac_tx_ready = tx_link_status_flags_data[4];
    assign tx_cmac_live_ready =
        tx_link_status_flags_data[0] &&
        tx_link_status_flags_data[2] &&
        tx_link_status_flags_data[3] &&
        tx_link_status_flags_data[4] &&
        !tx_link_status_flags_data[5] &&
        !tx_link_status_flags_data[6] &&
        !tx_link_status_flags_data[1];
    assign tx_dry_run_active =
        tx_control[0] ||
        tx_link_status_flags_data[1] ||
        ((!tx_qsfp_link_up) && !tx_control[4]) ||
        !tx_control[1] ||
        !tx_cmac_tx_ready;
    assign tx_count_packet_status = tx_dry_run_active ? tx_dry_run_packet_count : tx_cmac_test_packet_count_ctrl;
    assign tx_count_byte_status = tx_dry_run_active ? tx_dry_run_byte_count : tx_cmac_test_byte_count_ctrl;
    assign tx_preflight_status_flags = {
        14'd0,
        tx_link_status_flags_data[17],
        tx_link_status_flags_data[16],
        tx_link_status_flags_data[15],
        tx_link_status_flags_data[14],
        tx_link_status_flags_data[13],
        tx_qsfp_module_present,
        tx_control[1],
        tx_control[0],
        tx_control[2],
        (tx_route_error_count != 32'd0),
        (tx_route_miss_count != 32'd0),
        tx_link_status_flags_data[6],
        tx_link_status_flags_data[5],
        tx_cmac_tx_ready,
        tx_link_status_flags_data[3],
        tx_link_status_flags_data[2],
        tx_dry_run_active,
        tx_qsfp_link_up
    };
    assign tx_qsfp_test_dst_mac = tx_endpoint_mac_vec[2*48 +: 48];
    assign tx_qsfp_test_dst_ip = tx_endpoint_ip_vec[2*32 +: 32];
    assign tx_qsfp_test_src_port = tx_endpoint_src_port_vec[2*16 +: 16];
    assign tx_qsfp_test_dst_port = tx_endpoint_dst_port_vec[2*16 +: 16];
    assign tx_qsfp_test_enable =
        tx_control_cmac[1] &&
        tx_control_cmac[2] &&
        !tx_control_cmac[0] &&
        tx_link_status_flags_cmac[4] &&
        (
            tx_control_cmac[4] ||
            (
                tx_link_status_flags_cmac[0] &&
                !tx_link_status_flags_cmac[5] &&
                !tx_link_status_flags_cmac[6]
            )
        ) &&
        cmac_tx_rst_n;
    assign udp_packet_flags = {
        10'd0,
        (time_dropped_count != 32'd0),
        quant_clip_any,
        tx_dry_run_active,
        tx_qsfp_link_up,
        (sync_mode != 2'd0),
        (sync_mode == 2'd0) && pps_seen && ref_lock_in
    };
    assign error_flags     = {31'd0, quant_clip_any};
    assign irq             = (fsm_state == 4'd8);
    assign arm_latched     = arm_latched_sync[1];
    assign soft_epoch_pulse = soft_epoch_toggle_sync[2] ^ soft_epoch_toggle_seen;
    assign stop_pulse      = stop_toggle_sync[2] ^ stop_toggle_seen;
    assign soft_reset_pulse = soft_reset_toggle_sync[2] ^ soft_reset_toggle_seen;
    assign pfb_clear_pulse = pfb_clear_toggle_sync[2] ^ pfb_clear_toggle_seen;
    assign tx_clear_pulse = tx_clear_toggle_sync[2] ^ tx_clear_toggle_seen;
    assign tx_clear_pulse_cmac = tx_clear_toggle_cmac_sync[2] ^ tx_clear_toggle_cmac_seen;
    assign mode_change_pulse = (mode != mode_prev);
    assign packet_stream_reset_pulse = epoch_reset_pulse || stop_pulse || soft_reset_pulse || tx_clear_pulse || mode_change_pulse;
    assign rfdc_active_port_mask = rfdc_active_mask;
    assign dac_tone_enable = ctrl_dac_tone_enable;
    assign dac_tone_amplitude = ctrl_dac_tone_amplitude;
    assign dac_tone_phase_step = ctrl_dac_tone_phase_step;
    assign dac_enable_mask = ctrl_dac_enable_mask;
    assign dac_tone_amplitude_vec = ctrl_dac_tone_amplitude_vec;
    assign dac_tone_phase_step_vec = ctrl_dac_tone_phase_step_vec;
    assign dac_tone_phase0_vec = ctrl_dac_tone_phase0_vec;
    assign dac_tone_phase_inject_vec = ctrl_dac_tone_phase_inject_vec;
    assign dac_tone_mode_vec = ctrl_dac_tone_mode_vec;
    assign dac_phase_epoch = ctrl_dac_phase_epoch;
    assign spec_input_sample0 = spec_sample0;
    assign time_input_sample0 = time_sample0_sideband;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_soft_epoch_toggle <= 1'b0;
            ctrl_stop_toggle       <= 1'b0;
            ctrl_soft_reset_toggle <= 1'b0;
            ctrl_pfb_clear_toggle  <= 1'b0;
            ctrl_tx_clear_toggle   <= 1'b0;
        end else begin
            if (ctrl_soft_epoch_pulse) begin
                ctrl_soft_epoch_toggle <= ~ctrl_soft_epoch_toggle;
            end
            if (ctrl_stop_pulse) begin
                ctrl_stop_toggle <= ~ctrl_stop_toggle;
            end
            if (ctrl_soft_reset_pulse) begin
                ctrl_soft_reset_toggle <= ~ctrl_soft_reset_toggle;
            end
            if (ctrl_pfb_clear_pulse) begin
                ctrl_pfb_clear_toggle <= ~ctrl_pfb_clear_toggle;
            end
            if (ctrl_tx_clear_pulse) begin
                ctrl_tx_clear_toggle <= ~ctrl_tx_clear_toggle;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            board_id_meta          <= 16'd0;
            board_id               <= 16'd0;
            mode_meta              <= MODE_SPEC;
            mode                   <= MODE_SPEC;
            sample_rate_hz_meta    <= 32'd0;
            sample_rate_hz         <= 32'd0;
            quant_mode_meta        <= 16'd0;
            quant_mode             <= 16'd0;
            scale_mode_meta        <= 16'd0;
            scale_mode             <= 16'd0;
            scale_id_meta          <= 32'd0;
            scale_id               <= 32'd0;
            time_payload_nsamp_meta <= 16'd0;
            time_payload_nsamp     <= 16'd0;
            spec_time_count_meta   <= 16'd0;
            spec_time_count        <= 16'd0;
            spec_chan_count_meta   <= 16'd0;
            spec_chan_count        <= 16'd0;
            pfb_enable_sync        <= 2'b00;
            pfb_taps_meta          <= 16'd4;
            pfb_taps               <= 16'd4;
            pfb_fft_shift_meta     <= 16'd0;
            pfb_fft_shift          <= 16'd0;
            pfb_chan0_meta         <= 32'd0;
            pfb_chan0              <= 32'd0;
            pfb_chan_count_meta    <= 16'd64;
            pfb_chan_count         <= 16'd64;
            pfb_time_count_meta    <= 16'd4;
            pfb_time_count         <= 16'd4;
            science_bandwidth_mode_meta <= 2'd1;
            science_bandwidth_mode <= 2'd1;
            chan_split_meta        <= 32'd0;
            chan_split             <= 32'd0;
            src_ip_meta            <= 32'd0;
            src_ip                 <= 32'd0;
            src_mac_meta           <= 48'd0;
            src_mac                <= 48'd0;
            tx_control_meta        <= 32'h0000_000d;
            tx_control             <= 32'h0000_000d;
            tx_endpoint_enable_meta <= 8'h07;
            tx_endpoint_enable     <= 8'h07;
            tx_endpoint_ip_vec_meta <= 256'd0;
            tx_endpoint_ip_vec     <= 256'd0;
            tx_endpoint_mac_vec_meta <= 384'd0;
            tx_endpoint_mac_vec    <= 384'd0;
            tx_endpoint_src_port_vec_meta <= {8{16'd4000}};
            tx_endpoint_src_port_vec <= {8{16'd4000}};
            tx_endpoint_dst_port_vec_meta <= 128'd0;
            tx_endpoint_dst_port_vec <= 128'd0;
            tx_spec_route_enable_meta <= 8'h03;
            tx_spec_route_enable   <= 8'h03;
            tx_spec_route_chan0_vec_meta <= 256'd0;
            tx_spec_route_chan0_vec <= 256'd0;
            tx_spec_route_chan_count_vec_meta <= 128'd0;
            tx_spec_route_chan_count_vec <= 128'd0;
            tx_spec_route_endpoint_vec_meta <= 24'd0;
            tx_spec_route_endpoint_vec <= 24'd0;
            tx_time_route_enable_meta <= 8'h01;
            tx_time_route_enable   <= 8'h01;
            tx_time_route_input_mask_vec_meta <= 128'd0;
            tx_time_route_input_mask_vec <= 128'd0;
            tx_time_route_endpoint_vec_meta <= 24'd0;
            tx_time_route_endpoint_vec <= 24'd0;
            rfdc_active_mask_meta  <= 16'hffff;
            rfdc_active_mask       <= 16'hffff;
            sync_mode_meta         <= 2'd0;
            sync_mode              <= 2'd0;
            unix_seconds_meta      <= 64'd0;
            unix_seconds           <= 64'd0;
            arm_latched_sync       <= 2'b00;
            soft_epoch_toggle_sync <= 3'b000;
            stop_toggle_sync       <= 3'b000;
            soft_reset_toggle_sync <= 3'b000;
            pfb_clear_toggle_sync  <= 3'b000;
            tx_clear_toggle_sync   <= 3'b000;
            soft_epoch_toggle_seen <= 1'b0;
            stop_toggle_seen       <= 1'b0;
            soft_reset_toggle_seen <= 1'b0;
            pfb_clear_toggle_seen  <= 1'b0;
            tx_clear_toggle_seen   <= 1'b0;
            mode_prev              <= MODE_SPEC;
            mode_switch_reset_count <= 32'd0;
            pps_sync               <= 2'b00;
            pps_count              <= 64'd0;
            dac_phase_epoch_data_meta <= 32'd0;
            dac_phase_epoch_data      <= 32'd0;
            tx_link_status_flags_data_meta <= 32'd0;
            tx_link_status_flags_data      <= 32'd0;
        end else begin
            pps_sync                <= {pps_sync[0], pps_in};
            if (pps_sync[0] && !pps_sync[1]) begin
                pps_count <= pps_count + 64'd1;
            end
            tx_link_status_flags_data_meta <= tx_link_status_flags;
            tx_link_status_flags_data      <= tx_link_status_flags_data_meta;
            board_id_meta           <= ctrl_board_id;
            board_id                <= board_id_meta;
            mode_meta               <= ctrl_mode;
            mode                    <= mode_meta;
            mode_prev               <= mode;
            if (mode != mode_prev) begin
                mode_switch_reset_count <= mode_switch_reset_count + 32'd1;
            end
            sample_rate_hz_meta     <= ctrl_sample_rate_hz;
            sample_rate_hz          <= sample_rate_hz_meta;
            quant_mode_meta         <= ctrl_quant_mode;
            quant_mode              <= quant_mode_meta;
            scale_mode_meta         <= ctrl_scale_mode;
            scale_mode              <= scale_mode_meta;
            scale_id_meta           <= ctrl_scale_id;
            scale_id                <= scale_id_meta;
            time_payload_nsamp_meta <= ctrl_time_payload_nsamp;
            time_payload_nsamp      <= time_payload_nsamp_meta;
            spec_time_count_meta    <= ctrl_spec_time_count;
            spec_time_count         <= spec_time_count_meta;
            spec_chan_count_meta    <= ctrl_spec_chan_count;
            spec_chan_count         <= spec_chan_count_meta;
            pfb_enable_sync         <= {pfb_enable_sync[0], ctrl_pfb_enable};
            pfb_taps_meta           <= ctrl_pfb_taps;
            pfb_taps                <= pfb_taps_meta;
            pfb_fft_shift_meta      <= ctrl_pfb_fft_shift;
            pfb_fft_shift           <= pfb_fft_shift_meta;
            pfb_chan0_meta          <= ctrl_pfb_chan0;
            pfb_chan0               <= pfb_chan0_meta;
            pfb_chan_count_meta     <= ctrl_pfb_chan_count;
            pfb_chan_count          <= pfb_chan_count_meta;
            pfb_time_count_meta     <= ctrl_pfb_time_count;
            pfb_time_count          <= pfb_time_count_meta;
            science_bandwidth_mode_meta <= ctrl_science_bandwidth_mode_cfg;
            science_bandwidth_mode <= science_bandwidth_mode_meta;
            chan_split_meta         <= ctrl_chan_split;
            chan_split              <= chan_split_meta;
            src_ip_meta             <= ctrl_src_ip;
            src_ip                  <= src_ip_meta;
            src_mac_meta            <= ctrl_src_mac;
            src_mac                 <= src_mac_meta;
            tx_control_meta         <= ctrl_tx_control;
            tx_control              <= tx_control_meta;
            tx_endpoint_enable_meta <= ctrl_tx_endpoint_enable;
            tx_endpoint_enable      <= tx_endpoint_enable_meta;
            tx_endpoint_ip_vec_meta <= ctrl_tx_endpoint_ip_vec;
            tx_endpoint_ip_vec      <= tx_endpoint_ip_vec_meta;
            tx_endpoint_mac_vec_meta <= ctrl_tx_endpoint_mac_vec;
            tx_endpoint_mac_vec     <= tx_endpoint_mac_vec_meta;
            tx_endpoint_src_port_vec_meta <= ctrl_tx_endpoint_src_port_vec;
            tx_endpoint_src_port_vec <= tx_endpoint_src_port_vec_meta;
            tx_endpoint_dst_port_vec_meta <= ctrl_tx_endpoint_dst_port_vec;
            tx_endpoint_dst_port_vec <= tx_endpoint_dst_port_vec_meta;
            tx_spec_route_enable_meta <= ctrl_tx_spec_route_enable;
            tx_spec_route_enable    <= tx_spec_route_enable_meta;
            tx_spec_route_chan0_vec_meta <= ctrl_tx_spec_route_chan0_vec;
            tx_spec_route_chan0_vec <= tx_spec_route_chan0_vec_meta;
            tx_spec_route_chan_count_vec_meta <= ctrl_tx_spec_route_chan_count_vec;
            tx_spec_route_chan_count_vec <= tx_spec_route_chan_count_vec_meta;
            tx_spec_route_endpoint_vec_meta <= ctrl_tx_spec_route_endpoint_vec;
            tx_spec_route_endpoint_vec <= tx_spec_route_endpoint_vec_meta;
            tx_time_route_enable_meta <= ctrl_tx_time_route_enable;
            tx_time_route_enable    <= tx_time_route_enable_meta;
            tx_time_route_input_mask_vec_meta <= ctrl_tx_time_route_input_mask_vec;
            tx_time_route_input_mask_vec <= tx_time_route_input_mask_vec_meta;
            tx_time_route_endpoint_vec_meta <= ctrl_tx_time_route_endpoint_vec;
            tx_time_route_endpoint_vec <= tx_time_route_endpoint_vec_meta;
            rfdc_active_mask_meta   <= ctrl_rfdc_active_mask;
            rfdc_active_mask        <= rfdc_active_mask_meta;
            sync_mode_meta          <= ctrl_sync_mode;
            sync_mode               <= sync_mode_meta;
            unix_seconds_meta       <= ctrl_unix_seconds;
            unix_seconds            <= unix_seconds_meta;
            arm_latched_sync        <= {arm_latched_sync[0], ctrl_arm_latched};
            soft_epoch_toggle_sync  <= {soft_epoch_toggle_sync[1:0], ctrl_soft_epoch_toggle};
            stop_toggle_sync        <= {stop_toggle_sync[1:0], ctrl_stop_toggle};
            soft_reset_toggle_sync  <= {soft_reset_toggle_sync[1:0], ctrl_soft_reset_toggle};
            pfb_clear_toggle_sync   <= {pfb_clear_toggle_sync[1:0], ctrl_pfb_clear_toggle};
            tx_clear_toggle_sync    <= {tx_clear_toggle_sync[1:0], ctrl_tx_clear_toggle};
            soft_epoch_toggle_seen  <= soft_epoch_toggle_sync[2];
            stop_toggle_seen        <= stop_toggle_sync[2];
            soft_reset_toggle_seen  <= soft_reset_toggle_sync[2];
            pfb_clear_toggle_seen   <= pfb_clear_toggle_sync[2];
            tx_clear_toggle_seen    <= tx_clear_toggle_sync[2];
            dac_phase_epoch_data_meta <= ctrl_dac_phase_epoch;
            dac_phase_epoch_data      <= dac_phase_epoch_data_meta;
        end
    end

    always_ff @(posedge cmac_tx_clk) begin
        if (!cmac_tx_rst_n) begin
            src_mac_cmac_meta <= 48'd0;
            src_mac_cmac <= 48'd0;
            src_ip_cmac_meta <= 32'd0;
            src_ip_cmac <= 32'd0;
            tx_qsfp_test_dst_mac_meta <= 48'd0;
            tx_qsfp_test_dst_mac_cmac <= 48'd0;
            tx_qsfp_test_dst_ip_meta <= 32'd0;
            tx_qsfp_test_dst_ip_cmac <= 32'd0;
            tx_qsfp_test_src_port_meta <= 16'd4000;
            tx_qsfp_test_src_port_cmac <= 16'd4000;
            tx_qsfp_test_dst_port_meta <= 16'd4300;
            tx_qsfp_test_dst_port_cmac <= 16'd4300;
            tx_qsfp_test_interval_meta <= 32'd322_266;
            tx_qsfp_test_interval_cmac <= 32'd322_266;
            tx_link_status_flags_cmac_meta <= 32'd0;
            tx_link_status_flags_cmac <= 32'd0;
            tx_control_cmac_meta <= 32'h0000_000d;
            tx_control_cmac <= 32'h0000_000d;
            rfdc_sample_count_cmac_meta <= 64'd0;
            rfdc_sample_count_cmac <= 64'd0;
            ctrl_board_id_cmac_meta <= 16'd0;
            ctrl_board_id_cmac <= 16'd0;
            tx_clear_toggle_cmac_sync <= 3'b000;
            tx_clear_toggle_cmac_seen <= 1'b0;
        end else begin
            src_mac_cmac_meta <= src_mac;
            src_mac_cmac <= src_mac_cmac_meta;
            src_ip_cmac_meta <= src_ip;
            src_ip_cmac <= src_ip_cmac_meta;
            tx_qsfp_test_dst_mac_meta <= tx_qsfp_test_dst_mac;
            tx_qsfp_test_dst_mac_cmac <= tx_qsfp_test_dst_mac_meta;
            tx_qsfp_test_dst_ip_meta <= tx_qsfp_test_dst_ip;
            tx_qsfp_test_dst_ip_cmac <= tx_qsfp_test_dst_ip_meta;
            tx_qsfp_test_src_port_meta <= tx_qsfp_test_src_port;
            tx_qsfp_test_src_port_cmac <= tx_qsfp_test_src_port_meta;
            tx_qsfp_test_dst_port_meta <= tx_qsfp_test_dst_port;
            tx_qsfp_test_dst_port_cmac <= tx_qsfp_test_dst_port_meta;
            tx_qsfp_test_interval_meta <= ctrl_qsfp_test_interval_cycles;
            tx_qsfp_test_interval_cmac <= tx_qsfp_test_interval_meta;
            tx_link_status_flags_cmac_meta <= tx_link_status_flags;
            tx_link_status_flags_cmac <= tx_link_status_flags_cmac_meta;
            tx_control_cmac_meta <= tx_control;
            tx_control_cmac <= tx_control_cmac_meta;
            rfdc_sample_count_cmac_meta <= rfdc_sample_count;
            rfdc_sample_count_cmac <= rfdc_sample_count_cmac_meta;
            ctrl_board_id_cmac_meta <= ctrl_board_id;
            ctrl_board_id_cmac <= ctrl_board_id_cmac_meta;
            tx_clear_toggle_cmac_sync <= {tx_clear_toggle_cmac_sync[1:0], ctrl_tx_clear_toggle};
            tx_clear_toggle_cmac_seen <= tx_clear_toggle_cmac_sync[2];
        end
    end

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            fsm_state_ctrl_meta             <= 4'd0;
            fsm_state_ctrl                  <= 4'd0;
            status_bits_ctrl_meta           <= 32'd0;
            status_bits_ctrl                <= 32'd0;
            pps_seen_ctrl_meta              <= 1'b0;
            pps_seen_ctrl                   <= 1'b0;
            ref_lock_ctrl_meta              <= 1'b0;
            ref_lock_ctrl                   <= 1'b0;
            monitor_sample_count_ctrl_meta  <= 32'd0;
            monitor_sample_count_ctrl       <= 32'd0;
            clip_counts_ctrl_meta           <= 256'd0;
            clip_counts_ctrl                <= 256'd0;
            mean_mags_ctrl_meta             <= 256'd0;
            mean_mags_ctrl                  <= 256'd0;
            spec_packet_count_ctrl_meta     <= 32'd0;
            spec_packet_count_ctrl          <= 32'd0;
            spec_udp_byte_count_ctrl_meta   <= 32'd0;
            spec_udp_byte_count_ctrl        <= 32'd0;
            time_packet_count_ctrl_meta     <= 32'd0;
            time_packet_count_ctrl          <= 32'd0;
            time_udp_byte_count_ctrl_meta   <= 32'd0;
            time_udp_byte_count_ctrl        <= 32'd0;
            time_dropped_count_ctrl_meta    <= 32'd0;
            time_dropped_count_ctrl         <= 32'd0;
            spec_seq_no_ctrl_meta           <= 32'd0;
            spec_seq_no_ctrl                <= 32'd0;
            time_seq_no_ctrl_meta           <= 32'd0;
            time_seq_no_ctrl                <= 32'd0;
            time_sample0_ctrl_meta          <= 64'd0;
            time_sample0_ctrl               <= 64'd0;
            time_frame_id_ctrl_meta         <= 64'd0;
            time_frame_id_ctrl              <= 64'd0;
            spec_frame_id_ctrl_meta         <= 64'd0;
            spec_frame_id_ctrl              <= 64'd0;
            spec_chan0_ctrl_meta            <= 32'd0;
            spec_chan0_ctrl                 <= 32'd0;
            pfb_status_ctrl_meta            <= 32'd0;
            pfb_status_ctrl                 <= 32'd0;
            pfb_frame_count_ctrl_meta       <= 32'd0;
            pfb_frame_count_ctrl            <= 32'd0;
            pfb_overflow_count_ctrl_meta    <= 32'd0;
            pfb_overflow_count_ctrl         <= 32'd0;
            pfb_peak_chan_ctrl_meta         <= 32'd0;
            pfb_peak_chan_ctrl              <= 32'd0;
            pfb_peak_power_ctrl_meta        <= 32'd0;
            pfb_peak_power_ctrl             <= 32'd0;
            rfdc_status_flags_ctrl_meta     <= 32'd0;
            rfdc_status_flags_ctrl          <= 32'd0;
            rfdc_sample_count_ctrl_meta     <= 64'd0;
            rfdc_sample_count_ctrl          <= 64'd0;
            rfdc_dropped_count_ctrl_meta    <= 32'd0;
            rfdc_dropped_count_ctrl         <= 32'd0;
            rfdc_current_valid_mask_ctrl_meta <= 16'd0;
            rfdc_current_valid_mask_ctrl      <= 16'd0;
            rfdc_seen_valid_mask_ctrl_meta    <= 16'd0;
            rfdc_seen_valid_mask_ctrl         <= 16'd0;
            tx_preflight_status_flags_ctrl_meta <= 32'd0;
            tx_preflight_status_flags_ctrl      <= 32'd0;
            tx_frame_built_count_ctrl_meta      <= 32'd0;
            tx_frame_built_count_ctrl           <= 32'd0;
            tx_route_dropped_count_ctrl_meta    <= 32'd0;
            tx_route_dropped_count_ctrl         <= 32'd0;
            tx_frame_byte_count_ctrl_meta       <= 32'd0;
            tx_frame_byte_count_ctrl            <= 32'd0;
            tx_route_miss_count_ctrl_meta       <= 32'd0;
            tx_route_miss_count_ctrl            <= 32'd0;
            tx_route_error_count_ctrl_meta      <= 32'd0;
            tx_route_error_count_ctrl           <= 32'd0;
            tx_cmac_test_packet_count_ctrl_meta <= 32'd0;
            tx_cmac_test_packet_count_ctrl      <= 32'd0;
            tx_cmac_test_byte_count_ctrl_meta   <= 32'd0;
            tx_cmac_test_byte_count_ctrl        <= 32'd0;
            tx_link_status_flags_ctrl_meta      <= 32'd0;
            tx_link_status_flags_ctrl           <= 32'd0;
            tx_selected_endpoint_id_ctrl_meta   <= 3'd0;
            tx_selected_endpoint_id_ctrl        <= 3'd0;
            tx_selected_route_id_ctrl_meta      <= 3'd0;
            tx_selected_route_id_ctrl           <= 3'd0;
            tx_selected_route_is_time_ctrl_meta <= 1'b0;
            tx_selected_route_is_time_ctrl      <= 1'b0;
            tx_spec_route_hit_counts_ctrl_meta  <= 256'd0;
            tx_spec_route_hit_counts_ctrl       <= 256'd0;
            tx_time_route_hit_counts_ctrl_meta  <= 256'd0;
            tx_time_route_hit_counts_ctrl       <= 256'd0;
        end else begin
            fsm_state_ctrl_meta             <= fsm_state;
            fsm_state_ctrl                  <= fsm_state_ctrl_meta;
            status_bits_ctrl_meta           <= {27'd0, waiting_for_epoch, sync_mode, streaming, armed};
            status_bits_ctrl                <= status_bits_ctrl_meta;
            pps_seen_ctrl_meta              <= pps_seen;
            pps_seen_ctrl                   <= pps_seen_ctrl_meta;
            ref_lock_ctrl_meta              <= ref_lock_in;
            ref_lock_ctrl                   <= ref_lock_ctrl_meta;
            monitor_sample_count_ctrl_meta  <= monitor_sample_count;
            monitor_sample_count_ctrl       <= monitor_sample_count_ctrl_meta;
            clip_counts_ctrl_meta           <= clip_counts;
            clip_counts_ctrl                <= clip_counts_ctrl_meta;
            mean_mags_ctrl_meta             <= mean_mags;
            mean_mags_ctrl                  <= mean_mags_ctrl_meta;
            spec_packet_count_ctrl_meta     <= spec_packet_count;
            spec_packet_count_ctrl          <= spec_packet_count_ctrl_meta;
            spec_udp_byte_count_ctrl_meta   <= spec_udp_byte_count;
            spec_udp_byte_count_ctrl        <= spec_udp_byte_count_ctrl_meta;
            time_packet_count_ctrl_meta     <= time_packet_count;
            time_packet_count_ctrl          <= time_packet_count_ctrl_meta;
            time_udp_byte_count_ctrl_meta   <= time_udp_byte_count;
            time_udp_byte_count_ctrl        <= time_udp_byte_count_ctrl_meta;
            time_dropped_count_ctrl_meta    <= time_dropped_count;
            time_dropped_count_ctrl         <= time_dropped_count_ctrl_meta;
            spec_seq_no_ctrl_meta           <= spec_seq_no;
            spec_seq_no_ctrl                <= spec_seq_no_ctrl_meta;
            time_seq_no_ctrl_meta           <= time_seq_no;
            time_seq_no_ctrl                <= time_seq_no_ctrl_meta;
            time_sample0_ctrl_meta          <= time_sample0;
            time_sample0_ctrl               <= time_sample0_ctrl_meta;
            time_frame_id_ctrl_meta         <= time_frame_id;
            time_frame_id_ctrl              <= time_frame_id_ctrl_meta;
            spec_frame_id_ctrl_meta         <= spec_frame_id;
            spec_frame_id_ctrl              <= spec_frame_id_ctrl_meta;
            spec_chan0_ctrl_meta            <= spec_chan0;
            spec_chan0_ctrl                 <= spec_chan0_ctrl_meta;
            pfb_status_ctrl_meta            <= pfb_status;
            pfb_status_ctrl                 <= pfb_status_ctrl_meta;
            pfb_frame_count_ctrl_meta       <= pfb_frame_count;
            pfb_frame_count_ctrl            <= pfb_frame_count_ctrl_meta;
            pfb_overflow_count_ctrl_meta    <= pfb_overflow_count;
            pfb_overflow_count_ctrl         <= pfb_overflow_count_ctrl_meta;
            pfb_peak_chan_ctrl_meta         <= pfb_peak_chan;
            pfb_peak_chan_ctrl              <= pfb_peak_chan_ctrl_meta;
            pfb_peak_power_ctrl_meta        <= pfb_peak_power;
            pfb_peak_power_ctrl             <= pfb_peak_power_ctrl_meta;
            rfdc_status_flags_ctrl_meta     <= rfdc_status_flags;
            rfdc_status_flags_ctrl          <= rfdc_status_flags_ctrl_meta;
            rfdc_sample_count_ctrl_meta     <= rfdc_sample_count;
            rfdc_sample_count_ctrl          <= rfdc_sample_count_ctrl_meta;
            rfdc_dropped_count_ctrl_meta    <= rfdc_dropped_count;
            rfdc_dropped_count_ctrl         <= rfdc_dropped_count_ctrl_meta;
            rfdc_current_valid_mask_ctrl_meta <= rfdc_current_valid_mask;
            rfdc_current_valid_mask_ctrl      <= rfdc_current_valid_mask_ctrl_meta;
            rfdc_seen_valid_mask_ctrl_meta    <= rfdc_seen_valid_mask;
            rfdc_seen_valid_mask_ctrl         <= rfdc_seen_valid_mask_ctrl_meta;
            tx_preflight_status_flags_ctrl_meta <= tx_preflight_status_flags;
            tx_preflight_status_flags_ctrl      <= tx_preflight_status_flags_ctrl_meta;
            tx_frame_built_count_ctrl_meta      <= tx_frame_built_count;
            tx_frame_built_count_ctrl           <= tx_frame_built_count_ctrl_meta;
            tx_route_dropped_count_ctrl_meta    <= tx_route_dropped_count;
            tx_route_dropped_count_ctrl         <= tx_route_dropped_count_ctrl_meta;
            tx_frame_byte_count_ctrl_meta       <= tx_frame_byte_count;
            tx_frame_byte_count_ctrl            <= tx_frame_byte_count_ctrl_meta;
            tx_route_miss_count_ctrl_meta       <= tx_route_miss_count;
            tx_route_miss_count_ctrl            <= tx_route_miss_count_ctrl_meta;
            tx_route_error_count_ctrl_meta      <= tx_route_error_count;
            tx_route_error_count_ctrl           <= tx_route_error_count_ctrl_meta;
            tx_cmac_test_packet_count_ctrl_meta <= tx_cmac_test_packet_count;
            tx_cmac_test_packet_count_ctrl      <= tx_cmac_test_packet_count_ctrl_meta;
            tx_cmac_test_byte_count_ctrl_meta   <= tx_cmac_test_byte_count;
            tx_cmac_test_byte_count_ctrl        <= tx_cmac_test_byte_count_ctrl_meta;
            tx_link_status_flags_ctrl_meta      <= tx_link_status_flags;
            tx_link_status_flags_ctrl           <= tx_link_status_flags_ctrl_meta;
            tx_selected_endpoint_id_ctrl_meta   <= tx_selected_endpoint_id;
            tx_selected_endpoint_id_ctrl        <= tx_selected_endpoint_id_ctrl_meta;
            tx_selected_route_id_ctrl_meta      <= tx_selected_route_id;
            tx_selected_route_id_ctrl           <= tx_selected_route_id_ctrl_meta;
            tx_selected_route_is_time_ctrl_meta <= tx_selected_route_is_time;
            tx_selected_route_is_time_ctrl      <= tx_selected_route_is_time_ctrl_meta;
            tx_spec_route_hit_counts_ctrl_meta  <= tx_spec_route_hit_counts;
            tx_spec_route_hit_counts_ctrl       <= tx_spec_route_hit_counts_ctrl_meta;
            tx_time_route_hit_counts_ctrl_meta  <= tx_time_route_hit_counts;
            tx_time_route_hit_counts_ctrl       <= tx_time_route_hit_counts_ctrl_meta;
        end
    end

    sync_fsm u_sync_fsm (
        .clk(clk),
        .rst_n(rst_n),
        .arm_req(arm_latched),
        .stop_req(stop_pulse),
        .soft_epoch_req(soft_epoch_pulse),
        .soft_reset_req(soft_reset_pulse),
        .sync_mode(sync_mode),
        .ref_locked(ref_lock_in),
        .rfdc_ready(rfdc_ready_in),
        .pps_in(pps_sync[1]),
        .sync_error(1'b0),
        .state(fsm_state),
        .armed(armed),
        .streaming(streaming),
        .waiting_for_epoch(waiting_for_epoch),
        .epoch_reset_pulse(epoch_reset_pulse)
    );

    science_rate_selector #(
        .NINPUT(8),
        .SUBSAMPLES_PER_BEAT(4),
        .SAMPLE_W(32),
        .USER_W(32),
        .SAMPLE0_W(64)
    ) u_science_rate_selector (
        .clk(clk),
        .rst_n(rst_n),
        .bandwidth_mode(science_bandwidth_mode),
        .s_axis_tdata(s_axis_adc_tdata),
        .s_axis_tuser(s_axis_adc_tuser),
        .s_axis_sample0(s_axis_adc_sample0),
        .s_axis_tvalid(s_axis_adc_tvalid),
        .s_axis_tlast(s_axis_adc_tlast),
        .s_axis_tready(s_axis_adc_tready),
        .m_axis_tdata(science_tdata),
        .m_axis_tuser(science_tuser),
        .m_axis_sample0(science_sample0),
        .m_axis_tvalid(science_tvalid),
        .m_axis_tlast(science_tlast),
        .m_axis_tready(science_tready),
        .output_beat_count(science_output_beat_count),
        .dropped_beat_count(science_dropped_beat_count)
    );

    monitor_counters u_monitor_counters (
        .clk(clk),
        .rst_n(rst_n),
        .clear(epoch_reset_pulse),
        .sample_valid(s_axis_adc_tvalid && s_axis_adc_tready),
        .sample_tdata(s_axis_adc_tdata[255:0]),
        .sample_count(monitor_sample_count),
        .clip_counts(clip_counts),
        .mean_mags(mean_mags)
    );

    fft_debug_observer u_fft_debug_observer (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .streaming(streaming),
        .active_port_mask(rfdc_active_mask),
        .s_axis_adc_tdata(s_axis_adc_tdata[255:0]),
        .s_axis_adc_tvalid(s_axis_adc_tvalid && s_axis_adc_tready),
        .ctrl_capture_start_pulse(ctrl_debug_capture_start_pulse),
        .ctrl_capture_clear_pulse(ctrl_debug_capture_clear_pulse),
        .ctrl_time_rd_addr(ctrl_debug_time_rd_addr),
        .ctrl_fft_rd_addr(ctrl_debug_fft_rd_addr),
        .ctrl_time_rd_data(debug_time_rd_data_ctrl),
        .ctrl_fft_rd_data(debug_fft_rd_data_ctrl),
        .ctrl_busy(debug_busy_ctrl),
        .ctrl_done(debug_done_ctrl),
        .ctrl_error(debug_error_ctrl),
        .ctrl_capture_count(debug_capture_count_ctrl),
        .ctrl_peak_bin(debug_peak_bin_ctrl),
        .ctrl_peak_power(debug_peak_power_ctrl)
    );

    multi_preview_observer u_multi_preview_observer (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .streaming(streaming),
        .input_mask(ctrl_preview_input_mask),
        .s_axis_adc_tdata0(s_axis_preview_tdata0),
        .s_axis_adc_tdata1(s_axis_preview_tdata1),
        .s_axis_adc_tdata2(s_axis_preview_tdata2),
        .s_axis_adc_tdata3(s_axis_preview_tdata3),
        .s_axis_adc_sample0(s_axis_preview_sample0),
        .s_axis_adc_tvalid(s_axis_preview_tvalid),
        .audit_source_select(ctrl_preview_audit_source_select),
        .audit_event_enable(ctrl_preview_audit_event_enable),
        .audit_freeze_on_event(ctrl_preview_audit_freeze_on_event),
        .audit_clear_pulse(ctrl_preview_audit_clear_pulse),
        .audit_event_threshold(ctrl_preview_audit_event_threshold),
        .rfdc_status_flags(rfdc_status_flags),
        .dac_phase_epoch_ctrl(ctrl_dac_phase_epoch),
        .ctrl_capture_start_pulse(ctrl_preview_capture_start_pulse),
        .ctrl_capture_clear_pulse(ctrl_preview_capture_clear_pulse),
        .ctrl_rd_input(ctrl_preview_rd_input),
        .ctrl_rd_addr(ctrl_preview_rd_addr),
        .ctrl_event_rd_addr(ctrl_preview_event_rd_addr),
        .ctrl_rd_data(preview_rd_data_ctrl),
        .ctrl_event_rd_data(preview_event_rd_data_ctrl),
        .ctrl_busy(preview_busy_ctrl),
        .ctrl_done(preview_done_ctrl),
        .ctrl_error(preview_error_ctrl),
        .ctrl_capture_count(preview_capture_count_ctrl),
        .ctrl_sample0(preview_sample0_ctrl),
        .ctrl_audit_status(preview_audit_status_ctrl),
        .ctrl_audit_start_count(preview_audit_start_count_ctrl),
        .ctrl_audit_first_count(preview_audit_first_count_ctrl),
        .ctrl_audit_done_count(preview_audit_done_count_ctrl),
        .ctrl_audit_start_sample0(preview_audit_start_sample0_ctrl),
        .ctrl_audit_first_sample0(preview_audit_first_sample0_ctrl),
        .ctrl_audit_done_sample0(preview_audit_done_sample0_ctrl),
        .ctrl_audit_start_to_first_latency(preview_audit_start_to_first_latency_ctrl),
        .ctrl_audit_capture_beats(preview_audit_capture_beats_ctrl),
        .ctrl_audit_valid_gap_count(preview_audit_valid_gap_count_ctrl),
        .ctrl_audit_sample0_error_count(preview_audit_sample0_error_count_ctrl),
        .ctrl_event_sample0(preview_event_sample0_ctrl),
        .ctrl_event_max_code(preview_event_max_code_ctrl),
        .ctrl_event_info(preview_event_info_ctrl),
        .ctrl_event_rfdc_flags(preview_event_rfdc_flags_ctrl),
        .ctrl_event_dac_phase_epoch(preview_event_dac_phase_epoch_ctrl)
    );

    rfdc_axis_raw_witness_capture #(
        .CAPTURE_BEATS(256)
    ) u_rfdc_axis_raw_witness_capture (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(ctrl_rfdc_axis_raw_witness_arm_pulse),
        .clear_pulse_ctrl(ctrl_rfdc_axis_raw_witness_clear_pulse),
        .channel_select_ctrl(ctrl_rfdc_axis_raw_witness_channel_select),
        .capture_beats_ctrl(ctrl_rfdc_axis_raw_witness_capture_beats),
        .s_axis_adc_tdata0(s_axis_preview_tdata0),
        .s_axis_adc_tdata1(s_axis_preview_tdata1),
        .s_axis_adc_tdata2(s_axis_preview_tdata2),
        .s_axis_adc_tdata3(s_axis_preview_tdata3),
        .s_axis_adc_sample0(s_axis_preview_sample0),
        .s_axis_adc_tvalid(s_axis_preview_tvalid),
        .rfdc_status_flags(rfdc_status_flags),
        .rfdc_current_valid_mask(rfdc_current_valid_mask),
        .ctrl_rd_word(ctrl_rfdc_axis_raw_witness_rd_word),
        .ctrl_rd_data(rfdc_axis_raw_witness_rd_data_ctrl),
        .ctrl_armed(rfdc_axis_raw_witness_armed_ctrl),
        .ctrl_valid(rfdc_axis_raw_witness_valid_ctrl),
        .ctrl_capturing(rfdc_axis_raw_witness_capturing_ctrl),
        .ctrl_overflow(rfdc_axis_raw_witness_overflow_ctrl),
        .ctrl_tvalid_seen(rfdc_axis_raw_witness_tvalid_seen_ctrl),
        .ctrl_beat_count(rfdc_axis_raw_witness_beat_count_ctrl),
        .ctrl_channel_select(rfdc_axis_raw_witness_channel_select_ctrl),
        .ctrl_sample0(rfdc_axis_raw_witness_sample0_ctrl),
        .ctrl_rfdc_flags(rfdc_axis_raw_witness_rfdc_flags_ctrl),
        .ctrl_valid_mask(rfdc_axis_raw_witness_valid_mask_ctrl)
    );

    axis_stream_duplicator #(
        .DATA_W(SCIENCE_DATA_W),
        .USER_W(32),
        .SAMPLE0_W(64)
    ) u_axis_stream_duplicator (
        .clk(clk),
        .rst_n(rst_n),
        .spec_enable(spec_enable),
        .time_enable(time_enable),
        .snapshot_enable(snapshot_enable),
        .monitor_enable(monitor_enable),
        .time_drop_when_full(1'b1),
        .snapshot_drop_when_full(1'b1),
        .monitor_drop_when_full(1'b1),
        .s_axis_tdata(science_tdata),
        .s_axis_tuser(science_tuser),
        .s_axis_sample0(science_sample0),
        .s_axis_tvalid(science_tvalid),
        .s_axis_tlast(science_tlast),
        .s_axis_tready(science_tready),
        .m_spec_tdata(spec_tdata),
        .m_spec_tuser(spec_tuser),
        .m_spec_sample0(spec_sample0),
        .m_spec_tvalid(spec_tvalid),
        .m_spec_tlast(spec_tlast),
        .m_spec_tready(spec_tready),
        .m_time_tdata(time_tdata),
        .m_time_tuser(time_tuser),
        .m_time_sample0(time_sample0_sideband),
        .m_time_tvalid(time_tvalid),
        .m_time_tlast(time_tlast),
        .m_time_tready(time_tready),
        .m_snapshot_tdata(snapshot_tdata),
        .m_snapshot_tuser(snapshot_tuser),
        .m_snapshot_sample0(snapshot_sample0),
        .m_snapshot_tvalid(snapshot_tvalid),
        .m_snapshot_tlast(snapshot_tlast),
        .m_snapshot_tready(snapshot_tready),
        .m_monitor_tdata(monitor_tdata),
        .m_monitor_tuser(monitor_tuser),
        .m_monitor_sample0(monitor_sample0),
        .m_monitor_tvalid(monitor_tvalid),
        .m_monitor_tlast(monitor_tlast),
        .m_monitor_tready(monitor_tready),
        .dropped_time_count(time_dropped_count),
        .dropped_snapshot_count(),
        .dropped_monitor_count()
    );

    requantizer #(
        .DATA_W(SCIENCE_DATA_W),
        .LANE_W(16)
    ) u_requantizer (
        .in_tdata(spec_tdata),
        .in_tvalid(spec_tvalid),
        .quant_mode(quant_mode),
        .out_tdata(quant_spec_tdata),
        .clip_any(quant_clip_any)
    );

    pfb_channelizer #(
        .DATA_W(SCIENCE_DATA_W),
        .NINPUT(8),
        .NCHAN(4096)
    ) u_pfb_channelizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable(spec_enable && pfb_enable_sync[1]),
        .clear(packet_stream_reset_pulse || pfb_clear_pulse),
        .cfg_taps(pfb_taps),
        .cfg_fft_shift(pfb_fft_shift),
        .cfg_chan0(pfb_chan0),
        .cfg_chan_count(pfb_chan_count),
        .cfg_time_count(pfb_time_count),
        .s_axis_tdata(quant_spec_tdata),
        .s_axis_sample0(spec_input_sample0),
        .s_axis_tvalid(spec_tvalid),
        .s_axis_tready(spec_tready),
        .m_axis_tdata(pfb_spec_tdata),
        .m_axis_sample0(pfb_spec_sample0),
        .m_axis_tvalid(pfb_spec_tvalid),
        .m_axis_tready(pfb_spec_tready),
        .status(pfb_status),
        .frame_count(pfb_frame_count),
        .overflow_count(pfb_overflow_count),
        .peak_chan(pfb_peak_chan),
        .peak_power(pfb_peak_power),
        .packet_chan0(pfb_packet_chan0),
        .packet_chan_count(pfb_packet_chan_count),
        .packet_time_count(pfb_packet_time_count)
    );

    spectral_packetizer #(
        .DATA_W(SCIENCE_DATA_W),
        .OUT_W(64),
        .HEADER_WORDS(16)
    ) u_spectral_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable(spec_enable),
        .stream_reset(packet_stream_reset_pulse),
        .board_id(board_id),
        .global_input0({board_id[12:0], 3'b000}),
        .epoch_mode(udp_epoch_mode),
        .packet_flags(udp_packet_flags),
        .unix_seconds(unix_seconds),
        .pps_count(pps_count),
        .quant_mode(quant_mode),
        .scale_mode(scale_mode),
        .scale_id(scale_id),
        .spec_chan0(pfb_packet_chan0),
        .spec_time_count(pfb_packet_time_count),
        .spec_chan_count(pfb_packet_chan_count),
        .chan_split(chan_split),
        .s_axis_tdata(pfb_spec_tdata),
        .s_axis_sample0(pfb_spec_sample0),
        .s_axis_tvalid(pfb_spec_tvalid),
        .s_axis_tready(pfb_spec_tready),
        .m_axis_tdata(spec_axis_tdata),
        .m_axis_tkeep(spec_axis_tkeep),
        .m_axis_tvalid(spec_axis_tvalid),
        .m_axis_tlast(spec_axis_tlast),
        .m_axis_tready(spec_axis_tready),
        .packet_count(spec_packet_count),
        .udp_byte_count(spec_udp_byte_count),
        .seq_no_debug(spec_seq_no),
        .frame_id_debug(spec_frame_id),
        .chan0_debug(spec_chan0)
    );

    time_packetizer #(
        .DATA_W(SCIENCE_DATA_W),
        .OUT_W(64),
        .HEADER_WORDS(16)
    ) u_time_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable(time_enable),
        .stream_reset(packet_stream_reset_pulse),
        .board_id(board_id),
        .global_input0({board_id[12:0], 3'b000}),
        .epoch_mode(udp_epoch_mode),
        .packet_flags(udp_packet_flags),
        .unix_seconds(unix_seconds),
        .pps_count(pps_count),
        .quant_mode(quant_mode),
        .scale_mode(scale_mode),
        .scale_id(scale_id),
        .time_payload_nsamp(time_payload_nsamp),
        .s_axis_tdata(time_tdata),
        .s_axis_sample0(time_input_sample0),
        .s_axis_tvalid(time_tvalid),
        .s_axis_tready(time_tready),
        .m_axis_tdata(time_axis_tdata),
        .m_axis_tkeep(time_axis_tkeep),
        .m_axis_tvalid(time_axis_tvalid),
        .m_axis_tlast(time_axis_tlast),
        .m_axis_tready(time_axis_tready),
        .packet_count(time_packet_count),
        .dropped_count(),
        .udp_byte_count(time_udp_byte_count),
        .seq_no_debug(time_seq_no),
        .sample0_debug(time_sample0),
        .frame_id_debug(time_frame_id)
    );

    assign snapshot_tready = 1'b1;
    assign monitor_tready  = 1'b1;

    udp_tx_arbiter u_udp_tx_arbiter (
        .clk(clk),
        .rst_n(rst_n),
        .clear(packet_stream_reset_pulse),
        .s_spec_tdata(spec_axis_tdata),
        .s_spec_tkeep(spec_axis_tkeep),
        .s_spec_tvalid(spec_axis_tvalid),
        .s_spec_tlast(spec_axis_tlast),
        .s_spec_tready(spec_axis_tready),
        .s_time_tdata(time_axis_tdata),
        .s_time_tkeep(time_axis_tkeep),
        .s_time_tvalid(time_axis_tvalid),
        .s_time_tlast(time_axis_tlast),
        .s_time_tready(time_axis_tready),
        .s_snapshot_tdata(64'd0),
        .s_snapshot_tkeep(8'h00),
        .s_snapshot_tvalid(1'b0),
        .s_snapshot_tlast(1'b0),
        .s_snapshot_tready(),
        .s_monitor_tdata(64'd0),
        .s_monitor_tkeep(8'h00),
        .s_monitor_tvalid(1'b0),
        .s_monitor_tlast(1'b0),
        .s_monitor_tready(),
        .m_axis_tdata(arb_tx_tdata),
        .m_axis_tkeep(arb_tx_tkeep),
        .m_axis_tvalid(arb_tx_tvalid),
        .m_axis_tlast(arb_tx_tlast),
        .m_axis_tready(arb_tx_tready)
    );

    axis_packet_fifo #(
        .DATA_W(64),
        .DEPTH(4096),
        .COUNT_W(13)
    ) u_axis_packet_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .clear(packet_stream_reset_pulse),
        .s_axis_tdata(arb_tx_tdata),
        .s_axis_tkeep(arb_tx_tkeep),
        .s_axis_tvalid(arb_tx_tvalid),
        .s_axis_tlast(arb_tx_tlast),
        .s_axis_tready(arb_tx_tready),
        .m_axis_tdata(internal_tx_tdata),
        .m_axis_tkeep(internal_tx_tkeep),
        .m_axis_tvalid(internal_tx_tvalid),
        .m_axis_tlast(internal_tx_tlast),
        .m_axis_tready(internal_tx_tready),
        .level_words(tx_fifo_level_words),
        .high_water_words(tx_fifo_high_water_words),
        .backpressure_cycles(tx_fifo_backpressure_cycles)
    );

    tx_header_capture #(
        .DATA_W(64),
        .HEADER_WORDS(16)
    ) u_tx_header_capture (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(ctrl_tx_header_capture_arm_pulse),
        .s_axis_tdata(internal_tx_tdata),
        .s_axis_tvalid(internal_tx_tvalid),
        .s_axis_tlast(internal_tx_tlast),
        .s_axis_tready(internal_tx_tready),
        .ctrl_rd_word(ctrl_tx_header_capture_rd_word),
        .ctrl_rd_data(tx_header_capture_rd_data_ctrl),
        .ctrl_armed(tx_header_capture_armed_ctrl),
        .ctrl_valid(tx_header_capture_valid_ctrl),
        .ctrl_word_count(tx_header_capture_word_count_ctrl)
    );

    tx_route_selector #(
        .DATA_W(64),
        .N_ENDPOINTS(8),
        .N_SPEC_ROUTES(8),
        .N_TIME_ROUTES(8),
        .HEADER_WORDS(16)
    ) u_tx_route_selector (
        .clk(clk),
        .rst_n(rst_n),
        .enable(tx_control[2]),
        .clear(packet_stream_reset_pulse),
        .drop_on_route_miss(tx_control[3]),
        .time_input_mask({8'd0, rfdc_active_mask[7:0]}),
        .endpoint_enable(tx_endpoint_enable),
        .endpoint_ip_vec(tx_endpoint_ip_vec),
        .endpoint_mac_vec(tx_endpoint_mac_vec),
        .endpoint_src_port_vec(tx_endpoint_src_port_vec),
        .endpoint_dst_port_vec(tx_endpoint_dst_port_vec),
        .spec_route_enable(tx_spec_route_enable),
        .spec_route_chan0_vec(tx_spec_route_chan0_vec),
        .spec_route_chan_count_vec(tx_spec_route_chan_count_vec),
        .spec_route_endpoint_vec(tx_spec_route_endpoint_vec),
        .time_route_enable(tx_time_route_enable),
        .time_route_input_mask_vec(tx_time_route_input_mask_vec),
        .time_route_endpoint_vec(tx_time_route_endpoint_vec),
        .s_axis_tdata(internal_tx_tdata),
        .s_axis_tkeep(internal_tx_tkeep),
        .s_axis_tvalid(internal_tx_tvalid),
        .s_axis_tlast(internal_tx_tlast),
        .s_axis_tready(internal_tx_tready),
        .m_axis_tdata(routed_tx_tdata),
        .m_axis_tkeep(routed_tx_tkeep),
        .m_axis_tvalid(routed_tx_tvalid),
        .m_axis_tlast(routed_tx_tlast),
        .m_axis_tready(routed_tx_tready),
        .m_dst_mac(routed_dst_mac),
        .m_dst_ip(routed_dst_ip),
        .m_src_udp_port(routed_src_udp_port),
        .m_dst_udp_port(routed_dst_udp_port),
        .m_t510_payload_bytes(routed_t510_payload_bytes),
        .m_stream_type(routed_stream_type),
        .m_endpoint_id(routed_endpoint_id),
        .m_route_id(routed_route_id),
        .m_route_is_time(routed_route_is_time),
        .frame_forwarded_count(tx_route_forwarded_count),
        .frame_dropped_count(tx_route_dropped_count),
        .route_miss_count(tx_route_miss_count),
        .route_error_count(tx_route_error_count),
        .selected_endpoint_id(tx_selected_endpoint_id),
        .selected_route_id(tx_selected_route_id),
        .selected_route_is_time(tx_selected_route_is_time),
        .spec_route_hit_count_vec(tx_spec_route_hit_counts),
        .time_route_hit_count_vec(tx_time_route_hit_counts)
    );

    tx_payload_witness_capture #(
        .DATA_W(64),
        .CAPTURE_WORDS(1056)
    ) u_tx_payload_witness_capture (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(ctrl_tx_payload_witness_arm_pulse),
        .clear_pulse_ctrl(ctrl_tx_payload_witness_clear_pulse),
        .data_clear_pulse(packet_stream_reset_pulse),
        .stream_filter_ctrl(ctrl_tx_payload_witness_stream_filter),
        .capture_words_ctrl(ctrl_tx_payload_witness_capture_words),
        .s_axis_tdata(routed_tx_tdata),
        .s_axis_tvalid(routed_tx_tvalid),
        .s_axis_tlast(routed_tx_tlast),
        .s_axis_tready(routed_tx_tready),
        .route_endpoint_id(routed_endpoint_id),
        .route_id(routed_route_id),
        .route_is_time(routed_route_is_time),
        .rfdc_status_flags(rfdc_status_flags),
        .rfdc_sample_count(rfdc_sample_count),
        .dac_phase_epoch(dac_phase_epoch_data),
        .ctrl_rd_word(ctrl_tx_payload_witness_rd_word),
        .ctrl_rd_data(tx_payload_witness_rd_data_ctrl),
        .ctrl_armed(tx_payload_witness_armed_ctrl),
        .ctrl_valid(tx_payload_witness_valid_ctrl),
        .ctrl_capturing(tx_payload_witness_capturing_ctrl),
        .ctrl_word_count(tx_payload_witness_word_count_ctrl),
        .ctrl_stream_type(tx_payload_witness_stream_type_ctrl),
        .ctrl_sample0(tx_payload_witness_sample0_ctrl),
        .ctrl_frame_id(tx_payload_witness_frame_id_ctrl),
        .ctrl_seq_no(tx_payload_witness_seq_no_ctrl),
        .ctrl_chan0(tx_payload_witness_chan0_ctrl),
        .ctrl_layout_word(tx_payload_witness_layout_word_ctrl),
        .ctrl_payload_bytes(tx_payload_witness_payload_bytes_ctrl),
        .ctrl_route_meta(tx_payload_witness_route_meta_ctrl),
        .ctrl_rfdc_flags(tx_payload_witness_rfdc_flags_ctrl),
        .ctrl_rfdc_sample_count(tx_payload_witness_rfdc_sample_count_ctrl),
        .ctrl_dac_phase_epoch(tx_payload_witness_dac_phase_epoch_ctrl),
        .ctrl_overflow(tx_payload_witness_overflow_ctrl),
        .ctrl_filter_mismatch(tx_payload_witness_filter_mismatch_ctrl)
    );

    udp_frame_builder #(
        .DATA_W(64)
    ) u_udp_frame_builder (
        .clk(clk),
        .rst_n(rst_n),
        .enable(tx_control[2]),
        .clear(packet_stream_reset_pulse),
        .src_mac(src_mac),
        .src_ip(src_ip),
        .s_dst_mac(routed_dst_mac),
        .s_dst_ip(routed_dst_ip),
        .s_src_udp_port(routed_src_udp_port),
        .s_dst_udp_port(routed_dst_udp_port),
        .s_t510_payload_bytes(routed_t510_payload_bytes),
        .s_axis_tdata(routed_tx_tdata),
        .s_axis_tkeep(routed_tx_tkeep),
        .s_axis_tvalid(routed_tx_tvalid),
        .s_axis_tlast(routed_tx_tlast),
        .s_axis_tready(routed_tx_tready),
        .m_axis_tdata(m_axis_tx_tdata),
        .m_axis_tkeep(m_axis_tx_tkeep),
        .m_axis_tvalid(m_axis_tx_tvalid),
        .m_axis_tlast(m_axis_tx_tlast),
        .m_axis_tready(m_axis_tx_tready),
        .frame_built_count(tx_frame_built_count),
        .frame_byte_count(tx_frame_byte_count)
    );

    t510_qsfp_test_frame_gen u_qsfp_test_frame_gen (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .enable(tx_qsfp_test_enable),
        .clear(tx_clear_pulse_cmac),
        .interval_cycles(tx_qsfp_test_interval_cmac),
        .src_mac(src_mac_cmac),
        .src_ip(src_ip_cmac),
        .dst_mac(tx_qsfp_test_dst_mac_cmac),
        .dst_ip(tx_qsfp_test_dst_ip_cmac),
        .src_udp_port(tx_qsfp_test_src_port_cmac),
        .dst_udp_port(tx_qsfp_test_dst_port_cmac),
        .core_version(32'h0001_001A),
        .board_id(ctrl_board_id_cmac),
        .status_flags(tx_link_status_flags_cmac),
        .sample_count(rfdc_sample_count_cmac),
        .m_axis_tdata(cmac_tx_axis_tdata),
        .m_axis_tkeep(cmac_tx_axis_tkeep),
        .m_axis_tvalid(cmac_tx_axis_tvalid),
        .m_axis_tlast(cmac_tx_axis_tlast),
        .m_axis_tready(cmac_tx_axis_tready),
        .packet_count(tx_cmac_test_packet_count),
        .byte_count(tx_cmac_test_byte_count)
    );

    tx_header_capture #(
        .DATA_W(64),
        .HEADER_WORDS(16)
    ) u_tx_frame_header_capture (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(ctrl_tx_frame_capture_arm_pulse),
        .s_axis_tdata(m_axis_tx_tdata),
        .s_axis_tvalid(m_axis_tx_tvalid),
        .s_axis_tlast(m_axis_tx_tlast),
        .s_axis_tready(m_axis_tx_tready),
        .ctrl_rd_word(ctrl_tx_frame_capture_rd_word),
        .ctrl_rd_data(tx_frame_capture_rd_data_ctrl),
        .ctrl_armed(tx_frame_capture_armed_ctrl),
        .ctrl_valid(tx_frame_capture_valid_ctrl),
        .ctrl_word_count(tx_frame_capture_word_count_ctrl)
    );

    feng_ctrl_axi u_feng_ctrl_axi (
        .s_axi_aclk(ctrl_clk),
        .s_axi_aresetn(ctrl_rst_n),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .fsm_state(fsm_state_ctrl),
        .streaming(status_bits_ctrl[1]),
        .armed(status_bits_ctrl[0]),
        .active_sync_mode(status_bits_ctrl[3:2]),
        .waiting_for_epoch(status_bits_ctrl[4]),
        .pps_seen(pps_seen_ctrl),
        .pps_count(pps_count),
        .ref_locked(ref_lock_ctrl),
        .error_flags(error_flags),
        .monitor_sample_count(monitor_sample_count_ctrl),
        .clip_counts(clip_counts_ctrl),
        .mean_mags(mean_mags_ctrl),
        .spec_packet_count(spec_packet_count_ctrl),
        .spec_udp_byte_count(spec_udp_byte_count_ctrl),
        .time_packet_count(time_packet_count_ctrl),
        .time_udp_byte_count(time_udp_byte_count_ctrl),
        .time_dropped_count(time_dropped_count_ctrl),
        .spec_seq_no(spec_seq_no_ctrl),
        .time_seq_no(time_seq_no_ctrl),
        .time_sample0(time_sample0_ctrl),
        .time_frame_id(time_frame_id_ctrl),
        .spec_frame_id(spec_frame_id_ctrl),
        .spec_chan0(spec_chan0_ctrl),
        .rfdc_status_flags(rfdc_status_flags_ctrl),
        .rfdc_sample_count(rfdc_sample_count_ctrl),
        .rfdc_dropped_count(rfdc_dropped_count_ctrl),
        .rfdc_current_valid_mask(rfdc_current_valid_mask_ctrl),
        .rfdc_seen_valid_mask(rfdc_seen_valid_mask_ctrl),
        .tx_link_status_flags(tx_link_status_flags_ctrl),
        .tx_dry_run_packet_count(tx_count_packet_status),
        .tx_dry_run_byte_count(tx_count_byte_status),
        .tx_fifo_level_words(tx_fifo_level_words),
        .tx_fifo_high_water_words(tx_fifo_high_water_words),
        .tx_fifo_backpressure_cycles(tx_fifo_backpressure_cycles),
        .tx_preflight_status_flags(tx_preflight_status_flags_ctrl),
        .tx_frame_built_count(tx_frame_built_count_ctrl),
        .tx_frame_sent_count(tx_count_packet_status),
        .tx_frame_dropped_count(tx_route_dropped_count_ctrl),
        .tx_frame_byte_count(tx_frame_byte_count_ctrl),
        .tx_route_miss_count(tx_route_miss_count_ctrl),
        .tx_route_error_count(tx_route_error_count_ctrl),
        .tx_selected_endpoint_id(tx_selected_endpoint_id_ctrl),
        .tx_selected_route_id(tx_selected_route_id_ctrl),
        .tx_selected_route_is_time(tx_selected_route_is_time_ctrl),
        .tx_header_capture_armed(tx_header_capture_armed_ctrl),
        .tx_header_capture_valid(tx_header_capture_valid_ctrl),
        .tx_header_capture_word_count(tx_header_capture_word_count_ctrl),
        .tx_header_capture_rd_data(tx_header_capture_rd_data_ctrl),
        .tx_frame_capture_armed(tx_frame_capture_armed_ctrl),
        .tx_frame_capture_valid(tx_frame_capture_valid_ctrl),
        .tx_frame_capture_word_count(tx_frame_capture_word_count_ctrl),
        .tx_frame_capture_rd_data(tx_frame_capture_rd_data_ctrl),
        .tx_payload_witness_armed(tx_payload_witness_armed_ctrl),
        .tx_payload_witness_valid(tx_payload_witness_valid_ctrl),
        .tx_payload_witness_capturing(tx_payload_witness_capturing_ctrl),
        .tx_payload_witness_word_count(tx_payload_witness_word_count_ctrl),
        .tx_payload_witness_stream_type(tx_payload_witness_stream_type_ctrl),
        .tx_payload_witness_sample0(tx_payload_witness_sample0_ctrl),
        .tx_payload_witness_frame_id(tx_payload_witness_frame_id_ctrl),
        .tx_payload_witness_seq_no(tx_payload_witness_seq_no_ctrl),
        .tx_payload_witness_chan0(tx_payload_witness_chan0_ctrl),
        .tx_payload_witness_layout_word(tx_payload_witness_layout_word_ctrl),
        .tx_payload_witness_payload_bytes(tx_payload_witness_payload_bytes_ctrl),
        .tx_payload_witness_route_meta(tx_payload_witness_route_meta_ctrl),
        .tx_payload_witness_rfdc_flags(tx_payload_witness_rfdc_flags_ctrl),
        .tx_payload_witness_rfdc_sample_count(tx_payload_witness_rfdc_sample_count_ctrl),
        .tx_payload_witness_dac_phase_epoch(tx_payload_witness_dac_phase_epoch_ctrl),
        .tx_payload_witness_overflow(tx_payload_witness_overflow_ctrl),
        .tx_payload_witness_filter_mismatch(tx_payload_witness_filter_mismatch_ctrl),
        .tx_payload_witness_rd_data(tx_payload_witness_rd_data_ctrl),
        .dac_tx_witness_armed(dac_tx_witness_armed),
        .dac_tx_witness_valid(dac_tx_witness_valid),
        .dac_tx_witness_capturing(dac_tx_witness_capturing),
        .dac_tx_witness_overflow(dac_tx_witness_overflow),
        .dac_tx_witness_tvalid_seen(dac_tx_witness_tvalid_seen),
        .dac_tx_witness_tready_seen(dac_tx_witness_tready_seen),
        .dac_tx_witness_ready_gap_seen(dac_tx_witness_ready_gap_seen),
        .dac_tx_witness_word_count(dac_tx_witness_word_count),
        .dac_tx_witness_phase_epoch(dac_tx_witness_phase_epoch),
        .dac_tx_witness_phase_acc(dac_tx_witness_phase_acc),
        .dac_tx_witness_phase_step(dac_tx_witness_phase_step),
        .dac_tx_witness_phase0(dac_tx_witness_phase0),
        .dac_tx_witness_mode(dac_tx_witness_mode),
        .dac_tx_witness_ready_gap_count(dac_tx_witness_ready_gap_count),
        .dac_tx_witness_rd_data(dac_tx_witness_rd_data),
        .rfdc_axis_raw_witness_armed(rfdc_axis_raw_witness_armed_ctrl),
        .rfdc_axis_raw_witness_valid(rfdc_axis_raw_witness_valid_ctrl),
        .rfdc_axis_raw_witness_capturing(rfdc_axis_raw_witness_capturing_ctrl),
        .rfdc_axis_raw_witness_overflow(rfdc_axis_raw_witness_overflow_ctrl),
        .rfdc_axis_raw_witness_tvalid_seen(rfdc_axis_raw_witness_tvalid_seen_ctrl),
        .rfdc_axis_raw_witness_beat_count(rfdc_axis_raw_witness_beat_count_ctrl),
        .rfdc_axis_raw_witness_channel_select(rfdc_axis_raw_witness_channel_select_ctrl),
        .rfdc_axis_raw_witness_sample0(rfdc_axis_raw_witness_sample0_ctrl),
        .rfdc_axis_raw_witness_rfdc_flags(rfdc_axis_raw_witness_rfdc_flags_ctrl),
        .rfdc_axis_raw_witness_valid_mask(rfdc_axis_raw_witness_valid_mask_ctrl),
        .rfdc_axis_raw_witness_rd_data(rfdc_axis_raw_witness_rd_data_ctrl),
        .tx_spec_route_hit_counts(tx_spec_route_hit_counts_ctrl),
        .tx_time_route_hit_counts(tx_time_route_hit_counts_ctrl),
        .pfb_status(pfb_status_ctrl),
        .pfb_frame_count(pfb_frame_count_ctrl),
        .pfb_overflow_count(pfb_overflow_count_ctrl),
        .pfb_peak_chan(pfb_peak_chan_ctrl),
        .pfb_peak_power(pfb_peak_power_ctrl),
        .debug_busy(debug_busy_ctrl),
        .debug_done(debug_done_ctrl),
        .debug_error(debug_error_ctrl),
        .debug_capture_count(debug_capture_count_ctrl),
        .debug_peak_bin(debug_peak_bin_ctrl),
        .debug_peak_power(debug_peak_power_ctrl),
        .debug_time_rd_data(debug_time_rd_data_ctrl),
        .debug_fft_rd_data(debug_fft_rd_data_ctrl),
        .preview_busy(preview_busy_ctrl),
        .preview_done(preview_done_ctrl),
        .preview_error(preview_error_ctrl),
        .preview_capture_count(preview_capture_count_ctrl),
        .preview_sample0(preview_sample0_ctrl),
        .preview_rd_data(preview_rd_data_ctrl),
        .preview_event_rd_data(preview_event_rd_data_ctrl),
        .preview_audit_status(preview_audit_status_ctrl),
        .preview_audit_start_count(preview_audit_start_count_ctrl),
        .preview_audit_first_count(preview_audit_first_count_ctrl),
        .preview_audit_done_count(preview_audit_done_count_ctrl),
        .preview_audit_start_sample0(preview_audit_start_sample0_ctrl),
        .preview_audit_first_sample0(preview_audit_first_sample0_ctrl),
        .preview_audit_done_sample0(preview_audit_done_sample0_ctrl),
        .preview_audit_start_to_first_latency(preview_audit_start_to_first_latency_ctrl),
        .preview_audit_capture_beats(preview_audit_capture_beats_ctrl),
        .preview_audit_valid_gap_count(preview_audit_valid_gap_count_ctrl),
        .preview_audit_sample0_error_count(preview_audit_sample0_error_count_ctrl),
        .preview_event_sample0(preview_event_sample0_ctrl),
        .preview_event_max_code(preview_event_max_code_ctrl),
        .preview_event_info(preview_event_info_ctrl),
        .preview_event_rfdc_flags(preview_event_rfdc_flags_ctrl),
        .preview_event_dac_phase_epoch(preview_event_dac_phase_epoch_ctrl),
        .dac_audit_phase_epoch_seen(dac_audit_phase_epoch_seen),
        .dac_audit_ch0_phase_acc(dac_audit_ch0_phase_acc),
        .dac_audit_ch0_phase_step(dac_audit_ch0_phase_step),
        .dac_audit_ch0_phase0(dac_audit_ch0_phase0),
        .dac_audit_ch0_mode(dac_audit_ch0_mode),
        .board_id(ctrl_board_id),
        .mode(ctrl_mode),
        .arm_latched(ctrl_arm_latched),
        .soft_epoch_pulse(ctrl_soft_epoch_pulse),
        .stop_pulse(ctrl_stop_pulse),
        .soft_reset_pulse(ctrl_soft_reset_pulse),
        .sync_mode(ctrl_sync_mode),
        .clock_ref(ctrl_clock_ref),
        .sample_rate_hz(ctrl_sample_rate_hz),
        .quant_mode(ctrl_quant_mode),
        .scale_mode(ctrl_scale_mode),
        .scale_id(ctrl_scale_id),
        .time_payload_nsamp(ctrl_time_payload_nsamp),
        .spec_time_count(ctrl_spec_time_count),
        .spec_chan_count(ctrl_spec_chan_count),
        .pfb_enable(ctrl_pfb_enable),
        .pfb_clear_pulse(ctrl_pfb_clear_pulse),
        .pfb_taps(ctrl_pfb_taps),
        .pfb_fft_shift(ctrl_pfb_fft_shift),
        .pfb_chan0(ctrl_pfb_chan0),
        .pfb_chan_count(ctrl_pfb_chan_count),
        .pfb_time_count(ctrl_pfb_time_count),
        .chan_split(ctrl_chan_split),
        .src_ip(ctrl_src_ip),
        .dgx_a_ip(ctrl_dgx_a_ip),
        .dgx_b_ip(ctrl_dgx_b_ip),
        .time_dst_ip(ctrl_time_dst_ip),
        .src_mac(ctrl_src_mac),
        .dgx_a_mac(ctrl_dgx_a_mac),
        .dgx_b_mac(ctrl_dgx_b_mac),
        .src_udp_port(ctrl_src_udp_port),
        .dgx_a_udp_port(ctrl_dgx_a_udp_port),
        .dgx_b_udp_port(ctrl_dgx_b_udp_port),
        .time_udp_port(ctrl_time_udp_port),
        .tx_control(ctrl_tx_control),
        .tx_clear_pulse(ctrl_tx_clear_pulse),
        .tx_endpoint_enable(ctrl_tx_endpoint_enable),
        .tx_endpoint_ip_vec(ctrl_tx_endpoint_ip_vec),
        .tx_endpoint_mac_vec(ctrl_tx_endpoint_mac_vec),
        .tx_endpoint_src_port_vec(ctrl_tx_endpoint_src_port_vec),
        .tx_endpoint_dst_port_vec(ctrl_tx_endpoint_dst_port_vec),
        .qsfp_test_interval_cycles(ctrl_qsfp_test_interval_cycles),
        .tx_spec_route_enable(ctrl_tx_spec_route_enable),
        .tx_spec_route_chan0_vec(ctrl_tx_spec_route_chan0_vec),
        .tx_spec_route_chan_count_vec(ctrl_tx_spec_route_chan_count_vec),
        .tx_spec_route_endpoint_vec(ctrl_tx_spec_route_endpoint_vec),
        .tx_time_route_enable(ctrl_tx_time_route_enable),
        .tx_time_route_input_mask_vec(ctrl_tx_time_route_input_mask_vec),
        .tx_time_route_endpoint_vec(ctrl_tx_time_route_endpoint_vec),
        .rfdc_active_mask(ctrl_rfdc_active_mask),
        .debug_capture_start_pulse(ctrl_debug_capture_start_pulse),
        .debug_capture_clear_pulse(ctrl_debug_capture_clear_pulse),
        .debug_time_rd_addr(ctrl_debug_time_rd_addr),
        .debug_fft_rd_addr(ctrl_debug_fft_rd_addr),
        .dac_tone_enable(ctrl_dac_tone_enable),
        .dac_tone_amplitude(ctrl_dac_tone_amplitude),
        .dac_tone_phase_step(ctrl_dac_tone_phase_step),
        .dac_enable_mask(ctrl_dac_enable_mask),
        .dac_tone_amplitude_vec(ctrl_dac_tone_amplitude_vec),
        .dac_tone_phase_step_vec(ctrl_dac_tone_phase_step_vec),
        .dac_tone_phase0_vec(ctrl_dac_tone_phase0_vec),
        .dac_tone_phase_inject_vec(ctrl_dac_tone_phase_inject_vec),
        .dac_tone_mode_vec(ctrl_dac_tone_mode_vec),
        .dac_phase_epoch(ctrl_dac_phase_epoch),
        .preview_capture_start_pulse(ctrl_preview_capture_start_pulse),
        .preview_capture_clear_pulse(ctrl_preview_capture_clear_pulse),
        .preview_input_mask(ctrl_preview_input_mask),
        .preview_rd_input(ctrl_preview_rd_input),
        .preview_rd_addr(ctrl_preview_rd_addr),
        .preview_audit_clear_pulse(ctrl_preview_audit_clear_pulse),
        .preview_audit_source_select(ctrl_preview_audit_source_select),
        .preview_audit_event_enable(ctrl_preview_audit_event_enable),
        .preview_audit_freeze_on_event(ctrl_preview_audit_freeze_on_event),
        .preview_audit_event_threshold(ctrl_preview_audit_event_threshold),
        .preview_event_rd_addr(ctrl_preview_event_rd_addr),
        .tx_header_capture_arm_pulse(ctrl_tx_header_capture_arm_pulse),
        .tx_header_capture_rd_word(ctrl_tx_header_capture_rd_word),
        .tx_frame_capture_arm_pulse(ctrl_tx_frame_capture_arm_pulse),
        .tx_frame_capture_rd_word(ctrl_tx_frame_capture_rd_word),
        .tx_payload_witness_arm_pulse(ctrl_tx_payload_witness_arm_pulse),
        .tx_payload_witness_clear_pulse(ctrl_tx_payload_witness_clear_pulse),
        .tx_payload_witness_stream_filter(ctrl_tx_payload_witness_stream_filter),
        .tx_payload_witness_capture_words(ctrl_tx_payload_witness_capture_words),
        .tx_payload_witness_rd_word(ctrl_tx_payload_witness_rd_word),
        .dac_tx_witness_arm_pulse(dac_tx_witness_arm_pulse),
        .dac_tx_witness_clear_pulse(dac_tx_witness_clear_pulse),
        .dac_tx_witness_capture_words(dac_tx_witness_capture_words),
        .dac_tx_witness_rd_word(dac_tx_witness_rd_word),
        .rfdc_axis_raw_witness_arm_pulse(ctrl_rfdc_axis_raw_witness_arm_pulse),
        .rfdc_axis_raw_witness_clear_pulse(ctrl_rfdc_axis_raw_witness_clear_pulse),
        .rfdc_axis_raw_witness_channel_select_ctrl(ctrl_rfdc_axis_raw_witness_channel_select),
        .rfdc_axis_raw_witness_capture_beats(ctrl_rfdc_axis_raw_witness_capture_beats),
        .rfdc_axis_raw_witness_rd_word(ctrl_rfdc_axis_raw_witness_rd_word),
        .unix_seconds(ctrl_unix_seconds),
        .science_bandwidth_mode_cfg(ctrl_science_bandwidth_mode_cfg),
        .science_output_mode_cfg(ctrl_science_output_mode_cfg)
    );

endmodule
