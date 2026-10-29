// SPDX-License-Identifier: MIT
#ifndef RK_OPENXC7_PIP_INDEX_NAME_H
#define RK_OPENXC7_PIP_INDEX_NAME_H
#include <limits>
#include <string>

namespace rk_openxc7 {
// Canonical names identify database records, including parallel site variants.
// They are chipdb-specific, not portable device constraints or fixed routes.
inline bool parse_pip_index_name(const std::string &name, std::string &tile, int &index)
{
    tile.clear();
    index = -1;
    if (name.compare(0, 4, "PIP/") != 0)
        return false;
    const auto slash = name.find('/', 4);
    if (slash == std::string::npos || slash == 4 || slash + 1 == name.size())
        return false;
    for (std::size_t i = 4; i < slash; ++i) {
        const char c = name[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_'))
            return false;
    }
    if (name[slash + 1] == '0' && slash + 2 != name.size())
        return false;
    int value = 0;
    for (std::size_t i = slash + 1; i < name.size(); ++i) {
        const char c = name[i];
        if (c < '0' || c > '9' || value > (std::numeric_limits<int>::max() - (c - '0')) / 10)
            return false;
        value = value * 10 + (c - '0');
    }
    tile = name.substr(4, slash - 4);
    index = value;
    return true;
}
}
#endif
