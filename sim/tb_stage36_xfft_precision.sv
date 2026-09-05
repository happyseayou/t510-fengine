`timescale 1ns/1ps

// Real generated XFFT IP only; never compile with T510_SIM_FFT_MODEL.
module tb_stage36_xfft_precision;
`ifdef T510_SIM_FFT_MODEL
    initial $fatal(1, "real XFFT precision fileset must not inherit the simplified model define");
`endif
    localparam integer N = 4096;
    localparam integer FRAMES = 35;
    logic clk = 0;
    always #1.55 clk = ~clk;
    logic resetn = 0;
    logic [255:0] cfg = 0;
    logic cfg_valid = 0;
    wire cfg_ready;
    logic [255:0] s_data = 0;
    logic s_valid = 0, s_last = 0;
    wire s_ready;
    wire [255:0] m_data;
    wire [23:0] m_user;
    wire m_valid, m_last;
    wire [7:0] status_data;
    wire status_valid;
    wire frame_started, unexpected, missing, overflow, status_halt, in_halt, out_halt;
    logic [255:0] input_words [0:FRAMES*N-1];
    integer outfile, index, lane, out_frame=0, out_bin=0, input_wait_cycles=0;
    string input_path, output_path;

    t510_fengine_xfft_4096_8lane_streaming dut (
        .aclk(clk), .aresetn(resetn),
        .s_axis_config_tdata(cfg), .s_axis_config_tvalid(cfg_valid), .s_axis_config_tready(cfg_ready),
        .s_axis_data_tdata(s_data), .s_axis_data_tvalid(s_valid), .s_axis_data_tready(s_ready),
        .s_axis_data_tlast(s_last), .m_axis_data_tdata(m_data), .m_axis_data_tuser(m_user),
        .m_axis_data_tvalid(m_valid), .m_axis_data_tready(1'b1), .m_axis_data_tlast(m_last),
        .m_axis_status_tdata(status_data), .m_axis_status_tvalid(status_valid),
        .m_axis_status_tready(1'b1), .event_frame_started(frame_started),
        .event_tlast_unexpected(unexpected), .event_tlast_missing(missing),
        .event_fft_overflow(overflow), .event_status_channel_halt(status_halt),
        .event_data_in_channel_halt(in_halt), .event_data_out_channel_halt(out_halt)
    );

    always @(posedge clk) if (resetn) begin
        if (unexpected || missing || overflow || status_halt || out_halt)
            $fatal(1,"REAL_XFFT_PROTOCOL_OR_OVERFLOW_FAILURE");
        if (in_halt && s_valid)
            $fatal(1,"REAL_XFFT_INPUT_UNDERRUN");
        if (m_valid) begin
            if (m_user[11:0] !== out_bin[11:0] || m_last !== (out_bin==N-1))
                $fatal(1,"REAL_XFFT_BIN_OR_TLAST_FAILURE");
            $fdisplay(outfile,"%0d %0d %064h",out_frame,out_bin,m_data);
            if (out_bin==N-1) begin
                out_bin=0;
                out_frame=out_frame+1;
                if (out_frame==FRAMES) begin
                    $fclose(outfile);
                    $display("STAGE36_REAL_XFFT_COMPLETE frames=%0d overflow=0 slave_wait_cycles=%0d",out_frame,input_wait_cycles);
                    $finish;
                end
            end else out_bin=out_bin+1;
        end
    end

    initial begin
        if (!$value$plusargs("INPUT=%s",input_path) || !$value$plusargs("OUTPUT=%s",output_path))
            $fatal(1,"INPUT and OUTPUT plusargs are required");
        $readmemh(input_path,input_words);
        outfile=$fopen(output_path,"w");
        if (!outfile) $fatal(1,"cannot open real FFT output");
        // Wait beyond glbl's 100 ns GSR pulse before configuring the real IP.
        repeat (64) @(negedge clk);
        resetn=1;
        cfg[7:0]=8'hff;
        for (lane=0;lane<8;lane=lane+1) cfg[8+lane*12+:12]=12'h556;
        cfg_valid=1;
        do @(posedge clk); while (!cfg_ready);
        @(negedge clk);
        cfg_valid=0;
        repeat (8) @(negedge clk);
        for (index=0;index<FRAMES*N;index=index+1) begin
            s_data=input_words[index];
            s_valid=1;
            s_last=(index%N==N-1);
            @(posedge clk);
            // PG109 (May 4, 2022), Controlling the FFT Core: Realtime
            // forbids master waitstates, but the core may insert slave
            // waitstates (including after buffering the very first symbol).
            // Hold TVALID and data stable; only advance on a real transfer.
            while (!s_ready) begin
                input_wait_cycles=input_wait_cycles+1;
                @(posedge clk);
            end
            @(negedge clk);
        end
        s_valid=0;
        s_last=0;
    end
    initial begin
        #2000000;
        $fatal(1,"REAL_XFFT_TIMEOUT");
    end
endmodule
