# Test Captures

Everything here is real `nvidia-smi` output. Only identifiers are changed, using `scripts/scrub_capture.py`.

| Folder | Card | Driver | System | Captured | Method |
|---|---|---|---|---|---|
| `gtx1660_driver61088_windows` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-06 | `gpudoc inspect --ssh` |
| `gtx1660_driver61088_windows_local` | GTX 1660 6 GB | 610.88 | Windows 11 | 2026-11-07 | `gpudoc inspect` run on the machine, with NVML |

| `gtx1660_driver61088_wsl2` | GTX 1660 6 GB | 610.88 from Windows | Ubuntu 24.04 in WSL2 | 2026-11-07 | `gpudoc inspect` inside WSL, with NVML |

WSL goes through the Windows driver, so it doesn't count as a real Linux test.

## Not yet verified on real output

- Numeric ECC, page retirement, and row remapping values
- `[Not Supported]`, `[Insufficient Permissions]`, and other bracketed error values
- Older field names on older drivers, such as 560.94 on the GTX 1060
- Real Linux output on bare metal
- Multiple GPUs

Add a capture from real hardware before marking any of these as covered. Do not write sample output by hand.
