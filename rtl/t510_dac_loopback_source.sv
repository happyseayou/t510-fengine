module t510_dac_loopback_source (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [7:0]   tone_enable_mask,
    input  wire [127:0] tone_amplitude_vec,
    input  wire [255:0] tone_phase_step_vec,
    input  wire [255:0] tone_phase0_vec,
    input  wire [255:0] tone_phase_inject_vec,
    input  wire [15:0]  tone_mode_vec,
    input  wire [31:0]  tone_phase_epoch,
    output wire [127:0] s00_axis_tdata,
    input  wire         s00_axis_tready,
    output wire         s00_axis_tvalid,
    output wire [127:0] s02_axis_tdata,
    input  wire         s02_axis_tready,
    output wire         s02_axis_tvalid,
    output wire [127:0] s10_axis_tdata,
    input  wire         s10_axis_tready,
    output wire         s10_axis_tvalid,
    output wire [127:0] s12_axis_tdata,
    input  wire         s12_axis_tready,
    output wire         s12_axis_tvalid,
    output wire [127:0] s20_axis_tdata,
    input  wire         s20_axis_tready,
    output wire         s20_axis_tvalid,
    output wire [127:0] s22_axis_tdata,
    input  wire         s22_axis_tready,
    output wire         s22_axis_tvalid,
    output wire [127:0] s30_axis_tdata,
    input  wire         s30_axis_tready,
    output wire         s30_axis_tvalid,
    output wire [127:0] s32_axis_tdata,
    input  wire         s32_axis_tready,
    output wire         s32_axis_tvalid,
    output wire         all_dac_ready,
    output wire [31:0]  audit_phase_epoch_seen,
    output wire [31:0]  audit_ch0_phase_acc,
    output wire [31:0]  audit_ch0_phase_step,
    output wire [31:0]  audit_ch0_phase0,
    output wire [31:0]  audit_ch0_mode
);

    logic [31:0] phase [0:7];
    logic [31:0] phase_epoch_seen;
    integer ch;

    function automatic signed [15:0] quarter_sine_lut(input [8:0] idx);
        begin
            case (idx)
            9'd0: quarter_sine_lut = 16'sd0;
            9'd1: quarter_sine_lut = 16'sd101;
            9'd2: quarter_sine_lut = 16'sd201;
            9'd3: quarter_sine_lut = 16'sd302;
            9'd4: quarter_sine_lut = 16'sd403;
            9'd5: quarter_sine_lut = 16'sd504;
            9'd6: quarter_sine_lut = 16'sd604;
            9'd7: quarter_sine_lut = 16'sd705;
            9'd8: quarter_sine_lut = 16'sd806;
            9'd9: quarter_sine_lut = 16'sd906;
            9'd10: quarter_sine_lut = 16'sd1007;
            9'd11: quarter_sine_lut = 16'sd1108;
            9'd12: quarter_sine_lut = 16'sd1208;
            9'd13: quarter_sine_lut = 16'sd1309;
            9'd14: quarter_sine_lut = 16'sd1410;
            9'd15: quarter_sine_lut = 16'sd1510;
            9'd16: quarter_sine_lut = 16'sd1611;
            9'd17: quarter_sine_lut = 16'sd1712;
            9'd18: quarter_sine_lut = 16'sd1812;
            9'd19: quarter_sine_lut = 16'sd1913;
            9'd20: quarter_sine_lut = 16'sd2013;
            9'd21: quarter_sine_lut = 16'sd2114;
            9'd22: quarter_sine_lut = 16'sd2214;
            9'd23: quarter_sine_lut = 16'sd2315;
            9'd24: quarter_sine_lut = 16'sd2415;
            9'd25: quarter_sine_lut = 16'sd2516;
            9'd26: quarter_sine_lut = 16'sd2616;
            9'd27: quarter_sine_lut = 16'sd2716;
            9'd28: quarter_sine_lut = 16'sd2817;
            9'd29: quarter_sine_lut = 16'sd2917;
            9'd30: quarter_sine_lut = 16'sd3017;
            9'd31: quarter_sine_lut = 16'sd3118;
            9'd32: quarter_sine_lut = 16'sd3218;
            9'd33: quarter_sine_lut = 16'sd3318;
            9'd34: quarter_sine_lut = 16'sd3418;
            9'd35: quarter_sine_lut = 16'sd3519;
            9'd36: quarter_sine_lut = 16'sd3619;
            9'd37: quarter_sine_lut = 16'sd3719;
            9'd38: quarter_sine_lut = 16'sd3819;
            9'd39: quarter_sine_lut = 16'sd3919;
            9'd40: quarter_sine_lut = 16'sd4019;
            9'd41: quarter_sine_lut = 16'sd4119;
            9'd42: quarter_sine_lut = 16'sd4219;
            9'd43: quarter_sine_lut = 16'sd4319;
            9'd44: quarter_sine_lut = 16'sd4418;
            9'd45: quarter_sine_lut = 16'sd4518;
            9'd46: quarter_sine_lut = 16'sd4618;
            9'd47: quarter_sine_lut = 16'sd4718;
            9'd48: quarter_sine_lut = 16'sd4817;
            9'd49: quarter_sine_lut = 16'sd4917;
            9'd50: quarter_sine_lut = 16'sd5016;
            9'd51: quarter_sine_lut = 16'sd5116;
            9'd52: quarter_sine_lut = 16'sd5215;
            9'd53: quarter_sine_lut = 16'sd5315;
            9'd54: quarter_sine_lut = 16'sd5414;
            9'd55: quarter_sine_lut = 16'sd5514;
            9'd56: quarter_sine_lut = 16'sd5613;
            9'd57: quarter_sine_lut = 16'sd5712;
            9'd58: quarter_sine_lut = 16'sd5811;
            9'd59: quarter_sine_lut = 16'sd5910;
            9'd60: quarter_sine_lut = 16'sd6009;
            9'd61: quarter_sine_lut = 16'sd6108;
            9'd62: quarter_sine_lut = 16'sd6207;
            9'd63: quarter_sine_lut = 16'sd6306;
            9'd64: quarter_sine_lut = 16'sd6405;
            9'd65: quarter_sine_lut = 16'sd6504;
            9'd66: quarter_sine_lut = 16'sd6602;
            9'd67: quarter_sine_lut = 16'sd6701;
            9'd68: quarter_sine_lut = 16'sd6800;
            9'd69: quarter_sine_lut = 16'sd6898;
            9'd70: quarter_sine_lut = 16'sd6996;
            9'd71: quarter_sine_lut = 16'sd7095;
            9'd72: quarter_sine_lut = 16'sd7193;
            9'd73: quarter_sine_lut = 16'sd7291;
            9'd74: quarter_sine_lut = 16'sd7390;
            9'd75: quarter_sine_lut = 16'sd7488;
            9'd76: quarter_sine_lut = 16'sd7586;
            9'd77: quarter_sine_lut = 16'sd7684;
            9'd78: quarter_sine_lut = 16'sd7781;
            9'd79: quarter_sine_lut = 16'sd7879;
            9'd80: quarter_sine_lut = 16'sd7977;
            9'd81: quarter_sine_lut = 16'sd8075;
            9'd82: quarter_sine_lut = 16'sd8172;
            9'd83: quarter_sine_lut = 16'sd8270;
            9'd84: quarter_sine_lut = 16'sd8367;
            9'd85: quarter_sine_lut = 16'sd8465;
            9'd86: quarter_sine_lut = 16'sd8562;
            9'd87: quarter_sine_lut = 16'sd8659;
            9'd88: quarter_sine_lut = 16'sd8756;
            9'd89: quarter_sine_lut = 16'sd8853;
            9'd90: quarter_sine_lut = 16'sd8950;
            9'd91: quarter_sine_lut = 16'sd9047;
            9'd92: quarter_sine_lut = 16'sd9144;
            9'd93: quarter_sine_lut = 16'sd9240;
            9'd94: quarter_sine_lut = 16'sd9337;
            9'd95: quarter_sine_lut = 16'sd9433;
            9'd96: quarter_sine_lut = 16'sd9530;
            9'd97: quarter_sine_lut = 16'sd9626;
            9'd98: quarter_sine_lut = 16'sd9722;
            9'd99: quarter_sine_lut = 16'sd9819;
            9'd100: quarter_sine_lut = 16'sd9915;
            9'd101: quarter_sine_lut = 16'sd10011;
            9'd102: quarter_sine_lut = 16'sd10106;
            9'd103: quarter_sine_lut = 16'sd10202;
            9'd104: quarter_sine_lut = 16'sd10298;
            9'd105: quarter_sine_lut = 16'sd10393;
            9'd106: quarter_sine_lut = 16'sd10489;
            9'd107: quarter_sine_lut = 16'sd10584;
            9'd108: quarter_sine_lut = 16'sd10680;
            9'd109: quarter_sine_lut = 16'sd10775;
            9'd110: quarter_sine_lut = 16'sd10870;
            9'd111: quarter_sine_lut = 16'sd10965;
            9'd112: quarter_sine_lut = 16'sd11060;
            9'd113: quarter_sine_lut = 16'sd11154;
            9'd114: quarter_sine_lut = 16'sd11249;
            9'd115: quarter_sine_lut = 16'sd11344;
            9'd116: quarter_sine_lut = 16'sd11438;
            9'd117: quarter_sine_lut = 16'sd11532;
            9'd118: quarter_sine_lut = 16'sd11627;
            9'd119: quarter_sine_lut = 16'sd11721;
            9'd120: quarter_sine_lut = 16'sd11815;
            9'd121: quarter_sine_lut = 16'sd11909;
            9'd122: quarter_sine_lut = 16'sd12002;
            9'd123: quarter_sine_lut = 16'sd12096;
            9'd124: quarter_sine_lut = 16'sd12190;
            9'd125: quarter_sine_lut = 16'sd12283;
            9'd126: quarter_sine_lut = 16'sd12376;
            9'd127: quarter_sine_lut = 16'sd12470;
            9'd128: quarter_sine_lut = 16'sd12563;
            9'd129: quarter_sine_lut = 16'sd12656;
            9'd130: quarter_sine_lut = 16'sd12748;
            9'd131: quarter_sine_lut = 16'sd12841;
            9'd132: quarter_sine_lut = 16'sd12934;
            9'd133: quarter_sine_lut = 16'sd13026;
            9'd134: quarter_sine_lut = 16'sd13119;
            9'd135: quarter_sine_lut = 16'sd13211;
            9'd136: quarter_sine_lut = 16'sd13303;
            9'd137: quarter_sine_lut = 16'sd13395;
            9'd138: quarter_sine_lut = 16'sd13487;
            9'd139: quarter_sine_lut = 16'sd13579;
            9'd140: quarter_sine_lut = 16'sd13670;
            9'd141: quarter_sine_lut = 16'sd13762;
            9'd142: quarter_sine_lut = 16'sd13853;
            9'd143: quarter_sine_lut = 16'sd13944;
            9'd144: quarter_sine_lut = 16'sd14035;
            9'd145: quarter_sine_lut = 16'sd14126;
            9'd146: quarter_sine_lut = 16'sd14217;
            9'd147: quarter_sine_lut = 16'sd14308;
            9'd148: quarter_sine_lut = 16'sd14398;
            9'd149: quarter_sine_lut = 16'sd14489;
            9'd150: quarter_sine_lut = 16'sd14579;
            9'd151: quarter_sine_lut = 16'sd14669;
            9'd152: quarter_sine_lut = 16'sd14759;
            9'd153: quarter_sine_lut = 16'sd14849;
            9'd154: quarter_sine_lut = 16'sd14939;
            9'd155: quarter_sine_lut = 16'sd15028;
            9'd156: quarter_sine_lut = 16'sd15118;
            9'd157: quarter_sine_lut = 16'sd15207;
            9'd158: quarter_sine_lut = 16'sd15296;
            9'd159: quarter_sine_lut = 16'sd15385;
            9'd160: quarter_sine_lut = 16'sd15474;
            9'd161: quarter_sine_lut = 16'sd15563;
            9'd162: quarter_sine_lut = 16'sd15651;
            9'd163: quarter_sine_lut = 16'sd15740;
            9'd164: quarter_sine_lut = 16'sd15828;
            9'd165: quarter_sine_lut = 16'sd15916;
            9'd166: quarter_sine_lut = 16'sd16004;
            9'd167: quarter_sine_lut = 16'sd16092;
            9'd168: quarter_sine_lut = 16'sd16180;
            9'd169: quarter_sine_lut = 16'sd16267;
            9'd170: quarter_sine_lut = 16'sd16354;
            9'd171: quarter_sine_lut = 16'sd16442;
            9'd172: quarter_sine_lut = 16'sd16529;
            9'd173: quarter_sine_lut = 16'sd16616;
            9'd174: quarter_sine_lut = 16'sd16702;
            9'd175: quarter_sine_lut = 16'sd16789;
            9'd176: quarter_sine_lut = 16'sd16875;
            9'd177: quarter_sine_lut = 16'sd16962;
            9'd178: quarter_sine_lut = 16'sd17048;
            9'd179: quarter_sine_lut = 16'sd17134;
            9'd180: quarter_sine_lut = 16'sd17219;
            9'd181: quarter_sine_lut = 16'sd17305;
            9'd182: quarter_sine_lut = 16'sd17390;
            9'd183: quarter_sine_lut = 16'sd17476;
            9'd184: quarter_sine_lut = 16'sd17561;
            9'd185: quarter_sine_lut = 16'sd17646;
            9'd186: quarter_sine_lut = 16'sd17731;
            9'd187: quarter_sine_lut = 16'sd17815;
            9'd188: quarter_sine_lut = 16'sd17900;
            9'd189: quarter_sine_lut = 16'sd17984;
            9'd190: quarter_sine_lut = 16'sd18068;
            9'd191: quarter_sine_lut = 16'sd18152;
            9'd192: quarter_sine_lut = 16'sd18236;
            9'd193: quarter_sine_lut = 16'sd18319;
            9'd194: quarter_sine_lut = 16'sd18403;
            9'd195: quarter_sine_lut = 16'sd18486;
            9'd196: quarter_sine_lut = 16'sd18569;
            9'd197: quarter_sine_lut = 16'sd18652;
            9'd198: quarter_sine_lut = 16'sd18735;
            9'd199: quarter_sine_lut = 16'sd18817;
            9'd200: quarter_sine_lut = 16'sd18900;
            9'd201: quarter_sine_lut = 16'sd18982;
            9'd202: quarter_sine_lut = 16'sd19064;
            9'd203: quarter_sine_lut = 16'sd19146;
            9'd204: quarter_sine_lut = 16'sd19227;
            9'd205: quarter_sine_lut = 16'sd19309;
            9'd206: quarter_sine_lut = 16'sd19390;
            9'd207: quarter_sine_lut = 16'sd19471;
            9'd208: quarter_sine_lut = 16'sd19552;
            9'd209: quarter_sine_lut = 16'sd19633;
            9'd210: quarter_sine_lut = 16'sd19713;
            9'd211: quarter_sine_lut = 16'sd19794;
            9'd212: quarter_sine_lut = 16'sd19874;
            9'd213: quarter_sine_lut = 16'sd19954;
            9'd214: quarter_sine_lut = 16'sd20034;
            9'd215: quarter_sine_lut = 16'sd20113;
            9'd216: quarter_sine_lut = 16'sd20193;
            9'd217: quarter_sine_lut = 16'sd20272;
            9'd218: quarter_sine_lut = 16'sd20351;
            9'd219: quarter_sine_lut = 16'sd20430;
            9'd220: quarter_sine_lut = 16'sd20509;
            9'd221: quarter_sine_lut = 16'sd20587;
            9'd222: quarter_sine_lut = 16'sd20665;
            9'd223: quarter_sine_lut = 16'sd20743;
            9'd224: quarter_sine_lut = 16'sd20821;
            9'd225: quarter_sine_lut = 16'sd20899;
            9'd226: quarter_sine_lut = 16'sd20976;
            9'd227: quarter_sine_lut = 16'sd21054;
            9'd228: quarter_sine_lut = 16'sd21131;
            9'd229: quarter_sine_lut = 16'sd21208;
            9'd230: quarter_sine_lut = 16'sd21284;
            9'd231: quarter_sine_lut = 16'sd21361;
            9'd232: quarter_sine_lut = 16'sd21437;
            9'd233: quarter_sine_lut = 16'sd21513;
            9'd234: quarter_sine_lut = 16'sd21589;
            9'd235: quarter_sine_lut = 16'sd21665;
            9'd236: quarter_sine_lut = 16'sd21740;
            9'd237: quarter_sine_lut = 16'sd21815;
            9'd238: quarter_sine_lut = 16'sd21890;
            9'd239: quarter_sine_lut = 16'sd21965;
            9'd240: quarter_sine_lut = 16'sd22040;
            9'd241: quarter_sine_lut = 16'sd22114;
            9'd242: quarter_sine_lut = 16'sd22189;
            9'd243: quarter_sine_lut = 16'sd22263;
            9'd244: quarter_sine_lut = 16'sd22336;
            9'd245: quarter_sine_lut = 16'sd22410;
            9'd246: quarter_sine_lut = 16'sd22483;
            9'd247: quarter_sine_lut = 16'sd22557;
            9'd248: quarter_sine_lut = 16'sd22629;
            9'd249: quarter_sine_lut = 16'sd22702;
            9'd250: quarter_sine_lut = 16'sd22775;
            9'd251: quarter_sine_lut = 16'sd22847;
            9'd252: quarter_sine_lut = 16'sd22919;
            9'd253: quarter_sine_lut = 16'sd22991;
            9'd254: quarter_sine_lut = 16'sd23063;
            9'd255: quarter_sine_lut = 16'sd23134;
            9'd256: quarter_sine_lut = 16'sd23205;
            9'd257: quarter_sine_lut = 16'sd23276;
            9'd258: quarter_sine_lut = 16'sd23347;
            9'd259: quarter_sine_lut = 16'sd23418;
            9'd260: quarter_sine_lut = 16'sd23488;
            9'd261: quarter_sine_lut = 16'sd23558;
            9'd262: quarter_sine_lut = 16'sd23628;
            9'd263: quarter_sine_lut = 16'sd23698;
            9'd264: quarter_sine_lut = 16'sd23767;
            9'd265: quarter_sine_lut = 16'sd23836;
            9'd266: quarter_sine_lut = 16'sd23905;
            9'd267: quarter_sine_lut = 16'sd23974;
            9'd268: quarter_sine_lut = 16'sd24043;
            9'd269: quarter_sine_lut = 16'sd24111;
            9'd270: quarter_sine_lut = 16'sd24179;
            9'd271: quarter_sine_lut = 16'sd24247;
            9'd272: quarter_sine_lut = 16'sd24315;
            9'd273: quarter_sine_lut = 16'sd24382;
            9'd274: quarter_sine_lut = 16'sd24449;
            9'd275: quarter_sine_lut = 16'sd24516;
            9'd276: quarter_sine_lut = 16'sd24583;
            9'd277: quarter_sine_lut = 16'sd24649;
            9'd278: quarter_sine_lut = 16'sd24716;
            9'd279: quarter_sine_lut = 16'sd24782;
            9'd280: quarter_sine_lut = 16'sd24847;
            9'd281: quarter_sine_lut = 16'sd24913;
            9'd282: quarter_sine_lut = 16'sd24978;
            9'd283: quarter_sine_lut = 16'sd25043;
            9'd284: quarter_sine_lut = 16'sd25108;
            9'd285: quarter_sine_lut = 16'sd25173;
            9'd286: quarter_sine_lut = 16'sd25237;
            9'd287: quarter_sine_lut = 16'sd25301;
            9'd288: quarter_sine_lut = 16'sd25365;
            9'd289: quarter_sine_lut = 16'sd25429;
            9'd290: quarter_sine_lut = 16'sd25492;
            9'd291: quarter_sine_lut = 16'sd25555;
            9'd292: quarter_sine_lut = 16'sd25618;
            9'd293: quarter_sine_lut = 16'sd25681;
            9'd294: quarter_sine_lut = 16'sd25743;
            9'd295: quarter_sine_lut = 16'sd25806;
            9'd296: quarter_sine_lut = 16'sd25868;
            9'd297: quarter_sine_lut = 16'sd25929;
            9'd298: quarter_sine_lut = 16'sd25991;
            9'd299: quarter_sine_lut = 16'sd26052;
            9'd300: quarter_sine_lut = 16'sd26113;
            9'd301: quarter_sine_lut = 16'sd26174;
            9'd302: quarter_sine_lut = 16'sd26234;
            9'd303: quarter_sine_lut = 16'sd26294;
            9'd304: quarter_sine_lut = 16'sd26354;
            9'd305: quarter_sine_lut = 16'sd26414;
            9'd306: quarter_sine_lut = 16'sd26473;
            9'd307: quarter_sine_lut = 16'sd26533;
            9'd308: quarter_sine_lut = 16'sd26592;
            9'd309: quarter_sine_lut = 16'sd26650;
            9'd310: quarter_sine_lut = 16'sd26709;
            9'd311: quarter_sine_lut = 16'sd26767;
            9'd312: quarter_sine_lut = 16'sd26825;
            9'd313: quarter_sine_lut = 16'sd26883;
            9'd314: quarter_sine_lut = 16'sd26940;
            9'd315: quarter_sine_lut = 16'sd26997;
            9'd316: quarter_sine_lut = 16'sd27054;
            9'd317: quarter_sine_lut = 16'sd27111;
            9'd318: quarter_sine_lut = 16'sd27168;
            9'd319: quarter_sine_lut = 16'sd27224;
            9'd320: quarter_sine_lut = 16'sd27280;
            9'd321: quarter_sine_lut = 16'sd27335;
            9'd322: quarter_sine_lut = 16'sd27391;
            9'd323: quarter_sine_lut = 16'sd27446;
            9'd324: quarter_sine_lut = 16'sd27501;
            9'd325: quarter_sine_lut = 16'sd27555;
            9'd326: quarter_sine_lut = 16'sd27610;
            9'd327: quarter_sine_lut = 16'sd27664;
            9'd328: quarter_sine_lut = 16'sd27718;
            9'd329: quarter_sine_lut = 16'sd27771;
            9'd330: quarter_sine_lut = 16'sd27825;
            9'd331: quarter_sine_lut = 16'sd27878;
            9'd332: quarter_sine_lut = 16'sd27931;
            9'd333: quarter_sine_lut = 16'sd27983;
            9'd334: quarter_sine_lut = 16'sd28035;
            9'd335: quarter_sine_lut = 16'sd28087;
            9'd336: quarter_sine_lut = 16'sd28139;
            9'd337: quarter_sine_lut = 16'sd28191;
            9'd338: quarter_sine_lut = 16'sd28242;
            9'd339: quarter_sine_lut = 16'sd28293;
            9'd340: quarter_sine_lut = 16'sd28343;
            9'd341: quarter_sine_lut = 16'sd28394;
            9'd342: quarter_sine_lut = 16'sd28444;
            9'd343: quarter_sine_lut = 16'sd28494;
            9'd344: quarter_sine_lut = 16'sd28543;
            9'd345: quarter_sine_lut = 16'sd28593;
            9'd346: quarter_sine_lut = 16'sd28642;
            9'd347: quarter_sine_lut = 16'sd28691;
            9'd348: quarter_sine_lut = 16'sd28739;
            9'd349: quarter_sine_lut = 16'sd28787;
            9'd350: quarter_sine_lut = 16'sd28835;
            9'd351: quarter_sine_lut = 16'sd28883;
            9'd352: quarter_sine_lut = 16'sd28930;
            9'd353: quarter_sine_lut = 16'sd28978;
            9'd354: quarter_sine_lut = 16'sd29025;
            9'd355: quarter_sine_lut = 16'sd29071;
            9'd356: quarter_sine_lut = 16'sd29117;
            9'd357: quarter_sine_lut = 16'sd29164;
            9'd358: quarter_sine_lut = 16'sd29209;
            9'd359: quarter_sine_lut = 16'sd29255;
            9'd360: quarter_sine_lut = 16'sd29300;
            9'd361: quarter_sine_lut = 16'sd29345;
            9'd362: quarter_sine_lut = 16'sd29390;
            9'd363: quarter_sine_lut = 16'sd29434;
            9'd364: quarter_sine_lut = 16'sd29478;
            9'd365: quarter_sine_lut = 16'sd29522;
            9'd366: quarter_sine_lut = 16'sd29566;
            9'd367: quarter_sine_lut = 16'sd29609;
            9'd368: quarter_sine_lut = 16'sd29652;
            9'd369: quarter_sine_lut = 16'sd29695;
            9'd370: quarter_sine_lut = 16'sd29737;
            9'd371: quarter_sine_lut = 16'sd29779;
            9'd372: quarter_sine_lut = 16'sd29821;
            9'd373: quarter_sine_lut = 16'sd29863;
            9'd374: quarter_sine_lut = 16'sd29904;
            9'd375: quarter_sine_lut = 16'sd29945;
            9'd376: quarter_sine_lut = 16'sd29986;
            9'd377: quarter_sine_lut = 16'sd30026;
            9'd378: quarter_sine_lut = 16'sd30066;
            9'd379: quarter_sine_lut = 16'sd30106;
            9'd380: quarter_sine_lut = 16'sd30146;
            9'd381: quarter_sine_lut = 16'sd30185;
            9'd382: quarter_sine_lut = 16'sd30224;
            9'd383: quarter_sine_lut = 16'sd30263;
            9'd384: quarter_sine_lut = 16'sd30302;
            9'd385: quarter_sine_lut = 16'sd30340;
            9'd386: quarter_sine_lut = 16'sd30378;
            9'd387: quarter_sine_lut = 16'sd30415;
            9'd388: quarter_sine_lut = 16'sd30453;
            9'd389: quarter_sine_lut = 16'sd30490;
            9'd390: quarter_sine_lut = 16'sd30526;
            9'd391: quarter_sine_lut = 16'sd30563;
            9'd392: quarter_sine_lut = 16'sd30599;
            9'd393: quarter_sine_lut = 16'sd30635;
            9'd394: quarter_sine_lut = 16'sd30671;
            9'd395: quarter_sine_lut = 16'sd30706;
            9'd396: quarter_sine_lut = 16'sd30741;
            9'd397: quarter_sine_lut = 16'sd30776;
            9'd398: quarter_sine_lut = 16'sd30810;
            9'd399: quarter_sine_lut = 16'sd30844;
            9'd400: quarter_sine_lut = 16'sd30878;
            9'd401: quarter_sine_lut = 16'sd30912;
            9'd402: quarter_sine_lut = 16'sd30945;
            9'd403: quarter_sine_lut = 16'sd30978;
            9'd404: quarter_sine_lut = 16'sd31010;
            9'd405: quarter_sine_lut = 16'sd31043;
            9'd406: quarter_sine_lut = 16'sd31075;
            9'd407: quarter_sine_lut = 16'sd31107;
            9'd408: quarter_sine_lut = 16'sd31138;
            9'd409: quarter_sine_lut = 16'sd31169;
            9'd410: quarter_sine_lut = 16'sd31200;
            9'd411: quarter_sine_lut = 16'sd31231;
            9'd412: quarter_sine_lut = 16'sd31261;
            9'd413: quarter_sine_lut = 16'sd31291;
            9'd414: quarter_sine_lut = 16'sd31321;
            9'd415: quarter_sine_lut = 16'sd31351;
            9'd416: quarter_sine_lut = 16'sd31380;
            9'd417: quarter_sine_lut = 16'sd31409;
            9'd418: quarter_sine_lut = 16'sd31437;
            9'd419: quarter_sine_lut = 16'sd31465;
            9'd420: quarter_sine_lut = 16'sd31493;
            9'd421: quarter_sine_lut = 16'sd31521;
            9'd422: quarter_sine_lut = 16'sd31548;
            9'd423: quarter_sine_lut = 16'sd31575;
            9'd424: quarter_sine_lut = 16'sd31602;
            9'd425: quarter_sine_lut = 16'sd31629;
            9'd426: quarter_sine_lut = 16'sd31655;
            9'd427: quarter_sine_lut = 16'sd31681;
            9'd428: quarter_sine_lut = 16'sd31706;
            9'd429: quarter_sine_lut = 16'sd31732;
            9'd430: quarter_sine_lut = 16'sd31757;
            9'd431: quarter_sine_lut = 16'sd31781;
            9'd432: quarter_sine_lut = 16'sd31806;
            9'd433: quarter_sine_lut = 16'sd31830;
            9'd434: quarter_sine_lut = 16'sd31853;
            9'd435: quarter_sine_lut = 16'sd31877;
            9'd436: quarter_sine_lut = 16'sd31900;
            9'd437: quarter_sine_lut = 16'sd31923;
            9'd438: quarter_sine_lut = 16'sd31945;
            9'd439: quarter_sine_lut = 16'sd31968;
            9'd440: quarter_sine_lut = 16'sd31990;
            9'd441: quarter_sine_lut = 16'sd32011;
            9'd442: quarter_sine_lut = 16'sd32033;
            9'd443: quarter_sine_lut = 16'sd32054;
            9'd444: quarter_sine_lut = 16'sd32075;
            9'd445: quarter_sine_lut = 16'sd32095;
            9'd446: quarter_sine_lut = 16'sd32115;
            9'd447: quarter_sine_lut = 16'sd32135;
            9'd448: quarter_sine_lut = 16'sd32154;
            9'd449: quarter_sine_lut = 16'sd32174;
            9'd450: quarter_sine_lut = 16'sd32193;
            9'd451: quarter_sine_lut = 16'sd32211;
            9'd452: quarter_sine_lut = 16'sd32230;
            9'd453: quarter_sine_lut = 16'sd32248;
            9'd454: quarter_sine_lut = 16'sd32265;
            9'd455: quarter_sine_lut = 16'sd32283;
            9'd456: quarter_sine_lut = 16'sd32300;
            9'd457: quarter_sine_lut = 16'sd32317;
            9'd458: quarter_sine_lut = 16'sd32333;
            9'd459: quarter_sine_lut = 16'sd32349;
            9'd460: quarter_sine_lut = 16'sd32365;
            9'd461: quarter_sine_lut = 16'sd32381;
            9'd462: quarter_sine_lut = 16'sd32396;
            9'd463: quarter_sine_lut = 16'sd32411;
            9'd464: quarter_sine_lut = 16'sd32426;
            9'd465: quarter_sine_lut = 16'sd32440;
            9'd466: quarter_sine_lut = 16'sd32454;
            9'd467: quarter_sine_lut = 16'sd32468;
            9'd468: quarter_sine_lut = 16'sd32481;
            9'd469: quarter_sine_lut = 16'sd32494;
            9'd470: quarter_sine_lut = 16'sd32507;
            9'd471: quarter_sine_lut = 16'sd32520;
            9'd472: quarter_sine_lut = 16'sd32532;
            9'd473: quarter_sine_lut = 16'sd32544;
            9'd474: quarter_sine_lut = 16'sd32555;
            9'd475: quarter_sine_lut = 16'sd32567;
            9'd476: quarter_sine_lut = 16'sd32578;
            9'd477: quarter_sine_lut = 16'sd32588;
            9'd478: quarter_sine_lut = 16'sd32599;
            9'd479: quarter_sine_lut = 16'sd32609;
            9'd480: quarter_sine_lut = 16'sd32618;
            9'd481: quarter_sine_lut = 16'sd32628;
            9'd482: quarter_sine_lut = 16'sd32637;
            9'd483: quarter_sine_lut = 16'sd32646;
            9'd484: quarter_sine_lut = 16'sd32654;
            9'd485: quarter_sine_lut = 16'sd32662;
            9'd486: quarter_sine_lut = 16'sd32670;
            9'd487: quarter_sine_lut = 16'sd32678;
            9'd488: quarter_sine_lut = 16'sd32685;
            9'd489: quarter_sine_lut = 16'sd32692;
            9'd490: quarter_sine_lut = 16'sd32699;
            9'd491: quarter_sine_lut = 16'sd32705;
            9'd492: quarter_sine_lut = 16'sd32711;
            9'd493: quarter_sine_lut = 16'sd32717;
            9'd494: quarter_sine_lut = 16'sd32722;
            9'd495: quarter_sine_lut = 16'sd32727;
            9'd496: quarter_sine_lut = 16'sd32732;
            9'd497: quarter_sine_lut = 16'sd32737;
            9'd498: quarter_sine_lut = 16'sd32741;
            9'd499: quarter_sine_lut = 16'sd32745;
            9'd500: quarter_sine_lut = 16'sd32748;
            9'd501: quarter_sine_lut = 16'sd32752;
            9'd502: quarter_sine_lut = 16'sd32754;
            9'd503: quarter_sine_lut = 16'sd32757;
            9'd504: quarter_sine_lut = 16'sd32759;
            9'd505: quarter_sine_lut = 16'sd32761;
            9'd506: quarter_sine_lut = 16'sd32763;
            9'd507: quarter_sine_lut = 16'sd32765;
            9'd508: quarter_sine_lut = 16'sd32766;
            9'd509: quarter_sine_lut = 16'sd32766;
            9'd510: quarter_sine_lut = 16'sd32767;
            9'd511: quarter_sine_lut = 16'sd32767;
            default: quarter_sine_lut = 16'sd32767;
            endcase
        end
    endfunction

    function automatic signed [15:0] sine_raw(input [31:0] phase_value);
        reg [1:0] quadrant;
        reg [8:0] idx;
        reg signed [15:0] mag;
        begin
            quadrant = phase_value[31:30];
            idx = phase_value[29:21];
            case (quadrant)
                2'd0: mag = quarter_sine_lut(idx);
                2'd1: mag = quarter_sine_lut(~idx);
                2'd2: mag = -quarter_sine_lut(idx);
                default: mag = -quarter_sine_lut(~idx);
            endcase
            sine_raw = mag;
        end
    endfunction

    function automatic signed [15:0] sine_sample(
        input [31:0] phase,
        input [15:0] amplitude
    );
        reg signed [32:0] scaled;
        begin
            scaled = sine_raw(phase) * $signed({1'b0, amplitude});
            sine_sample = scaled >>> 15;
        end
    endfunction

    function automatic [15:0] channel_amp(input integer idx);
        begin
            channel_amp = tone_amplitude_vec[idx*16 +: 16];
        end
    endfunction

    function automatic [31:0] channel_phase_step(input integer idx);
        begin
            channel_phase_step = tone_phase_step_vec[idx*32 +: 32];
        end
    endfunction

    function automatic [31:0] channel_phase0(input integer idx);
        begin
            channel_phase0 = tone_phase0_vec[idx*32 +: 32];
        end
    endfunction

    function automatic [31:0] channel_phase_inject(input integer idx);
        begin
            channel_phase_inject = tone_phase_inject_vec[idx*32 +: 32];
        end
    endfunction

    function automatic [1:0] channel_mode(input integer idx);
        begin
            channel_mode = tone_mode_vec[idx*2 +: 2];
        end
    endfunction

    function automatic [127:0] channel_word_from(
        input [31:0] phase_acc,
        input [31:0] phase_step,
        input [31:0] phase0,
        input [31:0] phase_inject,
        input [15:0] amplitude,
        input [1:0] mode
    );
        reg [31:0] base_phase;
        reg [31:0] step;
        reg [15:0] amp;
        reg signed [15:0] i0;
        reg signed [15:0] q0;
        reg signed [15:0] i1;
        reg signed [15:0] q1;
        reg signed [15:0] i2;
        reg signed [15:0] q2;
        reg signed [15:0] i3;
        reg signed [15:0] q3;
        begin
            step = phase_step;
            amp = amplitude;
            base_phase = phase_acc + phase0 + phase_inject;
            if (mode == 2'd1) begin
                i0 = sine_sample(base_phase, amp);
                q0 = sine_sample(base_phase + 32'h4000_0000, amp);
                i1 = i0;
                q1 = q0;
                i2 = i0;
                q2 = q0;
                i3 = i0;
                q3 = q0;
            end else if (mode != 2'd0) begin
                i0 = 16'sd0;
                q0 = 16'sd0;
                i1 = 16'sd0;
                q1 = 16'sd0;
                i2 = 16'sd0;
                q2 = 16'sd0;
                i3 = 16'sd0;
                q3 = 16'sd0;
            end else begin
                i0 = sine_sample(base_phase, amp);
                q0 = sine_sample(base_phase + 32'h4000_0000, amp);
                i1 = sine_sample(base_phase + step, amp);
                q1 = sine_sample(base_phase + step + 32'h4000_0000, amp);
                i2 = sine_sample(base_phase + (step << 1), amp);
                q2 = sine_sample(base_phase + (step << 1) + 32'h4000_0000, amp);
                i3 = sine_sample(base_phase + (step << 1) + step, amp);
                q3 = sine_sample(base_phase + (step << 1) + step + 32'h4000_0000, amp);
            end
            channel_word_from = {q3, i3, q2, i2, q1, i1, q0, i0};
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase_epoch_seen <= 32'd0;
            for (ch = 0; ch < 8; ch = ch + 1) begin
                phase[ch] <= 32'd0;
            end
        end else if (tone_phase_epoch != phase_epoch_seen) begin
            phase_epoch_seen <= tone_phase_epoch;
            for (ch = 0; ch < 8; ch = ch + 1) begin
                phase[ch] <= 32'd0;
            end
        end else begin
            for (ch = 0; ch < 8; ch = ch + 1) begin
                phase[ch] <= phase[ch] + (channel_phase_step(ch) << 2);
            end
        end
    end

    assign s00_axis_tdata = tone_enable_mask[0] ? channel_word_from(
        phase[0], tone_phase_step_vec[0*32 +: 32], tone_phase0_vec[0*32 +: 32],
        tone_phase_inject_vec[0*32 +: 32], tone_amplitude_vec[0*16 +: 16], tone_mode_vec[0*2 +: 2]) : 128'd0;
    assign s02_axis_tdata = tone_enable_mask[1] ? channel_word_from(
        phase[1], tone_phase_step_vec[1*32 +: 32], tone_phase0_vec[1*32 +: 32],
        tone_phase_inject_vec[1*32 +: 32], tone_amplitude_vec[1*16 +: 16], tone_mode_vec[1*2 +: 2]) : 128'd0;
    assign s10_axis_tdata = tone_enable_mask[2] ? channel_word_from(
        phase[2], tone_phase_step_vec[2*32 +: 32], tone_phase0_vec[2*32 +: 32],
        tone_phase_inject_vec[2*32 +: 32], tone_amplitude_vec[2*16 +: 16], tone_mode_vec[2*2 +: 2]) : 128'd0;
    assign s12_axis_tdata = tone_enable_mask[3] ? channel_word_from(
        phase[3], tone_phase_step_vec[3*32 +: 32], tone_phase0_vec[3*32 +: 32],
        tone_phase_inject_vec[3*32 +: 32], tone_amplitude_vec[3*16 +: 16], tone_mode_vec[3*2 +: 2]) : 128'd0;
    assign s20_axis_tdata = tone_enable_mask[4] ? channel_word_from(
        phase[4], tone_phase_step_vec[4*32 +: 32], tone_phase0_vec[4*32 +: 32],
        tone_phase_inject_vec[4*32 +: 32], tone_amplitude_vec[4*16 +: 16], tone_mode_vec[4*2 +: 2]) : 128'd0;
    assign s22_axis_tdata = tone_enable_mask[5] ? channel_word_from(
        phase[5], tone_phase_step_vec[5*32 +: 32], tone_phase0_vec[5*32 +: 32],
        tone_phase_inject_vec[5*32 +: 32], tone_amplitude_vec[5*16 +: 16], tone_mode_vec[5*2 +: 2]) : 128'd0;
    assign s30_axis_tdata = tone_enable_mask[6] ? channel_word_from(
        phase[6], tone_phase_step_vec[6*32 +: 32], tone_phase0_vec[6*32 +: 32],
        tone_phase_inject_vec[6*32 +: 32], tone_amplitude_vec[6*16 +: 16], tone_mode_vec[6*2 +: 2]) : 128'd0;
    assign s32_axis_tdata = tone_enable_mask[7] ? channel_word_from(
        phase[7], tone_phase_step_vec[7*32 +: 32], tone_phase0_vec[7*32 +: 32],
        tone_phase_inject_vec[7*32 +: 32], tone_amplitude_vec[7*16 +: 16], tone_mode_vec[7*2 +: 2]) : 128'd0;
    assign s00_axis_tvalid = 1'b1;
    assign s02_axis_tvalid = 1'b1;
    assign s10_axis_tvalid = 1'b1;
    assign s12_axis_tvalid = 1'b1;
    assign s20_axis_tvalid = 1'b1;
    assign s22_axis_tvalid = 1'b1;
    assign s30_axis_tvalid = 1'b1;
    assign s32_axis_tvalid = 1'b1;
    assign all_dac_ready =
        s00_axis_tready && s02_axis_tready && s10_axis_tready && s12_axis_tready &&
        s20_axis_tready && s22_axis_tready && s30_axis_tready && s32_axis_tready;
    assign audit_phase_epoch_seen = phase_epoch_seen;
    assign audit_ch0_phase_acc = phase[0];
    assign audit_ch0_phase_step = tone_phase_step_vec[31:0];
    assign audit_ch0_phase0 = tone_phase0_vec[31:0];
    assign audit_ch0_mode = {30'd0, tone_mode_vec[1:0]};

endmodule
