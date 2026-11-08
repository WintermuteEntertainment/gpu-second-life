# Handoff: GPUDoc

**Last updated:** 2026-11-08

**Read first:** this file, then `NOTES.md`, then the relevant parts of `PLAN.md`. `GAPS.md` covers existing tools.

## Rules

- Local git only: no remote, no public release, and nobody gets contacted until Tim says otherwise.
- No invented data, including in tests and examples.
- Remove personal details before anything goes public.
- Tim approves purchases, publishing, deployment, and permanent deletion. Stress tests need his go-ahead.
- Be careful with anything JAZZ-related.
- GPU budget is zero through the end of 2026.
- Power use is a design principle: reduce, reuse, recycle.

## Git state

- **Committed:** `c8669f2`, Phase 1 (2026-11-07).
- **Committed:** `d1bb626`, Phase 2 draft, tests, real test captures, docs, and new scripts (2026-11-08).
- **Committed:** `b12aa4c`, doc corrections to `HANDOFF.md` and `PLAN.md` (2026-11-08).
- **Committed:** `7b40c22`, Noodlecart Mint notes: driver result, 1060 power cable, GRUB fix, xrdp, boot order (2026-11-08).
- **Committed:** GPU selection for `gpudoc test`, the reworded PCIe note, 13 new tests, the scrubbed Mint two-card capture, and notes on the 1060 reseat and first Linux inspect run (2026-11-08), the commit after `7b40c22`.
- **Uncommitted:** nothing.

## Phase 1: `gpudoc inspect`

Working on the GTX 1660 over SSH, locally on Windows, and in WSL2, with JSON, Markdown, and self-contained HTML reports. Local runs cross-check against NVML.

**First real Linux run, 2026-11-08 17:11 EST:** `gpudoc inspect` ran locally on Mint (Python 3.12.3, driver 580.178.04) and covered both cards. Complete, exit code 0. Every cross-check matched, for `nvidia-smi` query vs XML and vs NVML, on both cards. The ECC and memory-repair fields read `not_available` on both, as expected for consumer cards. Results are in `captures/noodlecart/inspect-20261108-221122-mint` (private, ignored by git). The code is on Mint in `~/gpudoc`.

**Still needed:**
- Done 2026-11-08: the scrubbed Mint capture is in `tests/captures/gtx1660_gtx1060_driver58017804_mint`, with UUIDs removed, and the GPU selection tests use it. No inspect-specific parser tests for it yet.
- Done 2026-11-08: the narrow-link note now gives both widths (for example x4 of x16), says slots, risers and adapters often limit width, and that this alone doesn't point to a fault in the card. A test on the real Mint capture checks it.
- Real numeric ECC values and other bracketed errors. See `tests/captures/README.md`.

## Phase 2: `gpudoc test`

Draft in `src/gpudoc/testing.py`. It runs `memtest_vulkan`, then `llama-bench`, with monitoring, a temperature stop, process-tree stopping, driver comparison, VRAM coverage, energy, and rules. 53 tests pass (2026-11-08, Python 3.11.9 on PT).

**GPU selection (added 2026-11-08):** `gpudoc test --gpu <index or PCI bus ID>`, such as `--gpu 1` or `--gpu 02:00.0`. It's required when more than one card is installed, and the card is named before the YES prompt.
- Monitoring uses the bus ID (`nvidia-smi --id=00000000:02:00.0`), which was checked on Mint, so it doesn't depend on index order.
- `memtest_vulkan` is given a device number as its first argument. The number assumes its main-branch order (highest PCI bus first), read from its source on GitHub but **not verified on v0.5.0**. If the order is wrong, nothing is trusted to it: the run reads the tool's own "Standard 5-minute test of N: Bus=... DevId=..." line, stops at the next check (up to 5 seconds) if that's a different card, and reports RUN-008 INCONCLUSIVE. With two cards, a run where the tool never names its device can't pass (RUN-009).
- With two cards, it refuses to run `llama-bench`, because its device choice isn't verified (RUN-006).
- Checked on Mint without running a test: with no `--gpu` it refuses and lists both cards; `--gpu 02:00.0` and `--gpu 0` name the right card, then stop at the prompt.
- Not yet run under load: needs the Linux `memtest_vulkan` binary on Mint and Tim's go-ahead.

