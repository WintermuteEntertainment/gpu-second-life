# Working Notes

Lessons, reminders, and storage history from real work on this project. See `HANDOFF.md` for current status and next steps.

## Reminders for Tim

- **Real Linux testing is still due.** WSL was only a first test run. The Mint install now exists, but GPUDoc hasn't run on it yet.
- **Delete `A:\PurpleThunder_OLD_saved` on BBB when ready.** Tim will do this himself after checking the D: copy. A: is 93% full.
- **Check Noodlecart's old WSL installs.** Tim wants old Petals data removed to reclaim space. The `twwca` installs (Ubuntu 24.04 at 128.1 GB, 22.04 at 70.2 GB, Ubuntu at 1.2 GB) are unopened, and each deletion needs confirming.
- **Keep PT's C: as it is until Tim decides.** He put moving Petals and older WSL installs on hold.

## Lessons

| What happened | Effect | Rule from now on |
|---|---|---|
| I said backups were "copying now" right after launching robocopy, but it had failed on a read-only share. | A false status stood until the job ended. | Confirm real data movement before saying a job is running. |
| I estimated 2 hours by assuming gigabit speed. | The first run was heading for about 8 hours; the real copy took 3:07:15. | Measure a few minutes of throughput before giving a time. |
| I added robocopy `/Z` without weighing its cost. | 26 MB/s, then about 70 MB/s without it, and 77 GB of progress was thrown away. | For large LAN transfers, try without `/Z` and check speed early. |
| I named E: as a possible bottleneck with no data. | It measured 96% idle. | Label guesses, and measure first when the check is cheap. |
| I presented E:'s spanned layout as a discovery. | Tim built it and already knew. | Ask or check notes before treating Tim's setup as news. |
| A failed launch saved a capture named as a real result. | A misleading file had to be renamed. | Check the run succeeded before naming a capture as a result. |
| A case-insensitive match treated "Passed" progress lines as the final pass. | A 5-minute test ended after about 10 seconds. | Match exact completion lines with case sensitivity. |
| Killing `memtest_vulkan` seemed to leave its worker running. | The GPU stayed busy and blocked the next tool. I first blamed stale readings. | Stop the process tree, check for leftovers, and test the theory before stating it. |
| I reported the stash as checked using sizes and dates. iCloud copies kept a cloud tag and couldn't be read normally. | I found it after BBB's D: was reformatted. All 7,336 files in those folders were then recovered and checksummed. | A successful copy isn't proof. Test normal reads and checksum anything irreplaceable before erasing a source. |
| A Git Bash SSH command used `-o UserKnownHostsFile=NUL`. | It created a real file named `NUL`. | Use `/dev/null` in Git Bash and `NUL` in PowerShell. |
| The GTX 1060 was missing from `nvidia-smi` on 2026-11-08 while `lspci` saw it. Its power cable wasn't connected, which had also happened once before. | Time went into driver and boot checks first. | When a card shows in `lspci` but not in `nvidia-smi`, ask Tim to check its power cable before software diagnosis. |

## What worked

- Checking sizes and timestamps before and after each transfer step.
- Holding deletion until checksums on both machines matched.
- Reading real machine state, which corrected wrong assumptions about GPUs, E:, and disk use.
- Running two tools together, Tim's idea, which exposed the stop bug right away.

## Exit codes

A failed robocopy run reported 0, while a successful one reported 1, which is normal for robocopy when files were copied. The app also marked that success as "failed". Read logs and compare sizes, then checksums, before deciding what happened.

## Storage history

**PT's WSL backups**
- `E:\WSL_archive` was copied to `A:\WSL_backups` on BBB, checksums matched, and Tim deleted the originals. E: gained 736 GB.

**BBB's old PurpleThunder drive**
- D: was reformatted on 2026-11-07 with Tim's approval and relabelled `PT_D_Backup`.
- Saved to `D:\OLD_PurpleThunder_C_Drive_SAVED_2026-11-07`: `Users`, `inetpub`, `Projects`, `Autodesk`, `xampp`, `Certbot`, `Selenium`, and `msys64`.
- Left out by Tim's decision: the Play Games `userdata.img`, `Temp`, `GOG Games`, program folders, and cloud placeholders.
- Use `iCloudPhotos_RECOVERED` and `iCloudDrive_RECOVERED`. The plain `iCloudPhotos` and `iCloudDrive` folders beside them are partial leftovers from a failed attempt.
- 228 files couldn't be copied from the old `Users` folder: about 105 Windows app shortcuts and phone or iCloud placeholders, including `The Piano - Recording 1.m4a` and `Gloop.fbx`. Tim was asked to check those exist in iCloud or on his phone.
- The stash includes old `.ssh` data and likely browser profiles. BBB's shares give Everyone read access, so consider restricting that folder.

**PT's D: backup**
- `scripts/backup_pt_d.ps1` mirrors PT's D: to `\\192.168.2.217\D\PT_D`. A mirror deletes files from the backup when they're deleted on PT, and it keeps no version history.
- The first run copied 418,801 of 418,805 files, 1.031 TB, in 5:31:40, at about 52 MB/s. Failures: `DedicatedDump.sys`, two `DumpStack` logs, and `D:\JAZZ\nul`. Robocopy also flagged 1 failed folder, which hasn't been identified. Don't touch `D:\JAZZ\nul`, and be careful with anything JAZZ-related.
- It hasn't been verified with checksums or scheduled.

**Backup coverage, per Tim's plan**
- PT's C: goes to his 2 TB USB-C NVMe stick, the same size as C:, about monthly. PT's D: goes to BBB's D:. E: isn't covered, and it's a spanned volume with no redundancy.

## Other decisions from Tim

- BBB's write access on the `A` and `D` shares can stay on.
- Several network switches are 1 Gbps, so about 110 MB/s is the practical ceiling. Tim very much wants to rework the network for speed, but carefully, because the whole household relies on fast internet. Plan changes in small, reversible steps.
- Leave `sudo` on Noodlecart's Mint install for Tim to handle. Don't prompt about it.
- The two cloud files that weren't copied, `The Piano - Recording 1.m4a` and `Gloop.fbx`, don't matter.
- NetMapperPro should identify devices as fully as it can, while staying discreet and keeping results private. A planned refactor will add JSON output that GPUDoc can use, plus GPU details in its HTML and diagram.
- The CA$25,000 to CA$50,000 AI rig is mostly a dream for now.
- Experiments can be worth doing even when a more practical option exists.
- Power use is a design principle: reduce, reuse, recycle.

## Parked ideas

- A possible subscription bundle of GPUDoc and NetMapperPro, as separate tools. No pricing, outreach, or public repos for now.
- Waste-heat temperature sensor experiment.
- NetMapperPro's refactor is planned soon, per Tim on 2026-11-08, replacing the earlier decision to drop it.

## Carry into GPUDoc

- Never trust a tool's exit code alone.
- Confirm that work started as well as that it finished.
- Name captures after their verified outcome.
- Record real elapsed time, throughput, and energy.
