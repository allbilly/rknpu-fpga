// Executes the unchanged pinned Project X-Ray CRC header as an offline oracle.
// No HDL, frame encoder, configuration interface or hardware is executed.
#include <cstdint>
#include <iostream>
#include <prjxray/xilinx/xc7series/crc.h>

int main() {
    std::uint32_t seed = 3588;
    auto next = [&seed]() {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        return seed;
    };
    for (unsigned index = 0; index < 10000; ++index) {
        auto address = next() & 31;
        auto data = next();
        auto previous = next();
        std::cout << address << ' ' << data << ' ' << previous << ' '
                  << prjxray::xilinx::xc7series::icap_crc(address, data, previous) << '\n';
    }
}
