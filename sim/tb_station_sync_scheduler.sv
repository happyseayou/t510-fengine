`timescale 1ns/1ps
`include "tb_common.svh"

module tb_station_sync_scheduler;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    always #5 clk = ~clk;

    logic prepare_pulse = 0, arm_pulse = 0, abort_pulse = 0;
    logic clear_status_pulse = 0, stop_pulse = 0, soft_reset_pulse = 0;
    logic [63:0] generation = 1, target_pps = 3, epoch_tai = 1000;
    logic [63:0] first_sample0 = 16, observation_tag = 64'h55;
    logic [31:0] signal_chain_tag = 32'h11, schedule_tag = 32'h22, mts_result_id = 32'h33;
    logic pps_in = 0;
    logic [63:0] pps_count = 0;
    logic [1:0] bandwidth_mode = 2'd2;
    logic aa100_active = 1'b0;
    logic adc_valid = 0;
    logic [63:0] adc_raw_sample0 = 0;
    logic science_valid = 0;
    logic [63:0] science_sample0 = 0;
    logic time_event = 0, spec_event = 0;
    logic [63:0] time_sample0 = 0, spec_sample0 = 0;
    wire [63:0] observation_sample0;
    wire selected, armed, streaming, release_now, waiting, epoch_reset, epoch_valid;
    wire [3:0] state;
    wire [31:0] status, error_code;
    wire [63:0] active_generation, active_target, active_tai, active_first, active_obs;
    wire [31:0] active_chain, active_schedule, active_mts;
    wire [63:0] actual_pps, actual_raw, actual_time, actual_spec;

    station_sync_scheduler dut (
        .clk(clk), .rst_n(rst_n),
        .prepare_pulse(prepare_pulse), .arm_pulse(arm_pulse),
        .abort_pulse(abort_pulse), .clear_status_pulse(clear_status_pulse),
        .stop_pulse(stop_pulse), .soft_reset_pulse(soft_reset_pulse),
        .schedule_generation(generation), .schedule_target_pps_count(target_pps),
        .schedule_epoch_tai_seconds(epoch_tai), .schedule_first_sample0(first_sample0),
        .schedule_observation_tag(observation_tag), .schedule_signal_chain_tag(signal_chain_tag),
        .schedule_tag(schedule_tag), .schedule_mts_result_id(mts_result_id),
        .pps_in(pps_in), .pps_count(pps_count), .pps_recent(1'b1),
        .ref_locked(1'b1), .rfdc_ready(1'b1),
        .science_bandwidth_mode(bandwidth_mode), .science_aa100_active(aa100_active),
        .adc_valid(adc_valid), .adc_raw_sample0(adc_raw_sample0),
        .adc_observation_sample0(observation_sample0),
        .science_valid(science_valid), .science_sample0(science_sample0),
        .time_packet_event(time_event), .time_packet_sample0(time_sample0),
        .spec_packet_event(spec_event), .spec_packet_sample0(spec_sample0),
        .selected(selected), .armed(armed), .streaming(streaming),
        .release_stream_now(release_now),
        .waiting_for_epoch(waiting), .epoch_reset_pulse(epoch_reset),
        .epoch_valid(epoch_valid), .state(state), .status_flags(status),
        .error_code(error_code), .active_generation(active_generation),
        .active_target_pps_count(active_target), .active_epoch_tai_seconds(active_tai),
        .active_first_sample0(active_first), .active_observation_tag(active_obs),
        .active_signal_chain_tag(active_chain), .active_schedule_tag(active_schedule),
        .active_mts_result_id(active_mts), .actual_commit_pps_count(actual_pps),
        .actual_epoch_raw_sample0(actual_raw), .actual_first_time_sample0(actual_time),
        .actual_first_spec_sample0(actual_spec)
    );

    task pulse(input integer which);
        begin
            @(negedge clk);
            case (which)
                0: prepare_pulse = 1;
                1: arm_pulse = 1;
                2: abort_pulse = 1;
            endcase
            @(negedge clk);
            prepare_pulse = 0; arm_pulse = 0; abort_pulse = 0;
        end
    endtask

    task pps;
        begin
            @(negedge clk); pps_in = 1;
            @(posedge clk); pps_count <= pps_count + 1;
            @(negedge clk); pps_in = 0;
            @(posedge clk);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        pulse(0);
        `TB_CHECK_EQ(state, 4'd1, "prepare enters PREPARED")
        `TB_CHECK_EQ(active_generation, 64'd1, "generation frozen on prepare")
        pulse(1);
        `TB_CHECK_EQ(state, 4'd2, "arm enters ARMED")
        pps();
        pps();
        @(negedge clk); adc_raw_sample0 = 64'd996; adc_valid = 1;
        pps();
        `TB_CHECK_EQ(actual_pps, 64'd3, "commit occurs on exact target PPS")
        `TB_CHECK_EQ(state, 4'd3, "commit waits for first ADC sample")
        `TB_CHECK_EQ(actual_raw, 64'd0, "ADC beat discarded by epoch reset is not sample zero")

        @(negedge clk); adc_raw_sample0 = 64'd1000;
        #1 `TB_CHECK_EQ(observation_sample0, 64'd0, "first valid sample maps to observation zero")
        @(posedge clk);
        @(negedge clk); adc_valid = 0;
        `TB_CHECK_EQ(actual_raw, 64'd1000, "raw epoch sample is recorded")
        `TB_CHECK_EQ(epoch_valid, 1'b1, "epoch mapping becomes valid")

        @(negedge clk);
        science_sample0 = 16; science_valid = 1;
        time_sample0 = 16; spec_sample0 = 16; time_event = 1; spec_event = 1;
        #1 `TB_CHECK_EQ(release_now, 1'b1, "first_sample0 is released without losing its beat")
        @(posedge clk);
        @(negedge clk); science_valid = 0; time_event = 0; spec_event = 0;
        `TB_CHECK_EQ(streaming, 1'b1, "streaming starts at configured first_sample0")
        `TB_CHECK_EQ(actual_time, 64'd16, "first TIME sample0 telemetry")
        `TB_CHECK_EQ(actual_spec, 64'd16, "first SPEC sample0 telemetry")

        pulse(2);
        generation = 2; first_sample0 = 32768;
        bandwidth_mode = 2'd1;
        aa100_active = 1'b1;
        pulse(0);
        `TB_CHECK_EQ(error_code, 32'd2, "AA100 rejects an unreachable first_sample0 residue")
        pulse(2);
        first_sample0 = 32788;
        generation = 2; target_pps = pps_count + 1;
        pulse(0); pulse(1);
        `TB_CHECK_EQ(error_code, 32'd9, "target with insufficient lead is rejected")
        pulse(2);
        generation = 3; target_pps = pps_count + 5; epoch_tai = 0;
        pulse(0);
        `TB_CHECK_EQ(error_code, 32'd13, "zero TAI epoch is rejected")
        `TB_PASS("tb_station_sync_scheduler")
    end
endmodule
