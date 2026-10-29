// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>
#include "pip_index_name.h"

int main()
{
    struct Case { const char *name; bool valid; const char *tile; int index; };
    const Case cases[] = {
        {"PIP/NULL_X0Y416/0", true, "NULL_X0Y416", 0},
        {"PIP/BRAM_L_X6Y5/123", true, "BRAM_L_X6Y5", 123},
        {"PIP/INT_L_X0Y399/2147483647", true, "INT_L_X0Y399", 2147483647},
        {"PIP/INT_L_X0Y399/2147483648", false, "", -1},
        {"PIP/T/999999999999999999999999", false, "", -1},
        {"", false, "", -1}, {"PIP/", false, "", -1},
        {"PIP/T", false, "", -1}, {"PIP/T/", false, "", -1},
        {"PIP//1", false, "", -1}, {"PIP/T/-1", false, "", -1},
        {"PIP/T/+1", false, "", -1}, {"PIP/T/01", false, "", -1},
        {"PIP/T/00", false, "", -1}, {"PIP/T/1x", false, "", -1},
        {"PIP/T/1/2", false, "", -1}, {"PIP/T/1.0", false, "", -1},
        {"PIP/T/ 1", false, "", -1}, {"PIP/T/1 ", false, "", -1},
        {"PIP/T X/1", false, "", -1}, {"PIP/T-X/1", false, "", -1},
        {"pip/T/1", false, "", -1}, {"SITEPIP/T/B/P", false, "", -1},
    };
    for (const auto &c : cases) {
        std::string tile = "unchanged";
        int index = 999;
        assert(rk_openxc7::parse_pip_index_name(c.name, tile, index) == c.valid);
        assert(tile == c.tile && index == c.index);
    }
    // Every local PIP index in a large synthetic tile round-trips exactly.
    for (int i = 0; i < 100000; ++i) {
        std::string tile;
        int index;
        assert(rk_openxc7::parse_pip_index_name("PIP/INT_L_X0Y399/" + std::to_string(i), tile, index));
        assert(tile == "INT_L_X0Y399" && index == i);
    }
    std::cout << "PASS PIP index parser: 23 directed cases and 100000 round trips\n";
}
