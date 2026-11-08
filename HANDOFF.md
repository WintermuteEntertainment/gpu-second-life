# Handoff: GPUDoc

**Last updated:** 2026-11-07

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

- **Committed:** `c8669f2`, Phase 1.
- **Uncommitted, needing Tim's OK:** Phase 2 draft, tests, real test captures, docs, and new scripts.

## Phase 1: `gpudoc inspect`

Working on the GTX 1660 over SSH, locally on Windows, and in WSL2, with JSON, Markdown, and self-contained HTML reports. Local runs cross-check against NVML.

**Still needed:**
- A run on real Linux with an Nvidia driver.
- A GTX 1060 capture.
- Real numeric ECC values and other bracketed errors. See `tests/captures/README.md`.

## Phase 2: `gpudoc test`

Draft in `src/gpudoc/testing.py`. It runs `memtest_vulkan`, then `llama-bench`, with monitoring, a temperature stop, process-tree stopping, driver comparison, VRAM coverage, energy, and rules. 40 tests pass.

**Real result:** both tools passed on the GTX 1660 under Windows on 2026-11-07, in `captures/noodlecart/gpudoc-test-20261107-134957`: about 32.6 tokens/s and about 1,021 tokens per GPU watt-hour.

**Not done:**
- Real hardware tests of failure paths, such as the temperature stop and a killed tool.
- Choosing a GPU when two are installed. `gpudoc test` refuses to run with two GPUs for now.
- HTML test reports.
- gpu-burn and DCGM evaluation.

**Open questions:**
- Why does `memtest_vulkan` use only 79% of the 1660's VRAM, but about 96% of the 1060's?
- The stop bug's cause is inferred from logs, not fully proven.

## Test machine: Noodlecart

- **Hardware:** i5-9600KF with no integrated graphics, 32 GB RAM, ASRock Z390 Phantom Gaming 4S/ac, 750 W power supply.
- **GPUs:** GTX 1660 in the x16 slot, GTX 1060 in the second slot at x4. Both are Zotac.
- **Windows:** on the 477 GB SATA drive, reached as `Admin@192.168.2.51` by key. Tools are in `C:\gpudoc`. A `gpudoc test` can't run while both cards are in. `nvidia-smi` showed only the 1660 on driver 560.94.
- **Linux Mint 22.3:** on the 238 GB USB drive, as host `noodlecart-mint`, reached as `tim@192.168.2.51` by key. `tim` has a password and passwordless `sudo`, which needs tightening later.
- **Boot:** Windows is the default. Press F11 and choose `TEAM TM8PS7256G` for Mint.
- **SSH identity:** each OS has its own host key at the same address. In Git Bash use `-o UserKnownHostsFile=/dev/null`. In PowerShell use `NUL`.
- **Mint state:** no Nvidia driver yet, and `nouveau` fails on the 1060 with `gpio: init failed`. Noodlecart was last booted into Mint.
- **Riser:** not in use and not proven faulty.
- **Off limits:** PT's RTX 4070, and Taichi's two GTX 1660 Tis, which run the JAZZ RAG.

## Next steps

1. Get Tim's OK to commit the Phase 2 draft and docs.
2. On Mint, install `nvidia-driver-580`, the standard version, not `-open`. Ubuntu lists it for the 1060, and the 1660 is expected to work on it but isn't listed. Reboot, then check both cards with `nvidia-smi`.
3. If the 1060 still fails, investigate its power cable, slot, or the card itself.
4. Copy GPUDoc to Mint and run `gpudoc inspect`, capturing real output as test data.
5. Add GPU selection, then test each card.
6. Compare VRAM coverage with both cards on the same driver.
7. With Tim's go-ahead, test failure paths on real hardware.
8. Add HTML test reports, then evaluate gpu-burn and DCGM on real Linux.

## Related

- **NetMapperPro:** `D:\Repos\netmapperpro`, separate repo, with `HANDOFF.md` and `NETWORK_PLAN.md`.
- **Storage and reminders:** `NOTES.md`.
