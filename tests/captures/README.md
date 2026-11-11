# Test Captures

Everything here is real `nvidia-smi` output. Only identifiers are changed, using `scripts/scrub_capture.py`.

| Folder | Card | Driver | System | Captured | Method |
|---|---|---|---|---|---|
| `gtx1660_driver61088_windows` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-06 | `gpudoc inspect --ssh` |
| `gtx1660_driver61088_windows_local` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-07 | `gpudoc inspect` run on the machine, with NVML |
| `gtx1660_gtx1060_driver58017804_mint` | GTX 1660 6 GB (bus 01) and GTX 1060 6 GB (bus 02) | 580.178.04 | Linux Mint 22.3, bare metal | 2026-11-08 | `gpudoc inspect` run on the machine, with NVML |

| `gtx1660_driver61088_wsl2` | GTX 1660 6 GB | 610.88 from Windows | Ubuntu 24.04 in WSL2 | 2026-11-07 | `gpudoc inspect` inside WSL, with NVML |

WSL goes through the Windows driver, so it doesn't count as a real Linux test.

The `memtest_gtx*_full` and `memtest_gtx1660_stopped_10s` folders hold real `memtest_vulkan` v0.5.0 output and telemetry from 2026-11-06, Windows, one card installed. The `memtest_gtx*_mint_driver58017804` folders are real `gpudoc test` runs on Linux Mint from 2026-11-08, with both cards installed and a device number passed. Their stdout has no header or device list. They hold only `tool_stdout.txt` and `telemetry.jsonl`, which contain no identifiers. `memtest_gtx1660_mint_70W_60s` is the real failure-path power-cap run from the same day: 60 s at the 1660's 70 W minimum. `memtest_gtx1660_stopped_10s` is the run a script bug ended early. No real failing `memtest_vulkan` log exists yet, so failure-text matching is unverified.

Compute tools, all from Noodlecart on Linux Mint with the GTX 1660 Ti (bus 01) and GTX 1060 (bus 02), driver 580.178.04:

- `gtx1660ti_gtx1060_driver58017804_mint`: `gpudoc inspect` raw output from 2026-11-09, UUIDs removed.
- `gpu_burn_gtx1660ti_mint_30s`: a real 30-second gpu-burn run (commit `0d19c94`) on the Ti and the `gpu_burn -l` list, 2026-11-10. UUIDs removed. Carriage returns are kept as the tool wrote them.
- `gpu_burn_gtx1060_mint_300s`: stdout and telemetry from a real `gpudoc test --gpu-burn` run on the 1060, 2026-11-10. UUIDs removed.
- `llama_bench_two_cards_mint`: `llama-bench --list-devices`, one llama-bench run per card with `-dev`, and `nvidia-smi` readings of both cards every 5 s during each run, 2026-11-10. The home folder name in the model path is replaced with `USER`.

- `llama_bench_gtx1660ti_mint_desktop_locked` and `llama_bench_gtx1660ti_mint_desktop_unlocked`: stdout and telemetry from two real `gpudoc test` llama-bench runs on the Ti, 2026-11-11. In the first, Mint's desktop was locked and the card ran at 1,200 MHz with no reason reported. The second ran three minutes after the desktop was unlocked. The home folder name in the model path is replaced with `USER`.

## Not yet verified on real output

- A failing gpu-burn run (result errors or a FAULTY verdict)
- Two installed cards with the same name, for llama-bench and gpu-burn selection

- Numeric ECC, page retirement, and row remapping values
- `[Not Supported]`, `[Insufficient Permissions]`, and other bracketed error values
- Older field names on older drivers, such as 560.94 on the GTX 1060
- `memtest_vulkan`'s interactive device menu (passing a device number skips it)
- A real Nvidia Xid line in the Linux kernel log
- Hardware thermal slowdown (THM-002)

Add a capture from real hardware before marking any of these as covered. Do not write sample output by hand.
