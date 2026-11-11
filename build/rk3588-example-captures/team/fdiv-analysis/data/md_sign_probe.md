| Case | A class | B class | device | finite-path sign | special-path sign |
|---|---|---|---|---|---|
| finite-numerator / -0 | `one_p` | `zero_n` | `0x7c00` | sign(a)^sign(b) | sign(a) |
| negative finite / -0 | `one_n` | `zero_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite-numerator / -inf | `one_p` | `inf_n` | `0x0000` | sign(a)^sign(b) | sign(a) |
| negative finite / -inf | `one_n` | `inf_n` | `0x8000` | sign(a)^sign(b) | sign(a) |
| -0 / finite-positive | `zero_n` | `one_p` | `0x8000` | sign(a)^sign(b) | sign(a) |
| -0 / finite-negative | `zero_n` | `one_n` | `0x8000` | sign(a)^sign(b) | sign(a) |
| +inf / finite-negative | `inf_p` | `one_n` | `0x7c00` | sign(a)^sign(b) | sign(a) |
| -inf / finite-negative | `inf_n` | `one_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite overflow with - divisor | `fin_max` | `half_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite underflow with - divisor | `sub_min` | `two_n` | `0x8000` | sign(a)^sign(b) | sign(a) |
