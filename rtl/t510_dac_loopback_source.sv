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
    output wire         all_dac_ready
);

    logic [31:0] phase [0:7];
    logic [31:0] phase_epoch_seen;
    integer ch;

    // 512 uniformly spaced samples over [0, pi/2); the exact pi/2 endpoint
    // is represented explicitly by sine_raw at the quadrant boundary.
    function automatic signed [15:0] quarter_sine_lut(input [8:0] idx);
        begin
            case (idx)
            9'd0: quarter_sine_lut = 16'sd0;
            9'd1: quarter_sine_lut = 16'sd101;
            9'd2: quarter_sine_lut = 16'sd201;
            9'd3: quarter_sine_lut = 16'sd302;
            9'd4: quarter_sine_lut = 16'sd402;
            9'd5: quarter_sine_lut = 16'sd503;
            9'd6: quarter_sine_lut = 16'sd603;
            9'd7: quarter_sine_lut = 16'sd704;
            9'd8: quarter_sine_lut = 16'sd804;
            9'd9: quarter_sine_lut = 16'sd905;
            9'd10: quarter_sine_lut = 16'sd1005;
            9'd11: quarter_sine_lut = 16'sd1106;
            9'd12: quarter_sine_lut = 16'sd1206;
            9'd13: quarter_sine_lut = 16'sd1307;
            9'd14: quarter_sine_lut = 16'sd1407;
            9'd15: quarter_sine_lut = 16'sd1507;
            9'd16: quarter_sine_lut = 16'sd1608;
            9'd17: quarter_sine_lut = 16'sd1708;
            9'd18: quarter_sine_lut = 16'sd1809;
            9'd19: quarter_sine_lut = 16'sd1909;
            9'd20: quarter_sine_lut = 16'sd2009;
            9'd21: quarter_sine_lut = 16'sd2110;
            9'd22: quarter_sine_lut = 16'sd2210;
            9'd23: quarter_sine_lut = 16'sd2310;
            9'd24: quarter_sine_lut = 16'sd2410;
            9'd25: quarter_sine_lut = 16'sd2511;
            9'd26: quarter_sine_lut = 16'sd2611;
            9'd27: quarter_sine_lut = 16'sd2711;
            9'd28: quarter_sine_lut = 16'sd2811;
            9'd29: quarter_sine_lut = 16'sd2911;
            9'd30: quarter_sine_lut = 16'sd3012;
            9'd31: quarter_sine_lut = 16'sd3112;
            9'd32: quarter_sine_lut = 16'sd3212;
            9'd33: quarter_sine_lut = 16'sd3312;
            9'd34: quarter_sine_lut = 16'sd3412;
            9'd35: quarter_sine_lut = 16'sd3512;
            9'd36: quarter_sine_lut = 16'sd3612;
            9'd37: quarter_sine_lut = 16'sd3712;
            9'd38: quarter_sine_lut = 16'sd3811;
            9'd39: quarter_sine_lut = 16'sd3911;
            9'd40: quarter_sine_lut = 16'sd4011;
            9'd41: quarter_sine_lut = 16'sd4111;
            9'd42: quarter_sine_lut = 16'sd4210;
            9'd43: quarter_sine_lut = 16'sd4310;
            9'd44: quarter_sine_lut = 16'sd4410;
            9'd45: quarter_sine_lut = 16'sd4509;
            9'd46: quarter_sine_lut = 16'sd4609;
            9'd47: quarter_sine_lut = 16'sd4708;
            9'd48: quarter_sine_lut = 16'sd4808;
            9'd49: quarter_sine_lut = 16'sd4907;
            9'd50: quarter_sine_lut = 16'sd5007;
            9'd51: quarter_sine_lut = 16'sd5106;
            9'd52: quarter_sine_lut = 16'sd5205;
            9'd53: quarter_sine_lut = 16'sd5305;
            9'd54: quarter_sine_lut = 16'sd5404;
            9'd55: quarter_sine_lut = 16'sd5503;
            9'd56: quarter_sine_lut = 16'sd5602;
            9'd57: quarter_sine_lut = 16'sd5701;
            9'd58: quarter_sine_lut = 16'sd5800;
            9'd59: quarter_sine_lut = 16'sd5899;
            9'd60: quarter_sine_lut = 16'sd5998;
            9'd61: quarter_sine_lut = 16'sd6096;
            9'd62: quarter_sine_lut = 16'sd6195;
            9'd63: quarter_sine_lut = 16'sd6294;
            9'd64: quarter_sine_lut = 16'sd6393;
            9'd65: quarter_sine_lut = 16'sd6491;
            9'd66: quarter_sine_lut = 16'sd6590;
            9'd67: quarter_sine_lut = 16'sd6688;
            9'd68: quarter_sine_lut = 16'sd6786;
            9'd69: quarter_sine_lut = 16'sd6885;
            9'd70: quarter_sine_lut = 16'sd6983;
            9'd71: quarter_sine_lut = 16'sd7081;
            9'd72: quarter_sine_lut = 16'sd7179;
            9'd73: quarter_sine_lut = 16'sd7277;
            9'd74: quarter_sine_lut = 16'sd7375;
            9'd75: quarter_sine_lut = 16'sd7473;
            9'd76: quarter_sine_lut = 16'sd7571;
            9'd77: quarter_sine_lut = 16'sd7669;
            9'd78: quarter_sine_lut = 16'sd7767;
            9'd79: quarter_sine_lut = 16'sd7864;
            9'd80: quarter_sine_lut = 16'sd7962;
            9'd81: quarter_sine_lut = 16'sd8059;
            9'd82: quarter_sine_lut = 16'sd8157;
            9'd83: quarter_sine_lut = 16'sd8254;
            9'd84: quarter_sine_lut = 16'sd8351;
            9'd85: quarter_sine_lut = 16'sd8448;
            9'd86: quarter_sine_lut = 16'sd8545;
            9'd87: quarter_sine_lut = 16'sd8642;
            9'd88: quarter_sine_lut = 16'sd8739;
            9'd89: quarter_sine_lut = 16'sd8836;
            9'd90: quarter_sine_lut = 16'sd8933;
            9'd91: quarter_sine_lut = 16'sd9030;
            9'd92: quarter_sine_lut = 16'sd9126;
            9'd93: quarter_sine_lut = 16'sd9223;
            9'd94: quarter_sine_lut = 16'sd9319;
            9'd95: quarter_sine_lut = 16'sd9416;
            9'd96: quarter_sine_lut = 16'sd9512;
            9'd97: quarter_sine_lut = 16'sd9608;
            9'd98: quarter_sine_lut = 16'sd9704;
            9'd99: quarter_sine_lut = 16'sd9800;
            9'd100: quarter_sine_lut = 16'sd9896;
            9'd101: quarter_sine_lut = 16'sd9992;
            9'd102: quarter_sine_lut = 16'sd10087;
            9'd103: quarter_sine_lut = 16'sd10183;
            9'd104: quarter_sine_lut = 16'sd10278;
            9'd105: quarter_sine_lut = 16'sd10374;
            9'd106: quarter_sine_lut = 16'sd10469;
            9'd107: quarter_sine_lut = 16'sd10564;
            9'd108: quarter_sine_lut = 16'sd10659;
            9'd109: quarter_sine_lut = 16'sd10754;
            9'd110: quarter_sine_lut = 16'sd10849;
            9'd111: quarter_sine_lut = 16'sd10944;
            9'd112: quarter_sine_lut = 16'sd11039;
            9'd113: quarter_sine_lut = 16'sd11133;
            9'd114: quarter_sine_lut = 16'sd11228;
            9'd115: quarter_sine_lut = 16'sd11322;
            9'd116: quarter_sine_lut = 16'sd11417;
            9'd117: quarter_sine_lut = 16'sd11511;
            9'd118: quarter_sine_lut = 16'sd11605;
            9'd119: quarter_sine_lut = 16'sd11699;
            9'd120: quarter_sine_lut = 16'sd11793;
            9'd121: quarter_sine_lut = 16'sd11886;
            9'd122: quarter_sine_lut = 16'sd11980;
            9'd123: quarter_sine_lut = 16'sd12074;
            9'd124: quarter_sine_lut = 16'sd12167;
            9'd125: quarter_sine_lut = 16'sd12260;
            9'd126: quarter_sine_lut = 16'sd12353;
            9'd127: quarter_sine_lut = 16'sd12446;
            9'd128: quarter_sine_lut = 16'sd12539;
            9'd129: quarter_sine_lut = 16'sd12632;
            9'd130: quarter_sine_lut = 16'sd12725;
            9'd131: quarter_sine_lut = 16'sd12817;
            9'd132: quarter_sine_lut = 16'sd12910;
            9'd133: quarter_sine_lut = 16'sd13002;
            9'd134: quarter_sine_lut = 16'sd13094;
            9'd135: quarter_sine_lut = 16'sd13187;
            9'd136: quarter_sine_lut = 16'sd13279;
            9'd137: quarter_sine_lut = 16'sd13370;
            9'd138: quarter_sine_lut = 16'sd13462;
            9'd139: quarter_sine_lut = 16'sd13554;
            9'd140: quarter_sine_lut = 16'sd13645;
            9'd141: quarter_sine_lut = 16'sd13736;
            9'd142: quarter_sine_lut = 16'sd13828;
            9'd143: quarter_sine_lut = 16'sd13919;
            9'd144: quarter_sine_lut = 16'sd14010;
            9'd145: quarter_sine_lut = 16'sd14101;
            9'd146: quarter_sine_lut = 16'sd14191;
            9'd147: quarter_sine_lut = 16'sd14282;
            9'd148: quarter_sine_lut = 16'sd14372;
            9'd149: quarter_sine_lut = 16'sd14462;
            9'd150: quarter_sine_lut = 16'sd14553;
            9'd151: quarter_sine_lut = 16'sd14643;
            9'd152: quarter_sine_lut = 16'sd14732;
            9'd153: quarter_sine_lut = 16'sd14822;
            9'd154: quarter_sine_lut = 16'sd14912;
            9'd155: quarter_sine_lut = 16'sd15001;
            9'd156: quarter_sine_lut = 16'sd15090;
            9'd157: quarter_sine_lut = 16'sd15180;
            9'd158: quarter_sine_lut = 16'sd15269;
            9'd159: quarter_sine_lut = 16'sd15358;
            9'd160: quarter_sine_lut = 16'sd15446;
            9'd161: quarter_sine_lut = 16'sd15535;
            9'd162: quarter_sine_lut = 16'sd15623;
            9'd163: quarter_sine_lut = 16'sd15712;
            9'd164: quarter_sine_lut = 16'sd15800;
            9'd165: quarter_sine_lut = 16'sd15888;
            9'd166: quarter_sine_lut = 16'sd15976;
            9'd167: quarter_sine_lut = 16'sd16063;
            9'd168: quarter_sine_lut = 16'sd16151;
            9'd169: quarter_sine_lut = 16'sd16238;
            9'd170: quarter_sine_lut = 16'sd16325;
            9'd171: quarter_sine_lut = 16'sd16413;
            9'd172: quarter_sine_lut = 16'sd16499;
            9'd173: quarter_sine_lut = 16'sd16586;
            9'd174: quarter_sine_lut = 16'sd16673;
            9'd175: quarter_sine_lut = 16'sd16759;
            9'd176: quarter_sine_lut = 16'sd16846;
            9'd177: quarter_sine_lut = 16'sd16932;
            9'd178: quarter_sine_lut = 16'sd17018;
            9'd179: quarter_sine_lut = 16'sd17104;
            9'd180: quarter_sine_lut = 16'sd17189;
            9'd181: quarter_sine_lut = 16'sd17275;
            9'd182: quarter_sine_lut = 16'sd17360;
            9'd183: quarter_sine_lut = 16'sd17445;
            9'd184: quarter_sine_lut = 16'sd17530;
            9'd185: quarter_sine_lut = 16'sd17615;
            9'd186: quarter_sine_lut = 16'sd17700;
            9'd187: quarter_sine_lut = 16'sd17784;
            9'd188: quarter_sine_lut = 16'sd17869;
            9'd189: quarter_sine_lut = 16'sd17953;
            9'd190: quarter_sine_lut = 16'sd18037;
            9'd191: quarter_sine_lut = 16'sd18121;
            9'd192: quarter_sine_lut = 16'sd18204;
            9'd193: quarter_sine_lut = 16'sd18288;
            9'd194: quarter_sine_lut = 16'sd18371;
            9'd195: quarter_sine_lut = 16'sd18454;
            9'd196: quarter_sine_lut = 16'sd18537;
            9'd197: quarter_sine_lut = 16'sd18620;
            9'd198: quarter_sine_lut = 16'sd18703;
            9'd199: quarter_sine_lut = 16'sd18785;
            9'd200: quarter_sine_lut = 16'sd18868;
            9'd201: quarter_sine_lut = 16'sd18950;
            9'd202: quarter_sine_lut = 16'sd19032;
            9'd203: quarter_sine_lut = 16'sd19113;
            9'd204: quarter_sine_lut = 16'sd19195;
            9'd205: quarter_sine_lut = 16'sd19276;
            9'd206: quarter_sine_lut = 16'sd19357;
            9'd207: quarter_sine_lut = 16'sd19438;
            9'd208: quarter_sine_lut = 16'sd19519;
            9'd209: quarter_sine_lut = 16'sd19600;
            9'd210: quarter_sine_lut = 16'sd19680;
            9'd211: quarter_sine_lut = 16'sd19761;
            9'd212: quarter_sine_lut = 16'sd19841;
            9'd213: quarter_sine_lut = 16'sd19921;
            9'd214: quarter_sine_lut = 16'sd20000;
            9'd215: quarter_sine_lut = 16'sd20080;
            9'd216: quarter_sine_lut = 16'sd20159;
            9'd217: quarter_sine_lut = 16'sd20238;
            9'd218: quarter_sine_lut = 16'sd20317;
            9'd219: quarter_sine_lut = 16'sd20396;
            9'd220: quarter_sine_lut = 16'sd20475;
            9'd221: quarter_sine_lut = 16'sd20553;
            9'd222: quarter_sine_lut = 16'sd20631;
            9'd223: quarter_sine_lut = 16'sd20709;
            9'd224: quarter_sine_lut = 16'sd20787;
            9'd225: quarter_sine_lut = 16'sd20865;
            9'd226: quarter_sine_lut = 16'sd20942;
            9'd227: quarter_sine_lut = 16'sd21019;
            9'd228: quarter_sine_lut = 16'sd21096;
            9'd229: quarter_sine_lut = 16'sd21173;
            9'd230: quarter_sine_lut = 16'sd21250;
            9'd231: quarter_sine_lut = 16'sd21326;
            9'd232: quarter_sine_lut = 16'sd21403;
            9'd233: quarter_sine_lut = 16'sd21479;
            9'd234: quarter_sine_lut = 16'sd21554;
            9'd235: quarter_sine_lut = 16'sd21630;
            9'd236: quarter_sine_lut = 16'sd21705;
            9'd237: quarter_sine_lut = 16'sd21781;
            9'd238: quarter_sine_lut = 16'sd21856;
            9'd239: quarter_sine_lut = 16'sd21930;
            9'd240: quarter_sine_lut = 16'sd22005;
            9'd241: quarter_sine_lut = 16'sd22079;
            9'd242: quarter_sine_lut = 16'sd22154;
            9'd243: quarter_sine_lut = 16'sd22227;
            9'd244: quarter_sine_lut = 16'sd22301;
            9'd245: quarter_sine_lut = 16'sd22375;
            9'd246: quarter_sine_lut = 16'sd22448;
            9'd247: quarter_sine_lut = 16'sd22521;
            9'd248: quarter_sine_lut = 16'sd22594;
            9'd249: quarter_sine_lut = 16'sd22667;
            9'd250: quarter_sine_lut = 16'sd22739;
            9'd251: quarter_sine_lut = 16'sd22812;
            9'd252: quarter_sine_lut = 16'sd22884;
            9'd253: quarter_sine_lut = 16'sd22956;
            9'd254: quarter_sine_lut = 16'sd23027;
            9'd255: quarter_sine_lut = 16'sd23099;
            9'd256: quarter_sine_lut = 16'sd23170;
            9'd257: quarter_sine_lut = 16'sd23241;
            9'd258: quarter_sine_lut = 16'sd23311;
            9'd259: quarter_sine_lut = 16'sd23382;
            9'd260: quarter_sine_lut = 16'sd23452;
            9'd261: quarter_sine_lut = 16'sd23522;
            9'd262: quarter_sine_lut = 16'sd23592;
            9'd263: quarter_sine_lut = 16'sd23662;
            9'd264: quarter_sine_lut = 16'sd23731;
            9'd265: quarter_sine_lut = 16'sd23801;
            9'd266: quarter_sine_lut = 16'sd23870;
            9'd267: quarter_sine_lut = 16'sd23938;
            9'd268: quarter_sine_lut = 16'sd24007;
            9'd269: quarter_sine_lut = 16'sd24075;
            9'd270: quarter_sine_lut = 16'sd24143;
            9'd271: quarter_sine_lut = 16'sd24211;
            9'd272: quarter_sine_lut = 16'sd24279;
            9'd273: quarter_sine_lut = 16'sd24346;
            9'd274: quarter_sine_lut = 16'sd24413;
            9'd275: quarter_sine_lut = 16'sd24480;
            9'd276: quarter_sine_lut = 16'sd24547;
            9'd277: quarter_sine_lut = 16'sd24613;
            9'd278: quarter_sine_lut = 16'sd24680;
            9'd279: quarter_sine_lut = 16'sd24746;
            9'd280: quarter_sine_lut = 16'sd24811;
            9'd281: quarter_sine_lut = 16'sd24877;
            9'd282: quarter_sine_lut = 16'sd24942;
            9'd283: quarter_sine_lut = 16'sd25007;
            9'd284: quarter_sine_lut = 16'sd25072;
            9'd285: quarter_sine_lut = 16'sd25137;
            9'd286: quarter_sine_lut = 16'sd25201;
            9'd287: quarter_sine_lut = 16'sd25265;
            9'd288: quarter_sine_lut = 16'sd25329;
            9'd289: quarter_sine_lut = 16'sd25393;
            9'd290: quarter_sine_lut = 16'sd25456;
            9'd291: quarter_sine_lut = 16'sd25519;
            9'd292: quarter_sine_lut = 16'sd25582;
            9'd293: quarter_sine_lut = 16'sd25645;
            9'd294: quarter_sine_lut = 16'sd25708;
            9'd295: quarter_sine_lut = 16'sd25770;
            9'd296: quarter_sine_lut = 16'sd25832;
            9'd297: quarter_sine_lut = 16'sd25893;
            9'd298: quarter_sine_lut = 16'sd25955;
            9'd299: quarter_sine_lut = 16'sd26016;
            9'd300: quarter_sine_lut = 16'sd26077;
            9'd301: quarter_sine_lut = 16'sd26138;
            9'd302: quarter_sine_lut = 16'sd26198;
            9'd303: quarter_sine_lut = 16'sd26259;
            9'd304: quarter_sine_lut = 16'sd26319;
            9'd305: quarter_sine_lut = 16'sd26378;
            9'd306: quarter_sine_lut = 16'sd26438;
            9'd307: quarter_sine_lut = 16'sd26497;
            9'd308: quarter_sine_lut = 16'sd26556;
            9'd309: quarter_sine_lut = 16'sd26615;
            9'd310: quarter_sine_lut = 16'sd26674;
            9'd311: quarter_sine_lut = 16'sd26732;
            9'd312: quarter_sine_lut = 16'sd26790;
            9'd313: quarter_sine_lut = 16'sd26848;
            9'd314: quarter_sine_lut = 16'sd26905;
            9'd315: quarter_sine_lut = 16'sd26962;
            9'd316: quarter_sine_lut = 16'sd27019;
            9'd317: quarter_sine_lut = 16'sd27076;
            9'd318: quarter_sine_lut = 16'sd27133;
            9'd319: quarter_sine_lut = 16'sd27189;
            9'd320: quarter_sine_lut = 16'sd27245;
            9'd321: quarter_sine_lut = 16'sd27300;
            9'd322: quarter_sine_lut = 16'sd27356;
            9'd323: quarter_sine_lut = 16'sd27411;
            9'd324: quarter_sine_lut = 16'sd27466;
            9'd325: quarter_sine_lut = 16'sd27521;
            9'd326: quarter_sine_lut = 16'sd27575;
            9'd327: quarter_sine_lut = 16'sd27629;
            9'd328: quarter_sine_lut = 16'sd27683;
            9'd329: quarter_sine_lut = 16'sd27737;
            9'd330: quarter_sine_lut = 16'sd27790;
            9'd331: quarter_sine_lut = 16'sd27843;
            9'd332: quarter_sine_lut = 16'sd27896;
            9'd333: quarter_sine_lut = 16'sd27949;
            9'd334: quarter_sine_lut = 16'sd28001;
            9'd335: quarter_sine_lut = 16'sd28053;
            9'd336: quarter_sine_lut = 16'sd28105;
            9'd337: quarter_sine_lut = 16'sd28157;
            9'd338: quarter_sine_lut = 16'sd28208;
            9'd339: quarter_sine_lut = 16'sd28259;
            9'd340: quarter_sine_lut = 16'sd28310;
            9'd341: quarter_sine_lut = 16'sd28360;
            9'd342: quarter_sine_lut = 16'sd28411;
            9'd343: quarter_sine_lut = 16'sd28460;
            9'd344: quarter_sine_lut = 16'sd28510;
            9'd345: quarter_sine_lut = 16'sd28560;
            9'd346: quarter_sine_lut = 16'sd28609;
            9'd347: quarter_sine_lut = 16'sd28658;
            9'd348: quarter_sine_lut = 16'sd28706;
            9'd349: quarter_sine_lut = 16'sd28755;
            9'd350: quarter_sine_lut = 16'sd28803;
            9'd351: quarter_sine_lut = 16'sd28850;
            9'd352: quarter_sine_lut = 16'sd28898;
            9'd353: quarter_sine_lut = 16'sd28945;
            9'd354: quarter_sine_lut = 16'sd28992;
            9'd355: quarter_sine_lut = 16'sd29039;
            9'd356: quarter_sine_lut = 16'sd29085;
            9'd357: quarter_sine_lut = 16'sd29131;
            9'd358: quarter_sine_lut = 16'sd29177;
            9'd359: quarter_sine_lut = 16'sd29223;
            9'd360: quarter_sine_lut = 16'sd29268;
            9'd361: quarter_sine_lut = 16'sd29313;
            9'd362: quarter_sine_lut = 16'sd29358;
            9'd363: quarter_sine_lut = 16'sd29403;
            9'd364: quarter_sine_lut = 16'sd29447;
            9'd365: quarter_sine_lut = 16'sd29491;
            9'd366: quarter_sine_lut = 16'sd29534;
            9'd367: quarter_sine_lut = 16'sd29578;
            9'd368: quarter_sine_lut = 16'sd29621;
            9'd369: quarter_sine_lut = 16'sd29664;
            9'd370: quarter_sine_lut = 16'sd29706;
            9'd371: quarter_sine_lut = 16'sd29749;
            9'd372: quarter_sine_lut = 16'sd29791;
            9'd373: quarter_sine_lut = 16'sd29832;
            9'd374: quarter_sine_lut = 16'sd29874;
            9'd375: quarter_sine_lut = 16'sd29915;
            9'd376: quarter_sine_lut = 16'sd29956;
            9'd377: quarter_sine_lut = 16'sd29997;
            9'd378: quarter_sine_lut = 16'sd30037;
            9'd379: quarter_sine_lut = 16'sd30077;
            9'd380: quarter_sine_lut = 16'sd30117;
            9'd381: quarter_sine_lut = 16'sd30156;
            9'd382: quarter_sine_lut = 16'sd30195;
            9'd383: quarter_sine_lut = 16'sd30234;
            9'd384: quarter_sine_lut = 16'sd30273;
            9'd385: quarter_sine_lut = 16'sd30311;
            9'd386: quarter_sine_lut = 16'sd30349;
            9'd387: quarter_sine_lut = 16'sd30387;
            9'd388: quarter_sine_lut = 16'sd30424;
            9'd389: quarter_sine_lut = 16'sd30462;
            9'd390: quarter_sine_lut = 16'sd30498;
            9'd391: quarter_sine_lut = 16'sd30535;
            9'd392: quarter_sine_lut = 16'sd30571;
            9'd393: quarter_sine_lut = 16'sd30607;
            9'd394: quarter_sine_lut = 16'sd30643;
            9'd395: quarter_sine_lut = 16'sd30679;
            9'd396: quarter_sine_lut = 16'sd30714;
            9'd397: quarter_sine_lut = 16'sd30749;
            9'd398: quarter_sine_lut = 16'sd30783;
            9'd399: quarter_sine_lut = 16'sd30818;
            9'd400: quarter_sine_lut = 16'sd30852;
            9'd401: quarter_sine_lut = 16'sd30885;
            9'd402: quarter_sine_lut = 16'sd30919;
            9'd403: quarter_sine_lut = 16'sd30952;
            9'd404: quarter_sine_lut = 16'sd30985;
            9'd405: quarter_sine_lut = 16'sd31017;
            9'd406: quarter_sine_lut = 16'sd31050;
            9'd407: quarter_sine_lut = 16'sd31082;
            9'd408: quarter_sine_lut = 16'sd31113;
            9'd409: quarter_sine_lut = 16'sd31145;
            9'd410: quarter_sine_lut = 16'sd31176;
            9'd411: quarter_sine_lut = 16'sd31206;
            9'd412: quarter_sine_lut = 16'sd31237;
            9'd413: quarter_sine_lut = 16'sd31267;
            9'd414: quarter_sine_lut = 16'sd31297;
            9'd415: quarter_sine_lut = 16'sd31327;
            9'd416: quarter_sine_lut = 16'sd31356;
            9'd417: quarter_sine_lut = 16'sd31385;
            9'd418: quarter_sine_lut = 16'sd31414;
            9'd419: quarter_sine_lut = 16'sd31442;
            9'd420: quarter_sine_lut = 16'sd31470;
            9'd421: quarter_sine_lut = 16'sd31498;
            9'd422: quarter_sine_lut = 16'sd31526;
            9'd423: quarter_sine_lut = 16'sd31553;
            9'd424: quarter_sine_lut = 16'sd31580;
            9'd425: quarter_sine_lut = 16'sd31607;
            9'd426: quarter_sine_lut = 16'sd31633;
            9'd427: quarter_sine_lut = 16'sd31659;
            9'd428: quarter_sine_lut = 16'sd31685;
            9'd429: quarter_sine_lut = 16'sd31710;
            9'd430: quarter_sine_lut = 16'sd31736;
            9'd431: quarter_sine_lut = 16'sd31760;
            9'd432: quarter_sine_lut = 16'sd31785;
            9'd433: quarter_sine_lut = 16'sd31809;
            9'd434: quarter_sine_lut = 16'sd31833;
            9'd435: quarter_sine_lut = 16'sd31857;
            9'd436: quarter_sine_lut = 16'sd31880;
            9'd437: quarter_sine_lut = 16'sd31903;
            9'd438: quarter_sine_lut = 16'sd31926;
            9'd439: quarter_sine_lut = 16'sd31949;
            9'd440: quarter_sine_lut = 16'sd31971;
            9'd441: quarter_sine_lut = 16'sd31993;
            9'd442: quarter_sine_lut = 16'sd32014;
            9'd443: quarter_sine_lut = 16'sd32036;
            9'd444: quarter_sine_lut = 16'sd32057;
            9'd445: quarter_sine_lut = 16'sd32077;
            9'd446: quarter_sine_lut = 16'sd32098;
            9'd447: quarter_sine_lut = 16'sd32118;
            9'd448: quarter_sine_lut = 16'sd32137;
            9'd449: quarter_sine_lut = 16'sd32157;
            9'd450: quarter_sine_lut = 16'sd32176;
            9'd451: quarter_sine_lut = 16'sd32195;
            9'd452: quarter_sine_lut = 16'sd32213;
            9'd453: quarter_sine_lut = 16'sd32232;
            9'd454: quarter_sine_lut = 16'sd32250;
            9'd455: quarter_sine_lut = 16'sd32267;
            9'd456: quarter_sine_lut = 16'sd32285;
            9'd457: quarter_sine_lut = 16'sd32302;
            9'd458: quarter_sine_lut = 16'sd32318;
            9'd459: quarter_sine_lut = 16'sd32335;
            9'd460: quarter_sine_lut = 16'sd32351;
            9'd461: quarter_sine_lut = 16'sd32367;
            9'd462: quarter_sine_lut = 16'sd32382;
            9'd463: quarter_sine_lut = 16'sd32397;
            9'd464: quarter_sine_lut = 16'sd32412;
            9'd465: quarter_sine_lut = 16'sd32427;
            9'd466: quarter_sine_lut = 16'sd32441;
            9'd467: quarter_sine_lut = 16'sd32455;
            9'd468: quarter_sine_lut = 16'sd32469;
            9'd469: quarter_sine_lut = 16'sd32482;
            9'd470: quarter_sine_lut = 16'sd32495;
            9'd471: quarter_sine_lut = 16'sd32508;
            9'd472: quarter_sine_lut = 16'sd32521;
            9'd473: quarter_sine_lut = 16'sd32533;
            9'd474: quarter_sine_lut = 16'sd32545;
            9'd475: quarter_sine_lut = 16'sd32556;
            9'd476: quarter_sine_lut = 16'sd32567;
            9'd477: quarter_sine_lut = 16'sd32578;
            9'd478: quarter_sine_lut = 16'sd32589;
            9'd479: quarter_sine_lut = 16'sd32599;
            9'd480: quarter_sine_lut = 16'sd32609;
            9'd481: quarter_sine_lut = 16'sd32619;
            9'd482: quarter_sine_lut = 16'sd32628;
            9'd483: quarter_sine_lut = 16'sd32637;
            9'd484: quarter_sine_lut = 16'sd32646;
            9'd485: quarter_sine_lut = 16'sd32655;
            9'd486: quarter_sine_lut = 16'sd32663;
            9'd487: quarter_sine_lut = 16'sd32671;
            9'd488: quarter_sine_lut = 16'sd32678;
            9'd489: quarter_sine_lut = 16'sd32685;
            9'd490: quarter_sine_lut = 16'sd32692;
            9'd491: quarter_sine_lut = 16'sd32699;
            9'd492: quarter_sine_lut = 16'sd32705;
            9'd493: quarter_sine_lut = 16'sd32711;
            9'd494: quarter_sine_lut = 16'sd32717;
            9'd495: quarter_sine_lut = 16'sd32722;
            9'd496: quarter_sine_lut = 16'sd32728;
            9'd497: quarter_sine_lut = 16'sd32732;
            9'd498: quarter_sine_lut = 16'sd32737;
            9'd499: quarter_sine_lut = 16'sd32741;
            9'd500: quarter_sine_lut = 16'sd32745;
            9'd501: quarter_sine_lut = 16'sd32748;
            9'd502: quarter_sine_lut = 16'sd32752;
            9'd503: quarter_sine_lut = 16'sd32755;
            9'd504: quarter_sine_lut = 16'sd32757;
            9'd505: quarter_sine_lut = 16'sd32759;
            9'd506: quarter_sine_lut = 16'sd32761;
            9'd507: quarter_sine_lut = 16'sd32763;
            9'd508: quarter_sine_lut = 16'sd32765;
            9'd509: quarter_sine_lut = 16'sd32766;
            9'd510: quarter_sine_lut = 16'sd32766;
            9'd511: quarter_sine_lut = 16'sd32767;
            default: quarter_sine_lut = 16'sd32767;
            endcase
        end
    endfunction

    function automatic signed [15:0] sine_raw(input [31:0] phase_value);
        reg [1:0] quadrant;
        reg [8:0] idx;
        reg [8:0] mirror_idx;
        reg signed [15:0] mag;
        begin
            quadrant = phase_value[31:30];
            idx = phase_value[29:21];
            // The phase address has 512 uniformly spaced samples per
            // quadrant.  Quadrants 1 and 3 need an explicit endpoint because
            // the exact pi/2 magnitude would otherwise require LUT index 512.
            // For every nonzero address, two's-complement negation implements
            // 512-idx without widening the 9-bit LUT address.
            mirror_idx = (~idx) + 9'd1;
            case (quadrant)
                2'd0: mag = quarter_sine_lut(idx);
                2'd1: mag = (idx == 9'd0) ? 16'sd32767 : quarter_sine_lut(mirror_idx);
                2'd2: mag = -quarter_sine_lut(idx);
                default: mag = (idx == 9'd0) ? -16'sd32767 : -quarter_sine_lut(mirror_idx);
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

    // Stage 33 direct-SSA plus complex ADC sideband measurements identify an
    // inverted Q path with a one-sample relative skew at 320 MS/s.  An earlier
    // 141/128-sample power-only fit restored the requested sideband but left
    // 34.51 dBc rejection; the complex product phase showed that correction
    // was excessive.  Keep mode 0 bit-for-bit compatible with the accepted
    // DDS.  Modes 2 and 3 apply exact one-sample shifts in both directions so
    // the physical correction remains explicit and independently testable.
    function automatic [31:0] stage33_q_phase_shift(input [31:0] phase_step);
        begin
            stage33_q_phase_shift = phase_step;
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
        reg [31:0] q_phase_shift;
        begin
            step = phase_step;
            amp = amplitude;
            base_phase = phase_acc + phase0 + phase_inject;
            q_phase_shift = stage33_q_phase_shift(step);
            if (mode == 2'd1) begin
                i0 = sine_sample(base_phase + 32'h4000_0000, amp);
                q0 = sine_sample(base_phase, amp);
                i1 = i0;
                q1 = q0;
                i2 = i0;
                q2 = q0;
                i3 = i0;
                q3 = q0;
            end else if (mode == 2'd0) begin
                // Standard positive complex rotation in the conventional
                // I=cos,Q=sin frame.  The Agent passes the signed baseband
                // offset requested_rf-center without an extra sign change.
                i0 = sine_sample(base_phase + 32'h4000_0000, amp);
                q0 = sine_sample(base_phase, amp);
                i1 = sine_sample(base_phase + step + 32'h4000_0000, amp);
                q1 = sine_sample(base_phase + step, amp);
                i2 = sine_sample(base_phase + (step << 1) + 32'h4000_0000, amp);
                q2 = sine_sample(base_phase + (step << 1), amp);
                i3 = sine_sample(base_phase + (step << 1) + step + 32'h4000_0000, amp);
                q3 = sine_sample(base_phase + (step << 1) + step, amp);
            end else begin
                // Mode 2 advances the generated Q path by one sample;
                // mode 3 applies the same correction in the opposite
                // direction.  Both invert Q to cancel the measured Stage 33
                // C2R polarity while preserving the requested DDS frequency.
                if (mode == 2'd3) begin
                    q_phase_shift = -q_phase_shift;
                end
                i0 = sine_sample(base_phase + 32'h4000_0000, amp);
                q0 = -sine_sample(base_phase + q_phase_shift, amp);
                i1 = sine_sample(base_phase + step + 32'h4000_0000, amp);
                q1 = -sine_sample(base_phase + step + q_phase_shift, amp);
                i2 = sine_sample(base_phase + (step << 1) + 32'h4000_0000, amp);
                q2 = -sine_sample(base_phase + (step << 1) + q_phase_shift, amp);
                i3 = sine_sample(base_phase + (step << 1) + step + 32'h4000_0000, amp);
                q3 = -sine_sample(base_phase + (step << 1) + step + q_phase_shift, amp);
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
endmodule
