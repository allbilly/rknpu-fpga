// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Binary next-state and asynchronous-clear rule, after unchanged default GSR.
module tb_prefix_state_fdce_fold;
    reg clk=0;
    always #10 clk=~clk;
    reg clear=0,enable=0,data=0;
    wire [3:0] observed;
    reg old_q,expected;
    integer vector,cell_index,negative,seeds,async_checks,next_checks;
    actual_prefix_state_fdces actual(.clk,.clear,.enable,.data,.observed);
    initial begin
        negative=0;seeds=0;async_checks=0;next_checks=0;
        if($value$plusargs("NEGATIVE=%d",negative)) begin end
        #1;if(glbl.GSR!==1'b1) $fatal(1,"FDCE fold default GSR missing");
        wait(glbl.GSR===1'b0);#1;
        for(vector=0;vector<16;vector=vector+1) begin
            old_q=vector[0];
            // Establish each old binary Q with an ordinary clocked write,
            // not hierarchy forcing or a substitute INIT value.
            @(negedge clk);clear=0;enable=1;data=old_q;
            @(posedge clk);#2;
            for(cell_index=0;cell_index<4;cell_index=cell_index+1) begin
                if(observed[cell_index]!==old_q)
                    $fatal(1,"FDCE fold seed mismatch cell=%0d vector=%0d got=%b expected=%b",cell_index,vector,observed[cell_index],old_q);
                seeds=seeds+1;
            end
            @(negedge clk);data=vector[1];enable=vector[2];clear=vector[3];#2;
            for(cell_index=0;cell_index<4;cell_index=cell_index+1) begin
                expected=clear?1'b0:old_q;
                if(observed[cell_index]!==expected)
                    $fatal(1,"FDCE asynchronous rule mismatch cell=%0d vector=%0d got=%b expected=%b",cell_index,vector,observed[cell_index],expected);
                async_checks=async_checks+1;
            end
            @(posedge clk);#2;
            for(cell_index=0;cell_index<4;cell_index=cell_index+1) begin
                expected=(clear?1'b0:enable?data:old_q)^((negative&&vector==0&&cell_index==0)?1'b1:1'b0);
                if(observed[cell_index]!==expected)
                    $fatal(1,"FDCE next fold mismatch cell=%0d vector=%0d got=%b expected=%b",cell_index,vector,observed[cell_index],expected);
                next_checks=next_checks+1;
            end
        end
        if(seeds!=64||async_checks!=64||next_checks!=64) $fatal(1,"incomplete FDCE fold corpus");
        $display("PASS actual four state FDCE binary fold vectors=16 seed_checks=64 async_checks=64 next_checks=64 default_gsr=100ns; not temporal startup or physical acceptance");
        $finish;
    end
    initial begin #2000;$fatal(1,"FDCE fold simulation timeout");end
endmodule
