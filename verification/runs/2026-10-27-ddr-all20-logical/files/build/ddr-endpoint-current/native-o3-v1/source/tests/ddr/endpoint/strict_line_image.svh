// SPDX-License-Identifier: MIT
// Strict complete-BO line images. The including bench supplies BASE and BYTES;
// its expected row count must come independently from the captured BO lengths.
function automatic bit ddr_image_hex(input string token,input integer digits);
    logic [7:0] character;
    ddr_image_hex=token.len()==digits;
    for(integer i=0;i<token.len();i=i+1)begin
        character=token[i];
        if(!((character>="0"&&character<="9")||(character>="a"&&character<="f")||
             (character>="A"&&character<="F")))ddr_image_hex=0;
    end
endfunction

task automatic ddr_image_open(input string path,input integer expected_rows,output integer image_fd);
    if(expected_rows<=0 || 33'(expected_rows)>(BYTES>>6))
        $fatal(1,"Invalid DDR image row count %0d",expected_rows);
    image_fd=$fopen(path,"r");
    if(image_fd==0)$fatal(1,"DDR image unavailable: %s",path);
endtask

task automatic ddr_image_read(input integer image_fd,input integer row_index,
    input logic [31:0] previous_address,output logic [31:0] image_address,
    output logic [511:0] image_data);
    reg [4095:0] line;
    integer bytes_read,parsed,unused_token_scan,next_character;
    logic [7:0] character;
    string address_token,data_token,extra_token;
    // Icarus fgets consumes an embedded-NUL suffix without returning those
    // bytes. Read bytes explicitly so no string conversion can hide them.
    line=0;bytes_read=0;next_character=$fgetc(image_fd);
    while(next_character!=-1 && next_character!=10)begin
        if(bytes_read>=511)$fatal(1,"Oversized DDR image row %0d",row_index);
        character=8'(next_character);
        if(!((character>="0"&&character<="9")||(character>="a"&&character<="f")||
             (character>="A"&&character<="F")||character==8'h20||character==8'h09||
             character==8'h0d))$fatal(1,"Invalid DDR image character at row %0d",row_index);
        line={line[4087:0],character};bytes_read=bytes_read+1;next_character=$fgetc(image_fd);
    end
    if(bytes_read==0)$fatal(1,"Short DDR image row %0d",row_index);
    address_token="";data_token="";extra_token="";
    // Explicit conversion handles packed buffers in both simulators.
    // Missing third-conversion return counts differ, so inspect cleared tokens.
    unused_token_scan=$sscanf(string'(line),"%s %s %s",address_token,data_token,extra_token);
    if(extra_token.len()!=0 || !ddr_image_hex(address_token,8) || !ddr_image_hex(data_token,128))
        $fatal(1,"Malformed DDR image row %0d",row_index);
    parsed=$sscanf({address_token," ",data_token},"%h %h",image_address,image_data);
    if(parsed!=2 || (^image_address)===1'bx || (^image_data)===1'bx || image_address[5:0]!=0 ||
       image_address<BASE || ({1'b0,image_address}+33'd64)>({1'b0,BASE}+BYTES) ||
       (row_index!=0 && image_address<=previous_address))
        $fatal(1,"Invalid or unordered DDR image address/data at row %0d",row_index);
endtask

task automatic ddr_image_finish(input integer image_fd);
    integer next_character;
    next_character=$fgetc(image_fd);
    if(next_character!=-1 || !$feof(image_fd))$fatal(1,"Extra or malformed DDR image tail");
    $fclose(image_fd);
endtask
