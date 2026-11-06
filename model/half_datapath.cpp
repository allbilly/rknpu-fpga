// SPDX-License-Identifier: MIT
// Executable integer arithmetic design model for rk_fp16_alu.sv.
// Testing this model DOES NOT constitute compiling or simulating the RTL.
#include <cstdint>

static int msb10(uint32_t x) {
    int p = 0;
    for (int i = 0; i < 10; ++i) if ((x >> i) & 1) p = i;
    return p;
}

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
static uint16_t fdiv(uint16_t a, uint16_t b) {
    const bool sa = a >> 15, sb = b >> 15;
    const bool na = (a & 0x7c00) == 0x7c00 && (a & 1023);
    const bool nb = (b & 0x7c00) == 0x7c00 && (b & 1023);
    const bool ia = (a & 0x7fff) == 0x7c00, ib = (b & 0x7fff) == 0x7c00;
    const bool za = !(a & 0x7fff), zb = !(b & 0x7fff);
    if (na || nb) return 0x7c01;
    if (a == 0x0000 && b == 0x0000) return 0x7c01;
    if (zb) return uint16_t((sa ? 0x8000 : 0) | 0x7c00);
    if (za) return uint16_t(sa ? 0x8000 : 0);
    if (ia) return uint16_t((sa ? 0x8000 : 0) | 0x7c00);
    if (ib) return uint16_t(sa ? 0x8000 : 0);
    int ea, eb;
    uint32_t ma, mb;
    const uint32_t fa = a & 1023, fb = b & 1023;
    if ((a >> 10) & 31) { ma = 1024 | fa; ea = int((a >> 10) & 31) - 15; }
    else { const int k = 10 - msb10(fa); ma = fa << k; ea = -14 - k; }
    if ((b >> 10) & 31) { mb = 1024 | fb; eb = int((b >> 10) & 31) - 15; }
    else { const int k = 10 - msb10(fb); mb = fb << k; eb = -14 - k; }
    int e;
    uint32_t qn;
    const uint32_t qd = mb;
    if (ma >= mb) { e = ea - eb; qn = ma; }
    else { e = ea - eb - 1; qn = ma << 1; }
    const int ue = e >= -14 ? e - 10 : -24;
    const int shift = e - ue + 3;
    const uint64_t num = shift >= 0 ? uint64_t(qn) << shift : qn;
    const uint64_t den = shift >= 0 ? qd : uint64_t(qd) << -shift;
    const uint32_t d = uint32_t(num / den);
    uint32_t n = d >> 3;
    const uint32_t m = d & 7;
    if (m > 4 || (m == 4 && (n & 1))) ++n;
    if (n == 2048) { n = 1024; ++e; }
    if (n == 1024 && e < -14) e = -14;
    const uint16_t sign = sa ^ sb ? 0x8000 : 0;
    if (e < -14) return uint16_t(sign | (n & 0x3ff));
    if (e > 15) return uint16_t(sign | 0x7c00);
    return uint16_t(sign | ((e + 15) << 10) | (n & 0x3ff));
}

extern "C" uint16_t rk_half_alu(uint16_t a, uint16_t b, unsigned op) {
    if (op == 4) return fdiv(a, b);
    const bool sa = a >> 15, sb = (b >> 15) ^ (op == 1);
    const bool na = (a & 0x7c00) == 0x7c00 && (a & 1023);
    const bool nb = (b & 0x7c00) == 0x7c00 && (b & 1023);
    const bool ia = (a & 0x7fff) == 0x7c00, ib = (b & 0x7fff) == 0x7c00;
    const bool za = !(a & 0x7fff), zb = !(b & 0x7fff);
    if (na || nb || op > 4) return 0x7c01;
    if (op == 3) {
        if (sa != sb) return sa ? b : a;
        if (!sa) return (a & 0x7fff) >= (b & 0x7fff) ? a : b;
        return (a & 0x7fff) <= (b & 0x7fff) ? a : b;
    }
    const int ea = ((a >> 10) & 31) ? ((a >> 10) & 31) : 1;
    const int eb = ((b >> 10) & 31) ? ((b >> 10) & 31) : 1;
    const uint64_t ma = (a & 1023) | ((a & 0x7c00) ? 1024 : 0);
    const uint64_t mb = (b & 1023) | ((b & 0x7c00) ? 1024 : 0);
    if (op == 2) {
        if ((ia && zb) || (ib && za)) return 0x7c01;
        if (ia || ib) return ((sa ^ sb) ? 0x8000 : 0) | 0x7c00;
        return pack(sa ^ sb, ma * mb, ea + eb - 50);
    }
    if (ia || ib) {
        if (ia && ib) {
            if (op == 1) return ((a >> 15) == (b >> 15)) ? 0x7c00 : 0x7c01;
            return sa == sb ? ((sa ? 0x8000 : 0) | 0x7c00) : 0x7c01;
        }
        if (ia) return (sa ? 0x8000 : 0) | 0x7c00;
        return (sb ? 0x8000 : 0) | 0x7c00;
    }
    const int64_t ua = int64_t(ma << (ea - 1)), ub = int64_t(mb << (eb - 1));
    const int64_t v = (sa ? -ua : ua) + (sb ? -ub : ub);
    if (!v) return 0;
    return pack(v < 0, uint64_t(v < 0 ? -v : v), -24);
}
