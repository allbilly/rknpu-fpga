// Actual Yosys memory inference, not a hand-built expected-width netlist.
module dsp_prefix_ram_capture_control(
    input wire clk, we,
    input wire [9:0] waddr, raddr,
    input wire [31:0] din,
    output reg [31:0] dout
);
    (* ram_style = "block" *) reg [31:0] memory [0:1023];
    always @(posedge clk) begin
        if (we) memory[waddr] <= din;
        dout <= memory[raddr];
    end
endmodule
