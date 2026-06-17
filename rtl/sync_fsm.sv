module sync_fsm (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        arm_req,
    input  wire        stop_req,
    input  wire        soft_epoch_req,
    input  wire        soft_reset_req,
    input  wire [1:0]  sync_mode,
    input  wire        ref_locked,
    input  wire        rfdc_ready,
    input  wire        pps_in,
    input  wire        sync_error,
    output logic [3:0] state,
    output logic       armed,
    output logic       streaming,
    output logic       waiting_for_epoch,
    output logic       epoch_reset_pulse
);

    localparam [3:0] ST_RESET        = 4'd0;
    localparam [3:0] ST_CLOCK_CONFIG = 4'd1;
    localparam [3:0] ST_RFDC_CONFIG  = 4'd2;
    localparam [3:0] ST_WAIT_LOCK    = 4'd3;
    localparam [3:0] ST_WAIT_PPS     = 4'd4;
    localparam [3:0] ST_ARMED        = 4'd5;
    localparam [3:0] ST_STREAMING    = 4'd6;
    localparam [3:0] ST_STOPPING     = 4'd7;
    localparam [3:0] ST_ERROR        = 4'd8;

    localparam [1:0] SYNC_EXTERNAL_PPS   = 2'd0;
    localparam [1:0] SYNC_SOFTWARE_EPOCH = 2'd1;
    localparam [1:0] SYNC_FREE_RUN       = 2'd2;

    logic pps_d;
    wire  pps_rise = pps_in && !pps_d;
    wire  epoch_event =
        (sync_mode == SYNC_EXTERNAL_PPS)   ? pps_rise :
        (sync_mode == SYNC_SOFTWARE_EPOCH) ? soft_epoch_req :
        (sync_mode == SYNC_FREE_RUN)       ? 1'b1 :
                                             pps_rise;

    always_comb begin
        waiting_for_epoch =
            (state == ST_ARMED) &&
            arm_req &&
            (sync_mode != SYNC_FREE_RUN) &&
            !epoch_event;
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
            state             <= ST_RESET;
            armed             <= 1'b0;
            streaming         <= 1'b0;
            epoch_reset_pulse <= 1'b0;
        end else begin
            epoch_reset_pulse <= 1'b0;

            if (soft_reset_req) begin
                state     <= ST_RESET;
                armed     <= 1'b0;
                streaming <= 1'b0;
            end else begin
                case (state)
                    ST_RESET: begin
                        armed     <= 1'b0;
                        streaming <= 1'b0;
                        state     <= ST_CLOCK_CONFIG;
                    end

                    ST_CLOCK_CONFIG: begin
                        if (ref_locked) begin
                            state <= ST_RFDC_CONFIG;
                        end
                    end

                    ST_RFDC_CONFIG: begin
                        state <= ST_WAIT_LOCK;
                    end

                    ST_WAIT_LOCK: begin
                        if (ref_locked && rfdc_ready) begin
                            state <= ST_WAIT_PPS;
                        end
                    end

                    ST_WAIT_PPS: begin
                        armed <= arm_req;
                        if (!arm_req) begin
                            state <= ST_RESET;
                        end else begin
                            state <= ST_ARMED;
                        end
                    end

                    ST_ARMED: begin
                        armed <= 1'b1;
                        if (!arm_req) begin
                            state <= ST_STOPPING;
                        end else if (!ref_locked || !rfdc_ready || sync_error) begin
                            state <= ST_ERROR;
                        end else if (epoch_event) begin
                            epoch_reset_pulse <= 1'b1;
                            streaming         <= 1'b1;
                            state             <= ST_STREAMING;
                        end
                    end

                    ST_STREAMING: begin
                        armed <= 1'b1;
                        if (stop_req || !arm_req) begin
                            streaming <= 1'b0;
                            state     <= ST_STOPPING;
                        end else if (!ref_locked || !rfdc_ready || sync_error) begin
                            streaming <= 1'b0;
                            state     <= ST_ERROR;
                        end
                    end

                    ST_STOPPING: begin
                        armed     <= 1'b0;
                        streaming <= 1'b0;
                        state     <= ST_RESET;
                    end

                    ST_ERROR: begin
                        armed     <= 1'b0;
                        streaming <= 1'b0;
                    end

                    default: begin
                        state     <= ST_RESET;
                        armed     <= 1'b0;
                        streaming <= 1'b0;
                    end
                endcase
            end
        end
    end

endmodule
