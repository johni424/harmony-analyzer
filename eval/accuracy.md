# Evaluation — synthetic

Cases: 6 · overall chord accuracy 0.8232

| case | genre | chord | family | root | bass | key | tempo | meter | brier | s/min audio |
|---|---|---|---|---|---|---|---|---|---|---|
| axis_c_major | pop | 0.99 | 0.99 | 0.99 | — | ✓ | ✓ | ✗ | 0.629 | 62 |
| doo_wop_c_major | pop | 1.00 | 1.00 | 1.00 | — | ✓ | ✓ | ✗ | 0.637 | 10 |
| inversions_c_major | classical | 1.00 | 1.00 | 1.00 | 1.00 | ✓ | ✓ | ✗ | 0.639 | 10 |
| sevenths_c_major | jazz | 0.00 | 0.98 | 0.98 | — | ✓ | — | — | 0.026 | 13 |
| minor_loop_e | rock | 0.98 | 0.98 | 0.98 | — | ✓ | ✓ | ✗ | 0.654 | 11 |
| waltz_f_major | folk | 0.97 | 0.97 | 0.97 | — | ✓ | ✓ | ✗ | 0.587 | 12 |

## By genre

| genre | n | chord | family | root | bass | brier |
|---|---|---|---|---|---|---|
| classical | 1 | 0.9965 | 0.9965 | 0.9965 | 0.9953 | 0.639 |
| folk | 1 | 0.9699 | 0.9699 | 0.9699 | — | 0.5872 |
| jazz | 1 | 0.0 | 0.9776 | 0.9776 | — | 0.0259 |
| pop | 2 | 0.9944 | 0.9944 | 0.9944 | — | 0.6332 |
| rock | 1 | 0.9839 | 0.9839 | 0.9839 | — | 0.6542 |

## By musical situation

| situation | chord accuracy |
|---|---|
| fast changes | 0.9699 |
| sevenths | 0.0 |
| slash | 0.9953 |
| triads | 0.9878 |
