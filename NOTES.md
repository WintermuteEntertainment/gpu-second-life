# Working Notes

Lessons and open items from real work on this project. See `HANDOFF.md` for current status.

## 2026-11-06: review of the backup copy and load test turns

### What went wrong

| What happened | Effect | Rule from now on |
|---|---|---|
| I told Tim the backups were "copying now" right after launching robocopy. It had failed on a read-only share. | A false status stood until the job ended. | Confirm real data movement before saying a job is running. |
| I estimated 2 hours by assuming gigabit speed, without measuring. | The first run was heading for about 8 hours; the real copy took 3:07:15. | Measure a few minutes of throughput before giving a time. |
| I added robocopy `/Z` for resume support without weighing the speed cost. | The speed was 26 MB/s, then about 70 MB/s without it, and 77 GB of progress was thrown away. | For large transfers on a reliable LAN, try without `/Z`, and check speed early. |
| I named E: as a possible bottleneck with no data. | It measured 96% idle, so the guess was wrong. | Label guesses, and measure first when the check is cheap. |
| I presented E:'s spanned layout as a discovery. | Tim built it and already knew. | Ask or check notes before treating Tim's own setup as news. |
| A load test launch failed with "command line too long", and my script still saved a capture named as a real result. | A misleading file had to be renamed. | Check the run succeeded before naming a capture as a result. |
| A case-insensitive match treated "Passed" progress lines as the final pass. | A 5-minute test ended after about 10 seconds. | Match exact completion lines with case sensitivity. |

### What exit codes taught us

- **Robocopy:** a failed copy reported exit code 0, while the successful copy reported 1, which is normal for robocopy when files were copied. The app also marked that success as "failed".
- **Rule:** read the log and compare sizes, then checksums, before deciding what happened. An exit code or task status alone isn't enough.

### What worked

- Checking file sizes and source timestamps before and after each transfer step.
- Holding deletion until checksums on both machines match.
- Stopping and asking when a job's speed changed the plan.
- Reading the machine's real state, which corrected wrong assumptions about the GPU, E:, and disk use.

### Tim's corrections

- Do the load test before the WSL move.
- Do not move anything from C: for now.
- Several network switches are 1 Gbps, so about 110 MB/s is the practical ceiling for now.
- Experiments can be worth doing even when a more practical option exists.

### Open items from those turns

- [x] Compared SHA-256 checksums of both backups on E: and BBB: both matched, 2026-11-06.
- [x] `E:\WSL_archive` deleted by Tim, confirmed 2026-11-07. E: now has 1,320 GiB free. The verified copies are in `A:\WSL_backups` on BBB.
- [ ] Tim gave permission on 2026-11-07 to continue: verify the stash, reformat BBB's D:, and set up the PurpleThunder D: backup.
- [ ] Soon: remap the network with NetMapperPro, found at `C:\Users\twwca\Downloads\NET_MAPPER_PRO.py`.
- [ ] Keep C: as it is until Tim decides.

BBB's write access on the `A` share can stay on permanently (Tim, 2026-11-06), so it doesn't need revoking.

### Storage ideas from Tim

- Repurpose the old PurpleThunder C: drive still installed in BBB. It appears to be BBB's D:, labelled `PurpleThunder_OLD_needs_recovery`: a Samsung 990 PRO 2 TB, with about 1,070 GB used and 662 GB free on 2026-11-06. Inventory it before erasing anything, because the label suggests recovery was still planned.
- If nothing on BBB's D: needs keeping, use it to back up PurpleThunder's D:. That was about 1,062 GB used on 2026-11-06, and it should take about 4.5 hours at the speed measured. Tim confirms before BBB's D: is erased.
- Tim's plan (2026-11-06): save `Users`, `inetpub`, `Projects`, and `Autodesk` from BBB's D: elsewhere, then reformat D: to back up PurpleThunder's D:. PurpleThunder's C: backs up to Tim's USB-C NVMe stick about monthly. E: isn't covered by this plan.
- BBB's `D:\Documents and Settings` reports 2,389 GB because it's a junction. Copies must skip junctions (`/XJ`), and early size totals are inflated.
- BBB's D:\Users is inflated by a 512 GiB sparse Google Play Games `userdata.img`. On 2026-11-06 the stash to `A:\PurpleThunder_OLD_saved` started with that file and `AppData\Local\Temp` (41 GiB) excluded. Tim decides on both before D: is reformatted.
- The stash includes old `.ssh` and browser data, and BBB's `A` share gives Everyone read access. Restrict it if needed.
- Tim approved adding small folders `xampp`, `Certbot`, `Selenium`, and `msys64` to the stash (2026-11-07). He accepted losing `GOG Games`, `Program Files`, `Program Files (x86)`, `ProgramData`, and other reinstallable items.
- Tim hopes for faster than 4.5 hours for the PurpleThunder D: backup, but there's no direct cable and he doesn't want to rework the network. As he recalls it, BBB sits behind a 2.5 Gbps router/extender and both paths run back to the modem. Run the first copy when the wait doesn't matter, such as overnight.
- BBB's D: was reformatted on 2026-11-07 with Tim's approval and relabelled `PT_D_Backup`. The stash is at `A:\PurpleThunder_OLD_saved`. `scripts/backup_pt_d.ps1` mirrors PT's D: to `\\192.168.2.217\D\PT_D`.
- **Do not delete `A:\PurpleThunder_OLD_saved` until this is resolved.** 7,324 iCloud files there still carry a cloud tag, so normal reads fail with error 1920. Sampled files read fine with reparse-aware reads and have valid headers. On 2026-11-07 recovery started into `iCloudPhotos_RECOVERED` and `iCloudDrive_RECOVERED` in the D: stash, with per-file checksums. Lesson: a successful copy isn't proof that the destination can be read normally.
- BBB's A: had 639 GB free before that stash.
- A spare 1 TB NVMe was found in a drawer and may still work. It's untested.
- Tim's main concern is drive space.

### Reminders for Tim

- **WSL is only a first test run.** Remind Tim that GPUDoc still needs testing on a real Linux install before Linux support counts as proven (his request, 2026-11-07).
- **Old Noodlecart WSL installs:** Tim wants old Petals data there deleted to reclaim space. The `twwca` installs (Ubuntu 24.04 at 128.1 GB, 22.04 at 70.2 GB, Ubuntu at 1.2 GB) still need opening first, and each deletion needs confirming.

### Parked ideas (Tim, 2026-11-07)

- Possibly market GPUDoc and NetMapperPro together as a subscription bundle, while keeping them as separate tools. Not active: no pricing work, outreach, or public repos for now.
- NetMapperPro works and needs no development for now. The earlier refactor idea is dropped.

### Carry into GPUDoc

- Never trust a tool's exit code alone.
- Confirm that work started as well as that it finished.
- Name captures after their verified outcome.
- Record real elapsed time and throughput.
