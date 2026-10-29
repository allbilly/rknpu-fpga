// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>
#include "bel_variant_name.h"
int main()
{
    struct Test { const char *input; bool valid; const char *base; int variant; };
    const Test tests[] = {
        {"CE1USED", true, "CE1USED", -1},
        {"IOB33/INBUF_EN", true, "IOB33/INBUF_EN", -1},
        {"CE1USED@0", true, "CE1USED", 0},
        {"CE1USED@1", true, "CE1USED", 1},
        {"CE1USED@32767", true, "CE1USED", 32767},
        {"CE1USED@01", true, "CE1USED", 1},
        {"CE1USED@", false, "CE1USED@", -1},
        {"@1", false, "@1", -1},
        {"CE1USED@-1", false, "CE1USED@-1", -1},
        {"CE1USED@32768", false, "CE1USED@32768", -1},
        {"CE1USED@999999999999999999999999", false, "CE1USED@999999999999999999999999", -1},
        {"CE1USED@1x", false, "CE1USED@1x", -1},
        {"CE1USED@1@2", false, "CE1USED@1@2", -1},
    };
    for (const auto &test : tests) {
        std::string name = test.input;
        int variant = 999;
        assert(split_bel_variant_name(name, variant) == test.valid);
        assert(name == test.base && variant == test.variant);
    }
    std::cout << "PASS BEL variant parser: " << sizeof(tests)/sizeof(tests[0]) << " cases\n";
}
