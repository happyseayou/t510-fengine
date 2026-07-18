`default_nettype none

module station_sync_scheduler #(
    parameter integer MIN_LEAD_PPS = 2
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        prepare_pulse,
    input  wire        arm_pulse,
    input  wire        abort_pulse,
    input  wire        clear_status_pulse,
    input  wire        stop_pulse,
    input  wire        soft_reset_pulse,

    input  wire [63:0] schedule_generation,
    input  wire [63:0] schedule_target_pps_count,
    input  wire [63:0] schedule_epoch_tai_seconds,
    input  wire [63:0] schedule_first_sample0,
    input  wire [63:0] schedule_observation_tag,
    input  wire [31:0] schedule_signal_chain_tag,
    input  wire [31:0] schedule_tag,
    input  wire [31:0] schedule_mts_result_id,

    input  wire        pps_in,
    input  wire [63:0] pps_count,
    input  wire        pps_recent,
    input  wire        ref_locked,
    input  wire        rfdc_ready,

    input  wire [1:0]  science_bandwidth_mode,
    input  wire        science_aa100_active,

    input  wire        adc_valid,
    input  wire [63:0] adc_raw_sample0,
    output wire [63:0] adc_observation_sample0,

    input  wire        science_valid,
    input  wire        science_ready,
    input  wire [63:0] science_sample0,
    input  wire        time_packet_event,
    input  wire [63:0] time_packet_sample0,
    input  wire        spec_packet_event,
    input  wire [63:0] spec_packet_sample0,

    output logic       selected,
    output logic       armed,
    output logic       streaming,
    output wire        release_stream_now,
    output logic       waiting_for_epoch,
    output logic       epoch_reset_pulse,
    output logic       epoch_valid,
    output logic [3:0] state,
    output logic [31:0] status_flags,
    output logic [31:0] error_code,

    output logic [63:0] active_generation,
    output logic [63:0] active_target_pps_count,
    output logic [63:0] active_epoch_tai_seconds,
    output logic [63:0] active_first_sample0,
    output logic [63:0] active_observation_tag,
    output logic [31:0] active_signal_chain_tag,
    output logic [31:0] active_schedule_tag,
    output logic [31:0] active_mts_result_id,
    output logic [63:0] actual_commit_pps_count,
    output logic [63:0] actual_epoch_raw_sample0,
    output logic [63:0] actual_first_time_sample0,
    output logic [63:0] actual_first_spec_sample0
);

    localparam [3:0] ST_IDLE              = 4'd0;
    localparam [3:0] ST_PREPARED          = 4'd1;
    localparam [3:0] ST_ARMED             = 4'd2;
    localparam [3:0] ST_WAIT_EPOCH_SAMPLE = 4'd3;
    localparam [3:0] ST_PRIMING           = 4'd4;
    localparam [3:0] ST_STREAMING         = 4'd5;
    localparam [3:0] ST_ERROR             = 4'd6;

    localparam [31:0] ERR_NONE             = 32'd0;
    localparam [31:0] ERR_PREPARE_BUSY     = 32'd1;
    localparam [31:0] ERR_BAD_ALIGNMENT    = 32'd2;
    localparam [31:0] ERR_GENERATION       = 32'd3;
    localparam [31:0] ERR_MTS_NOT_VALID    = 32'd4;
    localparam [31:0] ERR_REF_UNLOCKED     = 32'd5;
    localparam [31:0] ERR_RFDC_NOT_READY   = 32'd6;
    localparam [31:0] ERR_PPS_NOT_RECENT   = 32'd7;
    localparam [31:0] ERR_BAD_STATE        = 32'd8;
    localparam [31:0] ERR_TARGET_TOO_SOON  = 32'd9;
    localparam [31:0] ERR_TARGET_MISSED    = 32'd10;
    localparam [31:0] ERR_FIRST_SAMPLE_MISSED = 32'd11;
    localparam [31:0] ERR_SIGNAL_CHAIN_INVALID = 32'd12;
    localparam [31:0] ERR_EPOCH_TAI_INVALID = 32'd13;

    logic pps_d;
    logic time_seen;
    logic spec_seen;
    wire pps_rise = pps_in && !pps_d;
    wire [63:0] next_pps_count = pps_count + 64'd1;
    // The beat present while epoch_reset_pulse is high is intentionally
    // discarded by the science pipeline.  Epoch sample zero must therefore
    // be the first accepted beat after reset is released, or the decimator
    // alignment residues move by one four-sample ADC beat.
    wire capture_epoch_sample =
        selected && (state == ST_WAIT_EPOCH_SAMPLE) &&
        !epoch_reset_pulse && adc_valid;
    wire science_fire = science_valid && science_ready;
    wire first_sample0_reachable =
        (schedule_first_sample0 != 64'd0) &&
        ((science_bandwidth_mode == 2'd0) ?
            (schedule_first_sample0[4:0] == 5'd0) :
         (science_bandwidth_mode == 2'd1) ?
            (science_aa100_active ?
                (schedule_first_sample0[2:0] == 3'd4) :
                (schedule_first_sample0[2:0] == 3'd0)) :
            (schedule_first_sample0[1:0] == 2'd0));

    // Look ahead by one clock so the beat carrying first_sample0 is routed;
    // the registered streaming flag rises on that edge and then stays high.
    assign release_stream_now = selected && (state == ST_PRIMING) &&
        science_valid && (science_sample0 == active_first_sample0);

    assign adc_observation_sample0 = capture_epoch_sample ? 64'd0 :
        (selected && epoch_valid ?
            (adc_raw_sample0 - actual_epoch_raw_sample0) :
            adc_raw_sample0);

    always_comb begin
        waiting_for_epoch = selected &&
            ((state == ST_ARMED) || (state == ST_WAIT_EPOCH_SAMPLE));
        status_flags = {
            12'd0,
            state,
            3'd0,
            spec_seen,
            time_seen,
            (active_mts_result_id != 32'd0),
            rfdc_ready,
            ref_locked,
            pps_recent,
            (error_code != ERR_NONE),
            streaming,
            epoch_valid,
            (actual_commit_pps_count != 64'd0),
            armed,
            (state == ST_PREPARED),
            selected
        };
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pps_d <= 1'b0;
        end else begin
            pps_d <= pps_in;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            selected <= 1'b0;
            armed <= 1'b0;
            streaming <= 1'b0;
            epoch_reset_pulse <= 1'b0;
            epoch_valid <= 1'b0;
            state <= ST_IDLE;
            error_code <= ERR_NONE;
            active_generation <= 64'd0;
            active_target_pps_count <= 64'd0;
            active_epoch_tai_seconds <= 64'd0;
            active_first_sample0 <= 64'd0;
            active_observation_tag <= 64'd0;
            active_signal_chain_tag <= 32'd0;
            active_schedule_tag <= 32'd0;
            active_mts_result_id <= 32'd0;
            actual_commit_pps_count <= 64'd0;
            actual_epoch_raw_sample0 <= 64'd0;
            actual_first_time_sample0 <= 64'd0;
            actual_first_spec_sample0 <= 64'd0;
            time_seen <= 1'b0;
            spec_seen <= 1'b0;
        end else begin
            epoch_reset_pulse <= 1'b0;

            if (clear_status_pulse && (state != ST_ERROR)) begin
                error_code <= ERR_NONE;
                actual_first_time_sample0 <= 64'd0;
                actual_first_spec_sample0 <= 64'd0;
                time_seen <= 1'b0;
                spec_seen <= 1'b0;
            end

            if (soft_reset_pulse || abort_pulse) begin
                selected <= 1'b0;
                armed <= 1'b0;
                streaming <= 1'b0;
                epoch_valid <= 1'b0;
                state <= ST_IDLE;
                error_code <= ERR_NONE;
            end else if (stop_pulse && selected) begin
                selected <= 1'b0;
                armed <= 1'b0;
                streaming <= 1'b0;
                epoch_valid <= 1'b0;
                state <= ST_IDLE;
            end else begin
                if (prepare_pulse) begin
                    if (selected && (state != ST_IDLE)) begin
                        error_code <= ERR_PREPARE_BUSY;
                    end else if (!first_sample0_reachable) begin
                        selected <= 1'b1;
                        state <= ST_ERROR;
                        error_code <= ERR_BAD_ALIGNMENT;
                    end else if ((schedule_generation == 64'd0) ||
                                 (schedule_generation <= active_generation)) begin
                        selected <= 1'b1;
                        state <= ST_ERROR;
                        error_code <= ERR_GENERATION;
                    end else if (schedule_epoch_tai_seconds == 64'd0) begin
                        selected <= 1'b1;
                        state <= ST_ERROR;
                        error_code <= ERR_EPOCH_TAI_INVALID;
                    end else if (schedule_signal_chain_tag == 32'd0) begin
                        selected <= 1'b1;
                        state <= ST_ERROR;
                        error_code <= ERR_SIGNAL_CHAIN_INVALID;
                    end else begin
                        selected <= 1'b1;
                        armed <= 1'b0;
                        streaming <= 1'b0;
                        epoch_valid <= 1'b0;
                        state <= ST_PREPARED;
                        error_code <= ERR_NONE;
                        active_generation <= schedule_generation;
                        active_target_pps_count <= schedule_target_pps_count;
                        active_epoch_tai_seconds <= schedule_epoch_tai_seconds;
                        active_first_sample0 <= schedule_first_sample0;
                        active_observation_tag <= schedule_observation_tag;
                        active_signal_chain_tag <= schedule_signal_chain_tag;
                        active_schedule_tag <= schedule_tag;
                        active_mts_result_id <= schedule_mts_result_id;
                        actual_commit_pps_count <= 64'd0;
                        actual_epoch_raw_sample0 <= 64'd0;
                        actual_first_time_sample0 <= 64'd0;
                        actual_first_spec_sample0 <= 64'd0;
                        time_seen <= 1'b0;
                        spec_seen <= 1'b0;
                    end
                end

                if (arm_pulse) begin
                    if (!selected || (state != ST_PREPARED)) begin
                        state <= ST_ERROR;
                        error_code <= ERR_BAD_STATE;
                    end else if (active_mts_result_id == 32'd0) begin
                        state <= ST_ERROR;
                        error_code <= ERR_MTS_NOT_VALID;
                    end else if (!ref_locked) begin
                        state <= ST_ERROR;
                        error_code <= ERR_REF_UNLOCKED;
                    end else if (!rfdc_ready) begin
                        state <= ST_ERROR;
                        error_code <= ERR_RFDC_NOT_READY;
                    end else if (!pps_recent) begin
                        state <= ST_ERROR;
                        error_code <= ERR_PPS_NOT_RECENT;
                    end else if (active_target_pps_count <
                                 (pps_count + MIN_LEAD_PPS)) begin
                        state <= ST_ERROR;
                        error_code <= ERR_TARGET_TOO_SOON;
                    end else begin
                        armed <= 1'b1;
                        state <= ST_ARMED;
                    end
                end

                if (selected && (state >= ST_ARMED) && (state <= ST_STREAMING) &&
                    !ref_locked) begin
                    armed <= 1'b0;
                    streaming <= 1'b0;
                    state <= ST_ERROR;
                    error_code <= ERR_REF_UNLOCKED;
                end else if (selected && (state >= ST_ARMED) &&
                             (state <= ST_STREAMING) && !rfdc_ready) begin
                    armed <= 1'b0;
                    streaming <= 1'b0;
                    state <= ST_ERROR;
                    error_code <= ERR_RFDC_NOT_READY;
                end else if (selected && (state >= ST_ARMED) &&
                             (state <= ST_STREAMING) && !pps_recent) begin
                    armed <= 1'b0;
                    streaming <= 1'b0;
                    state <= ST_ERROR;
                    error_code <= ERR_PPS_NOT_RECENT;
                end else case (state)
                    ST_ARMED: begin
                        if (pps_rise && (next_pps_count == active_target_pps_count)) begin
                            armed <= 1'b0;
                            epoch_reset_pulse <= 1'b1;
                            epoch_valid <= 1'b0;
                            actual_commit_pps_count <= next_pps_count;
                            state <= ST_WAIT_EPOCH_SAMPLE;
                        end else if (pps_rise && (next_pps_count > active_target_pps_count)) begin
                            armed <= 1'b0;
                            state <= ST_ERROR;
                            error_code <= ERR_TARGET_MISSED;
                        end
                    end

                    ST_WAIT_EPOCH_SAMPLE: begin
                        if (!epoch_reset_pulse && adc_valid) begin
                            actual_epoch_raw_sample0 <= adc_raw_sample0;
                            epoch_valid <= 1'b1;
                            state <= ST_PRIMING;
                        end
                    end

                    ST_PRIMING: begin
                        // release_stream_now enables the selected branches while
                        // PRIMING.  Do not claim STREAMING until that exact beat
                        // is actually accepted by the shared science fanout.
                        if (science_fire && (science_sample0 == active_first_sample0)) begin
                            streaming <= 1'b1;
                            state <= ST_STREAMING;
                            if (time_packet_event && !time_seen) begin
                                time_seen <= 1'b1;
                                actual_first_time_sample0 <= time_packet_sample0;
                            end
                            if (spec_packet_event && !spec_seen) begin
                                spec_seen <= 1'b1;
                                actual_first_spec_sample0 <= spec_packet_sample0;
                            end
                        end else if (science_fire &&
                                    (science_sample0 > active_first_sample0)) begin
                            streaming <= 1'b0;
                            state <= ST_ERROR;
                            error_code <= ERR_FIRST_SAMPLE_MISSED;
                        end
                    end

                    ST_STREAMING: begin
                        if (time_packet_event && !time_seen) begin
                            time_seen <= 1'b1;
                            actual_first_time_sample0 <= time_packet_sample0;
                        end
                        if (spec_packet_event && !spec_seen) begin
                            spec_seen <= 1'b1;
                            actual_first_spec_sample0 <= spec_packet_sample0;
                        end
                    end

                    default: begin
                    end
                endcase
            end
        end
    end

endmodule

`default_nettype wire
