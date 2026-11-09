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
- **Committed:** `abf46c3`, GPU selection for `gpudoc test`, the reworded PCIe note, 13 new tests, the scrubbed Mint two-card capture, and notes on the 1060 reseat and first Linux inspect run (2026-11-08).
- **Committed (2026-11-08), the commit after `abf46c3`:** both cards' test results; the thermal rule split; per-card stop limits; kernel log (Xid) reading; interrupt safety on Linux and Windows; the power-cap note; `--gpu all`; `gpudoc sweep` and the first sweep; `scripts/failure_paths_mint.sh` and its results; three Mint memtest captures in `tests/captures/`; notes on network boot, Wake-on-LAN and test hygiene; 65 tests.
- **Uncommitted:** nothing.

## Phase 1: `gpudoc inspect`

Working on the GTX 1660 over SSH, locally on Windows, and in WSL2, with JSON, Markdown, and self-contained HTML reports. Local runs cross-check against NVML.

**First real Linux run, 2026-11-08 17:11 EST:** `gpudoc inspect` ran locally on Mint (Python 3.12.3, driver 580.178.04) and covered both cards. Complete, exit code 0. Every cross-check matched, for `nvidia-smi` query vs XML and vs NVML, on both cards. The ECC and memory-repair fields read `not_available` on both, as expected for consumer cards. Results are in `captures/noodlecart/inspect-20261108-221122-mint` (private, ignored by git). The code is on Mint in `~/gpudoc`.

**Still needed:**
- Done 2026-11-08: the scrubbed Mint capture is in `tests/captures/gtx1660_gtx1060_driver58017804_mint`, with UUIDs removed, and the GPU selection tests use it. No inspect-specific parser tests for it yet.
- Done 2026-11-08: the narrow-link note now gives both widths (for example x4 of x16), says slots, risers and adapters often limit width, and that this alone doesn't point to a fault in the card. A test on the real Mint capture checks it.
- Real numeric ECC values and other bracketed errors. See `tests/captures/README.md`.

## Phase 2: `gpudoc test`

Draft in `src/gpudoc/testing.py`. It runs `memtest_vulkan`, then `llama-bench`, with monitoring, a temperature stop, process-tree stopping, driver comparison, VRAM coverage, energy, and rules. 65 tests pass on PT (Python 3.11.9) and on Mint (Python 3.12.3), 2026-11-08. Rules version `draft-3`.

**Phase 2 exit check met on 2026-11-08:** PLAN section 13 requires real thermal, crash and interruption tests to pass on Noodlecart, and they did. Sensor failure wasn't tested, because doing it without faking would mean breaking `nvidia-smi` mid-run. gpu-burn and DCGM evaluation are still in Phase 2's scope.

**Failure-path tests, GTX 1660 on Mint, 2026-11-08 18:42 to 18:46 EST (23:42 to 23:46 UTC), with Tim's OK:** run by `scripts/failure_paths_mint.sh`. Every run that wrote a result was INCONCLUSIVE, never PASS, and each one confirmed the tool stopped with no leftovers. Results are in `captures/noodlecart/failure-paths-20261108-234232-mint-gtx1660` (private).

| Test | What happened | Result |
|---|---|---|
| 1. Temperature stop, limit 50 C | Stopped at 50 C after 9 samples | INCONCLUSIVE, THM-001 |
| 2. `memtest_vulkan` killed with SIGKILL after 20 s | Seen at the next sample as `tool_exited` | INCONCLUSIVE, RUN-002 |
| 3. GPUDoc sent SIGTERM after 20 s | Tool stopped, result written | INCONCLUSIVE, RUN-012 |
| 4. GPUDoc killed with SIGKILL after 20 s | The kernel stopped `memtest_vulkan` too: 0 left running. No `test.json`; telemetry and tool output remain | No result |
| 5. Power limit at the 70 W minimum, 60 s | Power cap active in 12 of 12 samples, peak 50 C | INCONCLUSIVE (time limit), PWR-001 |

