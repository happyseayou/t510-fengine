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
    input  wire [255:0] s_axis_raw_witness_tdata0,
    input  wire [255:0] s_axis_raw_witness_tdata1,
    input  wire [255:0] s_axis_raw_witness_tdata2,
    input  wire [255:0] s_axis_raw_witness_tdata3,
    input  wire [63:0]  s_axis_raw_witness_sample0,
    input  wire         s_axis_raw_witness_tvalid,
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
    output wire [5:0]   m_axi_ddr_awid,
    output wire [39:0]  m_axi_ddr_awaddr,
    output wire [7:0]   m_axi_ddr_awlen,
    output wire [2:0]   m_axi_ddr_awsize,
    output wire [1:0]   m_axi_ddr_awburst,
    output wire         m_axi_ddr_awlock,
    output wire [3:0]   m_axi_ddr_awcache,
    output wire [2:0]   m_axi_ddr_awprot,
    output wire [3:0]   m_axi_ddr_awqos,
    output wire         m_axi_ddr_awvalid,
    input  wire         m_axi_ddr_awready,
    output wire [127:0] m_axi_ddr_wdata,
    output wire [15:0]  m_axi_ddr_wstrb,
    output wire         m_axi_ddr_wlast,
    output wire         m_axi_ddr_wvalid,
    input  wire         m_axi_ddr_wready,
    input  wire [5:0]   m_axi_ddr_bid,
    input  wire [1:0]   m_axi_ddr_bresp,
    input  wire         m_axi_ddr_bvalid,
    output wire         m_axi_ddr_bready,
    output wire [5:0]   m_axi_ddr_arid,
    output wire [39:0]  m_axi_ddr_araddr,
    output wire [7:0]   m_axi_ddr_arlen,
    output wire [2:0]   m_axi_ddr_arsize,
    output wire [1:0]   m_axi_ddr_arburst,
    output wire         m_axi_ddr_arlock,
    output wire [3:0]   m_axi_ddr_arcache,
    output wire [2:0]   m_axi_ddr_arprot,
    output wire [3:0]   m_axi_ddr_arqos,
    output wire         m_axi_ddr_arvalid,
    input  wire         m_axi_ddr_arready,
    input  wire [5:0]   m_axi_ddr_rid,
    input  wire [127:0] m_axi_ddr_rdata,
    input  wire [1:0]   m_axi_ddr_rresp,
    input  wire         m_axi_ddr_rlast,
    input  wire         m_axi_ddr_rvalid,
    output wire         m_axi_ddr_rready,
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
    output wire         diag_adc_force_zero,
    output wire         diag_adc_force_hold,
    output wire [7:0]   diag_adc_channel_mask,
    output wire         diag_dac_gate,
    output wire         irq
);

    localparam [1:0] MODE_SPEC     = 2'd0;
    localparam [1:0] MODE_TIME     = 2'd1;
    localparam [1:0] MODE_DUAL     = 2'd2;
    localparam [1:0] MODE_SNAPSHOT = 2'd3;
    localparam bit   TIME_DDR_RING_COMPILED = 1'b0;
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    localparam integer TX_ENDPOINTS = 24;
    localparam integer TX_SPEC_ROUTES = 16;
    localparam bit CTRL_PRODUCTION_27H = 1'b1;
`else
    localparam integer TX_ENDPOINTS = 72;
    localparam integer TX_SPEC_ROUTES = 64;
    localparam bit CTRL_PRODUCTION_27H = 1'b0;
`endif
`ifdef T510_STAGE27I_RAW_WITNESS
    localparam bit RFDC_RAW_WITNESS_COMPILED = 1'b1;
`else
    localparam bit RFDC_RAW_WITNESS_COMPILED = !CTRL_PRODUCTION_27H;
