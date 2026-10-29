// SPDX-License-Identifier: MIT
// Executable integer arithmetic design model for rk_fp16_alu.sv.
// Testing this model DOES NOT constitute compiling or simulating the RTL.
#include <cstdint>

static uint64_t round_shift(uint64_t x, int shift) {
    if (shift <= 0) return x << (-shift);
    if (shift >= 64) return 0;
    const uint64_t q = x >> shift;
    const uint64_t r = x & ((uint64_t(1) << shift) - 1);
    const uint64_t h = uint64_t(1) << (shift - 1);
    return q + (r > h || (r == h && (q & 1)));
}
static uint16_t pack(bool s, uint64_t n, int scale) {
    const uint16_t sign = s ? 0x8000 : 0;
    if (!n) return sign;
    int p = 0;
    for (int i = 0; i < 64; ++i) if ((n >> i) & 1) p = i;
    int e = p + scale;
    if (e < -14) return sign | uint16_t(round_shift(n, -scale - 24));
    uint64_t q = round_shift(n, p - 10);
    if (q == 2048) { q >>= 1; ++e; }
    if (e > 15) return sign | 0x7c00;
    return sign | uint16_t((e + 15) << 10) | uint16_t(q & 1023);
}
extern "C" uint16_t rk_half_alu(uint16_t a, uint16_t b, unsigned op) {
    const bool sa = a >> 15, sb = (b >> 15) ^ (op == 1);
    const bool na = (a & 0x7c00) == 0x7c00 && (a & 1023);
    const bool nb = (b & 0x7c00) == 0x7c00 && (b & 1023);
    const bool ia = (a & 0x7fff) == 0x7c00, ib = (b & 0x7fff) == 0x7c00;
    const bool za = !(a & 0x7fff), zb = !(b & 0x7fff);
    if (na || nb || op > 2) return 0x7e00;
    const int ea = ((a >> 10) & 31) ? ((a >> 10) & 31) : 1;
    const int eb = ((b >> 10) & 31) ? ((b >> 10) & 31) : 1;
    const uint64_t ma = (a & 1023) | ((a & 0x7c00) ? 1024 : 0);
    const uint64_t mb = (b & 1023) | ((b & 0x7c00) ? 1024 : 0);
    if (op == 2) {
        if ((ia && zb) || (ib && za)) return 0x7e00;
        if (ia || ib) return ((sa ^ sb) ? 0x8000 : 0) | 0x7c00;
        return pack(sa ^ sb, ma * mb, ea + eb - 50);
    }
    if (ia && ib && sa != sb) return 0x7e00;
    if (ia) return (sa ? 0x8000 : 0) | 0x7c00;
    if (ib) return (sb ? 0x8000 : 0) | 0x7c00;
    const int64_t ua = int64_t(ma << (ea - 1)), ub = int64_t(mb << (eb - 1));
    const int64_t v = (sa ? -ua : ua) + (sb ? -ub : ub);
    if (!v) return (sa && sb) ? 0x8000 : 0;
    return pack(v < 0, uint64_t(v < 0 ? -v : v), -24);
}