- The power limit was restored to 120 W afterwards and checked.
- The kernel log was read after each run, with no Xid lines.
- Test 4 leaves a run folder with telemetry but no `test.json`. A Phase 3 `gpudoc report` should list such folders as incomplete runs.

**Added 2026-11-08 (Tim's go-ahead for all tests and features):**
- **Kernel log:** after each run on Linux, one `journalctl -k --since <start>` read. It needs no root, because `tim` is in `adm`. Xid events for the tested card's bus give DRV-001 ATTENTION, and Xid 48 gives DRV-004 FAIL. The Xid line format comes from Nvidia's documented form, and no real Xid line has been seen yet, so matching is unverified.
- **Interrupt safety:** SIGINT, SIGTERM or SIGHUP now stops the tool and writes an INCONCLUSIVE result (RUN-012). On Linux the tool is started with `PR_SET_PDEATHSIG`, so it dies if GPUDoc is killed outright. Before this, a killed GPUDoc would have left `memtest_vulkan` stressing the card with nothing watching the temperature.
- **Power cap:** PWR-001 NOTE when the power limit held clocks back. The 1060's real Mint run shows it in 14 of 65 samples.
- **Windows parity:** on Windows the tool is put in a job object that closes when GPUDoc exits, so the tool dies with it. That matches `PR_SET_PDEATHSIG` on Linux. A real-process test passes on both PT (Windows) and Mint. A child the tool starts before the job is assigned could escape; the normal stop still uses `taskkill /T`. RUN-013 NOTE appears if neither guard could be set up. Ctrl+Break (SIGBREAK) is handled like Ctrl+C.
- **`gpudoc test --gpu all`:** tests each card on its own, one after another, each with its own stop limit and folder. It's explicit only, not the default. Checked on Mint up to the YES prompt; not yet run under load.
- **`gpudoc sweep`:** runs memtest_vulkan at each listed power limit. Each step takes 75 s, with a cool-down to 45 C or less first, and the default limit is restored at the end, even after an error or interrupt. It reports memory traffic per watt. It uses `sudo -n` on Linux, and needs an admin shell on Windows (not yet tried on Windows).
- **Tests:** 65 pass on PT and on Mint (2026-11-08).

**First power sweep, GTX 1660 on Mint, 2026-11-09 02:19 UTC (2026-11-08 21:19 EST), with Tim's OK:** results in `captures/noodlecart/sweep-20261109-021909-mint-gtx1660` (private).

| Limit | Avg power | Peak temp | Memory traffic | GB/s per W | Power-capped samples |
|---|---|---|---|---|---|
| 70 W | 69.4 W | 44 C | 299.3 GB/s | 4.313 | 15 of 15 |
| 85 W | 84.0 W | 53 C | 302.6 GB/s | 3.605 | 15 of 15 |
| 100 W | 97.8 W | 58 C | 303.6 GB/s | 3.106 | 15 of 15 |
| 120 W | 105.4 W | 60 C | 303.8 GB/s | 2.883 | 0 of 15 |

- Memory traffic stayed within 1.5% across the whole range while power dropped by 36 W. At 70 W the card gave about 50% more GB/s per watt than at its default limit. At 120 W it never reached the limit: 105 W average, never capped.
- **Hygiene caveat:** start temperatures differed. The 70 W step started at 31 C, the others at 42 to 45 C, so the 70 W step may look slightly better than it would from the same start. Fix: wait for every step to start within a few degrees of a common temperature.
- This is memory-bound work only. The best limit for an AI workload is still unmeasured (Phase 4, llama-bench).

**GPU selection (added 2026-11-08):** `gpudoc test --gpu <index or PCI bus ID>`, such as `--gpu 1` or `--gpu 02:00.0`. It's required when more than one card is installed, and the card is named before the YES prompt.
- Monitoring uses the bus ID (`nvidia-smi --id=00000000:02:00.0`), which was checked on Mint, so it doesn't depend on index order.
- `memtest_vulkan` is given a device number as its first argument. The number assumes its main-branch order (highest PCI bus first), read from its source on GitHub but **not verified on v0.5.0**. If the order is wrong, nothing is trusted to it: the run reads the tool's own "Standard 5-minute test of N: Bus=... DevId=..." line, stops at the next check (up to 5 seconds) if that's a different card, and reports RUN-008 INCONCLUSIVE. With two cards, a run where the tool never names its device can't pass (RUN-009).
- With two cards, it refuses to run `llama-bench`, because its device choice isn't verified (RUN-006).
- Checked on Mint without running a test: with no `--gpu` it refuses and lists both cards; `--gpu 02:00.0` and `--gpu 0` name the right card, then stop at the prompt.
- **First two-card run, GTX 1060, 2026-11-08 17:31 EST (22:31 UTC), with Tim's OK:** `gpudoc test --gpu 02:00.0`, which ran `memtest_vulkan 1`. The tool reported `Bus=0x02:00 DevId=0x1C03`, which is the 1060, so memtest_vulkan's highest-bus-first numbering held on v0.5.0 here.
  - **Result:** ATTENTION overall. The memory test passed: the exact completion line appeared after 4,847 iterations, with no failure text.
  - **Temperature:** 42 C at the first sample, 83 C peak, and 82 C at the end, with fan 45% to 73%. The stop limit was 85 C.
  - **THM-002:** software thermal slowdown appeared in 12 of 65 samples, with no hardware slowdown. The card's own target temperature is 83 C (from `nvidia-smi -q`), so this is the driver holding that target. The rule's "check cooling first" text may overstate it.
  - **Power:** 122 W at the start with the power cap active, and about 106 W later. GPU-only energy was 9.42 Wh.
  - **Memory coverage:** 5,682 of 6,144 MiB, 92.5%.
  - **Stop:** process tree killed and confirmed, no leftovers.
  - **Kernel log:** no Xid lines, checked by hand. Automatic reading was added later the same day.
  - **Output:** with a device number given, stdout has no header or device-list lines, only the "Standard 5-minute test of" line onward; the parser handled it.
  - **Results:** `captures/noodlecart/test-20261108-223132-mint-gtx1060` (private). Run folders on Mint are named in UTC.
- **Second two-card run, GTX 1660, 2026-11-08 17:47 EST (22:47 UTC), with Tim's OK, rules `draft-2`:** `gpudoc test --gpu 01:00.0` ran `memtest_vulkan 2`. The tool reported `Bus=0x01:00 DevId=0x2184`, the 1660, so the device numbering held for both cards.
  - **Result:** PASS. The completion line appeared after 5,533 iterations, with no failure text.
  - **Temperature:** 41 C at the first sample, 63 C peak, fan 38% to 59%, stop limit 86 C. No slowdown flags in any of the 64 samples.
  - **Power:** about 103 to 110 W. GPU-only energy was 9.11 Wh.
  - **Memory coverage:** 5,358 of 6,144 MiB, 87.2%.
  - **Stop:** clean, with no leftovers and no Xid lines.
  - **Before the run:** Tim's xrdp session was ended with `loginctl terminate-session c2`, with his OK, after confirming it was the `xrdp-sesman` session. Closing the RDP window only disconnects; xrdp keeps the session and its VRAM.
  - **Results:** `captures/noodlecart/test-20261108-224743-mint-gtx1660` (private).
- **Rules changed per Tim, 2026-11-08 (rules version `draft-2`):**
  - Hardware thermal slowdown stays THM-002 ATTENTION. Software thermal slowdown is now THM-003 NOTE, stating the peak and the card's target temperature. THM-002 is still unverified on real data, because no capture has hardware slowdown.
  - The stop limit now comes from each card: 5 C below the lower of its slowdown temperature and its "GPU Max Operating Temp" (`gpu_temp_max_gpu_threshold` in the XML, label checked with `nvidia-smi -q` on Mint). That gives 86 C for the 1660 (slowdown 93, max operating 91) and 94 C for the 1060 (slowdown 99, max operating N/A). `--temp-limit` can only lower it. A card reporting no limits gets 85 C. The limit and the card's figures are printed before the YES prompt.
  - Re-scored with `draft-2`, today's 1060 run goes from ATTENTION to PASS, with THM-003 as a NOTE.

**Real result:** both tools passed on the GTX 1660 under Windows on 2026-11-07, in `captures/noodlecart/gpudoc-test-20261107-134957`: about 32.6 tokens/s and about 1,021 tokens per GPU watt-hour.

**Not done:**
- A sensor-failure test that doesn't fake anything.
- GPU selection for `llama-bench`, and `llama-bench` on Linux at all.
- HTML test reports (Phase 3).
- gpu-burn and DCGM evaluation.

**Open questions:**
- Why does `memtest_vulkan` cover less of the 1660's VRAM than the 1060's? On Windows it was 79% vs about 96%; on Mint, same driver, 87.2% vs 92.5%. The 1660 drives the login screen (204 MiB in use before its run), which explains only part of the gap.
- The stop bug's cause is inferred from logs, not fully proven.

## Test machine: Noodlecart

- **Hardware:** i5-9600KF with no integrated graphics, 32 GB RAM, ASRock Z390 Phantom Gaming 4S/ac, 750 W power supply.
- **GPUs:** GTX 1660 in the x16 slot, GTX 1060 in the second slot at x4. Both are Zotac.
- **Windows:** on the 477 GB SATA drive, reached as `Admin@192.168.2.51` by key. Tools are in `C:\gpudoc`. A `gpudoc test` can't run while both cards are in. `nvidia-smi` showed only the 1660 on driver 560.94.
- **Unresolved driver record:** the line above says 560.94, but the 1660 captures and `PLAN.md` section 15 say the 1660 ran on 610.88, and section 15 puts 560.94 on the 1060. Windows Update has changed the driver by itself before. Settle it with one `nvidia-smi` the next time Windows is booted.
- **Linux Mint 22.3:** on the 238 GB USB drive, as host `noodlecart-mint`, reached as `tim@192.168.2.51` by key. `tim` has a password and passwordless `sudo`, which needs tightening later.
- **Boot:** since 2026-11-08, Mint is the default: Tim set the firmware's "UEFI OS" entry for the USB stick first. For Windows, press F11 and choose Windows Boot Manager, or from Mint run `sudo efibootmgr --bootnext 0000 && sudo reboot`.
- **SSH identity:** each OS has its own host key at the same address. In Git Bash use `-o UserKnownHostsFile=/dev/null`. In PowerShell use `NUL`.
- **Mint state:** `nvidia-driver-580` version 580.178.04 was installed on 2026-11-08 and is loaded, running both cards. Before the driver, `nouveau` failed on the 1060 with `gpio: init failed`. Secure Boot was off when checked from Windows.
- **Mint clock:** set to UTC (`Etc/UTC`), 5 hours ahead of Montreal in November. Times in this file read from Mint (21:36, 21:57, 21:59, 22:09) are UTC, which is 16:36 to 17:09 EST. Run folders on Mint are also named in UTC.
- **Boot problem (2026-11-08):** the first reboot into Mint after the driver install stopped at the GRUB command line. Tim says it has happened before. Cause not yet found. Best guess: the signed GRUB, set up by `grub-install --removable` in `scripts/install_mint_to_usb.sh`, can't find or follow its config file on the EFI partition. The EFI partition holds only `EFI/BOOT` (`BOOTX64.EFI`, `grubx64.efi`, `mmx64.efi`, `BOOTX64.CSV`, `grub.cfg`), with no `EFI/ubuntu`. `EFI/BOOT/grub.cfg` is correct: it searches for UUID `7100f9dc-...` (the `mint-gpudoc` partition, `sdb2`) and loads `/boot/grub/grub.cfg`. Theory, unproven: Ubuntu's signed GRUB looks for its config in `EFI/ubuntu`, not `EFI/BOOT`. **Fix applied 2026-11-08 21:57, with Tim's OK:** created `/boot/efi/EFI/ubuntu/grub.cfg`, byte-identical to the `EFI/BOOT` stub. Nothing else changed; deleting that folder undoes it. **Confirmed by Tim, 2026-11-08:** the next boot went straight to the desktop with no `grub>` prompt, so the theory held. If `grub>` appears again, record `echo $prefix`, `echo $cmdpath` and `echo $root`. Manual boot: `search --no-floppy --label mint-gpudoc --set=root`, then `configfile /boot/grub/grub.cfg`.
- **Remote desktop (2026-11-08):** `xrdp` installed on Mint over SSH, enabled at boot, listening on port 3389. Connect from PT with Remote Desktop Connection to `192.168.2.51` as `tim`. `~/.xsession` was created with `xfce4-session`. A `ufw` rule allows 3389 from `192.168.2.0/24`, but `ufw` is inactive, so the port is open to the whole LAN. **First tries failed (2026-11-08 21:59):** login succeeded, then `xfce4-session` quit after 1 second and RDP returned to the login screen. `tim` was also logged in at the monitor (`loginctl`: seat0, tty7), and `~/.xsession-errors` shows the remote session finding that session's SSH and GPG agents already running. Likely cause: Xfce won't start a second session for a user who already has one. **Fix applied 2026-11-08, with Tim's OK:** `~/.xsession` now reads `dbus-launch --exit-with-session xfce4-session`, so the remote desktop gets its own D-Bus. The previous version is saved as `~/.xsession.before-dbus-20261108`. Confirmed working from PT by Tim, 2026-11-08, with `tim` also logged in at the monitor. If it breaks later, the fallback is logging out at the monitor before connecting.
- **Firmware boot entries (read from Mint, 2026-11-08):** `0005` "UEFI OS" (the USB stick's `\EFI\BOOT\BOOTX64.EFI`, created by the firmware), `0000` Windows Boot Manager, `0001` Hard Drive, `0004` USB. BootOrder `0005,0000,0001,0004`, so Mint boots first, which is Tim's choice. One-time boot to Windows from Mint: `sudo efibootmgr --bootnext 0000 && sudo reboot`. Remote reboots into Mint should now be safe, since the GRUB fix held on one boot.
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
5. GPU selection added for `memtest_vulkan` (see Phase 2). **Downloaded 2026-11-08, with Tim's OK:** `memtest_vulkan-v0.5.0_DesktopLinux_X86_64.tar.xz` (272,336 bytes) from the official GitHub release, SHA-256 `0e058c28...117d52` matching GitHub's published digest, extracted to `~/gpudoc/tools/memtest_vulkan-v0.5.0/memtest_vulkan` on Mint. That's an x86-64 ELF binary, not yet run. The archive dates the binary 2022-11-18, while GitHub lists the release as published 2025-09-11; this isn't explained, and the hash still matches. Done: both cards tested on Mint (see Phase 2).
6. VRAM coverage with both cards on driver 580.178.04, Mint: 1060 92.5% (5,682 MiB, 9 MiB in use before), 1660 87.2% (5,358 MiB, 204 MiB in use before by the login screen). The earlier Windows figures were 1660 about 79% (4,831 MiB) and 1060 about 96%. Both cards covered more on Linux, and the gap shrank, but it's still unexplained; see open questions.
7. Done 2026-11-08: failure paths tested on real hardware (see Phase 2). Next proposed: Phase 3, a combined per-card report from inspect plus test runs, which also lists incomplete run folders.
8. Add HTML test reports, then evaluate gpu-burn and DCGM on real Linux.
9. Noodlecart remote control: check the firmware for Wake-on-LAN and "power on after AC loss", and enable Wake-on-LAN. Test the Windows-to-Mint one-time boot (`bcdedit /enum firmware`, then `bcdedit /set {fwbootmgr} bootsequence {id}`) the next time Windows is up. A smart plug for remote hard resets is Tim's call. Network boot is parked in `NOTES.md`.
10. Test hygiene: plan a clean, known Linux image for test runs, and record enough setup in each result (OS image, kernel, driver, power limit, VRAM in use before the run, other GPU processes, start temperature) to refuse comparisons between runs that don't match.

## Related

- **NetMapperPro:** `D:\Repos\netmapperpro`, separate repo, with `HANDOFF.md` and `NETWORK_PLAN.md`.
- **Storage and reminders:** `NOTES.md`.
