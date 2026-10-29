// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_strict_line_image;
    localparam logic [31:0] BASE=32'h10000000;
    localparam logic [32:0] BYTES=33'd4096;
/* verilator lint_off INCABSPATH */
`include `RK_DDR_LINE_IMAGE_HEADER
/* verilator lint_on INCABSPATH */
    string image_path;
    integer rows,image_fd;
    logic [31:0] address,previous;
    logic [511:0] data;
    initial begin
        if(!$value$plusargs("IMAGE=%s",image_path)||!$value$plusargs("NROWS=%d",rows))$fatal(1,"Missing reader metadata");
        ddr_image_open(image_path,rows,image_fd);previous=0;
        for(integer row=0;row<rows;row=row+1)begin
            ddr_image_read(image_fd,row,previous,address,data);previous=address;
            $display("ROW %08h %0128h",address,data);
        end
        ddr_image_finish(image_fd);
        $display("PASS strict_ddr_image rows=%0d",rows);$finish;
    end
endmodule
