// Test driver for the frozen OpenTPU mailbox DR signals, not a BSCANE2 model.
// TCK is deliberately asynchronous to the 50 MHz SYS clock and never above 6 MHz.
task automatic tck_edge(input bit bit_in, output bit bit_out);
    tdi=bit_in;
    #83.334;bit_out=tdo;tck=1;
    #83.333;tck=0;
endtask
task automatic scan_frame(input logic [639:0] frame,output logic [639:0] received);
    bit sampled;
    sel=1;capture=1;shift=0;update=0;tck_edge(0,sampled);capture=0;
    shift=1;
    for(integer j=0;j<640;j=j+1) begin tck_edge(frame[j],sampled);received[j]=sampled;end
    shift=0;update=1;tck_edge(0,sampled);update=0;
endtask
