// Strict replay scoreboard. The including bench supplies BASE, WORDS and memory.
// NCHECKS comes from the fixture's mapped regions, independently of this file.
function automatic bit memory_check_hex(input string token, input integer digits);
    byte character;
    memory_check_hex=(token.len()==digits);
    for (integer i=0; i<token.len(); i=i+1) begin
        character=token[i];
        if (!((character>="0" && character<="9") ||
              (character>="a" && character<="f") ||
              (character>="A" && character<="F"))) memory_check_hex=0;
    end
endfunction
task automatic verify_memory(input string check_path, input string observed_path,
                             input integer expected_checks, input bit allow_empty=0);
    integer check_fd, observed_fd, parsed, checked, unused_token_scan;
    reg [2047:0] line;
    string address_token, value_token, extra_token;
    logic [31:0] address, previous_address;
    logic [15:0] expected_value;
    if (expected_checks < 0 || (expected_checks == 0 && !allow_empty))
        $fatal(1,"invalid expected memory-check count %0d",expected_checks);
    check_fd=$fopen(check_path,"r");
    if (check_fd==0) $fatal(1,"missing memory check file %s",check_path);
    observed_fd=0;
    if (observed_path!="") begin
        observed_fd=$fopen(observed_path,"w");
        if (observed_fd==0) $fatal(1,"cannot open observed-memory output");
    end
    checked=0; previous_address=0;
    while ($fgets(line,check_fd)!=0) begin
        // Packed fgets buffers contain leading NUL bytes. Convert explicitly
        // before scanning. Simulators differ on the return count when a third
        // conversion encounters EOF, so validate freshly cleared tokens.
        address_token=""; value_token=""; extra_token="";
        unused_token_scan=$sscanf(string'(line),"%s %s %s",address_token,value_token,extra_token);
        if (extra_token.len()!=0 || !memory_check_hex(address_token,8) || !memory_check_hex(value_token,4))
            $fatal(1,"malformed memory check file at row %0d",checked);
        parsed=$sscanf({address_token," ",value_token},"%h %h",address,expected_value);
        if (parsed!=2) $fatal(1,"malformed memory check values");
        if ((^address)===1'bx || (^expected_value)===1'bx || address[0] ||
            address<BASE || ((address-BASE)>>1)>=WORDS ||
            (checked!=0 && address<=previous_address))
            $fatal(1,"invalid or unordered memory check address/value at row %0d",checked);
        if (checked>=expected_checks) $fatal(1,"extra memory check row");
        if (observed_fd!=0)
            $fdisplay(observed_fd,"%08h %04h",address,memory[(address-BASE)>>1]);
        if (memory[(address-BASE)>>1]!==expected_value)
            $fatal(1,"memory mismatch @%08h got %04h want %04h",address,memory[(address-BASE)>>1],expected_value);
        previous_address=address; checked=checked+1;
    end
    if (!$feof(check_fd)) $fatal(1,"malformed memory check file");
    if (checked!=expected_checks)
        $fatal(1,"memory check count %0d wanted %0d",checked,expected_checks);
    $fclose(check_fd);
    if (observed_fd!=0) $fclose(observed_fd);
endtask
