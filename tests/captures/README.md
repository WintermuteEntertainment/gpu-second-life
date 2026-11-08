# Test Captures

Everything here is real `nvidia-smi` output. Only identifiers are changed, using `scripts/scrub_capture.py`.

| Folder | Card | Driver | System | Captured | Method |
|---|---|---|---|---|---|
| `gtx1660_driver61088_windows` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-06 | `gpudoc inspect --ssh` |
| `gtx1660_driver61088_windows_local` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-07 | `gpudoc inspect` run on the machine, with NVML |
| `gtx1660_gtx1060_driver58017804_mint` | GTX 1660 6 GB (bus 01) and GTX 1060 6 GB (bus 02) | 580.178.04 | Linux Mint 22.3, bare metal | 2026-11-08 | `gpudoc inspect` run on the machine, with NVML |

| `gtx1660_driver61088_wsl2` | GTX 1660 6 GB | 610.88 from Windows | Ubuntu 24.04 in WSL2 | 2026-11-07 | `gpudoc inspect` inside WSL, with NVML |

WSL goes through the Windows driver, so it doesn't count as a real Linux test.

The `memtest_gtx*` folders hold real `memtest_vulkan` v0.5.0 output and telemetry from 2026-11-06. `memtest_gtx1660_stopped_10s` is the run a script bug ended early. No real failing `memtest_vulkan` log exists yet, so failure-text matching is unverified.

## Not yet verified on real output

- Numeric ECC, page retirement, and row remapping values
- `[Not Supported]`, `[Insufficient Permissions]`, and other bracketed error values
- Older field names on older drivers, such as 560.94 on the GTX 1060
- `memtest_vulkan` output with more than one GPU installed, including its device menu and numbering
- `memtest_vulkan` and `llama-bench` on Linux

Add a capture from real hardware before marking any of these as covered. Do not write sample output by hand.
