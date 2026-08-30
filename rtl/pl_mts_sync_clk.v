module pl_mts_sync_clk (
    input  wire pl_clk_p,
    input  wire pl_clk_n,
    input  wire pl_sys_ref_p,
    input  wire pl_sys_ref_n,
    output wire pl_clk,
    output wire user_sysref_adc,
    output wire user_sysref_dac
);

    wire pl_clk_bufds;
    wire pl_sys_ref_bufds;
    wire pl_clk_bufg;
    reg  pl_sys_ref_capture = 1'b0;

    IBUFDS u_pl_clk_ibufds (
        .I(pl_clk_p),
        .IB(pl_clk_n),
        .O(pl_clk_bufds)
    );

    BUFG u_pl_clk_bufg (
        .I(pl_clk_bufds),
        .O(pl_clk_bufg)
    );

    IBUFDS u_pl_sys_ref_ibufds (
        .I(pl_sys_ref_p),
        .IB(pl_sys_ref_n),
        .O(pl_sys_ref_bufds)
    );

    always @(posedge pl_clk_bufg) begin
        pl_sys_ref_capture <= pl_sys_ref_bufds;
    end

    assign user_sysref_adc = pl_sys_ref_capture;
    assign user_sysref_dac = pl_sys_ref_capture;
    assign pl_clk = pl_clk_bufg;

endmodule
