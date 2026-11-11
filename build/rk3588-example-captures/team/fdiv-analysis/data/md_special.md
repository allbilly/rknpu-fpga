| # | A bits | A class | B bits | B class | device | IEEE class | IEEE bits | donor bits | verdict | grid | note |
|---:|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `0x3c00` | norm_p | `0x0000` | zero_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 160) | IEEE divide-by-zero; special-path sign(a) |
| 1 | `0xbc00` | norm_n | `0x0000` | zero_p | `0xfc00` (inf_n) | inf | `0xfc00` | `0xfc00` | match | `0xfc00` (pair 176) | IEEE divide-by-zero; special-path sign(a) |
| 2 | `0x0000` | zero_p | `0x0000` | zero_p | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0xfe00` | nan-class-match-encoding-quirk | `0x7c01` (pair 0) | **QUIRK**: IEEE requires qNaN; 0x7c01 is the sNaN encoding |
| 3 | `0x8000` | zero_n | `0x0000` | zero_p | `0xfc00` (inf_n) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0xfc00` (pair 16) | **QUIRK**: IEEE requires qNaN; zero/zero non-NaN -> sign(a)*inf |
| 4 | `0x7c00` | inf_p | `0x7c00` | inf_p | `0x7c00` (inf_p) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0x7c00` (pair 34) | **QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf |
| 5 | `0xfc00` | inf_n | `0x7c00` | inf_p | `0xfc00` (inf_n) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0xfc00` (pair 50) | **QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf |
| 6 | `0x7c00` | inf_p | `0x3c00` | norm_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 42) | IEEE inf numerator; special-path sign(a) |
| 7 | `0x3c00` | norm_p | `0x7c00` | inf_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 162) | IEEE finite / inf -> zero; special-path sign(a) |
| 8 | `0xbc00` | norm_n | `0x7c00` | inf_p | `0x8000` (zero_n) | zero | `0x8000` | `0x8000` | match | `0x8000` (pair 178) | IEEE finite / inf -> zero; special-path sign(a) |
| 9 | `0x7c00` | inf_p | `0x0000` | zero_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 32) | IEEE inf / zero -> inf; special-path sign(a) |
| 10 | `0x0000` | zero_p | `0x7c00` | inf_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 2) | IEEE zero / inf -> zero; special-path sign(a) |
| 11 | `0x7e00` | qnan | `0x3c00` | norm_p | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0x7e00` | nan-class-match-encoding-quirk | `0x7c01` (pair 74) | **QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear |
| 12 | `0x3c00` | norm_p | `0x7e00` | qnan | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0x7e00` | nan-class-match-encoding-quirk | `0x7c01` (pair 164) | **QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear |
| 13 | `0x3c00` | norm_p | `0x4200` | norm_p | `0x3555` (norm_p) | finite | `0x3555` | `0x3555` | match | — | finite; exact 1/3; 3G model = RNE |
| 14 | `0x4000` | norm_p | `0x4200` | norm_p | `0x3955` (norm_p) | finite | `0x3955` | `0x3955` | match | — | finite; exact 2/3; 3G model = RNE |
| 15 | `0x3c00` | norm_p | `0x4900` | norm_p | `0x2e66` (norm_p) | finite | `0x2e66` | `0x2e66` | match | — | finite; exact 1/10; 3G model = RNE |
| 16 | `0x7bff` | norm_p | `0x4200` | norm_p | `0x7555` (norm_p) | finite | `0x7555` | `0x7555` | match | — | finite; exact 65504/3; 3G model = RNE |
| 17 | `0x0001` | sub_p | `0x4000` | norm_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 110) | exact tie 0.5 ulp -> +0 (ties-to-even) |
| 18 | `0x0400` | norm_p | `0x4000` | norm_p | `0x0200` (sub_p) | finite | `0x0200` | `0x0200` | match | `0x0200` (pair 142) | exact subnormal result 0x0200 |
| 19 | `0x7bff` | norm_p | `0x3c00` | norm_p | `0x7bff` (norm_p) | finite | `0x7bff` | `0x7bff` | match | `0x7bff` (pair 154) | exact quotient |
| 20 | `0x7bff` | norm_p | `0x0400` | norm_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 152) | gross overflow -> +inf |
| 21 | `0x3c00` | norm_p | `0x0001` | sub_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 166) | gross overflow (exact 2^24) -> +inf |
| 22 | `0x0001` | sub_p | `0x7bff` | norm_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 105) | gross underflow -> +0 |
| 23 | `0x8001` | sub_n | `0x4000` | norm_p | `0x8000` (zero_n) | zero | `0x8000` | `0x8000` | match | — | exact negative tie 0.5 ulp -> -0 |
