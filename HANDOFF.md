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
- **Committed:** `48cfd80` (2026-11-08): both cards' test results; the thermal rule split; per-card stop limits; kernel log (Xid) reading; interrupt safety on Linux and Windows; the power-cap note; `--gpu all`; `gpudoc sweep` and the first sweep; `scripts/failure_paths_mint.sh` and its results; three Mint memtest captures in `tests/captures/`; notes on network boot, Wake-on-LAN and test hygiene; 65 tests.
- **Committed:** `aaae575`, `.gitattributes` pinning `*.sh` to LF line endings (2026-11-08).
- **Committed:** the commit after `aaae575` (2026-11-09): GRUB fixed by a standard install, the riser fault isolated, the 1660 Ti from Taichi inspected and memtested, and Taichi's Tailscale set to unattended.
- **Uncommitted:** nothing.

## Phase 1: `gpudoc inspect`

Working on the GTX 1660 over SSH, locally on Windows, and in WSL2, with JSON, Markdown, and self-contained HTML reports. Local runs cross-check against NVML.

**First real Linux run, 2026-11-08 17:11 EST:** `gpudoc inspect` ran locally on Mint (Python 3.12.3, driver 580.178.04) and covered both cards. Complete, exit code 0. Every cross-check matched, for `nvidia-smi` query vs XML and vs NVML, on both cards. The ECC and memory-repair fields read `not_available` on both, as expected for consumer cards. Results are in `captures/noodlecart/inspect-20261108-221122-mint` (private, ignored by git). The code is on Mint in `~/gpudoc`.

**Still needed:**
- Done 2026-11-08: the scrubbed Mint capture is in `tests/captures/gtx1660_gtx1060_driver58017804_mint`, with UUIDs removed, and the GPU selection tests use it. No inspect-specific parser tests for it yet.
- Done 2026-11-08: the narrow-link note now gives both widths (for example x4 of x16), says slots, risers and adapters often limit width, and that this alone doesn't point to a fault in the card. A test on the real Mint capture checks it.
- Real numeric ECC values and other bracketed errors. See `tests/captures/README.md`.

## New adapters, research 2026-11-11 (Tim asked for DCGM, gpu-fryer, Wattever and LocalScore)

From the tools' own docs and source, read from PT; nothing installed yet. gpu-burn stays the default compute test.

- **DCGM `dcgmi diag` 4.7.1:** GeForce cards from Maxwell on are supported, but only **level 1**, a quick deployment check, not a stress test. Package `datacenter-gpu-manager-4-cuda12` (Nvidia says driver-580 systems with Pascal cards use the CUDA 12 build) from Nvidia's CUDA apt repo, which needs adding with `cuda-keyring`. Runs through the `nvidia-dcgm` service (`nv-hostengine`) and needs root. `-i` picks GPUs by DCGM's own ID (mapping to bus IDs via `dcgmi discovery -l`), `-j` gives JSON with a `test_summary.status`. Its deployment check fails if a graphics process runs on the card, which affects the Ti while a desktop is up.
- **gpu-fryer 1.1.0 (Apache-2.0, Hugging Face):** installed with `cargo install gpu-fryer`; no release binary. Uses cuBLAS. No GPU selection flag; it tests every card and compares them. `CUDA_VISIBLE_DEVICES` should limit it to one card (unverified). Plain-text output with per-card Gflop/s, temperature and throttle flags, then "All GPUs seem healthy". Failure text and exit code not documented. Pascal support depends on the CUDA build; unverified.
- **Wattever 2.6.1 (MIT, 2026-11-06):** doesn't run models itself. It benchmarks an OpenAI-compatible endpoint, such as `llama-server` from the llama.cpp build already on Mint, through a local web page. Results are one JSON file per run in `results/runs/`, schema version 2, without GPU UUIDs, serials, usernames or hostnames. GPU power comes from `nvidia-smi`. Plan from PLAN.md stands: import its JSON. Whether it can run without the web page is unknown.
- **LocalScore 0.9.3 (CLI MIT):** a single binary from `blob.localscore.ai`, run as `localscore -m model.gguf`. Its reference models are Llama 3.2 1B (Tiny), an 8B and a 14B. **It asks before uploading to the public localscore.ai database by default.** `-n` / `--no-send-results` skips the upload; `-y` uploads without asking and must never be used. Passing both keeps whichever comes last, a bug in its check. With several cards it loops asking which one unless `-i` is given. `-o json` prints JSON mixed with other text. GPUDoc must always pass `-n` and `-i`, and the first run should be done with outbound network blocked to prove nothing is sent.

### Installed on Mint and built into GPUDoc, 2026-11-11 to 12

All four installed with Tim's go-ahead ("Build the DCGM anyway ... add gpu-fryer too. Add Wattever too. We def. want LocalScore, too."). Hashes are in the install logs in `~/gpudoc` on Mint.

