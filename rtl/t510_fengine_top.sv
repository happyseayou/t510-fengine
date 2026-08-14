module t510_fengine_top (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         ctrl_clk,
    input  wire         ctrl_rst_n,
    input  wire         pps_in,
    input  wire         ref_lock_in,
    input  wire         rfdc_ready_in,
    input  wire [31:0]  sysref_pl_edge_count_gray,
    input  wire [31:0]  sysref_adc_edge_count_gray,
    input  wire [31:0]  sysref_dac_edge_count_gray,
    input  wire [2:0]   sysref_capture_levels,
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
    output wire         irq
);

    localparam [1:0] MODE_SPEC     = 2'd0;
    localparam [1:0] MODE_TIME     = 2'd1;
    localparam [1:0] MODE_DUAL     = 2'd2;
    localparam [1:0] MODE_SNAPSHOT = 2'd3;
    localparam bit   TIME_DDR_RING_COMPILED = 1'b0;
    localparam integer TX_ENDPOINTS = 24;
    localparam integer TX_SPEC_ROUTES = 16;
    localparam integer TX_TIME_ROUTES = 8;
    localparam [2:0] SCIENCE_MODE_TIME_ONLY = 3'd1;
    localparam [2:0] SCIENCE_MODE_SPEC_ONLY = 3'd2;
    localparam [2:0] SCIENCE_MODE_TIME_SPEC = 3'd3;
    localparam [15:0] FFT_ONLY_DEFAULT_SHIFT = 16'h0556;
    integer tx_reset_idx;

    function automatic [31:0] gray32_to_binary(input [31:0] gray);
        integer gray_idx;
        begin
            gray32_to_binary[31] = gray[31];
            for (gray_idx = 30; gray_idx >= 0; gray_idx = gray_idx - 1)
                gray32_to_binary[gray_idx] = gray32_to_binary[gray_idx + 1] ^ gray[gray_idx];
        end
    endfunction

    wire [15:0] ctrl_board_id;
    wire [1:0]  ctrl_mode;
    wire        ctrl_arm_latched;
    wire        ctrl_soft_epoch_pulse;
    wire        ctrl_stop_pulse;
    wire        ctrl_soft_reset_pulse;
    wire        ctrl_scheduled_sync_prepare_pulse;
    wire        ctrl_scheduled_sync_arm_pulse;
    wire        ctrl_scheduled_sync_abort_pulse;
    wire        ctrl_scheduled_sync_clear_status_pulse;
    wire [63:0] ctrl_scheduled_sync_generation;
    wire [63:0] ctrl_scheduled_sync_target_pps_count;
    wire [63:0] ctrl_scheduled_sync_epoch_tai_seconds;
    wire [63:0] ctrl_scheduled_sync_first_sample0;
    wire [63:0] ctrl_scheduled_sync_observation_tag;
    wire [31:0] ctrl_scheduled_sync_signal_chain_tag;
    wire [31:0] ctrl_scheduled_sync_schedule_tag;
    wire [31:0] ctrl_mts_result_id;
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
    wire        ctrl_pfb_coeff_load_start_pulse;
    wire        ctrl_pfb_coeff_commit_pulse;
    wire        ctrl_pfb_coeff_abort_pulse;
    wire        ctrl_pfb_coeff_write_pulse;
    wire [3:0]  ctrl_pfb_coeff_requested_taps;
    wire [14:0] ctrl_pfb_coeff_index;
    wire signed [17:0] ctrl_pfb_coeff_data;
    wire [31:0] ctrl_pfb_coeff_id;
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
    wire        ctrl_preview_corrected_select;
    wire        ctrl_spur_corr_shadow_enable;
    wire        ctrl_spur_corr_shadow_in_band;
    wire        ctrl_spur_corr_shadow_bypass;
    wire        ctrl_spur_corr_shadow_phase_reload;
    wire [1:0]  ctrl_spur_corr_shadow_spur_id;
    wire [47:0] ctrl_spur_corr_shadow_phase_step;
    wire [47:0] ctrl_spur_corr_shadow_phase_seed;
    wire [383:0] ctrl_spur_corr_shadow_coefficients;
    wire [31:0] ctrl_spur_corr_shadow_profile_id;
    wire [31:0] ctrl_spur_corr_shadow_model_crc32;
    wire [31:0] ctrl_spur_corr_shadow_generation;
    wire        ctrl_spur_corr_shadow_crc_valid;
    wire        ctrl_spur_corr_commit_pulse;
    wire        ctrl_spur_corr_tracker_heartbeat_pulse;
    wire        ctrl_spur_corr_disable_pulse;
    wire        ctrl_spur_corr_clear_errors_pulse;
    wire [63:0] ctrl_unix_seconds;
    wire        ctrl_time_ddr_ring_enable;
    wire        ctrl_time_ddr_ring_clear_pulse;
    wire [63:0] ctrl_time_ddr_ring_base_addr;
    wire [15:0] ctrl_time_ddr_ring_slots;
    wire        ctrl_time_multiflow_enable;
    wire [2:0]  ctrl_time_multiflow_base_endpoint;
    wire [3:0]  ctrl_time_multiflow_count;

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
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_generation_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_generation;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_target_pps_count_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_target_pps_count;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_epoch_tai_seconds_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_epoch_tai_seconds;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_first_sample0_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_first_sample0;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_observation_tag_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0] scheduled_sync_observation_tag;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scheduled_sync_signal_chain_tag_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scheduled_sync_signal_chain_tag;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scheduled_sync_schedule_tag_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] scheduled_sync_schedule_tag;
    (* ASYNC_REG = "TRUE" *) logic [31:0] mts_result_id_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] mts_result_id;
    (* ASYNC_REG = "TRUE" *) logic [1:0]  arm_latched_sync;
    logic        ctrl_soft_epoch_toggle;
    logic        ctrl_stop_toggle;
    logic        ctrl_soft_reset_toggle;
    logic        ctrl_scheduled_sync_prepare_toggle;
    logic        ctrl_scheduled_sync_arm_toggle;
    logic        ctrl_scheduled_sync_abort_toggle;
    logic        ctrl_scheduled_sync_clear_status_toggle;
    logic        ctrl_pfb_clear_toggle;
    logic        ctrl_pfb_coeff_load_start_toggle;
    logic        ctrl_pfb_coeff_commit_toggle;
    logic        ctrl_pfb_coeff_abort_toggle;
    logic        ctrl_pfb_coeff_write_toggle;
    logic        ctrl_spur_corr_commit_toggle;
    logic        ctrl_spur_corr_tracker_heartbeat_toggle;
    logic        ctrl_spur_corr_disable_toggle;
    logic        ctrl_spur_corr_clear_errors_toggle;
    logic        ctrl_tx_clear_toggle;
    logic        ctrl_time_ddr_ring_clear_toggle;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_epoch_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  stop_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  soft_reset_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  scheduled_sync_prepare_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  scheduled_sync_arm_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  scheduled_sync_abort_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  scheduled_sync_clear_status_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_coeff_load_start_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_coeff_commit_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_coeff_abort_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  pfb_coeff_write_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  spur_corr_commit_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  spur_corr_tracker_heartbeat_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  spur_corr_disable_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  spur_corr_clear_errors_toggle_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  tx_clear_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  time_ddr_ring_clear_toggle_cmac_sync;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  packet_stream_reset_toggle_cmac_sync;
    logic        soft_epoch_toggle_seen;
    logic        stop_toggle_seen;
    logic        soft_reset_toggle_seen;
    logic        scheduled_sync_prepare_toggle_seen;
    logic        scheduled_sync_arm_toggle_seen;
    logic        scheduled_sync_abort_toggle_seen;
    logic        scheduled_sync_clear_status_toggle_seen;
    logic        pfb_clear_toggle_seen;
    logic        pfb_coeff_load_start_toggle_cmac_seen;
    logic        pfb_coeff_commit_toggle_cmac_seen;
    logic        pfb_coeff_abort_toggle_cmac_seen;
    logic        pfb_coeff_write_toggle_cmac_seen;
    logic        tx_clear_toggle_seen;
    logic        spur_corr_commit_toggle_seen;
    logic        spur_corr_tracker_heartbeat_toggle_seen;
    logic        spur_corr_disable_toggle_seen;
    logic        spur_corr_clear_errors_toggle_seen;
    logic        tx_clear_toggle_cmac_seen;
    logic        time_ddr_ring_clear_toggle_cmac_seen;
    logic        packet_stream_reset_toggle_cmac_seen;
    logic        packet_stream_reset_toggle_cmac_src;
    wire         arm_latched;
    wire         soft_epoch_pulse;
    wire         stop_pulse;
    wire         soft_reset_pulse;
    wire         scheduled_sync_prepare_pulse;
    wire         scheduled_sync_arm_pulse;
    wire         scheduled_sync_abort_pulse;
    wire         scheduled_sync_clear_status_pulse;
    wire         pfb_clear_pulse;
    wire         pfb_coeff_load_start_pulse_cmac;
    wire         pfb_coeff_commit_pulse_cmac;
    wire         pfb_coeff_abort_pulse_cmac;
    wire         pfb_coeff_write_pulse_cmac;
    wire         tx_clear_pulse;
    wire         spur_corr_commit_pulse;
    wire         spur_corr_tracker_heartbeat_pulse;
    wire         spur_corr_disable_pulse;
    wire         spur_corr_clear_errors_pulse;
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
    wire [3:0]  direct_fsm_state;
    wire        direct_armed;
    wire        direct_streaming;
    wire        direct_waiting_for_epoch;
    wire        direct_epoch_reset_pulse;
    wire        scheduled_sync_selected;
    wire        scheduled_sync_armed;
    wire        scheduled_sync_streaming;
    wire        scheduled_sync_release_stream_now;
    wire        scheduled_sync_waiting_for_epoch;
    wire        scheduled_sync_epoch_reset_pulse;
    wire        scheduled_sync_epoch_valid;
    wire [3:0]  scheduled_sync_state;
    wire [31:0] scheduled_sync_status;
    wire [31:0] scheduled_sync_error;
    wire [63:0] scheduled_sync_active_generation;
    wire [63:0] scheduled_sync_active_target_pps_count;
    wire [63:0] scheduled_sync_active_epoch_tai_seconds;
    wire [63:0] scheduled_sync_active_first_sample0;
    wire [63:0] scheduled_sync_active_observation_tag;
    wire [31:0] scheduled_sync_active_signal_chain_tag;
    wire [31:0] scheduled_sync_active_schedule_tag;
    wire [31:0] scheduled_sync_active_mts_result_id;
    wire [63:0] scheduled_sync_actual_commit_pps_count;
    wire [63:0] scheduled_sync_actual_epoch_raw_sample0;
    wire [63:0] scheduled_sync_actual_first_time_sample0;
    wire [63:0] scheduled_sync_actual_first_spec_sample0;
    wire [63:0] observation_adc_sample0;
    wire        pps_seen;
    logic [63:0] pps_count;
    wire [31:0] error_flags;
    (* ASYNC_REG = "TRUE" *) logic [1:0] pps_sync;
    logic       pps_count_d;
    logic       pps_seen_latched;
    (* ASYNC_REG = "TRUE" *) logic       pps_seen_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic       pps_seen_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_pl_gray_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_pl_gray_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_adc_gray_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_adc_gray_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_dac_gray_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] sysref_dac_gray_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  sysref_levels_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [2:0]  sysref_levels_ctrl;
    wire [31:0] sysref_pl_edge_count_ctrl = gray32_to_binary(sysref_pl_gray_ctrl);
    wire [31:0] sysref_adc_edge_count_ctrl = gray32_to_binary(sysref_adc_gray_ctrl);
    wire [31:0] sysref_dac_edge_count_ctrl = gray32_to_binary(sysref_dac_gray_ctrl);
    (* ASYNC_REG = "TRUE" *) logic       ref_lock_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic       ref_lock_ctrl;

    wire [31:0] monitor_sample_count;
    wire [255:0] clip_counts;
    wire [255:0] mean_mags;
    wire        preview_busy_ctrl;
    wire        preview_done_ctrl;
    wire        preview_error_ctrl;
    wire [31:0] preview_capture_count_ctrl;
    wire [63:0] preview_sample0_ctrl;
    wire [31:0] preview_rd_data_ctrl;

    wire [583:0] ctrl_spur_corr_config_bundle = {
        ctrl_preview_corrected_select,
        ctrl_spur_corr_shadow_crc_valid,
        ctrl_spur_corr_shadow_generation,
        ctrl_spur_corr_shadow_model_crc32,
        ctrl_spur_corr_shadow_profile_id,
        ctrl_spur_corr_shadow_coefficients,
        ctrl_spur_corr_shadow_phase_seed,
        ctrl_spur_corr_shadow_phase_step,
        ctrl_spur_corr_shadow_spur_id,
        ctrl_spur_corr_shadow_phase_reload,
        ctrl_spur_corr_shadow_bypass,
        ctrl_spur_corr_shadow_in_band,
        ctrl_spur_corr_shadow_enable
    };
    (* ASYNC_REG = "TRUE" *) logic [583:0] spur_corr_config_meta;
    (* ASYNC_REG = "TRUE" *) logic [583:0] spur_corr_config_data;
    wire preview_corrected_select;
    wire spur_corr_shadow_crc_valid;
    wire [31:0] spur_corr_shadow_generation;
    wire [31:0] spur_corr_shadow_model_crc32;
    wire [31:0] spur_corr_shadow_profile_id;
    wire [383:0] spur_corr_shadow_coefficients;
    wire [47:0] spur_corr_shadow_phase_seed;
    wire [47:0] spur_corr_shadow_phase_step;
    wire [1:0] spur_corr_shadow_spur_id;
    wire spur_corr_shadow_phase_reload;
    wire spur_corr_shadow_bypass;
    wire spur_corr_shadow_in_band;
    wire spur_corr_shadow_enable;
    assign {
        preview_corrected_select,
        spur_corr_shadow_crc_valid,
        spur_corr_shadow_generation,
        spur_corr_shadow_model_crc32,
        spur_corr_shadow_profile_id,
        spur_corr_shadow_coefficients,
        spur_corr_shadow_phase_seed,
        spur_corr_shadow_phase_step,
        spur_corr_shadow_spur_id,
        spur_corr_shadow_phase_reload,
        spur_corr_shadow_bypass,
        spur_corr_shadow_in_band,
        spur_corr_shadow_enable
    } = spur_corr_config_data;

    wire spur_corr_correction_active;
    wire spur_corr_correction_uncorrected;
    wire [31:0] spur_corr_status;
    wire [1:0] spur_corr_active_spur_id;
    wire [47:0] spur_corr_active_phase_step;
    wire [31:0] spur_corr_active_profile_id;
    wire [31:0] spur_corr_active_model_crc32;
    wire [31:0] spur_corr_active_generation;
    wire [63:0] spur_corr_last_commit_sample0;
    wire [31:0] spur_corr_saturation_count;
    wire [31:0] spur_corr_sample0_discontinuity_count;
    wire [31:0] spur_corr_crc_error_count;
    wire [31:0] spur_corr_tracker_stale_count;
    wire [31:0] spur_corr_commit_count;
    wire [401:0] spur_corr_status_bundle = {
        spur_corr_commit_count,
        spur_corr_tracker_stale_count,
        spur_corr_crc_error_count,
        spur_corr_sample0_discontinuity_count,
        spur_corr_saturation_count,
        spur_corr_last_commit_sample0,
        spur_corr_active_generation,
        spur_corr_active_model_crc32,
        spur_corr_active_profile_id,
        spur_corr_active_phase_step,
        spur_corr_active_spur_id,
        spur_corr_status
    };
    (* ASYNC_REG = "TRUE" *) logic [401:0] spur_corr_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [401:0] spur_corr_status_ctrl_bundle;
    wire [31:0] spur_corr_status_ctrl;
    wire [1:0] spur_corr_active_spur_id_ctrl;
    wire [47:0] spur_corr_active_phase_step_ctrl;
    wire [31:0] spur_corr_active_profile_id_ctrl;
    wire [31:0] spur_corr_active_model_crc32_ctrl;
    wire [31:0] spur_corr_active_generation_ctrl;
    wire [63:0] spur_corr_last_commit_sample0_ctrl;
    wire [31:0] spur_corr_saturation_count_ctrl;
    wire [31:0] spur_corr_sample0_discontinuity_count_ctrl;
    wire [31:0] spur_corr_crc_error_count_ctrl;
    wire [31:0] spur_corr_tracker_stale_count_ctrl;
    wire [31:0] spur_corr_commit_count_ctrl;
    assign {
        spur_corr_commit_count_ctrl,
        spur_corr_tracker_stale_count_ctrl,
        spur_corr_crc_error_count_ctrl,
        spur_corr_sample0_discontinuity_count_ctrl,
        spur_corr_saturation_count_ctrl,
        spur_corr_last_commit_sample0_ctrl,
        spur_corr_active_generation_ctrl,
        spur_corr_active_model_crc32_ctrl,
        spur_corr_active_profile_id_ctrl,
        spur_corr_active_phase_step_ctrl,
        spur_corr_active_spur_id_ctrl,
        spur_corr_status_ctrl
    } = spur_corr_status_ctrl_bundle;

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

    wire [SCIENCE_DATA_W-1:0] spur_corr_tdata;
    wire [31:0]  spur_corr_tuser;
    wire [63:0]  spur_corr_sample0;
    wire [63:0]  spur_corr_raw_sample0;
    wire         spur_corr_tvalid;
    wire         spur_corr_tlast;
    wire         spur_corr_tready;
    // Calibration is deliberately performed while the science session is
    // stopped.  Keep the corrector draining the live RFDC stream in that
    // state so an atomic coefficient commit can reach its raw-sample boundary
    // and corrected preview remains observable.  The selector valid gate
    // below prevents any of these calibration beats from entering PFB/TIME or
    // UDP.  Once streaming is asserted this reduces to the normal lossless
    // AXIS ready/valid path.
    wire         spur_corr_output_ready = streaming ? spur_corr_tready : 1'b1;
    wire         spur_corr_science_valid = spur_corr_tvalid && streaming;
    wire [255:0] preview_selected_tdata0 = preview_corrected_select ?
        spur_corr_tdata[255:0] : s_axis_preview_tdata0;
    wire [255:0] preview_selected_tdata1 = preview_corrected_select ?
        spur_corr_tdata[511:256] : s_axis_preview_tdata1;
    wire [255:0] preview_selected_tdata2 = preview_corrected_select ?
        spur_corr_tdata[767:512] : s_axis_preview_tdata2;
    wire [255:0] preview_selected_tdata3 = preview_corrected_select ?
        spur_corr_tdata[1023:768] : s_axis_preview_tdata3;
    wire [63:0] preview_selected_sample0 = preview_corrected_select ?
        spur_corr_raw_sample0 : s_axis_preview_sample0;
    wire preview_selected_tvalid = preview_corrected_select ?
        (spur_corr_tvalid && spur_corr_output_ready) : s_axis_preview_tvalid;

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
    wire         inactive_time_tready;
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
    wire [SCIENCE_DATA_W-1:0] spec_feng_cdc_tdata;
    wire [63:0]  spec_feng_cdc_sample0;
    wire         spec_feng_cdc_tvalid;
    wire         spec_feng_cdc_tready;
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
    wire         inactive_pfb_spec_tready;
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
    wire [31:0] pfb_coeff_status;
    wire [31:0] pfb_coeff_loaded_count;
    wire [31:0] pfb_coeff_active_id;
    wire [31:0] pfb_coeff_active_checksum;
    wire [31:0] pfb_coeff_error_count;
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
    wire [1:0] ctrl_science_sample_rate_mode_cfg;
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
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_sample_rate_mode_meta;
    (* ASYNC_REG = "TRUE" *) logic [1:0] science_sample_rate_mode;
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
    wire [31:0] inactive_tx_route_forwarded_count;
    wire [31:0] wide_tx_route_forwarded_count;
    wire [31:0] wide_spec_tx_route_forwarded_count;
    wire [31:0] tx_route_dropped_count;
    wire [31:0] inactive_tx_route_dropped_count;
    wire [31:0] wide_tx_route_dropped_count;
    wire [31:0] wide_spec_tx_route_dropped_count;
    wire [31:0] tx_route_miss_count;
    wire [31:0] inactive_tx_route_miss_count;
    wire [31:0] wide_tx_route_miss_count;
    wire [31:0] wide_spec_tx_route_miss_count;
    wire [31:0] tx_route_error_count;
    wire [31:0] inactive_tx_route_error_count;
    wire [31:0] wide_tx_route_error_count;
    wire [31:0] wide_spec_tx_route_error_count;
    wire [7:0]  tx_selected_endpoint_id;
    wire [7:0]  inactive_tx_selected_endpoint_id;
    wire [7:0]  wide_tx_selected_endpoint_id;
    wire [7:0]  wide_spec_tx_selected_endpoint_id;
    wire [5:0]  tx_selected_route_id;
    wire [5:0]  inactive_tx_selected_route_id;
    wire [5:0]  wide_tx_selected_route_id;
    wire [5:0]  wide_spec_tx_selected_route_id;
    wire        tx_selected_route_is_time;
    wire        inactive_tx_selected_route_is_time;
    wire        wide_tx_selected_route_is_time;
    wire        wide_spec_tx_selected_route_is_time;
    wire [TX_SPEC_ROUTES*32-1:0] tx_spec_route_hit_counts;
    wire [TX_SPEC_ROUTES*32-1:0] inactive_tx_spec_route_hit_counts;
    wire [TX_SPEC_ROUTES*32-1:0] wide_spec_tx_route_hit_counts;
    wire [255:0] tx_time_route_hit_counts;
    wire [255:0] inactive_tx_time_route_hit_counts;
    wire [255:0] wide_tx_time_route_hit_counts;
    wire [31:0] tx_frame_built_count;
    wire [31:0] inactive_tx_frame_built_count;
    wire [31:0] wide_tx_frame_built_count;
    wire [31:0] wide_spec_tx_frame_built_count;
    wire [31:0] tx_frame_byte_count;
    wire [31:0] inactive_tx_frame_byte_count;
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
    wire [511:0] inactive_time_live_cmac_tdata;
    wire [63:0]  inactive_time_live_cmac_tkeep;
    wire         inactive_time_live_cmac_tvalid;
    wire         inactive_time_live_cmac_tlast;
    wire         inactive_time_live_cmac_tready;
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
    wire         inactive_time_live_bridge_s_tready;
    wire         wide_time_live_bridge_s_tready;
    wire [31:0] time_live_bridge_fifo_level;
    wire [31:0] inactive_time_live_bridge_fifo_level;
    wire [31:0] wide_time_live_bridge_fifo_level;
    wire [31:0] time_live_bridge_input_frames;
    wire [31:0] inactive_time_live_bridge_input_frames;
    wire [31:0] wide_time_live_bridge_input_frames;
    wire [31:0] time_live_bridge_output_frames;
    wire [31:0] inactive_time_live_bridge_output_frames;
    wire [31:0] wide_time_live_bridge_output_frames;
    wire [31:0] time_live_bridge_backpressure_cycles;
    wire [31:0] inactive_time_live_bridge_backpressure_cycles;
    wire [31:0] wide_time_live_bridge_backpressure_cycles;
    wire         time_live_bridge_fifo_full;
    wire         inactive_time_live_bridge_fifo_full;
    wire         wide_time_live_bridge_fifo_full;
    wire         time_live_bridge_fifo_empty;
    wire         inactive_time_live_bridge_fifo_empty;
    wire         wide_time_live_bridge_fifo_empty;
    wire [31:0] tx_cmac_source_mux_status;
    wire [31:0] tx_cmac_source_status;
    wire        time_live_requested_data;
    logic       time_live_requested_cmac;
    wire        time_live_requested_cmac_comb;
    wire        spec_live_requested_data;
    logic       spec_live_requested_cmac;
    wire        spec_live_requested_cmac_comb;
    wire        inactive_bridge_requested_data;
    logic       inactive_bridge_requested_cmac;
    wire        inactive_bridge_requested_cmac_comb;
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
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_taps_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_taps_cmac;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [15:0] pfb_fft_shift_cmac;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  pfb_coeff_requested_taps_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [3:0]  pfb_coeff_requested_taps_cmac;
    (* ASYNC_REG = "TRUE" *) logic [14:0] pfb_coeff_index_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [14:0] pfb_coeff_index_cmac;
    (* ASYNC_REG = "TRUE" *) logic signed [17:0] pfb_coeff_data_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic signed [17:0] pfb_coeff_data_cmac;
    (* ASYNC_REG = "TRUE" *) logic [31:0] pfb_coeff_id_cmac_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0] pfb_coeff_id_cmac;
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

    wire [31:0] spec_packet_count;
    wire [31:0] inactive_spec_packet_count;
    wire [31:0] wide_spec_packet_count;
    wire [31:0] spec_udp_byte_count;
    wire [31:0] inactive_spec_udp_byte_count;
    wire [31:0] wide_spec_udp_byte_count;
    wire [31:0] spec_duplicator_dropped_count;
    wire [31:0] spec_decimator_selected_count;
    wire [31:0] spec_decimator_discarded_count;
    wire [31:0] spec_decimator_dropped_count;
    wire [31:0] spec_seq_no;
    wire [31:0] inactive_spec_seq_no;
    wire [31:0] wide_spec_seq_no;
    wire [63:0] spec_frame_id;
    wire [63:0] inactive_spec_frame_id;
    wire [63:0] wide_spec_sample0;
    wire [63:0] wide_spec_frame_id;
    wire [31:0] spec_chan0;
    wire [31:0] inactive_spec_chan0;
    wire [31:0] wide_spec_chan0;
    wire [31:0] time_packet_count;
    wire [31:0] inactive_time_packet_count;
    wire [31:0] wide_time_packet_count;
    wire [31:0] time_dropped_count;
    wire [31:0] time_duplicator_dropped_count;
    wire [31:0] inactive_time_dropped_count;
    wire [31:0] wide_time_dropped_count;
    wire [31:0] time_udp_byte_count;
    wire [31:0] inactive_time_udp_byte_count;
    wire [31:0] wide_time_udp_byte_count;
    wire [31:0] time_seq_no;
    wire [31:0] inactive_time_seq_no;
    wire [31:0] wide_time_seq_no;
    wire [63:0] time_sample0;
    wire [63:0] inactive_time_sample0;
    wire [63:0] wide_time_sample0;
    wire [63:0] time_frame_id;
    wire [63:0] inactive_time_frame_id;
    wire [63:0] wide_time_frame_id;
    wire [63:0] spec_input_sample0;
    wire [63:0] time_input_sample0;

    (* ASYNC_REG = "TRUE" *) logic [3:0]   fsm_state_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [3:0]   fsm_state_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  status_bits_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  status_bits_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  scheduled_sync_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  scheduled_sync_status_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  scheduled_sync_error_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  scheduled_sync_error_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_active_generation_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_active_generation_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_commit_pps_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_commit_pps_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_epoch_raw_sample0_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_epoch_raw_sample0_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_first_time_sample0_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_first_time_sample0_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_first_spec_sample0_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [63:0]  scheduled_sync_actual_first_spec_sample0_ctrl;
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
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_status_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_status_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_loaded_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_loaded_count_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_active_id_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_active_id_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_active_checksum_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_active_checksum_ctrl;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_error_count_ctrl_meta;
    (* ASYNC_REG = "TRUE" *) logic [31:0]  pfb_coeff_error_count_ctrl;
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
    assign pps_seen        = pps_seen_latched;
    // Packet v3 uses epoch_mode=2 to state explicitly that word 2 carries
    // the scheduled observation epoch in TAI seconds.
    assign udp_epoch_mode  = scheduled_sync_selected ? 16'd2 :
        ((sync_mode == 2'd0) ? 16'd0 : 16'd1);
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
    assign tx_route_forwarded_count = inactive_tx_route_forwarded_count +
                                      (time_live_full_rate_data ? wide_tx_route_forwarded_count : 32'd0) +
                                      (spec_live_requested_data ? wide_spec_tx_route_forwarded_count : 32'd0);
    assign tx_route_dropped_count = inactive_tx_route_dropped_count +
                                    (time_live_full_rate_data ? wide_tx_route_dropped_count : 32'd0) +
                                    (spec_live_requested_data ? wide_spec_tx_route_dropped_count : 32'd0);
    assign tx_route_miss_count = inactive_tx_route_miss_count +
                                 (time_live_full_rate_data ? wide_tx_route_miss_count : 32'd0) +
                                 (spec_live_requested_data ? wide_spec_tx_route_miss_count : 32'd0);
    assign tx_route_error_count = inactive_tx_route_error_count +
                                  (time_live_full_rate_data ? wide_tx_route_error_count : 32'd0) +
                                  (spec_live_requested_data ? wide_spec_tx_route_error_count : 32'd0);
    assign tx_selected_endpoint_id =
        spec_live_requested_data ? wide_spec_tx_selected_endpoint_id :
        (!time_live_full_rate_data ? inactive_tx_selected_endpoint_id : wide_tx_selected_endpoint_id);
    assign tx_selected_route_id =
        spec_live_requested_data ? wide_spec_tx_selected_route_id :
        (!time_live_full_rate_data ? inactive_tx_selected_route_id : wide_tx_selected_route_id);
    assign tx_selected_route_is_time =
        spec_live_requested_data ? wide_spec_tx_selected_route_is_time :
        (!time_live_full_rate_data ? inactive_tx_selected_route_is_time : wide_tx_selected_route_is_time);
    assign tx_spec_route_hit_counts = spec_live_requested_data ? wide_spec_tx_route_hit_counts : inactive_tx_spec_route_hit_counts;
    assign tx_time_route_hit_counts = time_live_full_rate_data ? wide_tx_time_route_hit_counts : inactive_tx_time_route_hit_counts;
    assign tx_frame_built_count = inactive_tx_frame_built_count +
                                  (time_live_full_rate_data ? wide_tx_frame_built_count : 32'd0) +
                                  (spec_live_requested_data ? wide_spec_tx_frame_built_count : 32'd0);
    assign tx_frame_byte_count = inactive_tx_frame_byte_count +
                                 (time_live_full_rate_data ? wide_tx_frame_byte_count : 32'd0) +
                                 (spec_live_requested_data ? wide_spec_tx_frame_byte_count : 32'd0);
    assign spec_packet_count = spec_live_requested_data ? wide_spec_packet_count : inactive_spec_packet_count;
    assign spec_udp_byte_count = spec_live_requested_data ? wide_spec_udp_byte_count : inactive_spec_udp_byte_count;
    assign spec_seq_no = spec_live_requested_data ? wide_spec_seq_no : inactive_spec_seq_no;
    assign spec_frame_id = spec_live_requested_data ? wide_spec_frame_id : inactive_spec_frame_id;
    assign spec_chan0 = spec_live_requested_data ? wide_spec_chan0 : inactive_spec_chan0;
    assign time_packet_count = time_live_full_rate_data ? wide_time_packet_count : inactive_time_packet_count;
    assign time_dropped_count = (time_live_full_rate_data ? wide_time_dropped_count : inactive_time_dropped_count) +
                                time_duplicator_dropped_count;
    assign time_udp_byte_count = time_live_full_rate_data ? wide_time_udp_byte_count : inactive_time_udp_byte_count;
    assign time_seq_no = time_live_full_rate_data ? wide_time_seq_no : inactive_time_seq_no;
    assign time_sample0 = time_live_full_rate_data ? wide_time_sample0 : inactive_time_sample0;
    assign time_frame_id = time_live_full_rate_data ? wide_time_frame_id : inactive_time_frame_id;
    assign time_live_bridge_s_tready = time_live_full_rate_data ? wide_time_live_bridge_s_tready : inactive_time_live_bridge_s_tready;
    assign time_live_bridge_fifo_level = time_live_full_rate_data ? wide_time_live_bridge_fifo_level : inactive_time_live_bridge_fifo_level;
    assign time_live_bridge_input_frames = time_live_full_rate_data ? wide_time_live_bridge_input_frames : inactive_time_live_bridge_input_frames;
    assign time_live_bridge_output_frames = time_live_full_rate_data ? wide_time_live_bridge_output_frames : inactive_time_live_bridge_output_frames;
    assign time_live_bridge_backpressure_cycles = time_live_full_rate_data ? wide_time_live_bridge_backpressure_cycles : inactive_time_live_bridge_backpressure_cycles;
    assign time_live_bridge_fifo_full = time_live_full_rate_data ? wide_time_live_bridge_fifo_full : inactive_time_live_bridge_fifo_full;
    assign time_live_bridge_fifo_empty = time_live_full_rate_data ? wide_time_live_bridge_fifo_empty : inactive_time_live_bridge_fifo_empty;
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
                .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac ||
                       time_ddr_ring_clear_pulse_cmac),
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
        .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
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
    assign time_live_full_rate_data = time_live_requested_data;
    assign inactive_bridge_requested_data = 1'b0;
    assign inactive_bridge_requested_cmac_comb = 1'b0;

    always_ff @(posedge cmac_tx_clk or negedge cmac_tx_rst_n) begin
        if (!cmac_tx_rst_n) begin
            time_live_requested_cmac <= 1'b0;
            spec_live_requested_cmac <= 1'b0;
            time_live_full_rate_cmac_meta <= 1'b0;
            time_live_full_rate_cmac <= 1'b0;
            inactive_bridge_requested_cmac <= 1'b0;
        end else begin
            time_live_requested_cmac <= time_live_requested_cmac_comb;
            spec_live_requested_cmac <= spec_live_requested_cmac_comb;
            time_live_full_rate_cmac_meta <= time_live_full_rate_data;
            time_live_full_rate_cmac <= time_live_full_rate_cmac_meta;
            inactive_bridge_requested_cmac <= inactive_bridge_requested_cmac_comb;
        end
    end
    assign tx_qsfp_test_enable = 1'b0;
    assign frame_tx_tready = 1'b0;
    assign m_axis_tx_tdata = 64'd0;
    assign m_axis_tx_tkeep = 8'd0;
    assign m_axis_tx_tvalid = 1'b0;
    assign m_axis_tx_tlast = 1'b0;
    assign tx_cmac_source_status = {
        tx_cmac_source_mux_status[15:0],
        wide_time_live_bridge_fifo_empty,
        wide_time_live_bridge_fifo_full,
        inactive_time_live_bridge_fifo_empty,
        inactive_time_live_bridge_fifo_full,
        inactive_bridge_requested_cmac,
        inactive_bridge_requested_data,
        spec_live_requested_cmac,
        spec_live_requested_data,
        time_live_requested_cmac,
        time_live_requested_data,
        (inactive_time_live_cmac_tready || wide_spec_live_cmac_tready),
        time_live_cmac_mux_tvalid,
        heartbeat_cmac_tvalid,
        tx_qsfp_test_enable,
        tx_cmac_source_mux_status[1:0]
    };
    assign udp_packet_flags = {
        8'd0,
        spur_corr_correction_uncorrected,
        spur_corr_correction_active,
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
    assign scheduled_sync_prepare_pulse = scheduled_sync_prepare_toggle_sync[3] ^ scheduled_sync_prepare_toggle_seen;
    assign scheduled_sync_arm_pulse = scheduled_sync_arm_toggle_sync[3] ^ scheduled_sync_arm_toggle_seen;
    assign scheduled_sync_abort_pulse = scheduled_sync_abort_toggle_sync[3] ^ scheduled_sync_abort_toggle_seen;
    assign scheduled_sync_clear_status_pulse =
        scheduled_sync_clear_status_toggle_sync[3] ^ scheduled_sync_clear_status_toggle_seen;
    assign pfb_clear_pulse = pfb_clear_toggle_sync[2] ^ pfb_clear_toggle_seen;
    assign tx_clear_pulse = tx_clear_toggle_sync[2] ^ tx_clear_toggle_seen;
    assign spur_corr_commit_pulse =
        spur_corr_commit_toggle_sync[2] ^ spur_corr_commit_toggle_seen;
    assign spur_corr_tracker_heartbeat_pulse =
        spur_corr_tracker_heartbeat_toggle_sync[2] ^
        spur_corr_tracker_heartbeat_toggle_seen;
    assign spur_corr_disable_pulse =
        spur_corr_disable_toggle_sync[2] ^ spur_corr_disable_toggle_seen;
    assign spur_corr_clear_errors_pulse =
        spur_corr_clear_errors_toggle_sync[2] ^ spur_corr_clear_errors_toggle_seen;
    assign tx_clear_pulse_cmac = tx_clear_toggle_cmac_sync[2] ^ tx_clear_toggle_cmac_seen;
    assign pfb_coeff_load_start_pulse_cmac =
        pfb_coeff_load_start_toggle_cmac_sync[2] ^ pfb_coeff_load_start_toggle_cmac_seen;
    assign pfb_coeff_commit_pulse_cmac =
        pfb_coeff_commit_toggle_cmac_sync[2] ^ pfb_coeff_commit_toggle_cmac_seen;
    assign pfb_coeff_abort_pulse_cmac =
        pfb_coeff_abort_toggle_cmac_sync[2] ^ pfb_coeff_abort_toggle_cmac_seen;
    assign pfb_coeff_write_pulse_cmac =
        pfb_coeff_write_toggle_cmac_sync[2] ^ pfb_coeff_write_toggle_cmac_seen;
    assign time_ddr_ring_clear_pulse_cmac =
        time_ddr_ring_clear_toggle_cmac_sync[2] ^ time_ddr_ring_clear_toggle_cmac_seen;
    assign packet_stream_reset_pulse_cmac =
        packet_stream_reset_toggle_cmac_sync[2] ^ packet_stream_reset_toggle_cmac_seen;
    assign mode_change_pulse = (mode != mode_prev);
    // One logical flush owns every stateful science/TX stage.  In particular,
    // ABORT must not leave a partial TIME/SPEC frame behind for the next run.
    assign packet_stream_reset_pulse = epoch_reset_pulse || stop_pulse ||
        soft_reset_pulse || scheduled_sync_abort_pulse || tx_clear_pulse ||
        mode_change_pulse;
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
    assign time_tready = time_live_full_rate_data ? wide_time_tready : inactive_time_tready;
    assign pfb_spec_tready = spec_live_requested_data ? wide_pfb_spec_tready : 1'b0;
    assign spec_decimator_selected_count = spec_tvalid && spec_tready ? 32'd1 : 32'd0;
    assign spec_decimator_discarded_count = 32'd0;
    assign spec_decimator_dropped_count = 32'd0;

    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            ctrl_soft_epoch_toggle <= 1'b0;
            ctrl_stop_toggle       <= 1'b0;
            ctrl_soft_reset_toggle <= 1'b0;
            ctrl_scheduled_sync_prepare_toggle <= 1'b0;
            ctrl_scheduled_sync_arm_toggle <= 1'b0;
            ctrl_scheduled_sync_abort_toggle <= 1'b0;
            ctrl_scheduled_sync_clear_status_toggle <= 1'b0;
            ctrl_pfb_clear_toggle  <= 1'b0;
            ctrl_tx_clear_toggle   <= 1'b0;
            ctrl_time_ddr_ring_clear_toggle <= 1'b0;
            ctrl_pfb_coeff_load_start_toggle <= 1'b0;
            ctrl_pfb_coeff_commit_toggle <= 1'b0;
            ctrl_pfb_coeff_abort_toggle <= 1'b0;
            ctrl_pfb_coeff_write_toggle <= 1'b0;
            ctrl_spur_corr_commit_toggle <= 1'b0;
            ctrl_spur_corr_tracker_heartbeat_toggle <= 1'b0;
            ctrl_spur_corr_disable_toggle <= 1'b0;
            ctrl_spur_corr_clear_errors_toggle <= 1'b0;
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
            if (ctrl_scheduled_sync_prepare_pulse) begin
                ctrl_scheduled_sync_prepare_toggle <= ~ctrl_scheduled_sync_prepare_toggle;
            end
            if (ctrl_scheduled_sync_arm_pulse) begin
                ctrl_scheduled_sync_arm_toggle <= ~ctrl_scheduled_sync_arm_toggle;
            end
            if (ctrl_scheduled_sync_abort_pulse) begin
                ctrl_scheduled_sync_abort_toggle <= ~ctrl_scheduled_sync_abort_toggle;
            end
            if (ctrl_scheduled_sync_clear_status_pulse) begin
                ctrl_scheduled_sync_clear_status_toggle <= ~ctrl_scheduled_sync_clear_status_toggle;
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
            if (ctrl_pfb_coeff_load_start_pulse) begin
                ctrl_pfb_coeff_load_start_toggle <= ~ctrl_pfb_coeff_load_start_toggle;
            end
            if (ctrl_pfb_coeff_commit_pulse) begin
                ctrl_pfb_coeff_commit_toggle <= ~ctrl_pfb_coeff_commit_toggle;
            end
            if (ctrl_pfb_coeff_abort_pulse) begin
                ctrl_pfb_coeff_abort_toggle <= ~ctrl_pfb_coeff_abort_toggle;
            end
            if (ctrl_pfb_coeff_write_pulse) begin
                ctrl_pfb_coeff_write_toggle <= ~ctrl_pfb_coeff_write_toggle;
            end
            if (ctrl_spur_corr_commit_pulse) begin
                ctrl_spur_corr_commit_toggle <= ~ctrl_spur_corr_commit_toggle;
            end
            if (ctrl_spur_corr_tracker_heartbeat_pulse) begin
                ctrl_spur_corr_tracker_heartbeat_toggle <=
                    ~ctrl_spur_corr_tracker_heartbeat_toggle;
            end
            if (ctrl_spur_corr_disable_pulse) begin
                ctrl_spur_corr_disable_toggle <= ~ctrl_spur_corr_disable_toggle;
            end
            if (ctrl_spur_corr_clear_errors_pulse) begin
                ctrl_spur_corr_clear_errors_toggle <= ~ctrl_spur_corr_clear_errors_toggle;
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
            pfb_taps_meta          <= 16'd8;
            pfb_taps               <= 16'd8;
            pfb_fft_shift_meta     <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_fft_shift          <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_chan0_meta         <= 32'd0;
            pfb_chan0              <= 32'd0;
            pfb_chan_count_meta    <= 16'd256;
            pfb_chan_count         <= 16'd256;
            pfb_time_count_meta    <= 16'd1;
            pfb_time_count         <= 16'd1;
            science_sample_rate_mode_meta <= 2'd1;
            science_sample_rate_mode <= 2'd1;
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
            scheduled_sync_generation_meta <= 64'd0;
            scheduled_sync_generation <= 64'd0;
            scheduled_sync_target_pps_count_meta <= 64'd0;
            scheduled_sync_target_pps_count <= 64'd0;
            scheduled_sync_epoch_tai_seconds_meta <= 64'd0;
            scheduled_sync_epoch_tai_seconds <= 64'd0;
            scheduled_sync_first_sample0_meta <= 64'd32788;
            scheduled_sync_first_sample0 <= 64'd32788;
            scheduled_sync_observation_tag_meta <= 64'd0;
            scheduled_sync_observation_tag <= 64'd0;
            scheduled_sync_signal_chain_tag_meta <= 32'd0;
            scheduled_sync_signal_chain_tag <= 32'd0;
            scheduled_sync_schedule_tag_meta <= 32'd0;
            scheduled_sync_schedule_tag <= 32'd0;
            mts_result_id_meta <= 32'd0;
            mts_result_id <= 32'd0;
            arm_latched_sync       <= 2'b00;
            soft_epoch_toggle_sync <= 3'b000;
            stop_toggle_sync       <= 3'b000;
            soft_reset_toggle_sync <= 3'b000;
            scheduled_sync_prepare_toggle_sync <= 4'b0000;
            scheduled_sync_arm_toggle_sync <= 4'b0000;
            scheduled_sync_abort_toggle_sync <= 4'b0000;
            scheduled_sync_clear_status_toggle_sync <= 4'b0000;
            pfb_clear_toggle_sync  <= 3'b000;
            tx_clear_toggle_sync   <= 3'b000;
            spur_corr_commit_toggle_sync <= 3'b000;
            spur_corr_tracker_heartbeat_toggle_sync <= 3'b000;
            spur_corr_disable_toggle_sync <= 3'b000;
            spur_corr_clear_errors_toggle_sync <= 3'b000;
            soft_epoch_toggle_seen <= 1'b0;
            stop_toggle_seen       <= 1'b0;
            soft_reset_toggle_seen <= 1'b0;
            scheduled_sync_prepare_toggle_seen <= 1'b0;
            scheduled_sync_arm_toggle_seen <= 1'b0;
            scheduled_sync_abort_toggle_seen <= 1'b0;
            scheduled_sync_clear_status_toggle_seen <= 1'b0;
            pfb_clear_toggle_seen  <= 1'b0;
            tx_clear_toggle_seen   <= 1'b0;
            spur_corr_commit_toggle_seen <= 1'b0;
            spur_corr_tracker_heartbeat_toggle_seen <= 1'b0;
            spur_corr_disable_toggle_seen <= 1'b0;
            spur_corr_clear_errors_toggle_seen <= 1'b0;
            spur_corr_config_meta <= 584'd0;
            spur_corr_config_data <= 584'd0;
            packet_stream_reset_toggle_cmac_src <= 1'b0;
            mode_prev              <= MODE_SPEC;
            mode_switch_reset_count <= 32'd0;
            pps_sync               <= 2'b00;
            pps_count_d            <= 1'b0;
            pps_seen_latched       <= 1'b0;
            pps_count              <= 64'd0;
            dac_phase_epoch_data_meta <= 32'd0;
            dac_phase_epoch_data      <= 32'd0;
            tx_link_status_flags_data_meta <= 32'd0;
            tx_link_status_flags_data      <= 32'd0;
        end else begin
            pps_sync                <= {pps_sync[0], pps_in};
            pps_count_d             <= pps_sync[1];
            if (pps_sync[1] && !pps_count_d) begin
                pps_count <= pps_count + 64'd1;
                pps_seen_latched <= 1'b1;
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
            science_sample_rate_mode_meta <= ctrl_science_sample_rate_mode_cfg;
            science_sample_rate_mode <= science_sample_rate_mode_meta;
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
            scheduled_sync_generation_meta <= ctrl_scheduled_sync_generation;
            scheduled_sync_generation <= scheduled_sync_generation_meta;
            scheduled_sync_target_pps_count_meta <= ctrl_scheduled_sync_target_pps_count;
            scheduled_sync_target_pps_count <= scheduled_sync_target_pps_count_meta;
            scheduled_sync_epoch_tai_seconds_meta <= ctrl_scheduled_sync_epoch_tai_seconds;
            scheduled_sync_epoch_tai_seconds <= scheduled_sync_epoch_tai_seconds_meta;
            scheduled_sync_first_sample0_meta <= ctrl_scheduled_sync_first_sample0;
            scheduled_sync_first_sample0 <= scheduled_sync_first_sample0_meta;
            scheduled_sync_observation_tag_meta <= ctrl_scheduled_sync_observation_tag;
            scheduled_sync_observation_tag <= scheduled_sync_observation_tag_meta;
            scheduled_sync_signal_chain_tag_meta <= ctrl_scheduled_sync_signal_chain_tag;
            scheduled_sync_signal_chain_tag <= scheduled_sync_signal_chain_tag_meta;
            scheduled_sync_schedule_tag_meta <= ctrl_scheduled_sync_schedule_tag;
            scheduled_sync_schedule_tag <= scheduled_sync_schedule_tag_meta;
            mts_result_id_meta <= ctrl_mts_result_id;
            mts_result_id <= mts_result_id_meta;
            arm_latched_sync        <= {arm_latched_sync[0], ctrl_arm_latched};
            soft_epoch_toggle_sync  <= {soft_epoch_toggle_sync[1:0], ctrl_soft_epoch_toggle};
            stop_toggle_sync        <= {stop_toggle_sync[1:0], ctrl_stop_toggle};
            soft_reset_toggle_sync  <= {soft_reset_toggle_sync[1:0], ctrl_soft_reset_toggle};
            scheduled_sync_prepare_toggle_sync <=
                {scheduled_sync_prepare_toggle_sync[2:0], ctrl_scheduled_sync_prepare_toggle};
            scheduled_sync_arm_toggle_sync <=
                {scheduled_sync_arm_toggle_sync[2:0], ctrl_scheduled_sync_arm_toggle};
            scheduled_sync_abort_toggle_sync <=
                {scheduled_sync_abort_toggle_sync[2:0], ctrl_scheduled_sync_abort_toggle};
            scheduled_sync_clear_status_toggle_sync <=
                {scheduled_sync_clear_status_toggle_sync[2:0], ctrl_scheduled_sync_clear_status_toggle};
            pfb_clear_toggle_sync   <= {pfb_clear_toggle_sync[1:0], ctrl_pfb_clear_toggle};
            tx_clear_toggle_sync    <= {tx_clear_toggle_sync[1:0], ctrl_tx_clear_toggle};
            spur_corr_commit_toggle_sync <= {
                spur_corr_commit_toggle_sync[1:0], ctrl_spur_corr_commit_toggle
            };
            spur_corr_tracker_heartbeat_toggle_sync <= {
                spur_corr_tracker_heartbeat_toggle_sync[1:0],
                ctrl_spur_corr_tracker_heartbeat_toggle
            };
            spur_corr_disable_toggle_sync <= {
                spur_corr_disable_toggle_sync[1:0], ctrl_spur_corr_disable_toggle
            };
            spur_corr_clear_errors_toggle_sync <= {
                spur_corr_clear_errors_toggle_sync[1:0], ctrl_spur_corr_clear_errors_toggle
            };
            soft_epoch_toggle_seen  <= soft_epoch_toggle_sync[2];
            stop_toggle_seen        <= stop_toggle_sync[2];
            soft_reset_toggle_seen  <= soft_reset_toggle_sync[2];
            scheduled_sync_prepare_toggle_seen <= scheduled_sync_prepare_toggle_sync[3];
            scheduled_sync_arm_toggle_seen <= scheduled_sync_arm_toggle_sync[3];
            scheduled_sync_abort_toggle_seen <= scheduled_sync_abort_toggle_sync[3];
            scheduled_sync_clear_status_toggle_seen <= scheduled_sync_clear_status_toggle_sync[3];
            pfb_clear_toggle_seen   <= pfb_clear_toggle_sync[2];
            tx_clear_toggle_seen    <= tx_clear_toggle_sync[2];
            spur_corr_commit_toggle_seen <= spur_corr_commit_toggle_sync[2];
            spur_corr_tracker_heartbeat_toggle_seen <=
                spur_corr_tracker_heartbeat_toggle_sync[2];
            spur_corr_disable_toggle_seen <= spur_corr_disable_toggle_sync[2];
            spur_corr_clear_errors_toggle_seen <= spur_corr_clear_errors_toggle_sync[2];
            spur_corr_config_meta <= ctrl_spur_corr_config_bundle;
            spur_corr_config_data <= spur_corr_config_meta;
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
            pfb_taps_cmac_meta <= 16'd8;
            pfb_taps_cmac <= 16'd8;
            pfb_fft_shift_cmac_meta <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_fft_shift_cmac <= FFT_ONLY_DEFAULT_SHIFT;
            pfb_coeff_requested_taps_cmac_meta <= 4'd8;
            pfb_coeff_requested_taps_cmac <= 4'd8;
            pfb_coeff_index_cmac_meta <= 15'd0;
            pfb_coeff_index_cmac <= 15'd0;
            pfb_coeff_data_cmac_meta <= 18'sd0;
            pfb_coeff_data_cmac <= 18'sd0;
            pfb_coeff_id_cmac_meta <= 32'h34a8_0001;
            pfb_coeff_id_cmac <= 32'h34a8_0001;
            rfdc_sample_count_cmac_meta <= 64'd0;
            rfdc_sample_count_cmac <= 64'd0;
            ctrl_board_id_cmac_meta <= 16'd0;
            ctrl_board_id_cmac <= 16'd0;
            tx_clear_toggle_cmac_sync <= 3'b000;
            tx_clear_toggle_cmac_seen <= 1'b0;
            pfb_coeff_load_start_toggle_cmac_sync <= 3'b000;
            pfb_coeff_load_start_toggle_cmac_seen <= 1'b0;
            pfb_coeff_commit_toggle_cmac_sync <= 3'b000;
            pfb_coeff_commit_toggle_cmac_seen <= 1'b0;
            pfb_coeff_abort_toggle_cmac_sync <= 3'b000;
            pfb_coeff_abort_toggle_cmac_seen <= 1'b0;
            pfb_coeff_write_toggle_cmac_sync <= 3'b000;
            pfb_coeff_write_toggle_cmac_seen <= 1'b0;
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
            pfb_taps_cmac_meta <= pfb_taps;
            pfb_taps_cmac <= pfb_taps_cmac_meta;
            pfb_fft_shift_cmac_meta <= pfb_fft_shift;
            pfb_fft_shift_cmac <= pfb_fft_shift_cmac_meta;
            pfb_coeff_requested_taps_cmac_meta <= ctrl_pfb_coeff_requested_taps;
            pfb_coeff_requested_taps_cmac <= pfb_coeff_requested_taps_cmac_meta;
            pfb_coeff_index_cmac_meta <= ctrl_pfb_coeff_index;
            pfb_coeff_index_cmac <= pfb_coeff_index_cmac_meta;
            pfb_coeff_data_cmac_meta <= ctrl_pfb_coeff_data;
            pfb_coeff_data_cmac <= pfb_coeff_data_cmac_meta;
            pfb_coeff_id_cmac_meta <= ctrl_pfb_coeff_id;
            pfb_coeff_id_cmac <= pfb_coeff_id_cmac_meta;
            rfdc_sample_count_cmac_meta <= rfdc_sample_count;
            rfdc_sample_count_cmac <= rfdc_sample_count_cmac_meta;
            ctrl_board_id_cmac_meta <= ctrl_board_id;
            ctrl_board_id_cmac <= ctrl_board_id_cmac_meta;
            tx_clear_toggle_cmac_sync <= {tx_clear_toggle_cmac_sync[1:0], ctrl_tx_clear_toggle};
            tx_clear_toggle_cmac_seen <= tx_clear_toggle_cmac_sync[2];
            pfb_coeff_load_start_toggle_cmac_sync <= {
                pfb_coeff_load_start_toggle_cmac_sync[1:0],
                ctrl_pfb_coeff_load_start_toggle
            };
            pfb_coeff_load_start_toggle_cmac_seen <= pfb_coeff_load_start_toggle_cmac_sync[2];
            pfb_coeff_commit_toggle_cmac_sync <= {
                pfb_coeff_commit_toggle_cmac_sync[1:0],
                ctrl_pfb_coeff_commit_toggle
            };
            pfb_coeff_commit_toggle_cmac_seen <= pfb_coeff_commit_toggle_cmac_sync[2];
            pfb_coeff_abort_toggle_cmac_sync <= {
                pfb_coeff_abort_toggle_cmac_sync[1:0],
                ctrl_pfb_coeff_abort_toggle
            };
            pfb_coeff_abort_toggle_cmac_seen <= pfb_coeff_abort_toggle_cmac_sync[2];
            pfb_coeff_write_toggle_cmac_sync <= {
                pfb_coeff_write_toggle_cmac_sync[1:0],
                ctrl_pfb_coeff_write_toggle
            };
            pfb_coeff_write_toggle_cmac_seen <= pfb_coeff_write_toggle_cmac_sync[2];
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
            scheduled_sync_status_ctrl_meta         <= 32'd0;
            scheduled_sync_status_ctrl              <= 32'd0;
            scheduled_sync_error_ctrl_meta          <= 32'd0;
            scheduled_sync_error_ctrl               <= 32'd0;
            scheduled_sync_active_generation_ctrl_meta <= 64'd0;
            scheduled_sync_active_generation_ctrl   <= 64'd0;
            scheduled_sync_actual_commit_pps_count_ctrl_meta <= 64'd0;
            scheduled_sync_actual_commit_pps_count_ctrl <= 64'd0;
            scheduled_sync_actual_epoch_raw_sample0_ctrl_meta <= 64'd0;
            scheduled_sync_actual_epoch_raw_sample0_ctrl <= 64'd0;
            scheduled_sync_actual_first_time_sample0_ctrl_meta <= 64'd0;
            scheduled_sync_actual_first_time_sample0_ctrl <= 64'd0;
            scheduled_sync_actual_first_spec_sample0_ctrl_meta <= 64'd0;
            scheduled_sync_actual_first_spec_sample0_ctrl <= 64'd0;
            pps_seen_ctrl_meta              <= 1'b0;
            pps_seen_ctrl                   <= 1'b0;
            sysref_pl_gray_ctrl_meta        <= 32'd0;
            sysref_pl_gray_ctrl             <= 32'd0;
            sysref_adc_gray_ctrl_meta       <= 32'd0;
            sysref_adc_gray_ctrl            <= 32'd0;
            sysref_dac_gray_ctrl_meta       <= 32'd0;
            sysref_dac_gray_ctrl            <= 32'd0;
            sysref_levels_ctrl_meta         <= 3'd0;
            sysref_levels_ctrl              <= 3'd0;
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
            pfb_coeff_status_ctrl_meta      <= 32'd0;
            pfb_coeff_status_ctrl           <= 32'd0;
            pfb_coeff_loaded_count_ctrl_meta <= 32'd0;
            pfb_coeff_loaded_count_ctrl      <= 32'd0;
            pfb_coeff_active_id_ctrl_meta   <= 32'd0;
            pfb_coeff_active_id_ctrl        <= 32'd0;
            pfb_coeff_active_checksum_ctrl_meta <= 32'd0;
            pfb_coeff_active_checksum_ctrl      <= 32'd0;
            pfb_coeff_error_count_ctrl_meta <= 32'd0;
            pfb_coeff_error_count_ctrl      <= 32'd0;
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
            scheduled_sync_status_ctrl_meta         <= scheduled_sync_status;
            scheduled_sync_status_ctrl              <= scheduled_sync_status_ctrl_meta;
            scheduled_sync_error_ctrl_meta          <= scheduled_sync_error;
            scheduled_sync_error_ctrl               <= scheduled_sync_error_ctrl_meta;
            scheduled_sync_active_generation_ctrl_meta <= scheduled_sync_active_generation;
            scheduled_sync_active_generation_ctrl   <= scheduled_sync_active_generation_ctrl_meta;
            scheduled_sync_actual_commit_pps_count_ctrl_meta <= scheduled_sync_actual_commit_pps_count;
            scheduled_sync_actual_commit_pps_count_ctrl <= scheduled_sync_actual_commit_pps_count_ctrl_meta;
            scheduled_sync_actual_epoch_raw_sample0_ctrl_meta <= scheduled_sync_actual_epoch_raw_sample0;
            scheduled_sync_actual_epoch_raw_sample0_ctrl <= scheduled_sync_actual_epoch_raw_sample0_ctrl_meta;
            scheduled_sync_actual_first_time_sample0_ctrl_meta <= scheduled_sync_actual_first_time_sample0;
            scheduled_sync_actual_first_time_sample0_ctrl <= scheduled_sync_actual_first_time_sample0_ctrl_meta;
            scheduled_sync_actual_first_spec_sample0_ctrl_meta <= scheduled_sync_actual_first_spec_sample0;
            scheduled_sync_actual_first_spec_sample0_ctrl <= scheduled_sync_actual_first_spec_sample0_ctrl_meta;
            pps_seen_ctrl_meta              <= pps_seen;
            pps_seen_ctrl                   <= pps_seen_ctrl_meta;
            sysref_pl_gray_ctrl_meta        <= sysref_pl_edge_count_gray;
            sysref_pl_gray_ctrl             <= sysref_pl_gray_ctrl_meta;
            sysref_adc_gray_ctrl_meta       <= sysref_adc_edge_count_gray;
            sysref_adc_gray_ctrl            <= sysref_adc_gray_ctrl_meta;
            sysref_dac_gray_ctrl_meta       <= sysref_dac_edge_count_gray;
            sysref_dac_gray_ctrl            <= sysref_dac_gray_ctrl_meta;
            sysref_levels_ctrl_meta         <= sysref_capture_levels;
            sysref_levels_ctrl              <= sysref_levels_ctrl_meta;
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
            pfb_coeff_status_ctrl_meta      <= pfb_coeff_status;
            pfb_coeff_status_ctrl           <= pfb_coeff_status_ctrl_meta;
            pfb_coeff_loaded_count_ctrl_meta <= pfb_coeff_loaded_count;
            pfb_coeff_loaded_count_ctrl      <= pfb_coeff_loaded_count_ctrl_meta;
            pfb_coeff_active_id_ctrl_meta   <= pfb_coeff_active_id;
            pfb_coeff_active_id_ctrl        <= pfb_coeff_active_id_ctrl_meta;
            pfb_coeff_active_checksum_ctrl_meta <= pfb_coeff_active_checksum;
            pfb_coeff_active_checksum_ctrl      <= pfb_coeff_active_checksum_ctrl_meta;
            pfb_coeff_error_count_ctrl_meta <= pfb_coeff_error_count;
            pfb_coeff_error_count_ctrl      <= pfb_coeff_error_count_ctrl_meta;
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

    assign fsm_state = scheduled_sync_selected ? scheduled_sync_state : direct_fsm_state;
    assign armed = scheduled_sync_selected ? scheduled_sync_armed : direct_armed;
    assign streaming = scheduled_sync_selected ?
        ((scheduled_sync_streaming || scheduled_sync_release_stream_now) &&
         ref_lock_in && rfdc_ready_in && rfdc_status_flags[6]) : direct_streaming;
    assign waiting_for_epoch = scheduled_sync_selected ?
        scheduled_sync_waiting_for_epoch : direct_waiting_for_epoch;
    assign epoch_reset_pulse = scheduled_sync_selected ?
        scheduled_sync_epoch_reset_pulse : direct_epoch_reset_pulse;

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
        .state(direct_fsm_state),
        .armed(direct_armed),
        .streaming(direct_streaming),
        .waiting_for_epoch(direct_waiting_for_epoch),
        .epoch_reset_pulse(direct_epoch_reset_pulse)
    );

    station_sync_scheduler #(
        .MIN_LEAD_PPS(2)
    ) u_station_sync_scheduler (
        .clk(clk),
        .rst_n(rst_n),
        .prepare_pulse(scheduled_sync_prepare_pulse),
        .arm_pulse(scheduled_sync_arm_pulse),
        .abort_pulse(scheduled_sync_abort_pulse),
        .clear_status_pulse(scheduled_sync_clear_status_pulse),
        .stop_pulse(stop_pulse),
        .soft_reset_pulse(soft_reset_pulse),
        .schedule_generation(scheduled_sync_generation),
        .schedule_target_pps_count(scheduled_sync_target_pps_count),
        .schedule_epoch_tai_seconds(scheduled_sync_epoch_tai_seconds),
        .schedule_first_sample0(scheduled_sync_first_sample0),
        .schedule_observation_tag(scheduled_sync_observation_tag),
        .schedule_signal_chain_tag(scheduled_sync_signal_chain_tag),
        .schedule_tag(scheduled_sync_schedule_tag),
        .schedule_mts_result_id(mts_result_id),
        .pps_in(pps_sync[1]),
        .pps_count(pps_count),
        .pps_recent(rfdc_status_flags[6]),
        .ref_locked(ref_lock_in),
        .rfdc_ready(rfdc_ready_in),
        .science_sample_rate_mode(science_sample_rate_mode),
        .science_aa100_active(science_aa100_active),
        .adc_valid(s_axis_adc_tvalid && s_axis_adc_tready),
        .adc_raw_sample0(s_axis_adc_sample0),
        .adc_observation_sample0(observation_adc_sample0),
        .science_valid(science_tvalid),
        .science_ready(science_tready),
        .science_sample0(science_sample0),
        .time_packet_event(time_enable && time_tvalid && time_tready),
        .time_packet_sample0(time_input_sample0),
        .spec_packet_event(spec_enable && pfb_spec_tvalid && pfb_spec_tready),
        .spec_packet_sample0(pfb_spec_sample0),
        .selected(scheduled_sync_selected),
        .armed(scheduled_sync_armed),
        .streaming(scheduled_sync_streaming),
        .release_stream_now(scheduled_sync_release_stream_now),
        .waiting_for_epoch(scheduled_sync_waiting_for_epoch),
        .epoch_reset_pulse(scheduled_sync_epoch_reset_pulse),
        .epoch_valid(scheduled_sync_epoch_valid),
        .state(scheduled_sync_state),
        .status_flags(scheduled_sync_status),
        .error_code(scheduled_sync_error),
        .active_generation(scheduled_sync_active_generation),
        .active_target_pps_count(scheduled_sync_active_target_pps_count),
        .active_epoch_tai_seconds(scheduled_sync_active_epoch_tai_seconds),
        .active_first_sample0(scheduled_sync_active_first_sample0),
        .active_observation_tag(scheduled_sync_active_observation_tag),
        .active_signal_chain_tag(scheduled_sync_active_signal_chain_tag),
        .active_schedule_tag(scheduled_sync_active_schedule_tag),
        .active_mts_result_id(scheduled_sync_active_mts_result_id),
        .actual_commit_pps_count(scheduled_sync_actual_commit_pps_count),
        .actual_epoch_raw_sample0(scheduled_sync_actual_epoch_raw_sample0),
        .actual_first_time_sample0(scheduled_sync_actual_first_time_sample0),
        .actual_first_spec_sample0(scheduled_sync_actual_first_spec_sample0)
    );

    adc_interleave_spur_corrector #(
        .NINPUT(8),
        .SUBSAMPLES(4),
        .SAMPLE_W(32),
        .USER_W(32),
        .SAMPLE0_W(64),
        .TRACKER_TIMEOUT_CYCLES(80_000_000)
    ) u_adc_interleave_spur_corrector (
        .clk(clk),
        .rst_n(rst_n),
        .clear(packet_stream_reset_pulse || pfb_clear_pulse),
        .s_axis_tdata(s_axis_adc_tdata),
        .s_axis_tuser(s_axis_adc_tuser),
        .s_axis_sample0(observation_adc_sample0),
        .s_axis_raw_sample0(s_axis_adc_sample0),
        .s_axis_tvalid(s_axis_adc_tvalid),
        .s_axis_tlast(s_axis_adc_tlast),
        .s_axis_tready(s_axis_adc_tready),
        .m_axis_tdata(spur_corr_tdata),
        .m_axis_tuser(spur_corr_tuser),
        .m_axis_sample0(spur_corr_sample0),
        .m_axis_raw_sample0(spur_corr_raw_sample0),
        .m_axis_tvalid(spur_corr_tvalid),
        .m_axis_tlast(spur_corr_tlast),
        .m_axis_tready(spur_corr_output_ready),
        .shadow_enable(spur_corr_shadow_enable),
        .shadow_in_band(spur_corr_shadow_in_band),
        .shadow_bypass(spur_corr_shadow_bypass),
        .shadow_phase_reload(spur_corr_shadow_phase_reload),
        .shadow_spur_id(spur_corr_shadow_spur_id),
        .shadow_phase_step(spur_corr_shadow_phase_step),
        .shadow_phase_seed(spur_corr_shadow_phase_seed),
        .shadow_coefficients(spur_corr_shadow_coefficients),
        .shadow_profile_id(spur_corr_shadow_profile_id),
        .shadow_model_crc32(spur_corr_shadow_model_crc32),
        .shadow_generation(spur_corr_shadow_generation),
        .shadow_crc_valid(spur_corr_shadow_crc_valid),
        .commit_pulse(spur_corr_commit_pulse),
        .tracker_heartbeat_pulse(spur_corr_tracker_heartbeat_pulse),
        .disable_pulse(spur_corr_disable_pulse),
        .clear_errors_pulse(spur_corr_clear_errors_pulse),
        .correction_active(spur_corr_correction_active),
        .correction_uncorrected(spur_corr_correction_uncorrected),
        .status_word(spur_corr_status),
        .active_spur_id(spur_corr_active_spur_id),
        .active_phase_step(spur_corr_active_phase_step),
        .active_profile_id(spur_corr_active_profile_id),
        .active_model_crc32(spur_corr_active_model_crc32),
        .active_generation(spur_corr_active_generation),
        .last_commit_sample0(spur_corr_last_commit_sample0),
        .saturation_count(spur_corr_saturation_count),
        .sample0_discontinuity_count(spur_corr_sample0_discontinuity_count),
        .crc_error_count(spur_corr_crc_error_count),
        .tracker_stale_count(spur_corr_tracker_stale_count),
        .commit_count(spur_corr_commit_count)
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
        .clear(packet_stream_reset_pulse || pfb_clear_pulse),
        .sample_rate_mode(science_sample_rate_mode),
        .s_axis_tdata(spur_corr_tdata),
        .s_axis_tuser(spur_corr_tuser),
        .s_axis_sample0(spur_corr_sample0),
        .s_axis_tvalid(spur_corr_science_valid),
        .s_axis_tlast(spur_corr_tlast),
        .s_axis_tready(spur_corr_tready),
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
        .clear(packet_stream_reset_pulse),
        .sample_valid(s_axis_adc_tvalid && s_axis_adc_tready),
        .sample_tdata(s_axis_adc_tdata[255:0]),
        .sample_count(monitor_sample_count),
        .clip_counts(clip_counts),
        .mean_mags(mean_mags)
    );


    multi_preview_observer u_multi_preview_observer (
        .clk(clk),
        .rst_n(rst_n),
        .ctrl_clk(ctrl_clk),
        .ctrl_rst_n(ctrl_rst_n),
        .streaming(streaming),
        .input_mask(ctrl_preview_input_mask),
        .s_axis_adc_tdata0(preview_selected_tdata0),
        .s_axis_adc_tdata1(preview_selected_tdata1),
        .s_axis_adc_tdata2(preview_selected_tdata2),
        .s_axis_adc_tdata3(preview_selected_tdata3),
        .s_axis_adc_sample0(preview_selected_sample0),
        .s_axis_adc_tvalid(preview_selected_tvalid),
        .ctrl_capture_start_pulse(ctrl_preview_capture_start_pulse),
        .ctrl_capture_clear_pulse(ctrl_preview_capture_clear_pulse),
        .ctrl_rd_input(ctrl_preview_rd_input),
        .ctrl_rd_addr(ctrl_preview_rd_addr),
        .ctrl_rd_data(preview_rd_data_ctrl),
        .ctrl_busy(preview_busy_ctrl),
        .ctrl_done(preview_done_ctrl),
        .ctrl_error(preview_error_ctrl),
        .ctrl_capture_count(preview_capture_count_ctrl),
        .ctrl_sample0(preview_sample0_ctrl)
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

    assign pfb_spec_cmac_sideband = {
        pfb_status,
        pfb_fft_shift_cmac,
        16'd8,
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
        .m_axis_tdata(spec_feng_cdc_tdata),
        .m_axis_tside(spec_feng_cdc_sample0),
        .m_axis_tvalid(spec_feng_cdc_tvalid),
        .m_axis_tready(spec_feng_cdc_tready),
        .wr_level_words(spec_feng_cmac_wr_level_words),
        .rd_level_words(spec_feng_cmac_rd_level_words),
        .fifo_full(spec_feng_cmac_fifo_full),
        .fifo_empty(spec_feng_cmac_fifo_empty)
    );

    axis512_register_slice #(
        .DATA_W(SCIENCE_DATA_W + 64),
        .KEEP_W(8),
        .DEPTH(2),
        .COUNT_W(2)
    ) u_spec_feng_input_slice (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
        .s_axis_tdata({spec_feng_cdc_sample0, spec_feng_cdc_tdata}),
        .s_axis_tkeep(8'hff),
        .s_axis_tvalid(spec_feng_cdc_tvalid),
        .s_axis_tlast(1'b0),
        .s_axis_tready(spec_feng_cdc_tready),
        .m_axis_tdata({spec_feng_cmac_sample0, spec_feng_cmac_tdata}),
        .m_axis_tkeep(),
        .m_axis_tvalid(spec_feng_cmac_tvalid),
        .m_axis_tlast(),
        .m_axis_tready(spec_feng_cmac_tready)
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
        .cfg_taps(16'd8),
        .cfg_fft_shift(pfb_fft_shift_cmac),
        .cfg_chan0(32'd0),
        .cfg_chan_count(16'd256),
        .cfg_time_count(16'd1),
        .coeff_load_start(pfb_coeff_load_start_pulse_cmac),
        .coeff_commit(pfb_coeff_commit_pulse_cmac),
        .coeff_abort(pfb_coeff_abort_pulse_cmac),
        .coeff_write(pfb_coeff_write_pulse_cmac),
        .coeff_requested_taps(pfb_coeff_requested_taps_cmac),
        .coeff_index(pfb_coeff_index_cmac),
        .coeff_data(pfb_coeff_data_cmac),
        .coeff_id(pfb_coeff_id_cmac),
        .coeff_status(pfb_coeff_status),
        .coeff_loaded_count(pfb_coeff_loaded_count),
        .coeff_active_id(pfb_coeff_active_id),
        .coeff_active_checksum(pfb_coeff_active_checksum),
        .coeff_error_count(pfb_coeff_error_count),
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
        .output_fifo_level(pfb_spec_cmac_to_data_wr_level_words),
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

    assign spec_product_status_flags = {
        21'd0,
        (pfb_taps_data == 16'd8) && pfb_status_data[5] && !pfb_status_data[8],
        science_aa100_active && (science_sample_rate_mode == 2'd1),
        pfb_status_data[8],
        pfb_status_data[7:0]
    };

    assign inactive_pfb_spec_tready = 1'b0;
    assign spec_axis_tdata = 64'd0;
    assign spec_axis_tkeep = 8'd0;
    assign spec_axis_tvalid = 1'b0;
    assign spec_axis_tlast = 1'b0;
    assign inactive_spec_packet_count = 32'd0;
    assign inactive_spec_udp_byte_count = 32'd0;
    assign inactive_spec_seq_no = 32'd0;
    assign inactive_spec_frame_id = 64'd0;
    assign inactive_spec_chan0 = 32'd0;

    spec_udp_cmac512 #(
        .DATA_W(SCIENCE_DATA_W),
        .N_ENDPOINTS(TX_ENDPOINTS),
        .N_SPEC_ROUTES(TX_SPEC_ROUTES),
        .DATA_FIFO_DEPTH(1024),
        .DATA_COUNT_W(11),
        .TOKEN_FIFO_DEPTH(64),
        .TOKEN_COUNT_W(7)
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
        .unix_seconds(scheduled_sync_selected ? scheduled_sync_active_epoch_tai_seconds : unix_seconds),
        .pps_count(scheduled_sync_selected ? scheduled_sync_actual_commit_pps_count : pps_count),
        .sync_generation(scheduled_sync_selected ? scheduled_sync_active_generation : 64'd0),
        .sync_observation_tag(scheduled_sync_active_observation_tag),
        .sync_metadata({scheduled_sync_active_signal_chain_tag, scheduled_sync_active_schedule_tag}),
        .sync_status({scheduled_sync_active_mts_result_id, scheduled_sync_status}),
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
        .m_clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
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

    assign inactive_time_tready = 1'b0;
    assign time_axis_tdata = 64'd0;
    assign time_axis_tkeep = 8'd0;
    assign time_axis_tvalid = 1'b0;
    assign time_axis_tlast = 1'b0;
    assign inactive_time_packet_count = 32'd0;
    assign inactive_time_dropped_count = 32'd0;
    assign inactive_time_udp_byte_count = 32'd0;
    assign inactive_time_seq_no = 32'd0;
    assign inactive_time_sample0 = 64'd0;
    assign inactive_time_frame_id = 64'd0;

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
        .unix_seconds(scheduled_sync_selected ? scheduled_sync_active_epoch_tai_seconds : unix_seconds),
        .pps_count(scheduled_sync_selected ? scheduled_sync_actual_commit_pps_count : pps_count),
        .sync_generation(scheduled_sync_selected ? scheduled_sync_active_generation : 64'd0),
        .sync_observation_tag(scheduled_sync_active_observation_tag),
        .sync_metadata({scheduled_sync_active_signal_chain_tag, scheduled_sync_active_schedule_tag}),
        .sync_status({scheduled_sync_active_mts_result_id, scheduled_sync_status}),
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
        .m_clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
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
    assign inactive_tx_route_forwarded_count = 32'd0;
    assign inactive_tx_route_dropped_count = 32'd0;
    assign inactive_tx_route_miss_count = 32'd0;
    assign inactive_tx_route_error_count = 32'd0;
    assign inactive_tx_selected_endpoint_id = 8'd0;
    assign inactive_tx_selected_route_id = 6'd0;
    assign inactive_tx_selected_route_is_time = 1'b0;
    assign inactive_tx_spec_route_hit_counts = {TX_SPEC_ROUTES*32{1'b0}};
    assign inactive_tx_time_route_hit_counts = 256'd0;
    assign frame_tx_tdata = 64'd0;
    assign frame_tx_tkeep = 8'd0;
    assign frame_tx_tvalid = 1'b0;
    assign frame_tx_tlast = 1'b0;
    assign inactive_tx_frame_built_count = 32'd0;
    assign inactive_tx_frame_byte_count = 32'd0;
    assign inactive_time_live_cmac_tdata = 512'd0;
    assign inactive_time_live_cmac_tkeep = 64'd0;
    assign inactive_time_live_cmac_tvalid = 1'b0;
    assign inactive_time_live_cmac_tlast = 1'b0;
    assign inactive_time_live_cmac_tready = 1'b0;
    assign inactive_time_live_bridge_s_tready = 1'b0;
    assign inactive_time_live_bridge_fifo_level = 32'd0;
    assign inactive_time_live_bridge_input_frames = 32'd0;
    assign inactive_time_live_bridge_output_frames = 32'd0;
    assign inactive_time_live_bridge_backpressure_cycles = 32'd0;
    assign inactive_time_live_bridge_fifo_full = 1'b0;
    assign inactive_time_live_bridge_fifo_empty = 1'b0;

    assign heartbeat_cmac_tdata = 512'd0;
    assign heartbeat_cmac_tkeep = 64'd0;
    assign heartbeat_cmac_tvalid = 1'b0;
    assign heartbeat_cmac_tlast = 1'b0;
    assign tx_cmac_test_packet_count = 32'd0;
    assign tx_cmac_test_byte_count = 32'd0;

    cmac_tx_source_mux u_cmac_tx_source_mux (
        .clk(cmac_tx_clk),
        .rst_n(cmac_tx_rst_n),
        .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
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
        .clear(tx_clear_pulse_cmac || packet_stream_reset_pulse_cmac),
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


    always_ff @(posedge ctrl_clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            spur_corr_status_ctrl_meta <= 402'd0;
            spur_corr_status_ctrl_bundle <= 402'd0;
        end else begin
            spur_corr_status_ctrl_meta <= spur_corr_status_bundle;
            spur_corr_status_ctrl_bundle <= spur_corr_status_ctrl_meta;
        end
    end

    feng_ctrl_axi #(
        .NINPUT(8),
        .N_TX_ENDPOINTS(TX_ENDPOINTS),
        .N_SPEC_ROUTES(TX_SPEC_ROUTES),
        .N_TIME_ROUTES(TX_TIME_ROUTES)
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
        .sysref_capture_levels(sysref_levels_ctrl),
        .sysref_pl_edge_count(sysref_pl_edge_count_ctrl),
        .sysref_adc_edge_count(sysref_adc_edge_count_ctrl),
        .sysref_dac_edge_count(sysref_dac_edge_count_ctrl),
        .ref_locked(ref_lock_ctrl),
        .error_flags(error_flags),
        .scheduled_sync_status(scheduled_sync_status_ctrl),
        .scheduled_sync_error(scheduled_sync_error_ctrl),
        .scheduled_sync_active_generation(scheduled_sync_active_generation_ctrl),
        .scheduled_sync_actual_commit_pps_count(scheduled_sync_actual_commit_pps_count_ctrl),
        .scheduled_sync_actual_epoch_raw_sample0(scheduled_sync_actual_epoch_raw_sample0_ctrl),
        .scheduled_sync_actual_first_time_sample0(scheduled_sync_actual_first_time_sample0_ctrl),
        .scheduled_sync_actual_first_spec_sample0(scheduled_sync_actual_first_spec_sample0_ctrl),
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
        .pfb_coeff_status(pfb_coeff_status_ctrl),
        .pfb_coeff_loaded_count(pfb_coeff_loaded_count_ctrl),
        .pfb_coeff_active_id(pfb_coeff_active_id_ctrl),
        .pfb_coeff_active_checksum(pfb_coeff_active_checksum_ctrl),
        .pfb_coeff_error_count(pfb_coeff_error_count_ctrl),
        .science_aa100_active(science_aa100_active),
        .science_aa100_primed(science_aa100_primed),
        .science_aa100_coeff_version(science_aa100_coeff_version),
        .preview_busy(preview_busy_ctrl),
        .preview_done(preview_done_ctrl),
        .preview_error(preview_error_ctrl),
        .preview_capture_count(preview_capture_count_ctrl),
        .preview_sample0(preview_sample0_ctrl),
        .preview_rd_data(preview_rd_data_ctrl),
        .spur_corr_status(spur_corr_status_ctrl),
        .spur_corr_active_spur_id(spur_corr_active_spur_id_ctrl),
        .spur_corr_active_phase_step(spur_corr_active_phase_step_ctrl),
        .spur_corr_active_profile_id(spur_corr_active_profile_id_ctrl),
        .spur_corr_active_model_crc32(spur_corr_active_model_crc32_ctrl),
        .spur_corr_active_generation(spur_corr_active_generation_ctrl),
        .spur_corr_last_commit_sample0(spur_corr_last_commit_sample0_ctrl),
        .spur_corr_saturation_count(spur_corr_saturation_count_ctrl),
        .spur_corr_sample0_discontinuity_count(spur_corr_sample0_discontinuity_count_ctrl),
        .spur_corr_crc_error_count(spur_corr_crc_error_count_ctrl),
        .spur_corr_tracker_stale_count(spur_corr_tracker_stale_count_ctrl),
        .spur_corr_commit_count(spur_corr_commit_count_ctrl),
        .board_id(ctrl_board_id),
        .mode(ctrl_mode),
        .arm_latched(ctrl_arm_latched),
        .soft_epoch_pulse(ctrl_soft_epoch_pulse),
        .stop_pulse(ctrl_stop_pulse),
        .soft_reset_pulse(ctrl_soft_reset_pulse),
        .scheduled_sync_prepare_pulse(ctrl_scheduled_sync_prepare_pulse),
        .scheduled_sync_arm_pulse(ctrl_scheduled_sync_arm_pulse),
        .scheduled_sync_abort_pulse(ctrl_scheduled_sync_abort_pulse),
        .scheduled_sync_clear_status_pulse(ctrl_scheduled_sync_clear_status_pulse),
        .scheduled_sync_generation(ctrl_scheduled_sync_generation),
        .scheduled_sync_target_pps_count(ctrl_scheduled_sync_target_pps_count),
        .scheduled_sync_epoch_tai_seconds(ctrl_scheduled_sync_epoch_tai_seconds),
        .scheduled_sync_first_sample0(ctrl_scheduled_sync_first_sample0),
        .scheduled_sync_observation_tag(ctrl_scheduled_sync_observation_tag),
        .scheduled_sync_signal_chain_tag(ctrl_scheduled_sync_signal_chain_tag),
        .scheduled_sync_schedule_tag(ctrl_scheduled_sync_schedule_tag),
        .mts_result_id(ctrl_mts_result_id),
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
        .pfb_coeff_load_start_pulse(ctrl_pfb_coeff_load_start_pulse),
        .pfb_coeff_commit_pulse(ctrl_pfb_coeff_commit_pulse),
        .pfb_coeff_abort_pulse(ctrl_pfb_coeff_abort_pulse),
        .pfb_coeff_write_pulse(ctrl_pfb_coeff_write_pulse),
        .pfb_coeff_requested_taps(ctrl_pfb_coeff_requested_taps),
        .pfb_coeff_index(ctrl_pfb_coeff_index),
        .pfb_coeff_data(ctrl_pfb_coeff_data),
        .pfb_coeff_id(ctrl_pfb_coeff_id),
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
        .preview_corrected_select(ctrl_preview_corrected_select),
        .spur_corr_shadow_enable(ctrl_spur_corr_shadow_enable),
        .spur_corr_shadow_in_band(ctrl_spur_corr_shadow_in_band),
        .spur_corr_shadow_bypass(ctrl_spur_corr_shadow_bypass),
        .spur_corr_shadow_phase_reload(ctrl_spur_corr_shadow_phase_reload),
        .spur_corr_shadow_spur_id(ctrl_spur_corr_shadow_spur_id),
        .spur_corr_shadow_phase_step(ctrl_spur_corr_shadow_phase_step),
        .spur_corr_shadow_phase_seed(ctrl_spur_corr_shadow_phase_seed),
        .spur_corr_shadow_coefficients(ctrl_spur_corr_shadow_coefficients),
        .spur_corr_shadow_profile_id(ctrl_spur_corr_shadow_profile_id),
        .spur_corr_shadow_model_crc32(ctrl_spur_corr_shadow_model_crc32),
        .spur_corr_shadow_generation(ctrl_spur_corr_shadow_generation),
        .spur_corr_shadow_crc_valid(ctrl_spur_corr_shadow_crc_valid),
        .spur_corr_commit_pulse(ctrl_spur_corr_commit_pulse),
        .spur_corr_tracker_heartbeat_pulse(ctrl_spur_corr_tracker_heartbeat_pulse),
        .spur_corr_disable_pulse(ctrl_spur_corr_disable_pulse),
        .spur_corr_clear_errors_pulse(ctrl_spur_corr_clear_errors_pulse),
        .unix_seconds(ctrl_unix_seconds),
        .time_live_interval_beats(ctrl_time_live_interval_beats),
        .time_ddr_ring_enable(ctrl_time_ddr_ring_enable),
        .time_ddr_ring_clear_pulse(ctrl_time_ddr_ring_clear_pulse),
        .time_ddr_ring_base_addr(ctrl_time_ddr_ring_base_addr),
        .time_ddr_ring_slots(ctrl_time_ddr_ring_slots),
        .time_multiflow_enable(ctrl_time_multiflow_enable),
        .time_multiflow_base_endpoint(ctrl_time_multiflow_base_endpoint),
        .time_multiflow_count(ctrl_time_multiflow_count),
        .science_sample_rate_mode_cfg(ctrl_science_sample_rate_mode_cfg),
        .science_output_mode_cfg(ctrl_science_output_mode_cfg)
    );

endmodule