**Real result:** both tools passed on the GTX 1660 under Windows on 2026-11-07, in `captures/noodlecart/gpudoc-test-20261107-134957`: about 32.6 tokens/s and about 1,021 tokens per GPU watt-hour.

**Not done:**
- Real hardware tests of failure paths, such as the temperature stop and a killed tool.
- A real two-card `memtest_vulkan` run, to confirm its device numbering. GPU selection for `llama-bench`.
- HTML test reports.
- gpu-burn and DCGM evaluation.

**Open questions:**
- Why does `memtest_vulkan` use only 79% of the 1660's VRAM, but about 96% of the 1060's?
- The stop bug's cause is inferred from logs, not fully proven.

## Test machine: Noodlecart

- **Hardware:** i5-9600KF with no integrated graphics, 32 GB RAM, ASRock Z390 Phantom Gaming 4S/ac, 750 W power supply.
- **GPUs:** GTX 1660 in the x16 slot, GTX 1060 in the second slot at x4. Both are Zotac.
- **Windows:** on the 477 GB SATA drive, reached as `Admin@192.168.2.51` by key. Tools are in `C:\gpudoc`. A `gpudoc test` can't run while both cards are in. `nvidia-smi` showed only the 1660 on driver 560.94.
- **Unresolved driver record:** the line above says 560.94, but the 1660 captures and `PLAN.md` section 15 say the 1660 ran on 610.88, and section 15 puts 560.94 on the 1060. Which driver Windows has now is unknown until a fresh `nvidia-smi` reading.
- **Linux Mint 22.3:** on the 238 GB USB drive, as host `noodlecart-mint`, reached as `tim@192.168.2.51` by key. `tim` has a password and passwordless `sudo`, which needs tightening later.
- **Boot:** since 2026-11-08, Mint is the default: Tim set the firmware's "UEFI OS" entry for the USB stick first. For Windows, press F11 and choose Windows Boot Manager, or from Mint run `sudo efibootmgr --bootnext 0000 && sudo reboot`.
- **SSH identity:** each OS has its own host key at the same address. In Git Bash use `-o UserKnownHostsFile=/dev/null`. In PowerShell use `NUL`.
- **Mint state:** `nvidia-driver-580` version 580.178.04 was installed on 2026-11-08 and is loaded, running both cards. Before the driver, `nouveau` failed on the 1060 with `gpio: init failed`. Secure Boot was off when checked from Windows.
- **Mint clock:** set to UTC (`Etc/UTC`), 5 hours ahead of Montreal in November. Times in this file read from Mint (21:36, 21:57, 21:59, 22:09) are UTC, which is 16:36 to 17:09 EST. Run folders on Mint are also named in UTC.
- **Boot problem (2026-11-08):** the first reboot into Mint after the driver install stopped at the GRUB command line. Tim says it has happened before. Cause not yet found. Best guess: the signed GRUB, set up by `grub-install --removable` in `scripts/install_mint_to_usb.sh`, can't find or follow its config file on the EFI partition. The EFI partition holds only `EFI/BOOT` (`BOOTX64.EFI`, `grubx64.efi`, `mmx64.efi`, `BOOTX64.CSV`, `grub.cfg`), with no `EFI/ubuntu`. `EFI/BOOT/grub.cfg` is correct: it searches for UUID `7100f9dc-...` (the `mint-gpudoc` partition, `sdb2`) and loads `/boot/grub/grub.cfg`. Theory, unproven: Ubuntu's signed GRUB looks for its config in `EFI/ubuntu`, not `EFI/BOOT`. **Fix applied 2026-11-08 21:57, with Tim's OK:** created `/boot/efi/EFI/ubuntu/grub.cfg`, byte-identical to the `EFI/BOOT` stub. Nothing else changed; deleting that folder undoes it. Not yet tested by a reboot. If `grub>` appears again, record `echo $prefix`, `echo $cmdpath` and `echo $root`. Manual boot: `search --no-floppy --label mint-gpudoc --set=root`, then `configfile /boot/grub/grub.cfg`.
- **Remote desktop (2026-11-08):** `xrdp` installed on Mint over SSH, enabled at boot, listening on port 3389. Connect from PT with Remote Desktop Connection to `192.168.2.51` as `tim`. `~/.xsession` was created with `xfce4-session`. A `ufw` rule allows 3389 from `192.168.2.0/24`, but `ufw` is inactive, so the port is open to the whole LAN. **First tries failed (2026-11-08 21:59):** login succeeded, then `xfce4-session` quit after 1 second and RDP returned to the login screen. `tim` was also logged in at the monitor (`loginctl`: seat0, tty7), and `~/.xsession-errors` shows the remote session finding that session's SSH and GPG agents already running. Likely cause: Xfce won't start a second session for a user who already has one. **Fix applied 2026-11-08, with Tim's OK:** `~/.xsession` now reads `dbus-launch --exit-with-session xfce4-session`, so the remote desktop gets its own D-Bus. The previous version is saved as `~/.xsession.before-dbus-20261108`. Confirmed working from PT by Tim, 2026-11-08, with `tim` also logged in at the monitor. If it breaks later, the fallback is logging out at the monitor before connecting.
- **Firmware boot entries (read from Mint, 2026-11-08):** `0005` "UEFI OS" (the USB stick's `\EFI\BOOT\BOOTX64.EFI`, created by the firmware), `0000` Windows Boot Manager, `0001` Hard Drive, `0004` USB. BootOrder `0005,0000,0001,0004`, so Mint boots first, which is Tim's choice. One-time boot to Windows from Mint: `sudo efibootmgr --bootnext 0000 && sudo reboot`. Remote reboots into Mint aren't safe until a reboot confirms the GRUB fix.
- **Riser:** not in use and not proven faulty.
- **Off limits:** PT's RTX 4070, and Taichi's two GTX 1660 Tis, which run the JAZZ RAG.

## Next steps

1. Done: rebooted into Mint, and the driver loads.
2. Done 2026-11-08 21:36: `nvidia-smi` on Mint shows driver 580.178.04, CUDA 13.0, and only the GTX 1660 (bus 01:00.0, 33 C, P8, 594 MiB used by the desktop). The GTX 1060 is missing from `nvidia-smi`, but `lspci` sees it at `02:00.0` (GP106, `10de:1c03`). The `nvidia` module is loaded and `nouveau` is not. Windows also showed only the 1660 with both cards in, while the 1060 worked alone in the top slot on 2026-11-06. **Cause, per Tim, 2026-11-08:** the 1060's PCIe power cable wasn't connected. After that, Tim found the card also wasn't seated properly, and reseated it. That likely also explains the earlier `nouveau` `gpio: init failed` and the 1660-only reading on Windows, though that is an inference.

**Both cards working on Mint, 2026-11-08 22:09** (idle, 1 minute after boot, driver 580.178.04):

| | GTX 1660 | GTX 1060 6GB |
|---|---|---|
| Bus | `01:00.0` | `02:00.0` |
| VBIOS | 90.16.34.00.C9 | 86.06.45.00.C3 |
| PCIe link now / max | Gen 1 x16 / Gen 3 x16 | Gen 1 x4 / Gen 3 x16 |
| Idle temp, power | 33 C, 20.06 W | 34 C, 5.96 W |
| VRAM used | 1,181 MiB of 6,144 | 7 MiB of 6,144 |

- Gen 1 at idle is normal power saving; the link has to be checked under load. x4 on the 1060 matches the board's published x16/x4 split.
- Two Xorg processes use the 1660's VRAM: about 169 MiB for the local desktop and about 977 MiB for the xrdp session. Log out of xrdp, not just close the window, before memory-coverage or power runs on the 1660.
- `dmesg` has no NVRM errors. One `i2c timeout` on the 1660's USB-C controller (`01:00.3`) is probably harmless; not investigated.
3. Done: the 1060 works after its power cable was connected and the card reseated.
4. Done 2026-11-08: GPUDoc copied to Mint and `gpudoc inspect` run there (see Phase 1). Still to do: scrub the capture into `tests/captures/`.
5. GPU selection added for `memtest_vulkan` (see Phase 2). Next, with Tim's go-ahead: download the Linux `memtest_vulkan` v0.5.0 release to Mint, then run `gpudoc test --gpu 02:00.0` (the 1060) and `--gpu 01:00.0` (the 1660), logged out of xrdp first.
6. Compare VRAM coverage with both cards on the same driver.
7. With Tim's go-ahead, test failure paths on real hardware.
8. Add HTML test reports, then evaluate gpu-burn and DCGM on real Linux.

## Related

- **NetMapperPro:** `D:\Repos\netmapperpro`, separate repo, with `HANDOFF.md` and `NETWORK_PLAN.md`.
- **Storage and reminders:** `NOTES.md`.
