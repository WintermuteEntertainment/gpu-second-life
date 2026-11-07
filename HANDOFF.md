# Handoff: GPUDoc

**Last updated:** 2026-11-07

## Rules

- Local git repo only: no remote, no public release, and nobody gets contacted until Tim says otherwise.
- No invented data, including in tests and examples.
- Remove personal details before anything goes public.
- Tim approves purchases, publishing, and deployment.
- Stress tests need Tim's go-ahead.

## Phase 1: `gpudoc inspect`

**Working on the GTX 1660:** over SSH, locally on Windows, and in WSL2. Reports come as JSON, Markdown, and self-contained HTML. Local runs add a direct NVML cross-check.

**Still needed:**
- A real Linux run on bare metal. WSL was only a first test run, and Tim asked to be reminded.
- A GTX 1060 capture on its older driver.
- Real numeric ECC values and other bracketed errors, listed in `tests/captures/README.md`.

## Phase 2: `gpudoc test`

First drafts started on 2026-11-07. See `src/gpudoc/` and `NOTES.md`. Not run on hardware until Tim approves.

## Test machine

Noodlecart, reached by key as `Admin@192.168.2.51`.

- **System:** Windows 11, 32 GB RAM, i5-9600KF with no integrated graphics, ASRock Z390 Phantom Gaming 4S/ac.
- **GPU:** GTX 1660 6 GB installed. Tim plans to add the GTX 1060 6 GB as a second card.
- **Tools in `C:\gpudoc`:** embeddable Python 3.11.9, app copy, memtest_vulkan v0.5.0, llama.cpp `b12177` Vulkan, Qwen2.5 7B Q4_K_M.
- **WSL:** Ubuntu 24.04 under `Admin`. Three unopened `twwca` installs total about 200 GB. Tim wants old Petals data removed, but each deletion needs confirming.

## Other open items

See `NOTES.md` for storage work, including the stash Tim will delete from BBB's A: himself, and the running backup of PurpleThunder's D:.