- **DCGM 4.8.0:** `datacenter-gpu-manager-4-cuda12` and `-cuda13` from Nvidia's CUDA apt repo (keyring `cuda-keyring_1.1-1_all.deb`, SHA-256 `d2a6b11c...a06dba`), about 2 GB downloaded and 10 GB on disk. The `nvidia-dcgm` service is enabled and running. **Driver safety:** the keyring package installs its own `cuda-repository-pin-600`, which ranked Nvidia's repo above Ubuntu's and would have let `apt upgrade` replace the driver with 580.196.07. `/etc/apt/preferences.d/00-gpudoc-nvidia-repo-dcgm-only` (sorted first) now limits that repo to `datacenter-gpu-manager*`; `apt-cache policy` confirms the driver stays at 580.178.04. One package from Nvidia's repo was already pulled in as a dependency before the fix: `libxnvctrl0` 620.70.06, replacing nothing (it wasn't installed). The Turing card needs the CUDA 13 plugin package; without it DCGM fails with a missing-plugin error. DCGM also needs persistence mode on (both cards had it off, and `nvidia-persistenced` runs without enabling it), so the adapter turns it on for the run and back off afterwards.
- **gpu-fryer 1.0.0:** the only version on crates.io (the README's Docker tag says 1.1.0). Built with a current Rust toolchain from rustup in `~/.cargo` (Mint's own Rust 1.75 is too old), in `~/gpudoc/tools/gpu-fryer-1.0.0`. It has no card option, so the adapter sets `CUDA_VISIBLE_DEVICES`; it prints the card's UUID, which GPUDoc checks. **It hangs after printing "All GPUs seem healthy"** and never exits by itself; GPUDoc stops it once that line appears. It doesn't check its results, so it's a load and throttling test, not an error test.
- **Wattever 2.6.1:** in `~/gpudoc/tools/wattever-2.6.1` (zip SHA-256 `c9dec5f9...eb7fbe`). `src/gpudoc/wattever_run.py` starts `llama-server` (llama.cpp b12177 Vulkan) on the selected card, starts Wattever with no browser, sends one benchmark through its local API, and shuts both down. Its result file records the motherboard, firmware and storage models, but no UUIDs, serials, usernames or hostnames. **Open:** Wattever labels runs "interrupted" with 4 tests remaining, although all 4 tests GPUDoc asked for completed OK; the source of the extra 4 is unknown.
- **LocalScore 0.9.3:** binary (380,479,144 bytes, SHA-256 `19348450...47c397`) in `~/gpudoc/tools/localscore-0.9.3`, model `Llama-3.2-1B-Instruct-Q4_K_M.gguf` (807,694,464 bytes, SHA-256 matching bartowski's Hugging Face upload) in `~/gpudoc/models`. Whether this exact file is LocalScore's official Tiny model is unconfirmed; its pages name only the file name. GPUDoc always passes `-n` and runs it with `sudo -n unshare -n`, a network namespace with no network; checked by a failed lookup of `www.localscore.ai` inside it. Both runs printed "Results Not Submitted."
- **LocalScore's 1660 Ti result is abnormal:** 37.1 generation tokens/s against 71.8 on the 1060, the reverse of every other tool. The Ti held 1,890 to 1,920 MHz but drew only 55 to 67 W; the 1060 drew 105 to 116 W. Best guess, unverified: LocalScore's bundled CUDA build (runtime 12.8) runs poorly on the GTX 16 series. Don't use LocalScore figures for the Ti until this is explained.
- **New rules (draft-7):** DCG-001 (ATTENTION) for a DCGM test that isn't Pass or Skip, DCG-002 (NOTE) for a skipped test, CMP-002 (ATTENTION) for gpu-fryer throttling or no healthy verdict, RUN-016 (INCONCLUSIVE) for a tool error. 106 tests pass on PT and Mint.

### First run of all six adapters through GPUDoc, Mint, 2026-11-12 01:50 to 02:34 UTC

`gpudoc test --gpu all` with DCGM, gpu-burn (300 s), gpu-fryer (300 s), llama-bench, LocalScore and Wattever, each card in turn, nobody logged in at the monitor. Results in `captures/noodlecart/all-adapters-20261112-015023-mint` (private).

**The saved states are wrong.** Every step after DCGM is recorded as INCONCLUSIVE with RUN-001 ("could not be confirmed stopped"). That was a GPUDoc bug, not leftovers: the new full-command-line leftover check matched the shell that launched the run, whose command line named every tool. Each flagged step counted exactly one leftover, and a check after the run found no tools running. Fixed the same night by skipping GPUDoc's own chain of parent processes, with a real-process test; 106 tests pass on PT and Mint. Apart from RUN-001, every step had only NOTE findings: no FAIL, no ATTENTION, no other INCONCLUSIVE. All steps ran at stock clocks with no driver errors, and memory use rose only on the selected card.

| Step | GTX 1660 Ti | GTX 1060 |
|---|---|---|
| DCGM level 1 | PASS | PASS |
| gpu-burn | 4,726 Gflop/s, 118.7 W, 77 C | 2,988 Gflop/s, 103.4 W, 82 C |
| gpu-fryer | 4,763 Gflop/s, 118.5 W, 77 C, no throttling | 3,116 Gflop/s, 99.0 W, 82 C, driver temperature control (THM-003) |
| llama-bench, Qwen2.5 7B | 41.2 generation, 418.6 prompt tokens/s | 27.1 generation, 178.5 prompt tokens/s |
| LocalScore, Llama 3.2 1B | 36.8 generation tokens/s at 67.9 W (abnormal, see above) | 70.3 generation tokens/s at 102.5 W |
| Wattever, Qwen2.5 7B, 512-token prompt | 39.6 generation tokens/s | 26.1 generation tokens/s |

- gpu-burn and gpu-fryer agree within 1% on the Ti and 4% on the 1060.
- llama-bench and Wattever agree within 4% on both cards, from two different tools and engines (llama-bench direct, Wattever through `llama-server`).
- LocalScore's Ti figure is the odd one out again, at the same low power as its first run. Its 1060 figure isn't comparable with the others, because it uses a 1B model.
- **Clean rerun, 2026-11-12 04:51 to 05:35 UTC, same script, fixed leftover check:** all 12 steps PASS, both cards PASS overall, no leftovers, no driver errors, all at stock clocks, memory rising only on the selected card. Results in `captures/noodlecart/all-adapters-20261112-045134-mint` (private). Figures matched the first run within 3%: Ti gpu-burn 4,729 Gflop/s, gpu-fryer 4,767, llama-bench 41.5 tokens/s, Wattever 40.0, LocalScore 36.7 (again at low power, 65.9 W); 1060 gpu-burn 3,028, gpu-fryer 3,116, llama-bench 27.1, Wattever 26.1, LocalScore 70.4. Wattever's prompt speed on the 1060 moved most, 142.2 to 170.1 tokens/s.

## Phase 2: `gpudoc test`

Draft in `src/gpudoc/testing.py`. It runs `memtest_vulkan` (memory), `gpu-burn` (compute, Linux only) and `llama-bench` (AI workload), each optional, with monitoring, a temperature stop, process-tree stopping, driver comparison, VRAM coverage, energy, and rules. 106 tests pass on PT (Python 3.11.9) and on Mint (Python 3.12.3), 2026-11-12. Rules version `draft-7`. Adapters: memtest_vulkan, gpu-burn, gpu-fryer, DCGM, llama-bench, LocalScore and Wattever. `gpudoc tune` is a separate command; see the Noodlecart section.

**Compute adapters, added 2026-11-10:**
- **Flags:** `--tool-path` (memtest_vulkan) is now optional. `--gpu-burn PATH` with `--burn-seconds` (default 300) adds gpu-burn. `--llama-bench` with `--model` adds llama-bench. At least one tool is required.
- **Card selection:** each adapter works out its own device for the selected card, or refuses (RUN-006). gpu-burn runs with `CUDA_DEVICE_ORDER=PCI_BUS_ID` and `-i N`, where N is the card's rank by bus, and its `-l` list must show the selected card's name at N. llama-bench matches the card's name in `--list-devices` and passes `-dev`; two cards with the same name are refused, because that list has no bus IDs.
- **Proof of the card used:** neither tool names its card by bus, so GPUDoc reads memory use on every card every 5 s. Another card rising 512 MiB or more stops the run (`wrong_device`, RUN-014). The selected card rising less than that gives RUN-015. Unreadable memory gives RUN-009. llama-bench's reported `devices` value must also match (RUN-008). Each `test.json` records `memory_rise_mib` per card.
- **Rules:** gpu-burn result errors or a FAULTY verdict give CMP-001 FAIL; that match is unverified, because no real failing gpu-burn output exists. The VRAM coverage note (MEM-002) now applies to memory tests only.
- **Windows:** gpu-burn has no Windows build, so the compute stress test is Linux only for now. PLAN section 6 names a sustained llama.cpp run as the Windows stand-in; not built.
- **Not tested:** killing GPUDoc outright during gpu-burn. gpu-burn starts child processes, and the Linux guard only covers the direct child, so leftovers are possible. gpu-burn does end by itself after its set time.

**First compute run through GPUDoc, Mint, 2026-11-10 23:54 to 2026-11-11 00:08 UTC, both cards in turn (`--gpu all`), Tim's go-ahead:** all four steps PASS. Results in `captures/noodlecart/compute-20261110-235403-mint` (private).

| Card | Tool | Result | Speed | Peak temp | Avg power under load | Notes |
|---|---|---|---|---|---|---|
| GTX 1660 Ti | gpu-burn 300 s | PASS | 4,462 Gflop/s, 44.1 per watt | 75 C | about 101 W | No slowdown flags |
| GTX 1660 Ti | llama-bench | PASS | 306.1 prompt, 30.6 generation tokens/s | 59 C | about 65 W | See open question below |
| GTX 1060 | gpu-burn 300 s | PASS | 2,999 Gflop/s, 29.0 per watt | 82 C | about 103 W | Power cap in 24 of 67 samples, software thermal slowdown in 29 |
| GTX 1060 | llama-bench | PASS | 179.4 prompt, 27.2 generation tokens/s | 73 C | about 108 W | Power cap in 3 of 9 samples |

- **Caveat on the Ti rows above:** they were taken with Mint's desktop locked, which capped the Ti at 1,200 MHz (found on 2026-11-11, see below). The PASS results stand, but the Ti's speed and energy figures in this table aren't comparable with unlocked runs. The same caveat is in `CAVEAT.md` in the run's folder. The 1060 rows are unaffected as far as known.
- **Card proof held:** memory rose 4,695 MiB (gpu-burn) and 4,544 MiB (llama) on the Ti with 2 and 0 MiB on the 1060, then 5,454 and 4,540 MiB on the 1060 with 3 and 10 MiB on the Ti.
- **Clean:** no Xid lines, no leftovers, Linux guard active on all four steps.
- **Open question, 1660 Ti speed:** in this run the Ti drew less power and ran slower than in the standalone checks about 30 minutes earlier, with no slowdown flag active in any sample. llama-bench: 30.6 generation tokens/s at about 65 W on average (steady readings near 70 W), against 41.3 with a 118 W peak. gpu-burn: 4,462 Gflop/s at about 101 W, against about 4,860 at about 120 W on 2026-11-09. Its power limit reads 120 W (the default). The 1060's figures barely moved (27.2 against 27.4). Cause unknown. Known differences: llama-bench ran 60 s after a 5-minute gpu-burn, and a desktop session was logged in at the monitor (two Xorg processes on the Ti). Until this is explained, don't compare the Ti's speed figures between runs. GPUDoc doesn't yet record clock speeds or the full slowdown-reason value, which would help here.
- **Follow-up, 2026-11-11 06:55 to 07:05 UTC, Ti only, fresh boot, nobody logged in at the monitor:** the slowdown did not come back, and gpu-burn beforehand is ruled out as its cause. Results in `captures/noodlecart/ti-slowdown-20261111-mint` (private).

  | Step | Speed | Avg power under load | Avg GPU clock under load | Peak temp |
  |---|---|---|---|---|
  | llama-bench, cold | 42.4 generation tokens/s | 100.8 W | 1,842 MHz | 55 C |
  | gpu-burn 300 s | 4,736 Gflop/s | 117.8 W | 1,642 MHz | 77 C |
  | llama-bench, 60 s after gpu-burn | 41.5 generation tokens/s | 102.9 W | 1,803 MHz | 68 C |

  In the slow run the Ti drew about 101 W in gpu-burn with the power cap never active; here it drew 117.8 W with the cap active in 60 of 66 samples. So in the slow run something held the card below its power limit without setting any slowdown flag GPUDoc read. The one known difference left is that `tim` was logged in to a desktop at the monitor during the slow run. Untested; it needs Tim logged in at the monitor for a rerun. Telemetry now records `clock_gpu`, `clock_mem` and `slowdown_reasons` (the full reasons value), and the summary gives average power and GPU clock under load, so a repeat would show up in the data.
- **Slowdown reproduced, 2026-11-11 07:10 to 07:20 UTC, Tim logged in at the monitor:** llama-bench at the start ran at full speed (41.8 tokens/s, 1,826 MHz), and so did gpu-burn (4,730 Gflop/s, 118.9 W). The llama-bench after it was slow: 30.3 tokens/s, 67.0 W, GPU clock at exactly 1,200 MHz in every loaded sample, with the reasons value at `0x1` (no slowdown reason given). Tim logged in at about 07:10; the lock screen started at 07:20:09 per the journal (`light-locker`, X screensaver timeout 600 s), within seconds of that llama-bench starting. Afterwards `loginctl` showed Tim's session `c2` as `online` (not active) with a `lightdm` greeter session active, the same state seen after the first slow run.
- **Monitor power is not the cause, 16:03 to 16:06 UTC:** with the screen still locked, llama-bench ran slow with the monitor reported Off (30.7 tokens/s, 1,200 MHz), and stayed slow after `xset dpms force on` reported it On (30.6 tokens/s, 1,200 MHz).
- **Where this stands:** every slow run happened with the desktop locked (the session switched away to the greeter), and every fast run happened before any lock: right after boot, or within 10 minutes of login. Under the lock, the Ti, which drives the monitor, runs capped at 1,200 MHz with no reason reported. **Confirmed 16:09 UTC:** Tim unlocked the desktop at 16:07:30, and llama-bench at 16:09 ran at full speed again (41.5 tokens/s, 1,836 MHz, 100.3 W), three minutes after the last slow run (30.6 tokens/s at 16:05), with nothing else changed. So the lock state switches the cap on and off. The mechanism is unknown. The 1060 doesn't drive a display and wasn't affected in the first slow run. Runs are in `captures/noodlecart/ti-slowdown-20261111-mint` (private).
- **Consequence for test hygiene:** on a machine with a desktop, a lock or screensaver can cut a display card's speed by about 27% without any slowdown flag. For every future run, record whether the desktop was locked, and don't compare speed figures across lock states.
- **Tim's view (2026-11-11):** a clock cap while the monitor is off is usually fine, and is probably an energy-saving setting, possibly in the firmware. Unverified. Screen locking on Mint was left on.
- **GPUDoc now flags it (rules `draft-5`):** CLK-001, a NOTE, appears when the GPU clock is exactly the same in every loaded sample (three or more) and no thermal or power-cap flag is active. The summary gives `pinned_gpu_clock_mhz`. It's a NOTE because a card can also sit at one clock when nothing limits it, and GPUDoc can't tell the two apart: the driver gave no maximum clock on these cards. Tested on the real locked run (flagged, 1,200 MHz) and the real unlocked run (not flagged). 83 tests pass on PT and Mint.
- **Restart from Windows, tested 2026-11-11:** a plain `shutdown /r` from Windows came back up in Mint.
- **Overclocking, read-only check on Mint, 2026-11-11 (planned "tune" feature, see NOTES):** Nvidia's library (NVML, `libnvidia-ml.so.1`, driver 580.178.04) reports clock offsets for both cards, with no desktop option needed. Nothing was changed.

  | | GTX 1660 Ti | GTX 1060 |
  |---|---|---|
  | GPU clock offset now | 0 MHz | 0 MHz |
  | GPU clock offset range | -1000 to +1000 MHz | -200 to +1200 MHz |
  | Memory clock offset now | 0 MHz | 0 MHz |
  | Memory clock offset range | -2000 to +6000 MHz | -2000 to +2000 MHz |
  | Max GPU clock (`nvmlDeviceGetMaxClockInfo`) | 2,100 MHz | 1,911 MHz |
  | Max memory clock | 6,001 MHz | 4,004 MHz |

  - The ranges are what the driver accepts, not what is stable. Real stable offsets are usually a small part of them.
  - **Set test, 2026-11-11, with Tim's OK:** `nvmlDeviceSetGpcClkVfOffset(+25)` on the Ti. As `tim` it returned Insufficient Permissions and changed nothing. As root it returned ok, read back as 25 MHz, and restoring 0 returned ok. Both cards read 0 MHz afterwards, and no driver errors were logged. So setting works on Linux and needs root, like the power limit. The card was idle; no load ran at +25.
  - **Untested:** whether the offset changes real speed under load, the memory offset call (`nvmlDeviceSetMemClkVfOffset`), whether an offset survives a reboot or driver reload, and whether the same calls work on Windows with 581.80.
  - `nvidia-settings` isn't installed on Mint and no Coolbits option is set. Neither is needed if the library route works.
  - **Useful for CLK-001:** the library does give a maximum GPU clock, which `nvidia-smi` showed as N/A. The Ti's locked-desktop cap of 1,200 MHz against a 2,100 MHz maximum could let the finding tell a real cap from a card at its top speed. Not built.
  - **Built 2026-11-11, `gpudoc tune` (draft):** `src/gpudoc/clocks.py` reads and sets GPU and memory clock offsets by PCI bus ID; `src/gpudoc/tune.py` steps the GPU clock offset up (default 25 MHz steps to +150), runs a stress tool at each step (`--gpu-burn` on Linux, or `--tool-path` for memtest_vulkan on either system), stops at the first problem, confirms the highest passing step with a longer run, and returns the card to stock in a `finally` block. `gpudoc tune --reset` only returns a card to stock. It refuses to start on a card that already has an offset. Memory clock tuning isn't built; the setter is.
  - **Every `gpudoc test` result is now stamped (rules `draft-6`):** `clock_offsets` and `stock_settings` in `test.json`, with SET-001 (a NOTE) when either offset isn't zero and SET-002 when they couldn't be read.
  - **Windows uses a different call:** on 581.80 the older `VfOffset` calls answer Not Supported, but `nvmlDeviceGetClockOffsets` / `nvmlDeviceSetClockOffsets` work, with the same ranges as Linux. Setting performance state P0 moved P1, P2, P3, P5 and P8 together. `clocks.py` tries the newer pair first and falls back to the older one. Tested on Windows on the Ti: GPU +25 MHz and memory +50 MHz each set, read back and reset; `tune --reset` works. The newer pair is untested on Linux.
  - **First tune run, Windows, Ti, memtest_vulkan, 2026-11-11 17:01 local:** stock 439.8 GB/s, +25 MHz 439.2 GB/s, +50 MHz 446.7 GB/s (+1.6%), all three clean over 60 s at about 119 W. The +75 MHz step then died with `ERROR_DEVICE_LOST`. **That failure is not evidence about the overclock:** Windows Update started installing Nvidia driver 610.88 at 17:08:56 and finished at 17:12:03, replacing the driver under the running test. Results in `captures/noodlecart/tune-20261111-170104-windows-gtx1660ti` (private). The run is invalid from the +75 step on, and nothing was confirmed.
  - **Windows is back in the broken driver state (17:17 local):** the Ti is on 610.88, and the 1060 shows device error 31 (`CM_PROB_FAILED_ADD`) because 610.88 doesn't include it. `nvidia-smi` lists only the Ti. The Ti's offsets read 0. To fix: stop Windows Update from replacing drivers (Tim's call, a system setting), then reinstall 581.80 from `C:\gpudoc\downloads\nvidia-581.80`.
  - **GPUDoc gaps this exposed:** the step was scored FAIL by MEM-001 on the tool's error text, which would wrongly fail a healthy card in a health test when the real cause is a driver swap. A driver change or a missing card during a run should make the result INCONCLUSIVE, ahead of failure text. The Windows driver log count was 0 despite the driver being replaced, so that check missed it. After the swap, the restore step couldn't write (Not Supported), and tune correctly reported "returned to stock: NO"; a later read showed 0.
  - **Windows Update driver delivery turned off by Tim, 2026-11-11:** `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\ExcludeWUDriversInQualityUpdate` = 1, confirmed by reading it back. It affects all drivers; deleting the value undoes it. A reinstall of 581.80 right after returned exit code 1 with a restart pending from Windows Update's own install; Windows was restarted (it came back in Mint, as expected). **581.80 still needs reinstalling** the next time Windows is booted; until then the Ti is on 610.88 and the 1060 has no working driver there.
  - **Memory offset on Linux, 2026-11-11 17:24 UTC:** the newer `ClockOffsets` calls also work on Mint 580.178.04, so both systems now use them. Memory +50 MHz on the Ti: refused as `tim` (Insufficient Permissions), set as root, read back 50 (the reported maximum memory clock moved from 6,001 to 6,026 MHz), and `gpudoc tune --reset` returned it to 0.
  - **First full tune, Mint, Ti, gpu-burn, 2026-11-11 17:28 to 18:02 UTC, nobody logged in at the monitor:** every step passed.

    | GPU clock offset | Speed | vs stock | Avg power | Gflop/s per W | Avg clock | Peak temp |
    |---|---|---|---|---|---|---|
    | Stock | 4,834 Gflop/s | | 119.4 W | 40.5 | 1,679 MHz | 72 C |
    | +25 MHz | 4,774 | -1.2% | 119.4 W | 40.0 | 1,667 MHz | 75 C |
    | +50 MHz | 4,868 | +0.7% | 118.7 W | 41.0 | 1,695 MHz | 75 C |
    | +75 MHz | 4,914 | +1.7% | 119.0 W | 41.3 | 1,711 MHz | 74 C |
    | +100 MHz | 4,934 | +2.1% | 118.2 W | 41.7 | 1,722 MHz | 75 C |
    | +125 MHz | 5,000 | +3.4% | 119.0 W | 42.0 | 1,740 MHz | 75 C |
    | +150 MHz | 5,038 | +4.2% | 119.5 W | 42.2 | 1,760 MHz | 75 C |
    | +150 MHz, 300 s confirm | 4,991 | +3.2% | 118.8 W | 42.0 | 1,732 MHz | 78 C |

    - The card sits at its 120 W power limit throughout, so a higher offset buys clock only where the power budget allows. Gains are small, about 3 to 4%, and the +25 MHz step came out slower than stock, which shows the run-to-run spread is around 1 to 2%. Treat differences below that as noise.
    - Every step up to the default +150 MHz ceiling passed, so the card's real limit wasn't found. A higher ceiling would find it, at a higher risk of a driver crash.
    - The card was returned to stock (both offsets read 0 afterwards), and the kernel log showed no Xid lines.
    - Results in `captures/noodlecart/tune-20261111-172819-mint-gtx1660ti` (private). Trimmed copies of both tune runs are test captures in `tests/captures/tune_gtx1660ti`; 89 tests pass.
  - **High-ceiling tune, Mint, Ti, gpu-burn, 2026-11-11 21:57 to 22:38 UTC, Tim's call to raise the ceiling and accept the risk:** 25 MHz steps up to +500 MHz. Every step to +200 MHz passed. **At +225 MHz gpu-burn found wrong results**: 144 errors within about 3 seconds, at 1,830 MHz. The driver didn't crash and the machine stayed up; the card computed wrong answers without any other sign. +200 MHz then passed the 300 s confirmation at 5,057 Gflop/s, **+4.2% over stock**, 1,760 MHz average, 77 C peak, 118.5 W. Card returned to stock; both offsets read 0 afterwards.
    - **Verdict for the Ti:** stable limit between +200 and +225 MHz in gpu-burn. Recommended everyday setting would be below +200, to leave margin; not tested. The gain is small because the card sits at its 120 W power limit.
    - **Why gpu-burn matters here:** a crash is easy to notice, but wrong results are silent. This is exactly what a self-checking stress tool exists to catch.
    - Results in `captures/noodlecart/tune-20261111-215755-mint-gtx1660ti-high` (private). The tune report now shows "not valid" for a failed step's speed, because that figure counts wrong results too; the first version showed it as +8.9%.
  - **Still untested:** whether an offset survives a reboot, tune on the 1060, and a Windows tune rerun on a stable driver.
  - **Tim's direction:** keep overclocked results clearly apart from stock ones. Most people want maximum performance; miners and similar users value efficiency more. So the feature should find both points.

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
- Done 2026-11-10: GPU selection for `llama-bench`, `llama-bench` on Linux, and the gpu-burn adapter.
- HTML test reports (Phase 3).
- DCGM evaluation.
- A compute stress test on Windows.
- Recording clock speeds and the full slowdown-reason value in telemetry.
- A kill test of GPUDoc during gpu-burn.

**Open questions:**
- Why does `memtest_vulkan` cover less of the 1660's VRAM than the 1060's? On Windows it was 79% vs about 96%; on Mint, same driver, 87.2% vs 92.5%. The 1660 drives the login screen (204 MiB in use before its run), which explains only part of the gap.
- The stop bug's cause is inferred from logs, not fully proven.

## Test machine: Noodlecart

- **Hardware:** i5-9600KF with no integrated graphics, 32 GB RAM, ASRock Z390 Phantom Gaming 4S/ac, 750 W power supply.
- **GPUs:** GTX 1660 in the x16 slot, GTX 1060 in the second slot at x4. Both are Zotac.
- **Windows:** on the 477 GB SATA drive, reached as `Admin@192.168.2.51` by key. Tools are in `C:\gpudoc`. A `gpudoc test` can't run while both cards are in. `nvidia-smi` showed only the 1660 on driver 560.94.
- **Unresolved driver record:** the line above says 560.94, but the 1660 captures and `PLAN.md` section 15 say the 1660 ran on 610.88, and section 15 puts 560.94 on the 1060. Windows Update has changed the driver by itself before. Settle it with one `nvidia-smi` the next time Windows is booted.
- **Driver record explained (read from Windows, 2026-11-11 06:08 UTC):** Windows holds three Nvidia driver packages at once: 560.94 (`32.0.15.6094`), 591.86 (`32.0.15.9186`) and 610.88 (`32.0.16.1088`). The installed-programs list says 610.88. The 1060 runs on 560.94, because drivers after the 580 branch don't include Pascal cards. So the earlier records were both right: each card was on a different driver. With the 1660 Ti and 1060 installed together, only the 1060 works: `nvidia-smi` and llama-bench see it alone, and the Ti shows `CM_PROB_REINSTALL` against the 591.86 package. Nvidia's lists (checked 2026-11-11): the newest Windows driver naming both the GTX 1060 and GTX 1660 Ti is Game Ready 581.80 (2025-11-04, 896.54 MB). The later 582.x security drivers (newest 582.78, 2026-09-30) list the 10 series and older only. 
- **Driver 581.80 installed on Windows, 2026-11-11 06:16 to 06:25 UTC, Tim's choice:** downloaded from `us.download.nvidia.com` to `C:\gpudoc\downloads\nvidia-581.80` (896,544,928 bytes, SHA-256 `0A08462764F4D36EEECB8DA6ABFC01A6E32C94359B9E1E3287399F057C1D2839`). Authenticode signature valid, signed by NVIDIA Corporation. Silent clean install (`-s -clean -noreboot -noeula`), exit code 0. Both cards now report 581.80 with no device errors: the 1660 Ti at `01:00.0` and the 1060 at `02:00.0`. Windows wasn't rebooted afterwards. The full package also installed the NVIDIA App, its containers, telemetry client, ShadowPlay and audio drivers, which weren't there before; they can be removed if Tim wants a leaner test system. Old packages 560.94 and 591.86 are still in the driver store. Windows Update may replace 581.80 by itself, as it has changed drivers before.
- **First two-card run on Windows, 2026-11-11 06:26 UTC, `gpudoc test --gpu all` with llama-bench only:** both PASS. Results in `captures/noodlecart/compute-20261111-062613-windows` (private).

  | Card | Prompt tokens/s | Generation tokens/s | Peak temp | Avg power under load | Tokens per GPU watt-hour |
  |---|---|---|---|---|---|
  | GTX 1660 Ti | 426.7 | 42.9 | 56 C | 99.8 W | 1,546 |
  | GTX 1060 | 182.5 | 27.8 | 60 C | 104.5 W | 959 |

  - **Device order differs by system:** on Windows llama-bench lists `Vulkan0` as the 1060 and `Vulkan1` as the Ti, the reverse of Mint. Selection by name picked the right device both times, and memory rose only on the selected card (4,543 MiB on the Ti with 4 on the 1060; 4,539 MiB on the 1060 with 0 on the Ti).
  - **Clean:** no `nvlddmkm` events, no leftovers, the Windows job-object guard was active. Power cap noted in 3 of 9 samples on each card.
  - **Ti speed:** 42.9 generation tokens/s here matches the 41.3 from the standalone Mint check, so the 30.6 in the Mint GPUDoc run is the odd one out. That run came 60 s after a 5-minute gpu-burn; whether that is the cause is untested.
  - **Not run on Windows:** a sustained compute stress test, because gpu-burn is Linux only.
- **Booting Windows from Mint, tested 2026-11-11:** `sudo efibootmgr --bootnext 0000` then a reboot brought Windows up with nobody at the machine. A plain restart of Windows should return to Mint, since Mint is first in the boot order; not yet tested.
- **GPUDoc on Windows:** new code deployed to `C:\gpudoc\app\gpudoc` on 2026-11-11, with the previous copy kept as `gpudoc.before-compute-adapters-20261111-060912`. No test has run there with it yet.
- **Linux Mint 22.3:** on the 238 GB USB drive, as host `noodlecart-mint`, reached as `tim@192.168.2.51` by key. `tim` has a password and passwordless `sudo`, which needs tightening later.
- **Boot:** since 2026-11-09, Mint boots through firmware entry `0002 "Ubuntu"` (`\EFI\ubuntu\shimx64.efi` on the USB stick), which is first in the boot order. Entry `0005 "UEFI OS"` (the old removable path) is still second. For Windows, press F11 and choose Windows Boot Manager, or from Mint run `sudo efibootmgr --bootnext 0000 && sudo reboot`.
- **SSH identity:** each OS has its own host key at the same address. In Git Bash use `-o UserKnownHostsFile=/dev/null`. In PowerShell use `NUL`.
- **Mint state:** `nvidia-driver-580` version 580.178.04 was installed on 2026-11-08 and is loaded, running both cards. Before the driver, `nouveau` failed on the 1060 with `gpio: init failed`. Secure Boot was off when checked from Windows.
- **Mint clock:** set to UTC (`Etc/UTC`), 5 hours ahead of Montreal in November. Times in this file read from Mint (21:36, 21:57, 21:59, 22:09) are UTC, which is 16:36 to 17:09 EST. Run folders on Mint are also named in UTC.
- **Boot problem (2026-11-08):** the first reboot into Mint after the driver install stopped at the GRUB command line. Tim says it has happened before. Cause not yet found. Best guess: the signed GRUB, set up by `grub-install --removable` in `scripts/install_mint_to_usb.sh`, can't find or follow its config file on the EFI partition. The EFI partition holds only `EFI/BOOT` (`BOOTX64.EFI`, `grubx64.efi`, `mmx64.efi`, `BOOTX64.CSV`, `grub.cfg`), with no `EFI/ubuntu`. `EFI/BOOT/grub.cfg` is correct: it searches for UUID `7100f9dc-...` (the `mint-gpudoc` partition, `sdb2`) and loads `/boot/grub/grub.cfg`. Theory, unproven: Ubuntu's signed GRUB looks for its config in `EFI/ubuntu`, not `EFI/BOOT`. **Fix applied 2026-11-08 21:57, with Tim's OK:** created `/boot/efi/EFI/ubuntu/grub.cfg`, byte-identical to the `EFI/BOOT` stub. Nothing else changed; deleting that folder undoes it. **Confirmed by Tim, 2026-11-08:** the next boot went straight to the desktop with no `grub>` prompt, so the theory held. If `grub>` appears again, record `echo $prefix`, `echo $cmdpath` and `echo $root`. Manual boot: `search --no-floppy --label mint-gpudoc --set=root`, then `configfile /boot/grub/grub.cfg`.
- **Remote desktop (2026-11-08):** `xrdp` installed on Mint over SSH, enabled at boot, listening on port 3389. Connect from PT with Remote Desktop Connection to `192.168.2.51` as `tim`. `~/.xsession` was created with `xfce4-session`. A `ufw` rule allows 3389 from `192.168.2.0/24`, but `ufw` is inactive, so the port is open to the whole LAN. **First tries failed (2026-11-08 21:59):** login succeeded, then `xfce4-session` quit after 1 second and RDP returned to the login screen. `tim` was also logged in at the monitor (`loginctl`: seat0, tty7), and `~/.xsession-errors` shows the remote session finding that session's SSH and GPG agents already running. Likely cause: Xfce won't start a second session for a user who already has one. **Fix applied 2026-11-08, with Tim's OK:** `~/.xsession` now reads `dbus-launch --exit-with-session xfce4-session`, so the remote desktop gets its own D-Bus. The previous version is saved as `~/.xsession.before-dbus-20261108`. Confirmed working from PT by Tim, 2026-11-08, with `tim` also logged in at the monitor. If it breaks later, the fallback is logging out at the monitor before connecting.
- **Firmware boot entries (read from Mint, 2026-11-08):** `0005` "UEFI OS" (the USB stick's `\EFI\BOOT\BOOTX64.EFI`, created by the firmware), `0000` Windows Boot Manager, `0001` Hard Drive, `0004` USB. BootOrder `0005,0000,0001,0004`, so Mint boots first, which is Tim's choice. One-time boot to Windows from Mint: `sudo efibootmgr --bootnext 0000 && sudo reboot`. Remote reboots into Mint should now be safe, since the GRUB fix held on one boot.
- **Riser:** not in use and not proven faulty.
- **Third card (2026-11-09, about 03:58 UTC):** Tim installed a third card, details not yet recorded. Mint doesn't see it, even with `lspci`: only the 1660 (`01:00.0`) and 1060 (`02:00.0`) appear. One chipset root port, `00:1c.0` (Slot #6, rated 10 W, likely an x1 slot), shows `Width x0` with no active link (`DLActive-`). That would fit a card in that slot that never connected, but it isn't confirmed that the card is there. No PCIe errors were logged. Tim: the card's power is connected, and it's on a riser, because the board has only two full-length slots. **The card is a GTX 1660 Ti that Tim moved from Taichi (2026-11-09, his decision).** Still unknown: the riser type, and whether the riser board has its own power. This is the second card that has failed to appear through a riser. The 1060 on 2026-11-06 was the first, but its power cable changed at the same time, so neither case proves the riser is faulty. The riser's SATA power is connected (Tim). **Rescan, 2026-11-09 04:52 UTC, card on the riser in the bottom x1 slot:** still not visible. Port `00:1c.0` now reports Slot #7 with `PresDet+` (the slot detects a card), `Width x1`, `DLActive-`, and no device on bus 03. So the card is detected in the slot but never enumerated. Next: test the 1660 Ti in a known good full-length slot. A `sudo` PCI rescan is a possible extra check, not yet done. **Swap test, 2026-11-09 14:33 UTC:** the 1660 Ti in the top x16 slot works (`01:00.0`, x16, VBIOS 90.16.29.00.2D, 36 C idle). The regular 1660, known good, on the riser in the same bottom x1 slot is not detected either: `PresDet+`, `Width x0`. So the card is fine and the riser path is at fault, meaning the riser, its cable, or that x1 slot. Two cards have now failed through it. The 1060 did not appear in this boot. Tim thinks he may have knocked it loose. It still didn't appear after the 14:44 UTC reboot (nothing on bus 02), so it needs reseating and its power cable checking. **Reseated, 2026-11-09 14:48 UTC:** the 1060 is back at `02:00.0`, x4, 36 C idle. Mint boots straight in via `0002`. Current layout: the 1660 Ti (`01:00.0`, x16) and the 1060 (`02:00.0`, x4) work; the regular 1660 on the riser in the bottom x1 slot is still not detected (`Width x0`).
- **GTX 1660 Ti, first GPUDoc runs, 2026-11-09 14:49 UTC (09:49 EST), with Tim's OK:**
  - **Inspect:** complete, all cross-checks matched. Turing, VBIOS 90.16.29.00.2D, x16. Reported slowdown 92 C, max operating 90 C, shutdown 95 C, target 83 C.
  - **memtest:** PASS. The tool tested device 2 (`Bus=0x01:00 DevId=0x2182`), the selected card; numbering held with this layout too. 7,822 iterations.
  - **Temperature and power:** 47 C at the start, 77 C peak, fan 24% to 44%, stop limit 85 C. About 119 W average against a 120 W limit (max 132 W). The power cap was active in 61 of 64 samples (PWR-001 NOTE). GPU-only energy was 10.04 Wh.
  - **Memory:** 231.2 GB/s written and 203.5 GB/s checked in the last 30 s window, against 156.9 and 147.1 on the 1660. Coverage 5,360 of 6,144 MiB, 87.2%.
  - **Clean:** no Xid lines, no leftovers, Linux guard active.
  - **Results:** `captures/noodlecart/1660ti-20261109-mint` (private).
- **Compute tools on Mint, 2026-11-09 22:12 to 23:44 UTC, with Tim's OK to download and install:**
  - **CUDA toolkit:** Ubuntu's `nvidia-cuda-toolkit` 12.0.140, installed with `--no-install-recommends` (1,465 MB download, 5,029 MB on disk, 48 packages, none removed or upgraded). The driver is unchanged at 580.178.04. This changes the test image, so it counts as part of the setup for hygiene.
  - **gpu-burn:** built from source at commit `0d19c94` (2026-10-02) in `~/gpudoc/tools/gpu-burn-0d19c94`, with `make COMPUTE=61 CUDAPATH=/usr`. Source archive SHA-256 `58a6f467...2bdad7`. Run it from its own folder, because it loads `compare.fatbin` from the current directory.
  - **gpu-burn device numbers:** with `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `./gpu_burn -l` lists ID 0 as the 1660 Ti and ID 1 as the 1060, matching `nvidia-smi`. Without that variable the order is unverified.
  - **Quick checks, outside GPUDoc, 60 s each, output not saved:** 1660 Ti: 0 errors, about 4,860 Gflop/s, 35 C to 70 C, about 120 W, power-capped throughout. 1060: reported OK, about 3,290 Gflop/s early in the run, 33 C to 70 C, about 120 W, power-capped from about 30 s. gpu-burn's own "temps" figure was wrong during the 1660 Ti run (it showed 33 C while `nvidia-smi` showed 67 C), so don't use it; GPUDoc's own telemetry is the source.
  - **llama.cpp:** build b12177, Ubuntu Vulkan x64, the same build as the Windows runs, in `~/gpudoc/tools/llama.cpp-b12177-vulkan/llama-b12177`. Archive SHA-256 `9b1e56f8...e218c2`, not yet compared with the published digest. Not yet run.
  - **Model, installed 2026-11-10 23:22 UTC:** `qwen2.5-7b-instruct-q4_k_m` (two parts, 3,993,201,344 and 689,872,288 bytes) in `~/gpudoc/models/qwen2.5-7b-instruct-q4_k_m`. Copied from Noodlecart's Windows drive (`sda3`, mounted read-only at `/mnt/win`, then unmounted), from `gpudoc\models\qwen2.5-7b-q4_k_m`, so both systems use the same files. SHA-256 of both parts matches Hugging Face's published values: part 1 `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db`, part 2 `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`. The earlier Hugging Face download ran at roughly 100 KB/s and was dropped; its 408 MB `.part` file is still in that folder and can be deleted with Tim's OK.
  - **Install script:** `~/gpudoc/scripts/install_compute_tools.sh` on Mint, not yet in the repo.
  - **llama-bench device selection, verified 2026-11-10 23:24 UTC:** `--list-devices` shows `Vulkan0` as the 1660 Ti and `Vulkan1` as the 1060. `-dev VulkanN` puts the load on that card only, confirmed by watching both cards, and each JSONL result row names it in its `devices` field. This is what GPUDoc needs to lift the several-cards refusal (RUN-006): pass `-dev`, then check `devices` and the other card's memory and power.
  - **llama-bench check, outside GPUDoc, same arguments as the adapter (`-ngl 99 -p 512 -n 256 -r 3`):**

    | Card | Prompt tokens/s | Generation tokens/s | Peak temp | Peak power | Peak memory | Other card |
    |---|---|---|---|---|---|---|
    | GTX 1660 Ti | 427.4 | 41.3 | 51 C | 118.6 W | 4,913 MiB | 1060 stayed at 7 MiB, 6.1 W |
    | GTX 1060 | 182.2 | 27.4 | 55 C | 123.2 W | 4,549 MiB | 1660 Ti stayed at 379 MiB, 16.7 W |

    The run is short, so the peak temperatures aren't a thermal result. Raw output: `captures/noodlecart/llama-check-20261110-232431-mint` (private).
  - **Done 2026-11-10:** the gpu-burn adapter, `-dev` selection in the `llama-bench` adapter, and the first compute run through GPUDoc. See Phase 2.
  - **Deployed code on Mint:** `~/gpudoc/src` and `~/gpudoc/tests`, with the previous copies kept as `src.before-compute-adapters-*` and `tests.before-compute-adapters-*`.
- **Wake-on-LAN (2026-11-10):** Tim enabled LAN power-on in the firmware. On Mint, `Wired connection 1` (`eno2`, MAC `a8:a1:59:53:3b:79`) now has `wake-on-lan magic`, and `ethtool` reports `Wake-on: g`; it was `d` before. Not yet tested with a real power-off and wake. Windows has its own setting, not checked. Noodlecart is on wired Ethernet; `wlo1` is down.
- **GRUB still stops at `grub>` on boot (Tim, 2026-11-09),** despite the `EFI/ubuntu/grub.cfg` fix and one clean boot. The files are intact: both stubs identical, `/boot/grub/grub.cfg` present, grubenv empty, booted from entry `0005`. `strings` on `grubx64.efi` found no readable built-in config. Next: at the prompt, record `echo $prefix`, `echo $cmdpath`, `echo $root` and `search.fs_uuid 7100f9dc-803d-43e5-9e63-9d8387cff15d`. **Fallback applied 2026-11-09 14:00 UTC, with Tim's OK, without the prompt output:** both stubs (`EFI/BOOT/grub.cfg` and `EFI/ubuntu/grub.cfg`) now keep the UUID search, and if `/boot/grub/grub.cfg` isn't found on the result, they search by the label `mint-gpudoc`, which is what Tim's manual command does. `grub-script-check` passed. The originals are saved beside them as `grub.cfg.before-fallback-20261109`. Not yet tested by a boot. A future `grub-install` would rewrite `EFI/BOOT/grub.cfg`. **Result: `grub>` appeared again on the next boot,** so the fallback didn't fix it. Tim typed the four commands but the output wasn't kept. **Self-logging added 2026-11-09 14:30 UTC, with Tim's OK:** both stubs now record `$prefix`, `$cmdpath`, `$root` at start, `$root` after the UUID search, and `$root` at the end. They save these with `save_env` to `grubenv` in the folder GRUB was loaded from: 1024-byte files created empty in `EFI/BOOT` and `EFI/ubuntu`. Each copy also records which copy ran (`gpudoc_stub`). The previous versions are saved as `grub.cfg.before-diaglog-20261109`. After the next boot, read them with `sudo grub-editenv /boot/efi/EFI/BOOT/grubenv list`, and the same for `EFI/ubuntu`. Both still empty means GRUB never reads either stub. **Read after the 2026-11-09 14:33 UTC boot: both logs empty.** So GRUB most likely never reads either stub. The other possibility is that `save_env` failed to write, which would be unusual on FAT. **Standard GRUB install done 2026-11-09 14:40 UTC, with Tim's OK:** `grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --uefi-secure-boot`, then `update-grub`. Both exited 0.
- **Backups:** `~/gpudoc/boot-backup-before-grub-install-20261109/` holds firmware entries before and after, the old `/boot/grub/grub.cfg`, and a tar of the whole ESP `EFI` folder. The old `EFI/ubuntu` folder was also copied to `EFI/ubuntu.before-grub-install-20261109`.
- **New firmware entry:** `Boot0002 "Ubuntu"`, pointing to `\EFI\ubuntu\shimx64.efi` on the USB stick's ESP, first in BootOrder (`0002,0005,0000,0001,0004`), so Mint stays the default.
- **New files in `EFI/ubuntu`:** shim, `grubx64.efi` (2,660,232 bytes, from the current `grub-efi-amd64-signed` 2.12-1ubuntu7.3), `mmx64.efi`, `BOOTX64.CSV`, and a fresh stub `grub.cfg`.
- **Finding:** the old `EFI/BOOT/grubx64.efi` is a different, older binary (2,328,456 bytes, dated 2026-11-07, installed by `install_mint_to_usb.sh`), never updated since. That may be part of the cause; unproven.
- **`EFI/BOOT` was not left fully untouched:** grub-install refreshed `BOOTX64.EFI` (shim, same size) and `mmx64.efi`, and added shim's fallback `fbx64.efi`. `EFI/BOOT/grubx64.efi` and its `grub.cfg` were not changed.
- **GRUB menu:** `update-grub` added Windows Boot Manager and a UEFI Firmware Settings entry, despite `GRUB_DISABLE_OS_PROBER=true` set by the install script. Not yet explained; the Windows entry may be handy.
- **Confirmed 2026-11-09 14:44 UTC:** the boot went straight to Mint through the new entry (`BootCurrent: 0002`), with no `grub>` prompt. The menu is hidden by `GRUB_TIMEOUT_STYLE=hidden` with a 3 s timeout; hold Shift or press Esc during boot to show it. The likely cause was the stale `EFI/BOOT/grubx64.efi` from 2026-11-07. That's inferred from the fix working, not proven.
- **Off limits:** PT's RTX 4070, and the GTX 1660 Ti still in Taichi, which runs the JAZZ RAG. On 2026-11-09 Tim moved Taichi's other 1660 Ti into Noodlecart. How the JAZZ RAG runs with one card, or whether it runs at all, hasn't been checked; Taichi stays off limits to this project.

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
