// SPDX-License-Identifier: MIT
// Offline frame interface to real RTL. No arithmetic, RAM injection, TAP or XVC
// hardware model lives in this harness. The public frame port is the boundary.
#include "Vrk_jtag_ew_bram.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

class Endpoint {
    VerilatedContext context;
    Vrk_jtag_ew_bram dut{&context};
    std::string response = std::string(18, '0') + "4f54504a" + std::string(134, '0');

    void tick() {
        dut.clk = 0; dut.eval(); context.timeInc(10);
        dut.clk = 1; dut.eval(); context.timeInc(10);
        if (context.gotFinish()) throw std::runtime_error("RTL terminated");
    }
    std::string sample() {
        std::array<uint8_t,80> bytes{};
        for (unsigned i=0;i<64;i++) bytes[i]=(dut.rsp_data[i/4]>>(8*(i%4)))&255;
        bytes[64]=dut.rsp_status;
        bytes[65]=dut.rsp_seq&255; bytes[66]=(dut.rsp_seq>>8)&255;
        bytes[67]=0x4a; bytes[68]=0x50; bytes[69]=0x54; bytes[70]=0x4f;
        std::ostringstream out;
        out << std::hex << std::setfill('0');
        for (auto i=bytes.rbegin();i!=bytes.rend();++i) out<<std::setw(2)<<unsigned(*i);
        return out.str();
    }
public:
    Endpoint() {
        dut.clk=0; dut.rst_n=0; dut.req_valid=0;
        for (unsigned i=0;i<19;i++) dut.req[i]=0;
        for (unsigned i=0;i<5;i++) tick();
        dut.rst_n=1;
        for (unsigned i=0;i<5;i++) tick();
    }
    ~Endpoint() { dut.final(); }
    std::string exchange(const std::string& frame) {
        if (frame.size()!=160 || frame.find_first_not_of("0123456789abcdef")!=std::string::npos)
            throw std::runtime_error("expected160 lower-case hex digits");
        // Zero polls only advance SYS time. Framing/sequence are preserved.
        if (frame.find_first_not_of('0')==std::string::npos) {
            for(unsigned i=0;i<16;i++) tick();
            return response;
        }
        if (frame.substr(0,9)!="000000000") throw std::runtime_error("nonzero reserved request bits");
        for (unsigned i=0;i<19;i++) {
            size_t end=frame.size()-8*i;
            dut.req[i]=static_cast<uint32_t>(std::stoul(frame.substr(end-8,8),nullptr,16));
        }
        dut.clk=0; dut.eval();
        if (!dut.req_ready) throw std::runtime_error("backend refused command; joint reset required");
        dut.req_valid=1;
        tick();
        dut.req_valid=0;
        unsigned cycles=0;
        while(!dut.rsp_valid && cycles<1000000) {tick();cycles++;}
        if(!dut.rsp_valid) throw std::runtime_error("RTL frame deadline");
        response=sample();
        tick(); // Consume the unbackpressured response pulse.
        return response;
    }
};

int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Endpoint endpoint;
        std::cout<<"READY raw-frame-rtl1"<<std::endl;
        std::string line;
        while(std::getline(std::cin,line)) {
            if(line.rfind("frame ",0)!=0) throw std::runtime_error("unknown harness command");
            std::cout<<"response "<<endpoint.exchange(line.substr(6))<<std::endl;
        }
        return 0;
    } catch(const std::exception& exc) {
        std::cerr<<"RTL endpoint error: "<<exc.what()<<std::endl;
        return 2;
    }
}
