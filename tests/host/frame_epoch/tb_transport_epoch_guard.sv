`timescale 1ns/1ps
module tb_transport_epoch_guard #(
    parameter integer FRESH_CYCLES=4
);
    logic clk;
    initial begin clk=0; forever #5 clk=~clk; end
    logic rst_n;
    logic up;
    wire ready,failed,seen_up;
    integer checks=0;
    logic [31:0] independent_jtag_count;
    integer z_tested;

    rk_transport_epoch_guard #(.FRESH_CYCLES(FRESH_CYCLES)) dut(
        .clk,.rst_n,.up,.ready,.failed,.seen_up);

    // Represents a separate JTAG path. Its progress is intentionally
    // independent of the PCIe epoch guard's `up` input.
    always @(posedge clk)
        independent_jtag_count<=independent_jtag_count+1'b1;

    task automatic check(input logic condition,input string message);
        begin
            checks=checks+1;
            if(condition!==1'b1) $fatal(1,"CHECK_FAILED %s",message);
        end
    endtask

    task automatic step;
        begin @(posedge clk); #1; end
    endtask

    task automatic reset_guard;
        begin
            up=0;
            rst_n=0;
            #1;
            check(!ready&&!failed&&!seen_up,"joint async reset clears epoch and gates ready");
            repeat(2) step();
            @(negedge clk); #1; rst_n=1; #1;
            check(!ready&&!failed&&!seen_up,"released reset starts unarmed");
        end
    endtask

    task automatic arm_exactly;
        integer i;
        begin
            up=1;
            for(i=1;i<FRESH_CYCLES;i=i+1) begin
                step();
                check(!ready,"ready asserted before FRESH_CYCLES high samples");
                check(!failed,"high startup samples faulted");
            end
            step();
            check(ready&&seen_up&&!failed,"ready did not assert on exact freshness boundary");
        end
    endtask

    task automatic test_startup_unknown;
        begin
            reset_guard();
            up=1'bx; repeat(FRESH_CYCLES+2) step();
            check(!ready&&!failed&&!seen_up,"startup X was treated as link history");
            up=1'bz; repeat(2) step();
            check(!ready&&!failed&&!seen_up,"startup Z was treated as link history");
            up=0; repeat(2) step();
            check(!ready&&!failed&&!seen_up,"startup absence poisoned an unseen epoch");
        end
    endtask

    task automatic test_brief_high_poison;
        begin
            reset_guard();
            up=1;
            step();
            check(seen_up&&!ready&&!failed,"first brief high sample was not remembered cleanly");
            @(negedge clk); #1; up=0; #1;
            check(!ready&&!failed,"ready failed to gate low before sticky fault capture");
            step();
            check(failed&&!ready&&seen_up,"brief high then low did not latch failure");
            up=1; repeat(FRESH_CYCLES+2) step();
            check(failed&&!ready,"link recovery rearmed an unarmed poisoned epoch");
        end
    endtask

    task automatic test_after_arm_poison(input logic bad_level,input string label);
        begin
            reset_guard(); arm_exactly();
            @(negedge clk); #1; up=bad_level; #1;
            check(!ready&&!failed,"bad link level did not gate ready immediately");
            step();
            check(failed&&!ready&&seen_up,{label," after arm did not latch failure"});
            up=1; repeat(FRESH_CYCLES+2) step();
            check(failed&&!ready,"recovered link cleared a latched failure");
        end
    endtask

    task automatic test_async_joint_recovery;
        begin
            reset_guard(); arm_exactly();
            up=0; step();
            check(failed&&!ready,"link loss did not poison before reset recovery case");
            up=1; repeat(FRESH_CYCLES+1) step();
            check(failed&&!ready,"link recovery cleared failure before joint reset");
            @(negedge clk); #2; rst_n=0; #1;
            check(!ready&&!failed&&!seen_up,"asynchronous joint reset did not clear failure");
            rst_n=1; #1;
            check(!ready&&!failed&&!seen_up,"post-reset ready bypassed fresh samples");
            arm_exactly();
        end
    endtask

    task automatic test_independent_jtag;
        integer before_count;
        begin
            reset_guard();
            up=0;
            before_count=independent_jtag_count;
            repeat(25) step();
            check(!ready&&!failed&&!seen_up,"absent PCIe link changed the guard");
            check(independent_jtag_count==before_count+25,
                  "independent JTAG progress was incorrectly gated by PCIe up");
        end
    endtask

    task automatic test_saturation;
        integer i;
        begin
            reset_guard(); arm_exactly();
            for(i=0;i<100;i=i+1) begin
                step();
                check(ready&&!failed&&seen_up,"long stable up interval overflowed freshness state");
            end
        end
    endtask

    initial begin
        rst_n=1; up=0; independent_jtag_count=0; z_tested=0;
        if(FRESH_CYCLES<2 || FRESH_CYCLES>65536) begin
            // The DUT's own initial $fatal is the expected invalid-parameter result.
            #1;
            $fatal(1,"INVALID_PARAMETER_DUT_DID_NOT_FAIL");
        end
        reset_guard();
        test_startup_unknown();
        reset_guard(); arm_exactly();
        test_brief_high_poison();
        test_after_arm_poison(1'bx,"X");
`ifndef VERILATOR
        test_after_arm_poison(1'bz,"Z");
        z_tested=1;
`else
        z_tested=0;
`endif
        test_async_joint_recovery();
        test_independent_jtag();
        test_saturation();
        $display("PASS_TRANSPORT_EPOCH_GUARD fresh=%0d checks=%0d z_four_state=%0d stimulus=directed_no_prng",FRESH_CYCLES,checks,z_tested);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1,"GLOBAL_TEST_TIMEOUT");
    end
endmodule
