// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Minimal independent parameter-forwarding diagnostic; not a RAM substitute.
module diagnostic_forwarded #(parameter INIT_00=256'h0) (output [255:0] value);
    assign value=INIT_00;
endmodule
module diagnostic_forwarding #(parameter RAM_MODE="TDP",parameter INIT_00=256'h0)
                             (output [255:0] value);
    generate case(RAM_MODE)
        "TDP": begin: gen_tdp
            diagnostic_forwarded #(.INIT_00(INIT_00)) inner(.value);
        end
        default: begin: gen_other
            diagnostic_forwarded #(.INIT_00(INIT_00)) inner(.value);
        end
    endcase endgenerate
endmodule
module tb_bram_parameter_forwarding_diagnostic;
    wire [255:0] mapped0,mapped1,zero0,zero1,one0,one1;
    diagnostic_forwarding #(.INIT_00({256{1'bx}})) mapped_0(.value(mapped0));
    diagnostic_forwarding #(.INIT_00({256{1'bx}})) mapped_1(.value(mapped1));
    diagnostic_forwarding #(.INIT_00(256'h0)) zero_0(.value(zero0));
    diagnostic_forwarding #(.INIT_00(256'h0)) zero_1(.value(zero1));
    diagnostic_forwarding #(.INIT_00({256{1'b1}})) one_0(.value(one0));
    diagnostic_forwarding #(.INIT_00({256{1'b1}})) one_1(.value(one1));
    initial begin
        #1;
        $display("FORWARDING mapped=%h/%h zero=%h/%h one=%h/%h",mapped0,mapped1,zero0,zero1,one0,one1);
        if(mapped0!=={256{1'bx}}||mapped1!=={256{1'bx}}||zero0!==256'h0||zero1!==256'h0||one0!=={256{1'b1}}||one1!=={256{1'b1}})
            $fatal(1,"independent parameter forwarding mismatch");
        $display("PASS independent constant parameter forwarding only; not vendor-model or board acceptance");
        $finish;
    end
endmodule
