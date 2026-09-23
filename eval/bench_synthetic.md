# Benchmark — measured per-analysis resources

`Darwin` · x86_64 · Python 3.12.13 · 4 cores

| case | ok | wall s | cpu s | peak RSS MB | rt× |
|---|---|---|---|---|---|
| import_baseline | ✓ | 0.27 | 0.35 | 25.0 | — |
| axis_c_major | ✓ | 8.08 | 7.53 | 221.7 | 0.762 |
| doo_wop_c_major | ✓ | 6.97 | 6.92 | 225.9 | 0.598 |
| inversions_c_major | ✓ | 7.28 | 7.13 | 229.6 | 0.56 |
| sevenths_c_major | ✓ | 6.7 | 6.59 | 229.6 | 0.744 |
| minor_loop_e | ✓ | 7.4 | 7.19 | 229.6 | 0.761 |
| waltz_f_major | ✓ | 6.68 | 6.23 | 229.6 | 1.375 |

**Per audio-minute:** cpu 46.0 s · peak RSS 229.6 MB · wav 2.6 MB · player 251.6 KB · doc 27.3 KB