`endif
    localparam integer TX_TIME_ROUTES = 8;
    localparam [2:0] SCIENCE_MODE_TIME_ONLY = 3'd1;
    localparam [2:0] SCIENCE_MODE_SPEC_ONLY = 3'd2;
    localparam [2:0] SCIENCE_MODE_TIME_SPEC = 3'd3;
    localparam [15:0] FFT_ONLY_DEFAULT_SHIFT = 16'h0556;
    integer tx_reset_idx;

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
    wire [TX_ENDPOINTS-1:0]  ctrl_tx_endpoint_enable;
    wire [TX_ENDPOINTS*32-1:0] ctrl_tx_endpoint_ip_vec;
    wire [TX_ENDPOINTS*48-1:0] ctrl_tx_endpoint_mac_vec;
    wire [TX_ENDPOINTS*16-1:0] ctrl_tx_endpoint_src_port_vec;
    wire [TX_ENDPOINTS*16-1:0] ctrl_tx_endpoint_dst_port_vec;
    wire [31:0] ctrl_qsfp_test_interval_cycles;
    wire [TX_SPEC_ROUTES-1:0]  ctrl_tx_spec_route_enable;
    wire [TX_SPEC_ROUTES*32-1:0] ctrl_tx_spec_route_chan0_vec;
    wire [TX_SPEC_ROUTES*16-1:0] ctrl_tx_spec_route_chan_count_vec;
    wire [TX_SPEC_ROUTES*8-1:0] ctrl_tx_spec_route_endpoint_vec;
    wire [7:0]  ctrl_tx_time_route_enable;
    wire [127:0] ctrl_tx_time_route_input_mask_vec;
    wire [TX_TIME_ROUTES*8-1:0] ctrl_tx_time_route_endpoint_vec;
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
    wire        ctrl_time_ddr_ring_enable;
    wire        ctrl_time_ddr_ring_clear_pulse;
    wire [63:0] ctrl_time_ddr_ring_base_addr;
    wire [15:0] ctrl_time_ddr_ring_slots;
    wire        ctrl_time_multiflow_enable;
    wire [2:0]  ctrl_time_multiflow_base_endpoint;
    wire [3:0]  ctrl_time_multiflow_count;
    wire        ctrl_diag_adc_force_zero;
    wire        ctrl_diag_adc_force_hold;
    wire [7:0]  ctrl_diag_adc_channel_mask;
    wire        ctrl_diag_dac_gate;

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
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS-1:0] tx_endpoint_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS-1:0] tx_endpoint_enable;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*32-1:0] tx_endpoint_ip_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*32-1:0] tx_endpoint_ip_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*48-1:0] tx_endpoint_mac_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*48-1:0] tx_endpoint_mac_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*16-1:0] tx_endpoint_src_port_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*16-1:0] tx_endpoint_src_port_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*16-1:0] tx_endpoint_dst_port_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_ENDPOINTS*16-1:0] tx_endpoint_dst_port_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES-1:0] tx_spec_route_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES-1:0] tx_spec_route_enable;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*32-1:0] tx_spec_route_chan0_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*32-1:0] tx_spec_route_chan0_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*16-1:0] tx_spec_route_chan_count_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*16-1:0] tx_spec_route_chan_count_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*8-1:0] tx_spec_route_endpoint_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*8-1:0] tx_spec_route_endpoint_vec;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_time_route_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic [7:0] tx_time_route_enable;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_time_route_input_mask_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [127:0] tx_time_route_input_mask_vec;
    (* ASYNC_REG = "TRUE" *) logic [TX_TIME_ROUTES*8-1:0] tx_time_route_endpoint_vec_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_TIME_ROUTES*8-1:0] tx_time_route_endpoint_vec;
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
    logic        ctrl_time_ddr_ring_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_epoch_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  stop_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_reset_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  time_ddr_ring_clear_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  packet_stream_reset_toggle_cmac_sync;
    logic        soft_epoch_toggle_seen;
    logic        stop_toggle_seen;
    logic        soft_reset_toggle_seen;
    logic        pfb_clear_toggle_seen;
    logic        tx_clear_toggle_seen;
    logic        tx_clear_toggle_cmac_seen;
    logic        time_ddr_ring_clear_toggle_cmac_seen;
    logic        packet_stream_reset_toggle_cmac_seen;
    logic        packet_stream_reset_toggle_cmac_src;
    wire         arm_latched;
    wire         soft_epoch_pulse;
    wire         stop_pulse;
    wire         soft_reset_pulse;
    wire         pfb_clear_pulse;
    wire         tx_clear_pulse;
    wire         tx_clear_pulse_cmac;
    wire         time_ddr_ring_clear_pulse_cmac;
    wire         packet_stream_reset_pulse_cmac;
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
    wire         science_aa100_active;
    wire         science_aa100_primed;
    wire [31:0]  science_aa100_coeff_version;

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
    wire         legacy_time_tready;
    wire         wide_time_tready;
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
    wire [SCIENCE_DATA_W-1:0] spec_feng_cmac_tdata;
    wire [63:0]  spec_feng_cmac_sample0;
    wire         spec_feng_cmac_tvalid;
    wire         spec_feng_cmac_tready;
    wire         spec_feng_input_cdc_ready;
    wire         spec_feng_cmac_fifo_full;
    wire         spec_feng_cmac_fifo_empty;
    wire [31:0]  spec_feng_cmac_wr_level_words;
    wire [31:0]  spec_feng_cmac_rd_level_words;
    wire [SCIENCE_DATA_W-1:0] pfb_spec_cmac_tdata;
    wire [63:0]  pfb_spec_cmac_sample0;
    wire         pfb_spec_cmac_tvalid;
    wire         pfb_spec_cmac_tready;
    wire         pfb_spec_cmac_to_data_fifo_full;
    wire         pfb_spec_cmac_to_data_fifo_empty;
    wire [31:0]  pfb_spec_cmac_to_data_wr_level_words;
    wire [31:0]  pfb_spec_cmac_to_data_rd_level_words;
    wire [191:0] pfb_spec_cmac_sideband;
    wire [191:0] pfb_spec_sideband;
    wire [SCIENCE_DATA_W-1:0] pfb_spec_tdata;
    wire [63:0]  pfb_spec_sample0;
    wire         pfb_spec_tvalid;
    wire         pfb_spec_tready;
    wire         legacy_pfb_spec_tready;
    wire         wide_pfb_spec_tready;
    wire [31:0] pfb_status;
    wire [31:0] pfb_frame_count;
    wire [31:0] pfb_overflow_count;
    wire [31:0] pfb_data_halt_count;
    wire [31:0] pfb_xfft_event_count;
    wire [31:0] pfb_tile_overflow_count;
    wire [31:0] pfb_xfft_tlast_unexpected_count;
    wire [31:0] pfb_xfft_tlast_missing_count;
    wire [31:0] pfb_xfft_fft_overflow_count;
    wire [31:0] pfb_xfft_data_out_halt_count;
    wire [31:0] pfb_xfft_status_halt_count;
    wire [31:0] pfb_capture_backpressure_count;
    wire [31:0] pfb_frame_sample0_overflow_count;
    wire [31:0] pfb_input_fifo_level;
    wire [31:0] pfb_peak_chan;
    wire [31:0] pfb_peak_power;
    wire [31:0] pfb_packet_chan0;
    wire [15:0] pfb_packet_chan_count;
    wire [15:0] pfb_packet_time_count;
    wire [31:0] pfb_packet_chan0_data;
    wire [15:0] pfb_packet_chan_count_data;
    wire [15:0] pfb_packet_time_count_data;
    wire [15:0] pfb_taps_data;
    wire [15:0] pfb_fft_shift_data;
    wire [31:0] pfb_status_data;
    wire [31:0] spec_product_status_flags;
    wire [1:0] ctrl_science_bandwidth_mode_cfg;
    wire [2:0] ctrl_science_output_mode_cfg;
    wire [31:0] ctrl_time_live_interval_beats;
    (* ASYNC_REG = "TRUE" *) logic        time_multiflow_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic        time_multiflow_enable;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  time_multiflow_base_endpoint_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  time_multiflow_base_endpoint;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  time_multiflow_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  time_multiflow_count;
    (* ASYNC_REG = "TRUE" *) logic        time_ddr_ring_enable_meta;
    (* ASYNC_REG = "TRUE" *) logic        time_ddr_ring_enable_cmac;
    (* ASYNC_REG = "TRUE" *) logic [63:0] time_ddr_ring_base_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] time_ddr_ring_base_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] time_ddr_ring_slots_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] time_ddr_ring_slots_cmac;
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_bandwidth_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_bandwidth_mode;
    (* ASYNC_REG = "TRUE" *) logic [2:0] science_output_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0] science_output_mode;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_live_interval_beats_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_live_interval_beats;

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
    wire [7:0]  routed_endpoint_id;
    wire [5:0]  routed_route_id;
    wire        routed_route_is_time;
    wire [31:0] tx_route_forwarded_count;
    wire [31:0] legacy_tx_route_forwarded_count;
    wire [31:0] wide_tx_route_forwarded_count;
    wire [31:0] wide_spec_tx_route_forwarded_count;
    wire [31:0] tx_route_dropped_count;
    wire [31:0] legacy_tx_route_dropped_count;
    wire [31:0] wide_tx_route_dropped_count;
    wire [31:0] wide_spec_tx_route_dropped_count;
    wire [31:0] tx_route_miss_count;
    wire [31:0] legacy_tx_route_miss_count;
    wire [31:0] wide_tx_route_miss_count;
    wire [31:0] wide_spec_tx_route_miss_count;
    wire [31:0] tx_route_error_count;
    wire [31:0] legacy_tx_route_error_count;
    wire [31:0] wide_tx_route_error_count;
    wire [31:0] wide_spec_tx_route_error_count;
    wire [7:0]  tx_selected_endpoint_id;
    wire [7:0]  legacy_tx_selected_endpoint_id;
    wire [7:0]  wide_tx_selected_endpoint_id;
    wire [7:0]  wide_spec_tx_selected_endpoint_id;
    wire [5:0]  tx_selected_route_id;
    wire [5:0]  legacy_tx_selected_route_id;
    wire [5:0]  wide_tx_selected_route_id;
    wire [5:0]  wide_spec_tx_selected_route_id;
    wire        tx_selected_route_is_time;
    wire        legacy_tx_selected_route_is_time;
    wire        wide_tx_selected_route_is_time;
    wire        wide_spec_tx_selected_route_is_time;
    wire [TX_SPEC_ROUTES*32-1:0] tx_spec_route_hit_counts;
    wire [TX_SPEC_ROUTES*32-1:0] legacy_tx_spec_route_hit_counts;
    wire [TX_SPEC_ROUTES*32-1:0] wide_spec_tx_route_hit_counts;
    wire [255:0] tx_time_route_hit_counts;
    wire [255:0] legacy_tx_time_route_hit_counts;
    wire [255:0] wide_tx_time_route_hit_counts;
    wire [31:0] tx_frame_built_count;
    wire [31:0] legacy_tx_frame_built_count;
    wire [31:0] wide_tx_frame_built_count;
    wire [31:0] wide_spec_tx_frame_built_count;
    wire [31:0] tx_frame_byte_count;
    wire [31:0] legacy_tx_frame_byte_count;
    wire [31:0] wide_tx_frame_byte_count;
    wire [31:0] wide_spec_tx_frame_byte_count;
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
    wire [511:0] heartbeat_cmac_tdata;
    wire [63:0]  heartbeat_cmac_tkeep;
    wire         heartbeat_cmac_tvalid;
    wire         heartbeat_cmac_tlast;
    wire         heartbeat_cmac_tready;
    wire [511:0] time_live_cmac_tdata;
    wire [63:0]  time_live_cmac_tkeep;
    wire         time_live_cmac_tvalid;
    wire         time_live_cmac_tlast;
    wire         time_live_cmac_tready;
    wire [511:0] time_live_cmac_mux_tdata;
    wire [63:0]  time_live_cmac_mux_tkeep;
    wire         time_live_cmac_mux_tvalid;
    wire         time_live_cmac_mux_tlast;
    wire         time_live_cmac_mux_tready;
    wire [511:0] cmac_mux_axis_tdata;
    wire [63:0]  cmac_mux_axis_tkeep;
    wire         cmac_mux_axis_tvalid;
    wire         cmac_mux_axis_tlast;
    wire         cmac_mux_axis_tready;
    wire [511:0] time_live_ddr_tdata;
    wire [63:0]  time_live_ddr_tkeep;
    wire         time_live_ddr_tvalid;
    wire         time_live_ddr_tlast;
    wire         time_live_ddr_tready;
    wire [31:0] time_ddr_ring_status;
    wire [31:0] time_ddr_ring_occupancy;
    wire [31:0] time_ddr_ring_write_count;
    wire [31:0] time_ddr_ring_read_count;
    wire [31:0] time_ddr_ring_drop_count;
    wire [31:0] time_ddr_ring_error_count;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_status_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_occupancy_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_occupancy_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_write_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_write_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_read_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_read_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_drop_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_drop_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_error_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] time_ddr_ring_error_count_ctrl;
    wire [511:0] legacy_time_live_cmac_tdata;
    wire [63:0]  legacy_time_live_cmac_tkeep;
    wire         legacy_time_live_cmac_tvalid;
    wire         legacy_time_live_cmac_tlast;
    wire         legacy_time_live_cmac_tready;
    wire [511:0] wide_time_live_cmac_tdata;
    wire [63:0]  wide_time_live_cmac_tkeep;
    wire         wide_time_live_cmac_tvalid;
    wire         wide_time_live_cmac_tlast;
    wire         wide_time_live_cmac_tready;
    wire [511:0] wide_spec_live_cmac_tdata;
    wire [63:0]  wide_spec_live_cmac_tkeep;
    wire         wide_spec_live_cmac_tvalid;
    wire         wide_spec_live_cmac_tlast;
    wire         wide_spec_live_cmac_tready;
    wire         time_live_bridge_s_tready;
    wire         legacy_time_live_bridge_s_tready;
    wire         wide_time_live_bridge_s_tready;
    wire [31:0] time_live_bridge_fifo_level;
    wire [31:0] legacy_time_live_bridge_fifo_level;
    wire [31:0] wide_time_live_bridge_fifo_level;
    wire [31:0] time_live_bridge_input_frames;
    wire [31:0] legacy_time_live_bridge_input_frames;
    wire [31:0] wide_time_live_bridge_input_frames;
    wire [31:0] time_live_bridge_output_frames;
    wire [31:0] legacy_time_live_bridge_output_frames;
    wire [31:0] wide_time_live_bridge_output_frames;
    wire [31:0] time_live_bridge_backpressure_cycles;
    wire [31:0] legacy_time_live_bridge_backpressure_cycles;
    wire [31:0] wide_time_live_bridge_backpressure_cycles;
    wire         time_live_bridge_fifo_full;
    wire         legacy_time_live_bridge_fifo_full;
    wire         wide_time_live_bridge_fifo_full;
    wire         time_live_bridge_fifo_empty;
    wire         legacy_time_live_bridge_fifo_empty;
    wire         wide_time_live_bridge_fifo_empty;
    wire [31:0] tx_cmac_source_mux_status;
    wire [31:0] tx_cmac_source_status;
    wire        time_live_requested_data;
    logic       time_live_requested_cmac;
    wire        time_live_requested_cmac_comb;
    wire        spec_live_requested_data;
    logic       spec_live_requested_cmac;
    wire        spec_live_requested_cmac_comb;
    wire        legacy_bridge_requested_data;
    logic       legacy_bridge_requested_cmac;
    wire        legacy_bridge_requested_cmac_comb;
    wire        time_live_full_rate_data;
    (* ASYNC_REG = "TRUE" *) logic time_live_full_rate_cmac_meta;
    logic       time_live_full_rate_cmac;
    wire        frame_tx_tready;
    wire [63:0] frame_tx_tdata;
    wire [7:0]  frame_tx_tkeep;
    wire        frame_tx_tvalid;
    wire        frame_tx_tlast;
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
    (* ASYNC_REG = "TRUE" *) logic [2:0] science_output_mode_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0] science_output_mode_cmac;
    (* ASYNC_REG = "TRUE" *) logic spec_enable_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic spec_enable_cmac;
    (* ASYNC_REG = "TRUE" *) logic pfb_enable_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic pfb_enable_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift_cmac;
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
    wire [31:0] legacy_spec_packet_count;
    wire [31:0] wide_spec_packet_count;
    wire [31:0] spec_udp_byte_count;
    wire [31:0] legacy_spec_udp_byte_count;
    wire [31:0] wide_spec_udp_byte_count;
    wire [31:0] spec_duplicator_dropped_count;
    wire [31:0] spec_decimator_selected_count;
    wire [31:0] spec_decimator_discarded_count;
    wire [31:0] spec_decimator_dropped_count;
    wire [31:0] spec_seq_no;
    wire [31:0] legacy_spec_seq_no;
    wire [31:0] wide_spec_seq_no;
    wire [63:0] spec_frame_id;
    wire [63:0] legacy_spec_frame_id;
    wire [63:0] wide_spec_sample0;
    wire [63:0] wide_spec_frame_id;
    wire [31:0] spec_chan0;
    wire [31:0] legacy_spec_chan0;
    wire [31:0] wide_spec_chan0;
    wire [31:0] time_packet_count;
    wire [31:0] legacy_time_packet_count;
    wire [31:0] wide_time_packet_count;
    wire [31:0] time_dropped_count;
    wire [31:0] time_duplicator_dropped_count;
    wire [31:0] legacy_time_dropped_count;
    wire [31:0] wide_time_dropped_count;
    wire [31:0] time_udp_byte_count;
    wire [31:0] legacy_time_udp_byte_count;
    wire [31:0] wide_time_udp_byte_count;
    wire [31:0] time_seq_no;
    wire [31:0] legacy_time_seq_no;
    wire [31:0] wide_time_seq_no;
    wire [63:0] time_sample0;
    wire [63:0] legacy_time_sample0;
    wire [63:0] wide_time_sample0;
    wire [63:0] time_frame_id;
    wire [63:0] legacy_time_frame_id;
    wire [63:0] wide_time_frame_id;
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
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_dropped_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  spec_dropped_count_ctrl;
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
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_data_halt_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_data_halt_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_event_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_event_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_tile_overflow_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_tile_overflow_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_tlast_unexpected_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_tlast_unexpected_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_tlast_missing_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_tlast_missing_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_fft_overflow_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_fft_overflow_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_data_out_halt_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_data_out_halt_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_status_halt_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_xfft_status_halt_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_capture_backpressure_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_capture_backpressure_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_frame_sample0_overflow_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_frame_sample0_overflow_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_input_fifo_level_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_input_fifo_level_ctrl;
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
    (* ASYNC_REG = "TRUE" *) logic [31:0]  science_dropped_beat_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  science_dropped_beat_count_ctrl;
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
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_cmac_source_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  tx_cmac_source_status_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   tx_selected_endpoint_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [7:0]   tx_selected_endpoint_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [5:0]   tx_selected_route_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [5:0]   tx_selected_route_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic         tx_selected_route_is_time_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic         tx_selected_route_is_time_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*32-1:0] tx_spec_route_hit_counts_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [TX_SPEC_ROUTES*32-1:0] tx_spec_route_hit_counts_ctrl;
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
    assign tx_count_packet_status = tx_dry_run_active ? tx_dry_run_packet_count :
                                    ((time_live_requested_data || spec_live_requested_data) ? tx_frame_built_count : tx_cmac_test_packet_count_ctrl);
    assign tx_count_byte_status = tx_dry_run_active ? tx_dry_run_byte_count :
                                  ((time_live_requested_data || spec_live_requested_data) ? tx_frame_byte_count : tx_cmac_test_byte_count_ctrl);
    assign tx_route_forwarded_count = legacy_tx_route_forwarded_count +
                                      (time_live_full_rate_data ? wide_tx_route_forwarded_count : 32'd0) +
                                      (spec_live_requested_data ? wide_spec_tx_route_forwarded_count : 32'd0);
    assign tx_route_dropped_count = legacy_tx_route_dropped_count +
                                    (time_live_full_rate_data ? wide_tx_route_dropped_count : 32'd0) +
                                    (spec_live_requested_data ? wide_spec_tx_route_dropped_count : 32'd0);
    assign tx_route_miss_count = legacy_tx_route_miss_count +
                                 (time_live_full_rate_data ? wide_tx_route_miss_count : 32'd0) +
                                 (spec_live_requested_data ? wide_spec_tx_route_miss_count : 32'd0);
    assign tx_route_error_count = legacy_tx_route_error_count +
                                  (time_live_full_rate_data ? wide_tx_route_error_count : 32'd0) +
                                  (spec_live_requested_data ? wide_spec_tx_route_error_count : 32'd0);
    assign tx_selected_endpoint_id =
        spec_live_requested_data ? wide_spec_tx_selected_endpoint_id :
        (!time_live_full_rate_data ? legacy_tx_selected_endpoint_id : wide_tx_selected_endpoint_id);
    assign tx_selected_route_id =
        spec_live_requested_data ? wide_spec_tx_selected_route_id :
        (!time_live_full_rate_data ? legacy_tx_selected_route_id : wide_tx_selected_route_id);
    assign tx_selected_route_is_time =
        spec_live_requested_data ? wide_spec_tx_selected_route_is_time :
        (!time_live_full_rate_data ? legacy_tx_selected_route_is_time : wide_tx_selected_route_is_time);
    assign tx_spec_route_hit_counts = spec_live_requested_data ? wide_spec_tx_route_hit_counts : legacy_tx_spec_route_hit_counts;
    assign tx_time_route_hit_counts = time_live_full_rate_data ? wide_tx_time_route_hit_counts : legacy_tx_time_route_hit_counts;
    assign tx_frame_built_count = legacy_tx_frame_built_count +
                                  (time_live_full_rate_data ? wide_tx_frame_built_count : 32'd0) +
                                  (spec_live_requested_data ? wide_spec_tx_frame_built_count : 32'd0);
    assign tx_frame_byte_count = legacy_tx_frame_byte_count +
                                 (time_live_full_rate_data ? wide_tx_frame_byte_count : 32'd0) +
                                 (spec_live_requested_data ? wide_spec_tx_frame_byte_count : 32'd0);
    assign spec_packet_count = spec_live_requested_data ? wide_spec_packet_count : legacy_spec_packet_count;
    assign spec_udp_byte_count = spec_live_requested_data ? wide_spec_udp_byte_count : legacy_spec_udp_byte_count;
    assign spec_seq_no = spec_live_requested_data ? wide_spec_seq_no : legacy_spec_seq_no;
    assign spec_frame_id = spec_live_requested_data ? wide_spec_frame_id : legacy_spec_frame_id;
    assign spec_chan0 = spec_live_requested_data ? wide_spec_chan0 : legacy_spec_chan0;
    assign time_packet_count = time_live_full_rate_data ? wide_time_packet_count : legacy_time_packet_count;
    assign time_dropped_count = (time_live_full_rate_data ? wide_time_dropped_count : legacy_time_dropped_count) +
                                time_duplicator_dropped_count;
    assign time_udp_byte_count = time_live_full_rate_data ? wide_time_udp_byte_count : legacy_time_udp_byte_count;
    assign time_seq_no = time_live_full_rate_data ? wide_time_seq_no : legacy_time_seq_no;
    assign time_sample0 = time_live_full_rate_data ? wide_time_sample0 : legacy_time_sample0;
    assign time_frame_id = time_live_full_rate_data ? wide_time_frame_id : legacy_time_frame_id;
    assign time_live_bridge_s_tready = time_live_full_rate_data ? wide_time_live_bridge_s_tready : legacy_time_live_bridge_s_tready;
    assign time_live_bridge_fifo_level = time_live_full_rate_data ? wide_time_live_bridge_fifo_level : legacy_time_live_bridge_fifo_level;
    assign time_live_bridge_input_frames = time_live_full_rate_data ? wide_time_live_bridge_input_frames : legacy_time_live_bridge_input_frames;
    assign time_live_bridge_output_frames = time_live_full_rate_data ? wide_time_live_bridge_output_frames : legacy_time_live_bridge_output_frames;
    assign time_live_bridge_backpressure_cycles = time_live_full_rate_data ? wide_time_live_bridge_backpressure_cycles : legacy_time_live_bridge_backpressure_cycles;
    assign time_live_bridge_fifo_full = time_live_full_rate_data ? wide_time_live_bridge_fifo_full : legacy_time_live_bridge_fifo_full;
    assign time_live_bridge_fifo_empty = time_live_full_rate_data ? wide_time_live_bridge_fifo_empty : legacy_time_live_bridge_fifo_empty;
    assign time_live_cmac_tdata = wide_time_live_cmac_tdata;
    assign time_live_cmac_tkeep = wide_time_live_cmac_tkeep;
    assign time_live_cmac_tvalid = time_live_full_rate_cmac ? wide_time_live_cmac_tvalid : 1'b0;
    assign time_live_cmac_tlast = wide_time_live_cmac_tlast;
    assign wide_time_live_cmac_tready = time_live_full_rate_cmac ? time_live_cmac_tready : 1'b0;

    generate
        if (TIME_DDR_RING_COMPILED) begin : g_time_ddr_ring
            time_axis512_ddr_ring #(
                .AXI_ADDR_W(40),
                .AXI_DATA_W(128),
                .AXI_ID_W(6),
                .AXIS_DATA_W(512),
                .AXIS_KEEP_W(64),
                .FRAME_BEATS(131),
                .DEFAULT_SLOTS(64)
            ) u_time_live_ddr_ring (
                .clk(cmac_tx_clk),
                .rst_n(cmac_tx_rst_n),
                .clear(tx_clear_pulse_cmac || time_ddr_ring_clear_pulse_cmac),
                .enable(time_ddr_ring_enable_cmac),
                .base_addr(time_ddr_ring_base_cmac[39:0]),
                .ring_slots_cfg(time_ddr_ring_slots_cmac),
                .s_axis_tdata(time_live_cmac_tdata),
                .s_axis_tkeep(time_live_cmac_tkeep),
                .s_axis_tvalid(time_live_cmac_tvalid),
                .s_axis_tlast(time_live_cmac_tlast),
                .s_axis_tready(time_live_cmac_tready),
                .m_axis_tdata(time_live_ddr_tdata),
                .m_axis_tkeep(time_live_ddr_tkeep),
                .m_axis_tvalid(time_live_ddr_tvalid),
                .m_axis_tlast(time_live_ddr_tlast),
                .m_axis_tready(time_live_ddr_tready),
                .m_axi_awid(m_axi_ddr_awid),
                .m_axi_awaddr(m_axi_ddr_awaddr),
                .m_axi_awlen(m_axi_ddr_awlen),
                .m_axi_awsize(m_axi_ddr_awsize),
                .m_axi_awburst(m_axi_ddr_awburst),
                .m_axi_awlock(m_axi_ddr_awlock),
                .m_axi_awcache(m_axi_ddr_awcache),
                .m_axi_awprot(m_axi_ddr_awprot),
                .m_axi_awqos(m_axi_ddr_awqos),
                .m_axi_awvalid(m_axi_ddr_awvalid),
                .m_axi_awready(m_axi_ddr_awready),
                .m_axi_wdata(m_axi_ddr_wdata),
                .m_axi_wstrb(m_axi_ddr_wstrb),
                .m_axi_wlast(m_axi_ddr_wlast),
                .m_axi_wvalid(m_axi_ddr_wvalid),
                .m_axi_wready(m_axi_ddr_wready),
                .m_axi_bid(m_axi_ddr_bid),
                .m_axi_bresp(m_axi_ddr_bresp),
                .m_axi_bvalid(m_axi_ddr_bvalid),
                .m_axi_bready(m_axi_ddr_bready),
                .m_axi_arid(m_axi_ddr_arid),
                .m_axi_araddr(m_axi_ddr_araddr),
                .m_axi_arlen(m_axi_ddr_arlen),
                .m_axi_arsize(m_axi_ddr_arsize),
                .m_axi_arburst(m_axi_ddr_arburst),
                .m_axi_arlock(m_axi_ddr_arlock),
                .m_axi_arcache(m_axi_ddr_arcache),
                .m_axi_arprot(m_axi_ddr_arprot),
                .m_axi_arqos(m_axi_ddr_arqos),
                .m_axi_arvalid(m_axi_ddr_arvalid),
                .m_axi_arready(m_axi_ddr_arready),
                .m_axi_rid(m_axi_ddr_rid),
                .m_axi_rdata(m_axi_ddr_rdata),
                .m_axi_rresp(m_axi_ddr_rresp),
                .m_axi_rlast(m_axi_ddr_rlast),
                .m_axi_rvalid(m_axi_ddr_rvalid),
                .m_axi_rready(m_axi_ddr_rready),
                .occupancy_frames(time_ddr_ring_occupancy),
                .write_frame_count(time_ddr_ring_write_count),
                .read_frame_count(time_ddr_ring_read_count),
                .drop_frame_count(time_ddr_ring_drop_count),
                .error_count(time_ddr_ring_error_count),
                .status(time_ddr_ring_status)
            );
        end else begin : g_time_ddr_bypass
            assign time_live_ddr_tdata = time_live_cmac_tdata;
            assign time_live_ddr_tkeep = time_live_cmac_tkeep;
            assign time_live_ddr_tvalid = time_live_cmac_tvalid;
            assign time_live_ddr_tlast = time_live_cmac_tlast;
            assign time_live_cmac_tready = time_live_ddr_tready;

            assign m_axi_ddr_awid = 6'd0;
            assign m_axi_ddr_awaddr = 40'd0;
            assign m_axi_ddr_awlen = 8'd0;
            assign m_axi_ddr_awsize = 3'd0;
            assign m_axi_ddr_awburst = 2'd1;
            assign m_axi_ddr_awlock = 1'b0;
            assign m_axi_ddr_awcache = 4'd0;
            assign m_axi_ddr_awprot = 3'd0;
            assign m_axi_ddr_awqos = 4'd0;
            assign m_axi_ddr_awvalid = 1'b0;
            assign m_axi_ddr_wdata = 128'd0;
            assign m_axi_ddr_wstrb = 16'd0;
            assign m_axi_ddr_wlast = 1'b0;
            assign m_axi_ddr_wvalid = 1'b0;
            assign m_axi_ddr_bready = 1'b1;
            assign m_axi_ddr_arid = 6'd0;
            assign m_axi_ddr_araddr = 40'd0;
            assign m_axi_ddr_arlen = 8'd0;
            assign m_axi_ddr_arsize = 3'd0;
            assign m_axi_ddr_arburst = 2'd1;
            assign m_axi_ddr_arlock = 1'b0;
            assign m_axi_ddr_arcache = 4'd0;
            assign m_axi_ddr_arprot = 3'd0;
            assign m_axi_ddr_arqos = 4'd0;
            assign m_axi_ddr_arvalid = 1'b0;
            assign m_axi_ddr_rready = 1'b1;

            assign time_ddr_ring_status = 32'd0;
            assign time_ddr_ring_occupancy = 32'd0;
            assign time_ddr_ring_write_count = 32'd0;
            assign time_ddr_ring_read_count = 32'd0;
            assign time_ddr_ring_drop_count = 32'd0;
            assign time_ddr_ring_error_count = 32'd0;
        end
    endgenerate

    axis512_register_slice #(
        .DATA_W(512),
        .KEEP_W(64),
        .DEPTH(2)
    ) u_time_live_cmac_tx_slice (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .clear(tx_clear_pulse_cmac),
        .s_axis_tdata(time_live_ddr_tdata),
        .s_axis_tkeep(time_live_ddr_tkeep),
        .s_axis_tvalid(time_live_ddr_tvalid),
        .s_axis_tlast(time_live_ddr_tlast),
        .s_axis_tready(time_live_ddr_tready),
        .m_axis_tdata(time_live_cmac_mux_tdata),
        .m_axis_tkeep(time_live_cmac_mux_tkeep),
        .m_axis_tvalid(time_live_cmac_mux_tvalid),
        .m_axis_tlast(time_live_cmac_mux_tlast),
        .m_axis_tready(time_live_cmac_mux_tready)
    );
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
    assign time_live_requested_data =
        tx_control[1] &&
        !tx_control[0] &&
        tx_control[2] &&
        ((science_output_mode == SCIENCE_MODE_TIME_ONLY) || (science_output_mode == SCIENCE_MODE_TIME_SPEC));
    assign spec_live_requested_data =
        tx_control[1] &&
        !tx_control[0] &&
        tx_control[2] &&
        ((science_output_mode == SCIENCE_MODE_SPEC_ONLY) || (science_output_mode == SCIENCE_MODE_TIME_SPEC));
    assign time_live_requested_cmac_comb =
        tx_control_cmac[1] &&
        !tx_control_cmac[0] &&
        tx_control_cmac[2] &&
        ((science_output_mode_cmac == SCIENCE_MODE_TIME_ONLY) || (science_output_mode_cmac == SCIENCE_MODE_TIME_SPEC));
    assign spec_live_requested_cmac_comb =
        tx_control_cmac[1] &&
        !tx_control_cmac[0] &&
        tx_control_cmac[2] &&
        ((science_output_mode_cmac == SCIENCE_MODE_SPEC_ONLY) || (science_output_mode_cmac == SCIENCE_MODE_TIME_SPEC));
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign time_live_full_rate_data = time_live_requested_data;
    assign legacy_bridge_requested_data = 1'b0;
    assign legacy_bridge_requested_cmac_comb = 1'b0;
`else
    assign time_live_full_rate_data = time_live_requested_data && (time_live_interval_beats == 32'd0);
    assign legacy_bridge_requested_data = time_live_requested_data && !time_live_full_rate_data;
    assign legacy_bridge_requested_cmac_comb =
        time_live_requested_cmac_comb && !time_live_full_rate_cmac;
`endif

    always_ff @(posedge cmac_tx_clk or negedge cmac_tx_rst_n) begin
        if (!cmac_tx_rst_n) begin
            time_live_requested_cmac <= 1'b0;
            spec_live_requested_cmac <= 1'b0;
            time_live_full_rate_cmac_meta <= 1'b0;
            time_live_full_rate_cmac <= 1'b0;
            legacy_bridge_requested_cmac <= 1'b0;
        end else begin
            time_live_requested_cmac <= time_live_requested_cmac_comb;
            spec_live_requested_cmac <= spec_live_requested_cmac_comb;
            time_live_full_rate_cmac_meta <= time_live_full_rate_data;
            time_live_full_rate_cmac <= time_live_full_rate_cmac_meta;
            legacy_bridge_requested_cmac <= legacy_bridge_requested_cmac_comb;
        end
    end
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign tx_qsfp_test_enable = 1'b0;
`else
    assign tx_qsfp_test_enable =
        tx_control_cmac[1] &&
        tx_control_cmac[2] &&
        !tx_control_cmac[0] &&
        !time_live_requested_cmac &&
        !spec_live_requested_cmac &&
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
`endif
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign frame_tx_tready = 1'b0;
    assign m_axis_tx_tdata = 64'd0;
    assign m_axis_tx_tkeep = 8'd0;
    assign m_axis_tx_tvalid = 1'b0;
    assign m_axis_tx_tlast = 1'b0;
`else
    assign frame_tx_tready = legacy_bridge_requested_data ? legacy_time_live_bridge_s_tready : m_axis_tx_tready;
    assign m_axis_tx_tdata = frame_tx_tdata;
    assign m_axis_tx_tkeep = frame_tx_tkeep;
    assign m_axis_tx_tvalid = frame_tx_tvalid && !legacy_bridge_requested_data;
    assign m_axis_tx_tlast = frame_tx_tlast;
`endif
    assign tx_cmac_source_status = {
        tx_cmac_source_mux_status[15:0],
        wide_time_live_bridge_fifo_empty,
        wide_time_live_bridge_fifo_full,
        legacy_time_live_bridge_fifo_empty,
        legacy_time_live_bridge_fifo_full,
        legacy_bridge_requested_cmac,
        legacy_bridge_requested_data,
        spec_live_requested_cmac,
        spec_live_requested_data,
        time_live_requested_cmac,
        time_live_requested_data,
        (legacy_time_live_cmac_tready || wide_spec_live_cmac_tready),
        time_live_cmac_mux_tvalid,
        heartbeat_cmac_tvalid,
        tx_qsfp_test_enable,
        tx_cmac_source_mux_status[1:0]
    };
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
    assign time_ddr_ring_clear_pulse_cmac =
        time_ddr_ring_clear_toggle_cmac_sync[2] ^ time_ddr_ring_clear_toggle_cmac_seen;
    assign packet_stream_reset_pulse_cmac =
        packet_stream_reset_toggle_cmac_sync[2] ^ packet_stream_reset_toggle_cmac_seen;
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
    assign diag_adc_force_zero = ctrl_diag_adc_force_zero;
    assign diag_adc_force_hold = ctrl_diag_adc_force_hold;
    assign diag_adc_channel_mask = ctrl_diag_adc_channel_mask;
    assign diag_dac_gate = ctrl_diag_dac_gate;
    assign spec_input_sample0 = spec_sample0;
    assign time_input_sample0 = time_sample0_sideband;
    assign time_tready = time_live_full_rate_data ? wide_time_tready : legacy_time_tready;
`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign pfb_spec_tready = spec_live_requested_data ? wide_pfb_spec_tready : 1'b0;
`else
    assign pfb_spec_tready = spec_live_requested_data ? wide_pfb_spec_tready : legacy_pfb_spec_tready;
`endif
    assign spec_decimator_selected_count = spec_tvalid && spec_tready ? 32'd1 : 32'd0;
    assign spec_decimator_discarded_count = 32'd0;
    assign spec_decimator_dropped_count = 32'd0;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_soft_epoch_toggle <= 1'b0;
            ctrl_stop_toggle       <= 1'b0;
            ctrl_soft_reset_toggle <= 1'b0;
            ctrl_pfb_clear_toggle  <= 1'b0;
            ctrl_tx_clear_toggle   <= 1'b0;
            ctrl_time_ddr_ring_clear_toggle <= 1'b0;
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
            if (ctrl_time_ddr_ring_clear_pulse) begin
                ctrl_time_ddr_ring_clear_toggle <= ~ctrl_time_ddr_ring_clear_toggle;
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
            pfb_taps_meta          <= 16'd0;
            pfb_taps               <= 16'd0;
            pfb_fft_shift_meta     <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_fft_shift          <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_chan0_meta         <= 32'd0;
            pfb_chan0              <= 32'd0;
            pfb_chan_count_meta    <= 16'd256;
            pfb_chan_count         <= 16'd256;
            pfb_time_count_meta    <= 16'd1;
            pfb_time_count         <= 16'd1;
            science_bandwidth_mode_meta <= 2'd1;
            science_bandwidth_mode <= 2'd1;
            science_output_mode_meta <= 3'd0;
            science_output_mode <= 3'd0;
            time_live_interval_beats_meta <= 32'd7680;
            time_live_interval_beats <= 32'd7680;
            time_multiflow_enable_meta <= 1'b0;
            time_multiflow_enable <= 1'b0;
            time_multiflow_base_endpoint_meta <= 3'd0;
            time_multiflow_base_endpoint <= 3'd0;
            time_multiflow_count_meta <= 4'd1;
            time_multiflow_count <= 4'd1;
            chan_split_meta        <= 32'd0;
            chan_split             <= 32'd0;
            src_ip_meta            <= 32'd0;
            src_ip                 <= 32'd0;
            src_mac_meta           <= 48'd0;
            src_mac                <= 48'd0;
            tx_control_meta        <= 32'h0000_000d;
            tx_control             <= 32'h0000_000d;
            tx_endpoint_enable_meta <= {TX_ENDPOINTS{1'b1}};
            tx_endpoint_enable     <= {TX_ENDPOINTS{1'b1}};
            tx_endpoint_ip_vec_meta <= {TX_ENDPOINTS{32'h0a00_0110}};
            tx_endpoint_ip_vec     <= {TX_ENDPOINTS{32'h0a00_0110}};
            tx_endpoint_mac_vec_meta <= {TX_ENDPOINTS{48'h08c0_ebd5_95b2}};
            tx_endpoint_mac_vec    <= {TX_ENDPOINTS{48'h08c0_ebd5_95b2}};
            tx_endpoint_src_port_vec_meta <= {TX_ENDPOINTS{16'd4000}};
            tx_endpoint_src_port_vec <= {TX_ENDPOINTS{16'd4000}};
            tx_endpoint_dst_port_vec_meta <= {TX_ENDPOINTS{16'd4300}};
            tx_endpoint_dst_port_vec <= {TX_ENDPOINTS{16'd4300}};
            for (tx_reset_idx = 0; tx_reset_idx < TX_ENDPOINTS; tx_reset_idx = tx_reset_idx + 1) begin
                tx_endpoint_enable_meta[tx_reset_idx] <= 1'b1;
                tx_endpoint_enable[tx_reset_idx] <= 1'b1;
                tx_endpoint_ip_vec_meta[tx_reset_idx*32 +: 32] <= 32'h0a00_0110;
                tx_endpoint_ip_vec[tx_reset_idx*32 +: 32] <= 32'h0a00_0110;
                tx_endpoint_mac_vec_meta[tx_reset_idx*48 +: 48] <= 48'h08c0_ebd5_95b2;
                tx_endpoint_mac_vec[tx_reset_idx*48 +: 48] <= 48'h08c0_ebd5_95b2;
                tx_endpoint_src_port_vec_meta[tx_reset_idx*16 +: 16] <= 16'd4000 + tx_reset_idx;
                tx_endpoint_src_port_vec[tx_reset_idx*16 +: 16] <= 16'd4000 + tx_reset_idx;
                tx_endpoint_dst_port_vec_meta[tx_reset_idx*16 +: 16] <= 16'd4300 + tx_reset_idx;
                tx_endpoint_dst_port_vec[tx_reset_idx*16 +: 16] <= 16'd4300 + tx_reset_idx;
            end
            tx_spec_route_enable_meta <= {TX_SPEC_ROUTES{1'b0}};
            tx_spec_route_enable   <= {TX_SPEC_ROUTES{1'b0}};
            tx_spec_route_chan0_vec_meta <= {TX_SPEC_ROUTES{32'd0}};
            tx_spec_route_chan0_vec <= {TX_SPEC_ROUTES{32'd0}};
            tx_spec_route_chan_count_vec_meta <= {TX_SPEC_ROUTES{16'd0}};
            tx_spec_route_chan_count_vec <= {TX_SPEC_ROUTES{16'd0}};
            tx_spec_route_endpoint_vec_meta <= {TX_SPEC_ROUTES{8'd8}};
            tx_spec_route_endpoint_vec <= {TX_SPEC_ROUTES{8'd8}};
            for (tx_reset_idx = 0; tx_reset_idx < TX_SPEC_ROUTES; tx_reset_idx = tx_reset_idx + 1) begin
                tx_spec_route_enable_meta[tx_reset_idx] <= (tx_reset_idx < 16);
                tx_spec_route_enable[tx_reset_idx] <= (tx_reset_idx < 16);
                tx_spec_route_chan0_vec_meta[tx_reset_idx*32 +: 32] <= (tx_reset_idx < 16) ? (tx_reset_idx * 32'd256) : 32'd0;
                tx_spec_route_chan0_vec[tx_reset_idx*32 +: 32] <= (tx_reset_idx < 16) ? (tx_reset_idx * 32'd256) : 32'd0;
                tx_spec_route_chan_count_vec_meta[tx_reset_idx*16 +: 16] <= (tx_reset_idx < 16) ? 16'd256 : 16'd0;
                tx_spec_route_chan_count_vec[tx_reset_idx*16 +: 16] <= (tx_reset_idx < 16) ? 16'd256 : 16'd0;
                tx_spec_route_endpoint_vec_meta[tx_reset_idx*8 +: 8] <= 8'd8 + tx_reset_idx[7:0];
                tx_spec_route_endpoint_vec[tx_reset_idx*8 +: 8] <= 8'd8 + tx_reset_idx[7:0];
            end
            tx_time_route_enable_meta <= 8'h01;
            tx_time_route_enable   <= 8'h01;
            tx_time_route_input_mask_vec_meta <= 128'd0;
            tx_time_route_input_mask_vec <= 128'd0;
            tx_time_route_endpoint_vec_meta <= {TX_TIME_ROUTES{8'd0}};
            tx_time_route_endpoint_vec <= {TX_TIME_ROUTES{8'd0}};
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
            packet_stream_reset_toggle_cmac_src <= 1'b0;
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
            science_output_mode_meta <= ctrl_science_output_mode_cfg;
            science_output_mode <= science_output_mode_meta;
            time_live_interval_beats_meta <= ctrl_time_live_interval_beats;
            time_live_interval_beats <= time_live_interval_beats_meta;
            time_multiflow_enable_meta <= ctrl_time_multiflow_enable;
            time_multiflow_enable <= time_multiflow_enable_meta;
            time_multiflow_base_endpoint_meta <= ctrl_time_multiflow_base_endpoint;
            time_multiflow_base_endpoint <= time_multiflow_base_endpoint_meta;
            time_multiflow_count_meta <= ctrl_time_multiflow_count;
            time_multiflow_count <= time_multiflow_count_meta;
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
            if (packet_stream_reset_pulse || pfb_clear_pulse) begin
                packet_stream_reset_toggle_cmac_src <= ~packet_stream_reset_toggle_cmac_src;
            end
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
            time_ddr_ring_enable_meta <= 1'b0;
            time_ddr_ring_enable_cmac <= 1'b0;
            time_ddr_ring_base_meta <= 64'h0000_0008_0000_0000;
            time_ddr_ring_base_cmac <= 64'h0000_0008_0000_0000;
            time_ddr_ring_slots_meta <= 16'd64;
            time_ddr_ring_slots_cmac <= 16'd64;
            tx_link_status_flags_cmac_meta <= 32'd0;
            tx_link_status_flags_cmac <= 32'd0;
            tx_control_cmac_meta <= 32'h0000_000d;
            tx_control_cmac <= 32'h0000_000d;
            science_output_mode_cmac_meta <= 3'd0;
            science_output_mode_cmac <= 3'd0;
            spec_enable_cmac_meta <= 1'b0;
            spec_enable_cmac <= 1'b0;
            pfb_enable_cmac_meta <= 1'b0;
            pfb_enable_cmac <= 1'b0;
            pfb_fft_shift_cmac_meta <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_fft_shift_cmac <= FFT_ONLY_DEFAULT_SHIFT;
            rfdc_sample_count_cmac_meta <= 64'd0;
            rfdc_sample_count_cmac <= 64'd0;
            ctrl_board_id_cmac_meta <= 16'd0;
            ctrl_board_id_cmac <= 16'd0;
            tx_clear_toggle_cmac_sync <= 3'b000;
            tx_clear_toggle_cmac_seen <= 1'b0;
            time_ddr_ring_clear_toggle_cmac_sync <= 3'b000;
            time_ddr_ring_clear_toggle_cmac_seen <= 1'b0;
            packet_stream_reset_toggle_cmac_sync <= 3'b000;
            packet_stream_reset_toggle_cmac_seen <= 1'b0;
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
            time_ddr_ring_enable_meta <= ctrl_time_ddr_ring_enable;
            time_ddr_ring_enable_cmac <= time_ddr_ring_enable_meta;
            time_ddr_ring_base_meta <= ctrl_time_ddr_ring_base_addr;
            time_ddr_ring_base_cmac <= time_ddr_ring_base_meta;
            time_ddr_ring_slots_meta <= ctrl_time_ddr_ring_slots;
            time_ddr_ring_slots_cmac <= time_ddr_ring_slots_meta;
            tx_link_status_flags_cmac_meta <= tx_link_status_flags;
            tx_link_status_flags_cmac <= tx_link_status_flags_cmac_meta;
            tx_control_cmac_meta <= tx_control;
            tx_control_cmac <= tx_control_cmac_meta;
            science_output_mode_cmac_meta <= science_output_mode;
            science_output_mode_cmac <= science_output_mode_cmac_meta;
            spec_enable_cmac_meta <= spec_enable;
            spec_enable_cmac <= spec_enable_cmac_meta;
            pfb_enable_cmac_meta <= pfb_enable_sync[1];
            pfb_enable_cmac <= pfb_enable_cmac_meta;
            pfb_fft_shift_cmac_meta <= pfb_fft_shift;
            pfb_fft_shift_cmac <= pfb_fft_shift_cmac_meta;
            rfdc_sample_count_cmac_meta <= rfdc_sample_count;
            rfdc_sample_count_cmac <= rfdc_sample_count_cmac_meta;
            ctrl_board_id_cmac_meta <= ctrl_board_id;
            ctrl_board_id_cmac <= ctrl_board_id_cmac_meta;
            tx_clear_toggle_cmac_sync <= {tx_clear_toggle_cmac_sync[1:0], ctrl_tx_clear_toggle};
            tx_clear_toggle_cmac_seen <= tx_clear_toggle_cmac_sync[2];
            time_ddr_ring_clear_toggle_cmac_sync <= {
                time_ddr_ring_clear_toggle_cmac_sync[1:0],
                ctrl_time_ddr_ring_clear_toggle
            };
            time_ddr_ring_clear_toggle_cmac_seen <= time_ddr_ring_clear_toggle_cmac_sync[2];
            packet_stream_reset_toggle_cmac_sync <= {
                packet_stream_reset_toggle_cmac_sync[1:0],
                packet_stream_reset_toggle_cmac_src
            };
            packet_stream_reset_toggle_cmac_seen <= packet_stream_reset_toggle_cmac_sync[2];
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
            spec_dropped_count_ctrl_meta    <= 32'd0;
            spec_dropped_count_ctrl         <= 32'd0;
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
            pfb_data_halt_count_ctrl_meta   <= 32'd0;
            pfb_data_halt_count_ctrl        <= 32'd0;
            pfb_xfft_event_count_ctrl_meta  <= 32'd0;
            pfb_xfft_event_count_ctrl       <= 32'd0;
            pfb_tile_overflow_count_ctrl_meta <= 32'd0;
            pfb_tile_overflow_count_ctrl      <= 32'd0;
            pfb_xfft_tlast_unexpected_count_ctrl_meta <= 32'd0;
            pfb_xfft_tlast_unexpected_count_ctrl      <= 32'd0;
            pfb_xfft_tlast_missing_count_ctrl_meta <= 32'd0;
            pfb_xfft_tlast_missing_count_ctrl      <= 32'd0;
            pfb_xfft_fft_overflow_count_ctrl_meta <= 32'd0;
            pfb_xfft_fft_overflow_count_ctrl      <= 32'd0;
            pfb_xfft_data_out_halt_count_ctrl_meta <= 32'd0;
            pfb_xfft_data_out_halt_count_ctrl      <= 32'd0;
            pfb_xfft_status_halt_count_ctrl_meta <= 32'd0;
            pfb_xfft_status_halt_count_ctrl      <= 32'd0;
            pfb_capture_backpressure_count_ctrl_meta <= 32'd0;
            pfb_capture_backpressure_count_ctrl      <= 32'd0;
            pfb_frame_sample0_overflow_count_ctrl_meta <= 32'd0;
            pfb_frame_sample0_overflow_count_ctrl      <= 32'd0;
            pfb_input_fifo_level_ctrl_meta  <= 32'd0;
            pfb_input_fifo_level_ctrl       <= 32'd0;
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
            science_dropped_beat_count_ctrl_meta <= 32'd0;
            science_dropped_beat_count_ctrl      <= 32'd0;
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
            tx_cmac_source_status_ctrl_meta     <= 32'd0;
            tx_cmac_source_status_ctrl          <= 32'd0;
            tx_cmac_test_packet_count_ctrl_meta <= 32'd0;
            tx_cmac_test_packet_count_ctrl      <= 32'd0;
            tx_cmac_test_byte_count_ctrl_meta   <= 32'd0;
            tx_cmac_test_byte_count_ctrl        <= 32'd0;
            tx_link_status_flags_ctrl_meta      <= 32'd0;
            tx_link_status_flags_ctrl           <= 32'd0;
            tx_selected_endpoint_id_ctrl_meta   <= 8'd0;
            tx_selected_endpoint_id_ctrl        <= 8'd0;
            tx_selected_route_id_ctrl_meta      <= 6'd0;
            tx_selected_route_id_ctrl           <= 6'd0;
            tx_selected_route_is_time_ctrl_meta <= 1'b0;
            tx_selected_route_is_time_ctrl      <= 1'b0;
            tx_spec_route_hit_counts_ctrl_meta  <= {TX_SPEC_ROUTES*32{1'b0}};
            tx_spec_route_hit_counts_ctrl       <= {TX_SPEC_ROUTES*32{1'b0}};
            tx_time_route_hit_counts_ctrl_meta  <= 256'd0;
            tx_time_route_hit_counts_ctrl       <= 256'd0;
            time_ddr_ring_status_ctrl_meta      <= 32'd0;
            time_ddr_ring_status_ctrl           <= 32'd0;
            time_ddr_ring_occupancy_ctrl_meta   <= 32'd0;
            time_ddr_ring_occupancy_ctrl        <= 32'd0;
            time_ddr_ring_write_count_ctrl_meta <= 32'd0;
            time_ddr_ring_write_count_ctrl      <= 32'd0;
            time_ddr_ring_read_count_ctrl_meta  <= 32'd0;
            time_ddr_ring_read_count_ctrl       <= 32'd0;
            time_ddr_ring_drop_count_ctrl_meta  <= 32'd0;
            time_ddr_ring_drop_count_ctrl       <= 32'd0;
            time_ddr_ring_error_count_ctrl_meta <= 32'd0;
            time_ddr_ring_error_count_ctrl      <= 32'd0;
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
            spec_dropped_count_ctrl_meta    <= spec_duplicator_dropped_count;
            spec_dropped_count_ctrl         <= spec_dropped_count_ctrl_meta;
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
            pfb_data_halt_count_ctrl_meta   <= pfb_data_halt_count;
            pfb_data_halt_count_ctrl        <= pfb_data_halt_count_ctrl_meta;
            pfb_xfft_event_count_ctrl_meta  <= pfb_xfft_event_count;
            pfb_xfft_event_count_ctrl       <= pfb_xfft_event_count_ctrl_meta;
            pfb_tile_overflow_count_ctrl_meta <= pfb_tile_overflow_count;
            pfb_tile_overflow_count_ctrl      <= pfb_tile_overflow_count_ctrl_meta;
            pfb_xfft_tlast_unexpected_count_ctrl_meta <= pfb_xfft_tlast_unexpected_count;
            pfb_xfft_tlast_unexpected_count_ctrl      <= pfb_xfft_tlast_unexpected_count_ctrl_meta;
            pfb_xfft_tlast_missing_count_ctrl_meta <= pfb_xfft_tlast_missing_count;
            pfb_xfft_tlast_missing_count_ctrl      <= pfb_xfft_tlast_missing_count_ctrl_meta;
            pfb_xfft_fft_overflow_count_ctrl_meta <= pfb_xfft_fft_overflow_count;
            pfb_xfft_fft_overflow_count_ctrl      <= pfb_xfft_fft_overflow_count_ctrl_meta;
            pfb_xfft_data_out_halt_count_ctrl_meta <= pfb_xfft_data_out_halt_count;
            pfb_xfft_data_out_halt_count_ctrl      <= pfb_xfft_data_out_halt_count_ctrl_meta;
            pfb_xfft_status_halt_count_ctrl_meta <= pfb_xfft_status_halt_count;
            pfb_xfft_status_halt_count_ctrl      <= pfb_xfft_status_halt_count_ctrl_meta;
            pfb_capture_backpressure_count_ctrl_meta <= pfb_capture_backpressure_count;
            pfb_capture_backpressure_count_ctrl      <= pfb_capture_backpressure_count_ctrl_meta;
            pfb_frame_sample0_overflow_count_ctrl_meta <= pfb_frame_sample0_overflow_count;
            pfb_frame_sample0_overflow_count_ctrl      <= pfb_frame_sample0_overflow_count_ctrl_meta;
            pfb_input_fifo_level_ctrl_meta  <= pfb_input_fifo_level;
            pfb_input_fifo_level_ctrl       <= pfb_input_fifo_level_ctrl_meta;
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
            science_dropped_beat_count_ctrl_meta <= science_dropped_beat_count;
            science_dropped_beat_count_ctrl      <= science_dropped_beat_count_ctrl_meta;
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
            tx_cmac_source_status_ctrl_meta     <= tx_cmac_source_status;
            tx_cmac_source_status_ctrl          <= tx_cmac_source_status_ctrl_meta;
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
            time_ddr_ring_status_ctrl_meta      <= time_ddr_ring_status;
            time_ddr_ring_status_ctrl           <= time_ddr_ring_status_ctrl_meta;
            time_ddr_ring_occupancy_ctrl_meta   <= time_ddr_ring_occupancy;
            time_ddr_ring_occupancy_ctrl        <= time_ddr_ring_occupancy_ctrl_meta;
            time_ddr_ring_write_count_ctrl_meta <= time_ddr_ring_write_count;
            time_ddr_ring_write_count_ctrl      <= time_ddr_ring_write_count_ctrl_meta;
            time_ddr_ring_read_count_ctrl_meta  <= time_ddr_ring_read_count;
            time_ddr_ring_read_count_ctrl       <= time_ddr_ring_read_count_ctrl_meta;
            time_ddr_ring_drop_count_ctrl_meta  <= time_ddr_ring_drop_count;
            time_ddr_ring_drop_count_ctrl       <= time_ddr_ring_drop_count_ctrl_meta;
            time_ddr_ring_error_count_ctrl_meta <= time_ddr_ring_error_count;
            time_ddr_ring_error_count_ctrl      <= time_ddr_ring_error_count_ctrl_meta;
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
        .aa100_active(science_aa100_active),
        .aa100_primed(science_aa100_primed),
        .aa100_coeff_version(science_aa100_coeff_version),
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

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign debug_busy_ctrl = 1'b0;
    assign debug_done_ctrl = 1'b0;
    assign debug_error_ctrl = 1'b0;
    assign debug_capture_count_ctrl = 32'd0;
    assign debug_peak_bin_ctrl = 32'd0;
    assign debug_peak_power_ctrl = 32'd0;
    assign debug_time_rd_data_ctrl = 32'd0;
    assign debug_fft_rd_data_ctrl = 32'd0;
`else
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
`endif

    multi_preview_observer #(
        .PRODUCTION_27H(CTRL_PRODUCTION_27H)
    ) u_multi_preview_observer (
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

`ifdef T510_STAGE27I_RAW_WITNESS
`define T510_INCLUDE_RFDC_AXIS_RAW_WITNESS_CAPTURE
`elsif T510_STAGE27H_PRODUCTION_ONLY
`else
`define T510_INCLUDE_RFDC_AXIS_RAW_WITNESS_CAPTURE
`endif

`ifdef T510_INCLUDE_RFDC_AXIS_RAW_WITNESS_CAPTURE
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
        .s_axis_adc_tdata0(s_axis_raw_witness_tdata0),
        .s_axis_adc_tdata1(s_axis_raw_witness_tdata1),
        .s_axis_adc_tdata2(s_axis_raw_witness_tdata2),
        .s_axis_adc_tdata3(s_axis_raw_witness_tdata3),
        .s_axis_adc_sample0(s_axis_raw_witness_sample0),
        .s_axis_adc_tvalid(s_axis_raw_witness_tvalid),
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
`else
    assign rfdc_axis_raw_witness_rd_data_ctrl = 32'd0;
    assign rfdc_axis_raw_witness_armed_ctrl = 1'b0;
    assign rfdc_axis_raw_witness_valid_ctrl = 1'b0;
    assign rfdc_axis_raw_witness_capturing_ctrl = 1'b0;
    assign rfdc_axis_raw_witness_overflow_ctrl = 1'b0;
    assign rfdc_axis_raw_witness_tvalid_seen_ctrl = 1'b0;
    assign rfdc_axis_raw_witness_beat_count_ctrl = 9'd0;
    assign rfdc_axis_raw_witness_channel_select_ctrl = 3'd0;
    assign rfdc_axis_raw_witness_sample0_ctrl = 64'd0;
    assign rfdc_axis_raw_witness_rfdc_flags_ctrl = 32'd0;
    assign rfdc_axis_raw_witness_valid_mask_ctrl = 16'd0;
`endif
`ifdef T510_INCLUDE_RFDC_AXIS_RAW_WITNESS_CAPTURE
`undef T510_INCLUDE_RFDC_AXIS_RAW_WITNESS_CAPTURE
`endif

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
        .spec_drop_when_full(1'b0),
        .time_drop_when_full(1'b0),
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
        .dropped_spec_count(spec_duplicator_dropped_count),
        .dropped_time_count(time_duplicator_dropped_count),
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

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign pfb_spec_cmac_sideband = {
        pfb_status,
        pfb_fft_shift_cmac,
        16'd0,
        pfb_packet_time_count,
        pfb_packet_chan_count,
        pfb_packet_chan0,
        pfb_spec_cmac_sample0
    };
    assign pfb_spec_sample0 = pfb_spec_sideband[0 +: 64];
    assign pfb_packet_chan0_data = pfb_spec_sideband[64 +: 32];
    assign pfb_packet_chan_count_data = pfb_spec_sideband[96 +: 16];
    assign pfb_packet_time_count_data = pfb_spec_sideband[112 +: 16];
    assign pfb_taps_data = pfb_spec_sideband[128 +: 16];
    assign pfb_fft_shift_data = pfb_spec_sideband[144 +: 16];
    assign pfb_status_data = pfb_spec_sideband[160 +: 32];

    axis_sideband_async_fifo #(
        .DATA_W(SCIENCE_DATA_W),
        .SIDE_W(64),
        .DEPTH(4096),
        .COUNT_W(13)
    ) u_spec_feng_input_cdc (
        .s_clk(clk),
        .s_rst_n(rst_n),
        .s_clear(packet_stream_reset_pulse || pfb_clear_pulse),
        .s_axis_tdata(quant_spec_tdata),
        .s_axis_tside(spec_input_sample0),
        .s_axis_tvalid(spec_tvalid && spec_live_requested_data),
        .s_axis_tready(spec_feng_input_cdc_ready),
        .m_clk(cmac_tx_clk),
        .m_rst_n(cmac_tx_rst_n),
        .m_clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
        .m_axis_tdata(spec_feng_cmac_tdata),
        .m_axis_tside(spec_feng_cmac_sample0),
        .m_axis_tvalid(spec_feng_cmac_tvalid),
        .m_axis_tready(spec_feng_cmac_tready),
        .wr_level_words(spec_feng_cmac_wr_level_words),
        .rd_level_words(spec_feng_cmac_rd_level_words),
        .fifo_full(spec_feng_cmac_fifo_full),
        .fifo_empty(spec_feng_cmac_fifo_empty)
    );
    assign spec_tready = spec_live_requested_data ? spec_feng_input_cdc_ready : 1'b1;

    pfb_channelizer #(
        .DATA_W(SCIENCE_DATA_W),
        .NINPUT(8),
        .NCHAN(4096)
    ) u_pfb_channelizer (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .enable(spec_enable_cmac && pfb_enable_cmac),
        .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
        .cfg_taps(16'd0),
        .cfg_fft_shift(pfb_fft_shift_cmac),
        .cfg_chan0(32'd0),
        .cfg_chan_count(16'd256),
        .cfg_time_count(16'd1),
        .s_axis_tdata(spec_feng_cmac_tdata),
        .s_axis_sample0(spec_feng_cmac_sample0),
        .s_axis_tvalid(spec_feng_cmac_tvalid),
        .s_axis_tready(spec_feng_cmac_tready),
        .m_axis_tdata(pfb_spec_cmac_tdata),
        .m_axis_sample0(pfb_spec_cmac_sample0),
        .m_axis_tvalid(pfb_spec_cmac_tvalid),
        .m_axis_tready(pfb_spec_cmac_tready),
        .status(pfb_status),
        .frame_count(pfb_frame_count),
        .overflow_count(pfb_overflow_count),
        .data_halt_count(pfb_data_halt_count),
        .xfft_event_count(pfb_xfft_event_count),
        .tile_overflow_count(pfb_tile_overflow_count),
        .xfft_tlast_unexpected_count(pfb_xfft_tlast_unexpected_count),
        .xfft_tlast_missing_count(pfb_xfft_tlast_missing_count),
        .xfft_fft_overflow_count(pfb_xfft_fft_overflow_count),
        .xfft_data_out_halt_count(pfb_xfft_data_out_halt_count),
        .xfft_status_halt_count(pfb_xfft_status_halt_count),
        .capture_backpressure_count(pfb_capture_backpressure_count),
        .frame_sample0_overflow_count(pfb_frame_sample0_overflow_count),
        .input_fifo_level(pfb_input_fifo_level),
        .peak_chan(pfb_peak_chan),
        .peak_power(pfb_peak_power),
        .packet_chan0(pfb_packet_chan0),
        .packet_chan_count(pfb_packet_chan_count),
        .packet_time_count(pfb_packet_time_count)
    );

    axis_sideband_async_fifo #(
        .DATA_W(SCIENCE_DATA_W),
        .SIDE_W(192),
        .DEPTH(4096),
        .COUNT_W(13)
    ) u_spec_feng_output_cdc (
        .s_clk(cmac_tx_clk),
        .s_rst_n(cmac_tx_rst_n),
        .s_clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
        .s_axis_tdata(pfb_spec_cmac_tdata),
        .s_axis_tside(pfb_spec_cmac_sideband),
        .s_axis_tvalid(pfb_spec_cmac_tvalid),
        .s_axis_tready(pfb_spec_cmac_tready),
        .m_clk(clk),
        .m_rst_n(rst_n),
        .m_clear(packet_stream_reset_pulse || pfb_clear_pulse),
        .m_axis_tdata(pfb_spec_tdata),
        .m_axis_tside(pfb_spec_sideband),
        .m_axis_tvalid(pfb_spec_tvalid),
        .m_axis_tready(pfb_spec_tready),
        .wr_level_words(pfb_spec_cmac_to_data_wr_level_words),
        .rd_level_words(pfb_spec_cmac_to_data_rd_level_words),
        .fifo_full(pfb_spec_cmac_to_data_fifo_full),
        .fifo_empty(pfb_spec_cmac_to_data_fifo_empty)
    );
`else
    assign spec_feng_cmac_tdata = {SCIENCE_DATA_W{1'b0}};
    assign spec_feng_cmac_sample0 = 64'd0;
    assign spec_feng_cmac_tvalid = 1'b0;
    assign spec_feng_cmac_tready = 1'b0;
    assign spec_feng_cmac_fifo_full = 1'b0;
    assign spec_feng_cmac_fifo_empty = 1'b1;
    assign spec_feng_cmac_wr_level_words = 32'd0;
    assign spec_feng_cmac_rd_level_words = 32'd0;
    assign pfb_spec_cmac_tdata = {SCIENCE_DATA_W{1'b0}};
    assign pfb_spec_cmac_sample0 = 64'd0;
    assign pfb_spec_cmac_tvalid = 1'b0;
    assign pfb_spec_cmac_tready = 1'b0;
    assign pfb_spec_cmac_to_data_fifo_full = 1'b0;
    assign pfb_spec_cmac_to_data_fifo_empty = 1'b1;
    assign pfb_spec_cmac_to_data_wr_level_words = 32'd0;
    assign pfb_spec_cmac_to_data_rd_level_words = 32'd0;
    assign pfb_spec_cmac_sideband = 192'd0;
    assign pfb_spec_sideband = 192'd0;
    assign pfb_packet_chan0_data = pfb_packet_chan0;
    assign pfb_packet_chan_count_data = pfb_packet_chan_count;
    assign pfb_packet_time_count_data = pfb_packet_time_count;
    assign pfb_taps_data = pfb_taps;
    assign pfb_fft_shift_data = pfb_fft_shift;
    assign pfb_status_data = pfb_status;

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
        .data_halt_count(pfb_data_halt_count),
        .xfft_event_count(pfb_xfft_event_count),
        .tile_overflow_count(pfb_tile_overflow_count),
        .xfft_tlast_unexpected_count(pfb_xfft_tlast_unexpected_count),
        .xfft_tlast_missing_count(pfb_xfft_tlast_missing_count),
        .xfft_fft_overflow_count(pfb_xfft_fft_overflow_count),
        .xfft_data_out_halt_count(pfb_xfft_data_out_halt_count),
        .xfft_status_halt_count(pfb_xfft_status_halt_count),
        .capture_backpressure_count(pfb_capture_backpressure_count),
        .frame_sample0_overflow_count(pfb_frame_sample0_overflow_count),
        .input_fifo_level(pfb_input_fifo_level),
        .peak_chan(pfb_peak_chan),
        .peak_power(pfb_peak_power),
        .packet_chan0(pfb_packet_chan0),
        .packet_chan_count(pfb_packet_chan_count),
        .packet_time_count(pfb_packet_time_count)
    );
`endif

    assign spec_product_status_flags = {
        22'd0,
        science_aa100_active && (science_bandwidth_mode == 2'd1),
        pfb_status_data[8],
        pfb_status_data[7:0]
    };

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign legacy_pfb_spec_tready = 1'b0;
    assign spec_axis_tdata = 64'd0;
    assign spec_axis_tkeep = 8'd0;
    assign spec_axis_tvalid = 1'b0;
    assign spec_axis_tlast = 1'b0;
    assign legacy_spec_packet_count = 32'd0;
    assign legacy_spec_udp_byte_count = 32'd0;
    assign legacy_spec_seq_no = 32'd0;
    assign legacy_spec_frame_id = 64'd0;
    assign legacy_spec_chan0 = 32'd0;
`else
    spectral_packetizer #(
        .DATA_W(SCIENCE_DATA_W),
        .OUT_W(64),
        .HEADER_WORDS(16)
    ) u_spectral_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable(spec_enable && !spec_live_requested_data),
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
        .spec_nchan(16'd4096),
        .spec_taps(pfb_taps_data),
        .spec_fft_shift(pfb_fft_shift_data),
        .spec_sample_rate_hz(sample_rate_hz),
        .spec_status_flags(spec_product_status_flags),
        .chan_split(chan_split),
        .s_axis_tdata(pfb_spec_tdata),
        .s_axis_sample0(pfb_spec_sample0),
        .s_axis_tvalid(pfb_spec_tvalid && !spec_live_requested_data),
        .s_axis_tready(legacy_pfb_spec_tready),
        .m_axis_tdata(spec_axis_tdata),
        .m_axis_tkeep(spec_axis_tkeep),
        .m_axis_tvalid(spec_axis_tvalid),
        .m_axis_tlast(spec_axis_tlast),
        .m_axis_tready(spec_axis_tready),
        .packet_count(legacy_spec_packet_count),
        .udp_byte_count(legacy_spec_udp_byte_count),
        .seq_no_debug(legacy_spec_seq_no),
        .frame_id_debug(legacy_spec_frame_id),
        .chan0_debug(legacy_spec_chan0)
    );
`endif

    spec_udp_cmac512 #(
        .DATA_W(SCIENCE_DATA_W),
        .N_ENDPOINTS(TX_ENDPOINTS),
        .N_SPEC_ROUTES(TX_SPEC_ROUTES),
        .DATA_FIFO_DEPTH(1024),
        .DATA_COUNT_W(11),
        .TOKEN_FIFO_DEPTH(64),
        .TOKEN_COUNT_W(7),
        .PRODUCTION_27H(CTRL_PRODUCTION_27H)
    ) u_spec_udp_cmac512 (
        .s_clk(clk),
        .s_rst_n(rst_n),
        .s_clear(packet_stream_reset_pulse || tx_clear_pulse),
        .enable(spec_enable && spec_live_requested_data),
        .drop_on_route_miss(tx_control[3]),
        .board_id(board_id),
        .global_input0({board_id[12:0], 3'b000}),
        .epoch_mode(udp_epoch_mode),
        .packet_flags(udp_packet_flags),
        .unix_seconds(unix_seconds),
        .pps_count(pps_count),
        .quant_mode(quant_mode),
        .scale_mode(scale_mode),
        .scale_id(scale_id),
        .spec_chan0(pfb_packet_chan0_data),
        .spec_chan_count(pfb_packet_chan_count_data),
        .spec_time_count(pfb_packet_time_count_data),
        .spec_nchan(16'd4096),
        .spec_taps(pfb_taps_data),
        .spec_fft_shift(pfb_fft_shift_data),
        .spec_sample_rate_hz(sample_rate_hz),
        .spec_status_flags(spec_product_status_flags),
        .chan_split(chan_split),
        .src_mac(src_mac),
        .src_ip(src_ip),
        .endpoint_enable(tx_endpoint_enable),
        .endpoint_ip_vec(tx_endpoint_ip_vec),
        .endpoint_mac_vec(tx_endpoint_mac_vec),
        .endpoint_src_port_vec(tx_endpoint_src_port_vec),
        .endpoint_dst_port_vec(tx_endpoint_dst_port_vec),
        .spec_route_enable(tx_spec_route_enable),
        .spec_route_chan0_vec(tx_spec_route_chan0_vec),
        .spec_route_chan_count_vec(tx_spec_route_chan_count_vec),
        .spec_route_endpoint_vec(tx_spec_route_endpoint_vec),
        .s_axis_tdata(pfb_spec_tdata),
        .s_axis_sample0(pfb_spec_sample0),
        .s_axis_tvalid(pfb_spec_tvalid && spec_live_requested_data),
        .s_axis_tready(wide_pfb_spec_tready),
        .m_clk(cmac_tx_clk),
        .m_rst_n(cmac_tx_rst_n),
        .m_clear(tx_clear_pulse_cmac),
        .m_axis_tdata(wide_spec_live_cmac_tdata),
        .m_axis_tkeep(wide_spec_live_cmac_tkeep),
        .m_axis_tvalid(wide_spec_live_cmac_tvalid),
        .m_axis_tlast(wide_spec_live_cmac_tlast),
        .m_axis_tready(wide_spec_live_cmac_tready),
        .packet_count(wide_spec_packet_count),
        .udp_byte_count(wide_spec_udp_byte_count),
        .frame_built_count(wide_spec_tx_frame_built_count),
        .frame_byte_count(wide_spec_tx_frame_byte_count),
        .frame_dropped_count(wide_spec_tx_route_dropped_count),
        .route_miss_count(wide_spec_tx_route_miss_count),
        .route_error_count(wide_spec_tx_route_error_count),
        .seq_no_debug(wide_spec_seq_no),
        .sample0_debug(wide_spec_sample0),
        .frame_id_debug(wide_spec_frame_id),
        .chan0_debug(wide_spec_chan0),
        .selected_endpoint_id(wide_spec_tx_selected_endpoint_id),
        .selected_route_id(wide_spec_tx_selected_route_id),
        .selected_route_is_time(wide_spec_tx_selected_route_is_time),
        .spec_route_hit_count_vec(wide_spec_tx_route_hit_counts),
        .fifo_level_words(),
        .output_frame_count(),
        .backpressure_cycles(),
        .fifo_full(),
        .fifo_empty()
    );
    assign wide_spec_tx_route_forwarded_count = wide_spec_tx_frame_built_count;

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign legacy_time_tready = 1'b0;
    assign time_axis_tdata = 64'd0;
    assign time_axis_tkeep = 8'd0;
    assign time_axis_tvalid = 1'b0;
    assign time_axis_tlast = 1'b0;
    assign legacy_time_packet_count = 32'd0;
    assign legacy_time_dropped_count = 32'd0;
    assign legacy_time_udp_byte_count = 32'd0;
    assign legacy_time_seq_no = 32'd0;
    assign legacy_time_sample0 = 64'd0;
    assign legacy_time_frame_id = 64'd0;
`else
    time_packetizer #(
        .DATA_W(SCIENCE_DATA_W),
        .OUT_W(64),
        .HEADER_WORDS(16)
    ) u_time_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable(time_enable && !time_live_full_rate_data),
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
        .packet_interval_beats(time_live_interval_beats),
        .s_axis_tdata(time_tdata),
        .s_axis_sample0(time_input_sample0),
        .s_axis_tvalid(time_tvalid && !time_live_full_rate_data),
        .s_axis_tready(legacy_time_tready),
        .m_axis_tdata(time_axis_tdata),
        .m_axis_tkeep(time_axis_tkeep),
        .m_axis_tvalid(time_axis_tvalid),
        .m_axis_tlast(time_axis_tlast),
        .m_axis_tready(time_axis_tready),
        .packet_count(legacy_time_packet_count),
        .dropped_count(legacy_time_dropped_count),
        .udp_byte_count(legacy_time_udp_byte_count),
        .seq_no_debug(legacy_time_seq_no),
        .sample0_debug(legacy_time_sample0),
        .frame_id_debug(legacy_time_frame_id)
    );
`endif

    time_udp_cmac512 #(
        .DATA_W(SCIENCE_DATA_W),
        .N_ENDPOINTS(TX_ENDPOINTS),
        .N_TIME_ROUTES(TX_TIME_ROUTES),
        .DATA_FIFO_DEPTH(256),
        .DATA_COUNT_W(9),
        .TOKEN_FIFO_DEPTH(16),
        .TOKEN_COUNT_W(5)
    ) u_time_udp_cmac512 (
        .s_clk(clk),
        .s_rst_n(rst_n),
        .s_clear(packet_stream_reset_pulse || tx_clear_pulse),
        .enable(time_enable && time_live_full_rate_data),
        .drop_on_route_miss(tx_control[3]),
        .board_id(board_id),
        .global_input0({board_id[12:0], 3'b000}),
        .epoch_mode(udp_epoch_mode),
        .packet_flags(udp_packet_flags),
        .unix_seconds(unix_seconds),
        .pps_count(pps_count),
        .quant_mode(quant_mode),
        .scale_id(scale_id),
        .src_mac(src_mac),
        .src_ip(src_ip),
        .time_input_mask({8'd0, rfdc_active_mask[7:0]}),
        .endpoint_enable(tx_endpoint_enable),
        .endpoint_ip_vec(tx_endpoint_ip_vec),
        .endpoint_mac_vec(tx_endpoint_mac_vec),
        .endpoint_src_port_vec(tx_endpoint_src_port_vec),
        .endpoint_dst_port_vec(tx_endpoint_dst_port_vec),
        .time_route_enable(tx_time_route_enable),
        .time_route_input_mask_vec(tx_time_route_input_mask_vec),
        .time_route_endpoint_vec(tx_time_route_endpoint_vec),
        .time_multiflow_enable(time_multiflow_enable),
        .time_multiflow_base_endpoint(time_multiflow_base_endpoint),
        .time_multiflow_count(time_multiflow_count),
        .s_axis_tdata(time_tdata),
        .s_axis_sample0(time_input_sample0),
        .s_axis_tvalid(time_tvalid && time_live_full_rate_data),
        .s_axis_tready(wide_time_tready),
        .m_clk(cmac_tx_clk),
        .m_rst_n(cmac_tx_rst_n),
        .m_clear(tx_clear_pulse_cmac),
        .m_axis_tdata(wide_time_live_cmac_tdata),
        .m_axis_tkeep(wide_time_live_cmac_tkeep),
        .m_axis_tvalid(wide_time_live_cmac_tvalid),
        .m_axis_tlast(wide_time_live_cmac_tlast),
        .m_axis_tready(wide_time_live_cmac_tready),
        .packet_count(wide_time_packet_count),
        .udp_byte_count(wide_time_udp_byte_count),
        .frame_built_count(wide_tx_frame_built_count),
        .frame_byte_count(wide_tx_frame_byte_count),
        .frame_dropped_count(wide_tx_route_dropped_count),
        .route_miss_count(wide_tx_route_miss_count),
        .route_error_count(wide_tx_route_error_count),
        .seq_no_debug(wide_time_seq_no),
        .sample0_debug(wide_time_sample0),
        .frame_id_debug(wide_time_frame_id),
        .selected_endpoint_id(wide_tx_selected_endpoint_id),
        .selected_route_id(wide_tx_selected_route_id),
        .selected_route_is_time(wide_tx_selected_route_is_time),
        .time_route_hit_count_vec(wide_tx_time_route_hit_counts),
        .fifo_level_words(wide_time_live_bridge_fifo_level),
        .output_frame_count(wide_time_live_bridge_output_frames),
        .backpressure_cycles(wide_time_live_bridge_backpressure_cycles),
        .fifo_full(wide_time_live_bridge_fifo_full),
        .fifo_empty(wide_time_live_bridge_fifo_empty)
    );
    assign wide_tx_route_forwarded_count = wide_tx_frame_built_count;
    assign wide_time_dropped_count = wide_tx_route_dropped_count;
    assign wide_time_live_bridge_input_frames = wide_tx_frame_built_count;
    assign wide_time_live_bridge_s_tready = wide_time_tready;

    assign snapshot_tready = 1'b1;
    assign monitor_tready  = 1'b1;

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign spec_axis_tready = 1'b0;
    assign time_axis_tready = 1'b0;
    assign arb_tx_tdata = 64'd0;
    assign arb_tx_tkeep = 8'd0;
    assign arb_tx_tvalid = 1'b0;
    assign arb_tx_tlast = 1'b0;
    assign arb_tx_tready = 1'b0;
    assign tx_fifo_level_words = 32'd0;
    assign tx_fifo_high_water_words = 32'd0;
    assign tx_fifo_backpressure_cycles = 32'd0;
    assign tx_header_capture_rd_data_ctrl = 32'd0;
    assign tx_header_capture_armed_ctrl = 1'b0;
    assign tx_header_capture_valid_ctrl = 1'b0;
    assign tx_header_capture_word_count_ctrl = 5'd0;
    assign tx_frame_capture_rd_data_ctrl = 32'd0;
    assign tx_frame_capture_armed_ctrl = 1'b0;
    assign tx_frame_capture_valid_ctrl = 1'b0;
    assign tx_frame_capture_word_count_ctrl = 5'd0;
    assign internal_tx_tdata = 64'd0;
    assign internal_tx_tkeep = 8'd0;
    assign internal_tx_tvalid = 1'b0;
    assign internal_tx_tlast = 1'b0;
    assign internal_tx_tready = 1'b0;
    assign routed_tx_tdata = 64'd0;
    assign routed_tx_tkeep = 8'd0;
    assign routed_tx_tvalid = 1'b0;
    assign routed_tx_tlast = 1'b0;
    assign routed_tx_tready = 1'b0;
    assign routed_dst_mac = 48'd0;
    assign routed_dst_ip = 32'd0;
    assign routed_src_udp_port = 16'd0;
    assign routed_dst_udp_port = 16'd0;
    assign routed_t510_payload_bytes = 32'd0;
    assign routed_stream_type = 16'd0;
    assign routed_endpoint_id = 8'd0;
    assign routed_route_id = 6'd0;
    assign routed_route_is_time = 1'b0;
    assign legacy_tx_route_forwarded_count = 32'd0;
    assign legacy_tx_route_dropped_count = 32'd0;
    assign legacy_tx_route_miss_count = 32'd0;
    assign legacy_tx_route_error_count = 32'd0;
    assign legacy_tx_selected_endpoint_id = 8'd0;
    assign legacy_tx_selected_route_id = 6'd0;
    assign legacy_tx_selected_route_is_time = 1'b0;
    assign legacy_tx_spec_route_hit_counts = {TX_SPEC_ROUTES*32{1'b0}};
    assign legacy_tx_time_route_hit_counts = 256'd0;
    assign tx_payload_witness_rd_data_ctrl = 32'd0;
    assign tx_payload_witness_armed_ctrl = 1'b0;
    assign tx_payload_witness_valid_ctrl = 1'b0;
    assign tx_payload_witness_capturing_ctrl = 1'b0;
    assign tx_payload_witness_word_count_ctrl = 11'd0;
    assign tx_payload_witness_stream_type_ctrl = 16'd0;
    assign tx_payload_witness_sample0_ctrl = 64'd0;
    assign tx_payload_witness_frame_id_ctrl = 64'd0;
    assign tx_payload_witness_seq_no_ctrl = 32'd0;
    assign tx_payload_witness_chan0_ctrl = 32'd0;
    assign tx_payload_witness_layout_word_ctrl = 64'd0;
    assign tx_payload_witness_payload_bytes_ctrl = 32'd0;
    assign tx_payload_witness_route_meta_ctrl = 32'd0;
    assign tx_payload_witness_rfdc_flags_ctrl = 32'd0;
    assign tx_payload_witness_rfdc_sample_count_ctrl = 64'd0;
    assign tx_payload_witness_dac_phase_epoch_ctrl = 32'd0;
    assign tx_payload_witness_overflow_ctrl = 1'b0;
    assign tx_payload_witness_filter_mismatch_ctrl = 1'b0;
    assign frame_tx_tdata = 64'd0;
    assign frame_tx_tkeep = 8'd0;
    assign frame_tx_tvalid = 1'b0;
    assign frame_tx_tlast = 1'b0;
    assign legacy_tx_frame_built_count = 32'd0;
    assign legacy_tx_frame_byte_count = 32'd0;
    assign legacy_time_live_cmac_tdata = 512'd0;
    assign legacy_time_live_cmac_tkeep = 64'd0;
    assign legacy_time_live_cmac_tvalid = 1'b0;
    assign legacy_time_live_cmac_tlast = 1'b0;
    assign legacy_time_live_cmac_tready = 1'b0;
    assign legacy_time_live_bridge_s_tready = 1'b0;
    assign legacy_time_live_bridge_fifo_level = 32'd0;
    assign legacy_time_live_bridge_input_frames = 32'd0;
    assign legacy_time_live_bridge_output_frames = 32'd0;
    assign legacy_time_live_bridge_backpressure_cycles = 32'd0;
    assign legacy_time_live_bridge_fifo_full = 1'b0;
    assign legacy_time_live_bridge_fifo_empty = 1'b0;
`else
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
        .N_ENDPOINTS(TX_ENDPOINTS),
        .N_SPEC_ROUTES(TX_SPEC_ROUTES),
        .N_TIME_ROUTES(TX_TIME_ROUTES),
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
        .frame_forwarded_count(legacy_tx_route_forwarded_count),
        .frame_dropped_count(legacy_tx_route_dropped_count),
        .route_miss_count(legacy_tx_route_miss_count),
        .route_error_count(legacy_tx_route_error_count),
        .selected_endpoint_id(legacy_tx_selected_endpoint_id),
        .selected_route_id(legacy_tx_selected_route_id),
        .selected_route_is_time(legacy_tx_selected_route_is_time),
        .spec_route_hit_count_vec(legacy_tx_spec_route_hit_counts),
        .time_route_hit_count_vec(legacy_tx_time_route_hit_counts)
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
        .m_axis_tdata(frame_tx_tdata),
        .m_axis_tkeep(frame_tx_tkeep),
        .m_axis_tvalid(frame_tx_tvalid),
        .m_axis_tlast(frame_tx_tlast),
        .m_axis_tready(frame_tx_tready),
        .frame_built_count(legacy_tx_frame_built_count),
        .frame_byte_count(legacy_tx_frame_byte_count)
    );

    axis64_to_cmac512_async #(
        .FIFO_DEPTH(1024),
        .COUNT_W(11)
    ) u_time_live_cmac_bridge (
        .s_clk(clk),
        .s_rst_n(rst_n),
        .s_clear(packet_stream_reset_pulse || tx_clear_pulse),
        .s_axis_tdata(frame_tx_tdata),
        .s_axis_tkeep(frame_tx_tkeep),
        .s_axis_tvalid(frame_tx_tvalid && legacy_bridge_requested_data),
        .s_axis_tlast(frame_tx_tlast),
        .s_axis_tready(legacy_time_live_bridge_s_tready),
        .m_clk(cmac_tx_clk),
        .m_rst_n(cmac_tx_rst_n),
        .m_axis_tdata(legacy_time_live_cmac_tdata),
        .m_axis_tkeep(legacy_time_live_cmac_tkeep),
        .m_axis_tvalid(legacy_time_live_cmac_tvalid),
        .m_axis_tlast(legacy_time_live_cmac_tlast),
        .m_axis_tready(legacy_time_live_cmac_tready),
        .fifo_level_words(legacy_time_live_bridge_fifo_level),
        .input_frame_count(legacy_time_live_bridge_input_frames),
        .output_frame_count(legacy_time_live_bridge_output_frames),
        .backpressure_cycles(legacy_time_live_bridge_backpressure_cycles),
        .fifo_full(legacy_time_live_bridge_fifo_full),
        .fifo_empty(legacy_time_live_bridge_fifo_empty)
    );
`endif

`ifdef T510_STAGE27H_PRODUCTION_ONLY
    assign heartbeat_cmac_tdata = 512'd0;
    assign heartbeat_cmac_tkeep = 64'd0;
    assign heartbeat_cmac_tvalid = 1'b0;
    assign heartbeat_cmac_tlast = 1'b0;
    assign tx_cmac_test_packet_count = 32'd0;
    assign tx_cmac_test_byte_count = 32'd0;
`else
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
        .core_version(32'h0001_0028),
        .board_id(ctrl_board_id_cmac),
        .status_flags(tx_link_status_flags_cmac),
        .sample_count(rfdc_sample_count_cmac),
        .m_axis_tdata(heartbeat_cmac_tdata),
        .m_axis_tkeep(heartbeat_cmac_tkeep),
        .m_axis_tvalid(heartbeat_cmac_tvalid),
        .m_axis_tlast(heartbeat_cmac_tlast),
        .m_axis_tready(heartbeat_cmac_tready),
        .packet_count(tx_cmac_test_packet_count),
        .byte_count(tx_cmac_test_byte_count)
    );
`endif

    cmac_tx_source_mux u_cmac_tx_source_mux (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .clear(tx_clear_pulse_cmac),
        .select_time_live(time_live_full_rate_cmac),
        .select_spec_live(spec_live_requested_cmac),
        .heartbeat_tdata(heartbeat_cmac_tdata),
        .heartbeat_tkeep(heartbeat_cmac_tkeep),
        .heartbeat_tvalid(heartbeat_cmac_tvalid),
        .heartbeat_tlast(heartbeat_cmac_tlast),
        .heartbeat_tready(heartbeat_cmac_tready),
        .time_tdata(time_live_cmac_mux_tdata),
        .time_tkeep(time_live_cmac_mux_tkeep),
        .time_tvalid(time_live_cmac_mux_tvalid),
        .time_tlast(time_live_cmac_mux_tlast),
        .time_tready(time_live_cmac_mux_tready),
        .spec_tdata(wide_spec_live_cmac_tdata),
        .spec_tkeep(wide_spec_live_cmac_tkeep),
        .spec_tvalid(wide_spec_live_cmac_tvalid),
        .spec_tlast(wide_spec_live_cmac_tlast),
        .spec_tready(wide_spec_live_cmac_tready),
        .m_axis_tdata(cmac_mux_axis_tdata),
        .m_axis_tkeep(cmac_mux_axis_tkeep),
        .m_axis_tvalid(cmac_mux_axis_tvalid),
        .m_axis_tlast(cmac_mux_axis_tlast),
        .m_axis_tready(cmac_mux_axis_tready),
        .status(tx_cmac_source_mux_status)
    );

    axis512_register_slice #(
        .DATA_W(512),
        .KEEP_W(64),
        .DEPTH(2)
    ) u_cmac_tx_output_slice (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .clear(tx_clear_pulse_cmac),
        .s_axis_tdata(cmac_mux_axis_tdata),
        .s_axis_tkeep(cmac_mux_axis_tkeep),
        .s_axis_tvalid(cmac_mux_axis_tvalid),
        .s_axis_tlast(cmac_mux_axis_tlast),
        .s_axis_tready(cmac_mux_axis_tready),
        .m_axis_tdata(cmac_tx_axis_tdata),
        .m_axis_tkeep(cmac_tx_axis_tkeep),
        .m_axis_tvalid(cmac_tx_axis_tvalid),
        .m_axis_tlast(cmac_tx_axis_tlast),
        .m_axis_tready(cmac_tx_axis_tready)
    );

`ifndef T510_STAGE27H_PRODUCTION_ONLY
    tx_header_capture #(
        .DATA_W(64),
        .HEADER_WORDS(16)
    ) u_tx_frame_header_capture (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .arm_pulse_ctrl(ctrl_tx_frame_capture_arm_pulse),
        .s_axis_tdata(frame_tx_tdata),
        .s_axis_tvalid(frame_tx_tvalid),
        .s_axis_tlast(frame_tx_tlast),
        .s_axis_tready(frame_tx_tready),
        .ctrl_rd_word(ctrl_tx_frame_capture_rd_word),
        .ctrl_rd_data(tx_frame_capture_rd_data_ctrl),
        .ctrl_armed(tx_frame_capture_armed_ctrl),
        .ctrl_valid(tx_frame_capture_valid_ctrl),
        .ctrl_word_count(tx_frame_capture_word_count_ctrl)
    );
`endif

    feng_ctrl_axi #(
        .NINPUT(8),
        .N_TX_ENDPOINTS(TX_ENDPOINTS),
        .N_SPEC_ROUTES(TX_SPEC_ROUTES),
        .N_TIME_ROUTES(TX_TIME_ROUTES),
        .PRODUCTION_27H(CTRL_PRODUCTION_27H),
        .RAW_WITNESS_DIAGNOSTIC(RFDC_RAW_WITNESS_COMPILED)
    ) u_feng_ctrl_axi (
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
        .spec_dropped_count(spec_dropped_count_ctrl),
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
        .science_dropped_beat_count(science_dropped_beat_count_ctrl),
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
        .tx_cmac_source_status(tx_cmac_source_status_ctrl),
        .tx_selected_endpoint_id(tx_selected_endpoint_id_ctrl),
        .tx_selected_route_id(tx_selected_route_id_ctrl),
        .tx_selected_route_is_time(tx_selected_route_is_time_ctrl),
        .time_ddr_ring_status(time_ddr_ring_status_ctrl),
        .time_ddr_ring_occupancy(time_ddr_ring_occupancy_ctrl),
        .time_ddr_ring_write_count(time_ddr_ring_write_count_ctrl),
        .time_ddr_ring_read_count(time_ddr_ring_read_count_ctrl),
        .time_ddr_ring_drop_count(time_ddr_ring_drop_count_ctrl),
        .time_ddr_ring_error_count(time_ddr_ring_error_count_ctrl),
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
        .pfb_data_halt_count(pfb_data_halt_count_ctrl),
        .pfb_xfft_event_count(pfb_xfft_event_count_ctrl),
        .pfb_tile_overflow_count(pfb_tile_overflow_count_ctrl),
        .pfb_xfft_tlast_unexpected_count(pfb_xfft_tlast_unexpected_count_ctrl),
        .pfb_xfft_tlast_missing_count(pfb_xfft_tlast_missing_count_ctrl),
        .pfb_xfft_fft_overflow_count(pfb_xfft_fft_overflow_count_ctrl),
        .pfb_xfft_data_out_halt_count(pfb_xfft_data_out_halt_count_ctrl),
        .pfb_xfft_status_halt_count(pfb_xfft_status_halt_count_ctrl),
        .pfb_capture_backpressure_count(pfb_capture_backpressure_count_ctrl),
        .pfb_frame_sample0_overflow_count(pfb_frame_sample0_overflow_count_ctrl),
        .pfb_input_fifo_level(pfb_input_fifo_level_ctrl),
        .pfb_peak_chan(pfb_peak_chan_ctrl),
        .pfb_peak_power(pfb_peak_power_ctrl),
        .science_aa100_active(science_aa100_active),
        .science_aa100_primed(science_aa100_primed),
        .science_aa100_coeff_version(science_aa100_coeff_version),
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
        .diag_adc_force_zero(ctrl_diag_adc_force_zero),
        .diag_adc_force_hold(ctrl_diag_adc_force_hold),
        .diag_adc_channel_mask(ctrl_diag_adc_channel_mask),
        .diag_dac_gate(ctrl_diag_dac_gate),
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
        .time_live_interval_beats(ctrl_time_live_interval_beats),
        .time_ddr_ring_enable(ctrl_time_ddr_ring_enable),
        .time_ddr_ring_clear_pulse(ctrl_time_ddr_ring_clear_pulse),
        .time_ddr_ring_base_addr(ctrl_time_ddr_ring_base_addr),
        .time_ddr_ring_slots(ctrl_time_ddr_ring_slots),
        .time_multiflow_enable(ctrl_time_multiflow_enable),
        .time_multiflow_base_endpoint(ctrl_time_multiflow_base_endpoint),
        .time_multiflow_count(ctrl_time_multiflow_count),
        .science_bandwidth_mode_cfg(ctrl_science_bandwidth_mode_cfg),
        .science_output_mode_cfg(ctrl_science_output_mode_cfg)
    );

endmodule
