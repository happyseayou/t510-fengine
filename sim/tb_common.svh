`ifndef TB_COMMON_SVH
`define TB_COMMON_SVH

`timescale 1ns/1ps

`define TB_CHECK(COND, MSG) \
    if (!(COND)) begin \
        $display("[%0t] CHECK FAILED: %s", $time, MSG); \
        $error("%s", MSG); \
        $finish; \
    end

`define TB_CHECK_EQ(ACT, EXP, MSG) \
    if ((ACT) !== (EXP)) begin \
        $display("[%0t] CHECK FAILED: %s", $time, MSG); \
        $display("    actual   = 0x%0h", ACT); \
        $display("    expected = 0x%0h", EXP); \
        $error("%s", MSG); \
        $finish; \
    end

`define TB_PASS(NAME) \
    begin \
        $display("[%0t] PASS: %s", $time, NAME); \
        $finish; \
    end

`endif
