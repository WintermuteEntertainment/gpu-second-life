# GPU Second Life: Project Plan

**Status:** Phase 1 (`gpudoc inspect`) committed 2026-11-07, Phase 2 draft (`gpudoc test`) committed 2026-11-08; gpu-burn and llama-bench ran through it on Linux on 2026-11-10. Nothing purchased. See `HANDOFF.md` for current state; parts of this plan, such as Phase 0 and section 15, still describe earlier hardware layouts.
**Created:** 2026-11-05
**Visibility:** Private planning document. Remove personal details before any of this goes into a public repo.
**Working names:** `gpu-second-life` for the project and GPUDoc (`gpudoc`) for the tool. As of 2026-11-06, `gpudoc` was unused on PyPI, npm, and crates.io, with no GitHub account of that name. Trademarks have not been checked.

---

## 1. Summary

**What it does:** `gpudoc` tests a used GPU and produces a report showing what was tested, what passed, what failed, and what could not be tested. It also measures how fast real AI models run on the card and what that costs in electricity.

**Why it matters:** Used GPUs are harder to reuse than they should be. Buyers cannot easily tell whether a card is healthy, what it can run, or which software still supports it. Those gaps push usable hardware toward waste.

**What it costs:** No purchases are planned. All testing uses the GTX 1060 6 GB now working in Noodlecart and any spare cards on hand, including a GTX 1660 that Tim recalls being faulty. The cost is time, Claude usage, and a small amount of electricity. A V100 test card is deferred with no date (section 13).

**First goal:** Produce one accurate, repeatable report on the GTX 1060 in Noodlecart.

**Biggest limit:** A report can show how a card behaved during testing. It cannot predict how long the card will last, and it cannot prove a seller did not alter the results (section 9).

---

## 2. Scope

### In scope for version 1

- Read the card's identity, settings, and error history.
- Run memory, load, and thermal tests with safety limits.
- Run repeatable LLM benchmarks with power measurement.
- Produce a machine-readable report and a human-readable report.
- Let a user remove private details before sharing a report.

### Out of scope for version 1

- Predicting remaining lifespan.
- Certifying a card as "guaranteed good".
- Selling, brokering, or warrantying hardware.
- AMD and Intel support. The design leaves room for them, but Nvidia comes first because the retired data-center cards are the target.
- A hosted upload service.
- Physical dock or adapter design.

### Design principle: power use (Tim, 2026-11-07)

Power is something GPUDoc measures and something the project tries to use less of.

- **Measure it:** Report GPU-only energy per run and output per watt-hour, and say when a figure excludes the rest of the machine.
- **Use less:** Run tests only on request, with no background service or constant polling. Use the shortest test that answers the question, and let the card return to idle afterward.
- **Compare fairly:** Show efficiency beside speed, so a slower, efficient card can come out ahead.
- **Tune:** A later feature could find the power limit with the best output per watt.
- **Prefer reuse:** Prove a used card can do the job before anyone buys a new one.

### Project rules

- **No invented data.** Benchmarks, thresholds, examples, and test fixtures must come from real runs or be clearly labelled as empty. Any exception needs Tim's approval first.
- **Missing is not zero.** `[N/A]` on a card means "not available", and it must never be stored or displayed as zero errors.
- **Report what was not tested** with the same prominence as what was.
- **No telemetry.** Nothing leaves the machine unless the user explicitly exports and shares it.
- **Tim presses the button** on purchases, publishing, and deployment.
- **Private for now.** All repos stay private, and nobody is contacted, until Tim says otherwise (2026-11-06). This includes other projects' maintainers, scoreboards, and databases.

---

## 3. Users and needs

| User | Main question | What the tool must provide |
|---|---|---|
| Used-GPU buyer | Is this card healthy? | A repeatable health report they can run themselves |
| Home-lab owner | What can this card run, and at what cost? | Speed, memory, and energy measurements for specific models |
| Refurbisher or charity | Can I intake many cards consistently? | Scriptable runs, standard reports, and intake IDs |
| Nonprofit or clinic | Can it run our work locally? | A plain answer for specific tasks, supplied later by the private AI box (section 14) |
| Seller | How do I show a card's condition? | A shareable report, with honest limits on what it proves |

---

## 4. What already exists

Do not rebuild these. Use them where the licence and platform allow it.

| Tool | What it does | Plan |
|---|---|---|
| `nvidia-smi` and NVML | Reports GPU identity, counters, temperature, power, and clocks | Core data source |
| DCGM `dcgmi diag` | Nvidia diagnostics, with levels from quick validation up to extended hardware tests | Use on supported data-center cards |
| memtest_vulkan | Writes, reads, and verifies GPU memory through Vulkan; zlib licence | Primary memory test, especially on cards without ECC |
| llama.cpp `llama-bench` | Measures LLM speed | Primary benchmark engine |
| LocalScore | Open-source LLM benchmark with a public results database; Apache 2.0; single-GPU | Optional comparison and possible partner, not a competitor to clone |
| gpu-burn | Multi-GPU CUDA stress test; BSD-2-Clause | Linux load test |
| gpu-fryer | Stress test with throttling and performance checks; Apache-2.0 | Optional Linux load test |
| GPUd | Linux GPU monitoring and diagnostics; Apache-2.0 | Optional evidence on data-center setups |
| Wattever | Cross-platform LLM benchmark with optional power data; MIT | Import its JSON results |
| llmfit | Shows which models fit the hardware; MIT | Use for model suggestions |

**The gap:** I found no tool aimed at home-lab owners that adapts to one used GPU, from consumer cards to the V100 and A100, and explains the combined result. See [GAPS.md](GAPS.md) for the full analysis and its limits.

### Adapt, do not compete

Tim's direction, 2026-11-06: keep our own datasets, but adapt to what already exists.

- **Run existing tools** through adapters, and record their versions and raw output.
- **Read their results** where the format is stable, starting with Wattever's JSON files.
- **Keep our own dataset** of real runs, with card condition, setup, speed, and energy.
- **Keep imported data separate,** with its source, licence, and retrieval date. Check terms before redistributing any of it.
- **Share compatible results back, later.** Run the official LocalScore client for its database, and produce text ready to post on the llama.cpp scoreboards. Nothing is submitted without the user's action, and this project submits nothing while it is private.
- **Follow others' formats when practical,** such as LocalScore's reference models and common llama.cpp settings.
- **Send improvements upstream** where a fix belongs to another project.
- **Borrow the fail-closed rule from Glimmer:** a required test that cannot run can never produce a pass.

---

## 5. Architecture

### Plain-language version

The tool has six parts. One reads facts from the card. One runs tests. One records temperature and power during those tests and stops them if limits are crossed. One applies published rules to the results. One writes the report. One removes private details before sharing.

### Data flow

```text
               +-------------------+
               |   CLI (gpudoc)    |
               +---------+---------+
                         |
                         v
               +-------------------+
               |    Preflight      |  driver, tools, disk, cooling answers,
               |                   |  user confirmation before stress tests
               +---------+---------+
                         |
                         v
               +-------------------+       +----------------------+
               |    Inspector      | ----> | Before snapshot      |
               | (NVML/nvidia-smi) |       +----------------------+
               +---------+---------+
                         |
                         v
      +------------------+------------------+
      |            Test runner              |
      |  memtest_vulkan | DCGM | load       |
      |  llama-bench    | future adapters   |
      +------------------+------------------+
                         ^
                         | stop signal
      +------------------+------------------+
      |        Sampler and safety monitor   |
      |  temp, power, clocks, throttle,     |
      |  errors, kernel log (Xid)           |
      +------------------+------------------+
                         |
                         v
               +-------------------+       +----------------------+
               |    Inspector      | ----> | After snapshot       |
               +---------+---------+       +----------------------+
                         |
                         v
               +-------------------+
               | Rules engine      |  versioned rules, evidence attached
               +---------+---------+
                         |
                         v
               +-------------------+
               | Report writer     |  JSON, Markdown, HTML, raw logs
               +---------+---------+
                         |
                         v  (only when the user asks)
               +-------------------+
               | Redacted export   |  removes private fields, shows a preview
               +-------------------+
```

### Technology choices

| Decision | Recommendation | Reason |
|---|---|---|
| Language | Python 3.11 or newer | Fast to build, easy to read, and well suited to wrapping other tools |
| GPU access | NVML through `nvidia-ml-py`, with `nvidia-smi` as a cross-check | Direct API, with a second source to catch parsing or driver problems |
| Platforms | Windows and Linux from the start, with tests that do not exist on one platform clearly reported as not run | Tim wants both. DCGM is Linux-only, so data-center diagnostics stay on Linux |
| Noodlecart setup | Start from Tim's Linux Mint USB, then install Mint beside Windows if there is disk space | Free and already on hand, and it tests both systems on the same hardware. DCGM's list names Ubuntu and not Mint, so add Ubuntu later if DCGM work needs it |
| AI benchmark engine | Built into the workflow, downloaded on first use | See "Getting llama.cpp" in section 6 |
| Results storage | One folder per run, with JSON and raw logs | Easy to inspect, compare, and archive without a database |
| Report format | JSON is the source of truth; Markdown and HTML are generated from it | One source prevents reports from disagreeing |
| Public database, later | JSON files in a Git repo, published as a static site | Low cost, public history, and no server to secure |

A bootable Linux USB is a good later option because it gives each test a known environment and reduces the risk from the host OS. It is not needed for version 1.

### Designing for bigger cards

This is the project's main differentiator. Version 1 runs on 6 GB consumer cards, but these choices keep the V100, A100, and newer cards within reach. All of this remains unproven until tested on real hardware.

- **Ask the card what it supports.** Do not hard-code behaviour by model name.
- **Memory-repair strategies by generation:** none reported, page retirement, or row remapping.
- **Scale tests to VRAM.** Memory test size and duration must grow with capacity.
- **Benchmark tiers by VRAM.** Keep a shared small model for cross-card comparisons, then add larger models when the card can hold them.
- **Software profiles.** Support a pinned legacy path, such as CUDA 12.x for Volta, beside a current path.
- **Optional adapters.** DCGM is added where available; its absence is reported, not treated as failure.
- **Multiple GPUs.** Use device IDs from the start, even when testing one card.
- **Setup details.** Record adapters, risers, cooling, and whether the card has a display output. Noodlecart's own riser shows why: a riser can limit the link or stop detection, and that must not be blamed on the GPU.

### Proposed layout

```text
gpu-second-life/
  PLAN.md
  HANDOFF.md
  pyproject.toml
  src/gpudoc/
    cli.py
    preflight.py
    inspector/        # NVML and nvidia-smi collectors
    adapters/         # memtest_vulkan, dcgm, load, llama_bench
    engines/          # pinned llama.cpp builds, hashes, download logic
    monitor/          # sampling, safety limits, kernel log watching
    rules/            # versioned grading rules
    report/           # JSON, Markdown, HTML
    export/           # redaction and sharing
    compatdb/         # driver and software support data
  schemas/            # versioned JSON schemas
  docs/               # test explanations, limits, safety notes
  tests/
    captures/         # real recorded output only, with source notes
```

### Adapter contract

Every test or benchmark implements the same interface, so new tools can be added without changing the core:

```python
class TestAdapter(Protocol):
    id: str
    version: str

    def preflight(self, gpu: GpuInfo) -> PreflightResult: ...
    def run(self, gpu: GpuInfo, profile: Profile,
            stop: StopSignal, run_dir: Path) -> RawResult: ...
    def parse(self, raw: RawResult) -> TestResult: ...
```

Raw output is always saved before parsing. If a parser has a bug, results can be re-parsed later without running the test again.

### Commands

| Command | Purpose | Stresses the card? |
|---|---|---|
| `gpudoc inspect` | Read identity, counters, and support status | No |
| `gpudoc test --profile quick\|standard\|soak` | Run health tests | Yes, after confirmation |
| `gpudoc setup bench` | Show and download the right llama.cpp build for this card | No |
| `gpudoc bench --suite <name>` | Run AI benchmarks, offering setup first if needed | Yes, after confirmation |
| `gpudoc report <run>` | Regenerate reports from saved results | No |
| `gpudoc compare <run-a> <run-b>` | Show changes, such as before and after a repair | No |
| `gpudoc export <run> --redact` | Create a shareable report after previewing it | No |

Target durations are about 10 minutes for `quick`, 1 hour for `standard`, and overnight for `soak`. These are design targets and will change once measured.

---

## 6. Test catalogue

### Stage A: inspection

No stress is applied. All of these field names were confirmed in `nvidia-smi --help-query-gpu` while planning. Whether a given card returns values is a separate question.

| Check | `nvidia-smi` fields | Why it matters |
|---|---|---|
| Identity | `name`, `gpu_uuid`, `serial`, `vbios_version` | Identifies the card and helps expose mismatches |
| ECC history | `ecc.errors.corrected.aggregate.total`, `ecc.errors.uncorrected.aggregate.total` | Shows lifetime memory errors, when supported |
| Page retirement | `retired_pages.sbe`, `retired_pages.dbe`, `retired_pages.pending` | Legacy memory-repair state, relevant to cards like the V100 |
| Row remapping | `remapped_rows.correctable`, `remapped_rows.uncorrectable`, `remapped_rows.pending`, `remapped_rows.failure` | Newer memory-repair state, starting with Ampere |
| PCIe link | `pcie.link.gen.current`, `pcie.link.gen.max`, `pcie.link.width.current`, `pcie.link.width.max` | Shows whether the slot, adapter, or card is limiting the connection |
| Power and thermals | `power.draw`, `power.limit`, `temperature.gpu`, `temperature.memory` | Baseline values |
| Throttling | `clocks_event_reasons.*` | Shows why the card slowed down |

**Real example from a one-time planning check on an RTX 4070:** `ecc.mode.current` returned `[N/A]`. Consumer cards like this one need a memory pattern test because ECC history is not available. The GTX 1060 in Noodlecart also returned `[N/A]` on 2026-11-06.

### Stage B: health tests

| Test | Tool | Passes when | Notes |
|---|---|---|---|
| Memory integrity | memtest_vulkan | No errors reported | Main evidence for cards without ECC. On 2026-11-06, v0.5.0 ran over SSH on headless Windows with a GTX 1060, so a monitor is not required for this test |
| Sustained compute load, Linux | gpu-burn, gpu-fryer, or DCGM `targeted_stress` | Completes with no new errors or crash | gpu-fryer compares against other GPUs, so a single card has no peer |
| Sustained compute load, Windows | Sustained llama.cpp run, unless a verified stress tool is found | Completes with no new errors or crash | May stress the card less than a dedicated tool; reports must say so |
| Nvidia diagnostics | `dcgmi diag` | Passes the selected level | Current docs say non-data-center cards support level 1 unless higher levels are documented for that product |
| Memory bandwidth | DCGM memory bandwidth plugin | Meets the product threshold | Bandwidth is not memory integrity, and Nvidia's docs say so |
| Thermal behaviour | Sampler during load | Holds speed without hardware slowdown | The result depends on the cooling setup, which must be recorded |
| PCIe link under load | Sampler during load | Reaches the expected link | Check under load, since links can drop at idle to save power |
| Error delta | Before and after snapshots | No new errors | Often the most useful result |
| Kernel log | Xid messages on Linux | No serious Xid events | Xid 48 is uncorrectable ECC; 63 and 64 relate to row-remapping records |

### Stage C: AI benchmarks

| Metric | Source |
|---|---|
| Prompt processing speed | `llama-bench` |
| Generation speed | `llama-bench` |
| Time to first token | LocalScore or a custom timed run |
| Peak memory use | NVML sampling |
| Average GPU power | NVML sampling |
| Energy per 1,000 tokens | Average watts x seconds / 3,600, per 1,000 tokens generated |
| Electricity cost | Energy x a rate entered by the user |

### Getting llama.cpp

**Decision (Tim, 2026-11-06):** The llama.cpp test should feel built in, with fetching allowed if bundling is too heavy.

**Recommendation:** Keep the core tool small and treat llama.cpp as a managed part of it. The user runs one command, sees the size, approves it, and never has to install llama.cpp separately. Bundling every build would be too heavy.

Real x64 release sizes from llama.cpp build `b12144`, checked 2026-11-06:

| Build | Windows | Ubuntu-labelled Linux |
|---|---|---|
| Vulkan | 35.9 MiB | 34.2 MiB |
| CUDA 12.x (Windows 12.4, Linux 12.8) | 275.0 MiB, plus 373.3 MiB runtime | 179.4 MiB, plus 566.8 MiB runtime |
| CUDA 13.4 | 162.4 MiB, plus 403.9 MiB runtime | 161.5 MiB, plus 419.8 MiB runtime |

**How it should work:**

1. **Choose by card and driver.** Use the software support data to pick a build, then explain the choice.
2. **Show the download size and ask first.** No hidden downloads.
3. **Pin each build by tag and SHA-256.** The project's release file records approved builds, because llama.cpp publishes builds very often and newer is not always comparable.
4. **Offer an offline package.** A refurbisher can prepare one on a connected machine and carry it to test machines.
5. **Allow a user-supplied engine.** `--engine-path` lets someone use their own build, and the report marks it as such.
6. **Keep backends separate in results.** Vulkan and CUDA results are not treated as the same benchmark.
7. **Handle models the same way.** Model files are separate downloads and are usually much larger than the engine. They are also pinned by hash and approved first.

The Vulkan build is small enough to include in a full release package later, so a basic benchmark could work out of the box once a model is available. Check whether the CUDA runtime may be redistributed before bundling it. Downloading from the official release avoids that question.

**To confirm on real hardware:** whether Ubuntu-labelled builds run on Mint, which backend works best on the 1660 Ti, and whether the CUDA 12 builds support Volta cards such as the V100.

### Valid comparisons

- Pin each model by file hash (SHA-256).
- Record the llama.cpp commit, backend, driver, GPU layers, context size, and prompt set.
- Repeat runs and report the spread as well as the average.
- Label power as **GPU-only** unless a wall meter was used. NVML does not capture the whole system.
- Start with models that overlap LocalScore's reference set where practical: Llama 3.2 1B, Llama 3.1 8B, and Qwen 2.5 14B at Q4_K_M. Check the current list first.
- Add useful non-chat workloads later, such as transcription, embeddings, and translation.

---

## 7. Safety design

Stress tests can expose or worsen existing faults, and improvised adapter cooling raises the risk. Safety is a core feature.

- **Explicit confirmation** before any test that stresses the card.
- **Cooling declaration:** stock, shroud and fan, server airflow, or liquid.
- **Automatic stop** at a temperature limit. Use the card's reported limits where available. Default values are chosen in Phase 2 from documentation and real measurements.
- **Automatic stop** on sensor loss, a serious Xid event, or a sharp rise in errors.
- **Stepped load:** begin with inspection and a light run before the full test.
- **Independent watchdog:** if the test tool hangs, the monitor must still be able to stop it.
- **Confirm the stop.** memtest_vulkan continues into an endless test after its 5-minute pass, and on 2026-11-06 it still showed as running 3 seconds after a forced stop. Adapters must detect completion, stop the tool, and confirm that the process and GPU load are gone before writing the result.
- **Compare the driver before and after.** Windows Update installed an Nvidia driver on Noodlecart by itself on 2026-11-06. Every run must record the driver at both ends and flag any change.
- **Parse results strictly.** A real script bug on 2026-11-06 matched normal "Passed" progress lines as the final pass and ended a test after about 10 seconds. Match the tool's exact completion line, with case sensitivity, and test parsers against real logs.
- **Report memory coverage.** In real runs, memtest_vulkan showed about 5.9 GB in use on a 6 GB GTX 1060 but 4,831 MiB on a 6 GB GTX 1660. Reports must show how much VRAM was actually in use and must not imply full coverage without evidence.
- **Plain warning:** consumer use of data-center cards is unsupported, and running this tool is at the owner's risk.

**Test machine:** All GPU inspection, testing, and benchmarking for this project runs on Noodlecart (section 15). PurpleThunder may be used to write code, but its RTX 4070 is off limits for this project.

---

## 8. Grading

### Result states

| State | Meaning |
|---|---|
| **FAIL** | A test produced clear evidence of a fault |
| **ATTENTION** | Something needs a human decision, or the setup may be limiting the card |
| **PASS** | Every test that ran met its rule |
| **INCONCLUSIVE** | A test could not run, could not finish, or lacks enough data. It can never count as a pass. |

Each report shows the overall state, each result, the evidence, the rule version, and the tests not run. "PASS" is always shown with its limits: it means the card passed these tests on this date in this setup.

There is no single 1 to 100 score in version 1. A score would look more precise than the evidence allows.

### Initial rules

These rules use clear evidence and avoid invented thresholds.

| Evidence | Result |
|---|---|
| Memory test reports an error | FAIL |
| New uncorrected ECC errors during the run | FAIL |
| Xid 48 during the run | FAIL |
| `remapped_rows.failure` indicates a failure | FAIL |
| Card crashes or disappears during a test | FAIL, unless evidence points to the host or adapter; otherwise INCONCLUSIVE |
| Historic uncorrected errors or retired pages, with no new errors | ATTENTION |
| Pending page retirement or row remap | ATTENTION; reboot and retest |
| Retired pages approaching the legacy limit | ATTENTION; Nvidia's table gives a maximum of 64 |
| Zero lifetime ECC counts on a used data-center card | Note only: counters may have been cleared, so rely on the load test |
| InfoROM corruption reported | ATTENTION |
| Thermal slowdown under load | ATTENTION; check cooling first |
| PCIe link below expected under load | ATTENTION; check slot and adapter first |
| ECC data unavailable and no memory test run | INCONCLUSIVE |
| Speed with no real baseline | Show the measurement and say "no baseline yet" |

Performance and error-rate thresholds should only be added after enough real results exist to justify them. The sample size is an open decision.

Every rule carries an ID and a version, so older reports remain understandable when the rules change.

---

## 9. Trust and security

### What the report can and cannot prove

A seller controls the machine running the test, so a report generated there can be edited or faked. Signing the report does not solve this: it shows who signed the file, not that the results are true. Attackers could also alter the tool, driver, or displayed GPU identity.

**Honest positioning:** The report is useful evidence, and the strongest check is the buyer rerunning the tool on hardware they control.

| Scenario | Trust level | Method |
|---|---|---|
| Buyer tests the card on their own machine | Strongest | Rerun and compare |
| Buyer watches a test in person | Moderate | Fresh run with live screen output |
| Refurbisher tests many cards | Depends on reputation | Refurbisher signs reports with its own key |
| Unverified report from a seller | Weak | Treat as a claim |

File hashes can detect later edits to a report and raw logs. The report must not imply that this proves honesty.

### Security controls

- Download external tools from pinned releases and verify their hashes.
- Avoid administrator or root access unless a specific step needs it, and explain why at that point.
- Treat tool output and model files as untrusted input.
- Treat submitted reports as untrusted: validate them against a schema, escape everything displayed, and never execute uploaded content.
- Do not include hidden network calls. Model downloads must be visible and approved.

### Privacy

| Field | Default in a shared report |
|---|---|
| Hostname, username, file paths, IP addresses | Removed |
| Full serial and GPU UUID | Removed, or replaced by a salted hash if the user wants to link their own runs |
| Kernel log | Only GPU-related lines, shown for review |
| GPU model, VBIOS, driver, and test results | Kept |
| Electricity rate | Removed unless the user opts in |

A plain unsalted hash of a serial would be weak, because serial numbers can be guessed. The user sees a preview before exporting anything.

---

## 10. Report data model

This is a structure only. It contains no sample results, and real examples will be added once real runs exist.

| Section | Contents |
|---|---|
| `meta` | Schema version, tool version, rule version, start and end times, profile |
| `gpu` | Model, memory size, architecture, VBIOS, identity fields, cooling declaration |
| `host` | OS, kernel, driver, CUDA, CPU, RAM, PCIe slot, adapter used or not |
| `snapshots.before` and `snapshots.after` | Counters and link data, each marked as value, unsupported, or read error |
| `tests[]` | Test ID, tool version, state, duration, parsed values, raw log path, hash |
| `telemetry` | Time series for temperature, power, clocks, and throttling |
| `benchmarks[]` | Model hash, build, settings, repeat values, power, energy |
| `findings[]` | Rule ID, result state, evidence, plain-language explanation, next step |
| `not_tested[]` | Skipped tests and reasons |
| `integrity` | Hashes of raw files |

Each collected field stores its status as well as its value:

```json
{
  "ecc_uncorrected_aggregate": {
    "status": "unsupported",
    "value": null,
    "source": "nvidia-smi"
  }
}
```

---

## 11. Software support matrix

Many old GPUs fail because of software before hardware. The tool should warn users about this early and list known-good versions tested on real hardware.

| Generation | Status | Evidence |
|---|---|---|
| Maxwell, Pascal, Volta (includes GTX 1060 and V100) | R580 is reported as the final driver branch. Nvidia recommends staying on branch 580 and CUDA Toolkit 12.9 to build for these GPUs. | Nvidia developer blog and secondary reports |
| Newer generations | To be filled from Nvidia's architecture matrix | Not yet reviewed |

**Consequence:** Old-card support needs pinned builds. In particular, a V100 needs a CUDA 12 build of llama.cpp or similar software. The security-update end date for the final branch still needs confirming on Nvidia's own pages.

Each matrix entry should record the GPU, driver, CUDA, tool version, date tested, and result. Only tested combinations are marked "tested".

---

## 12. Testing the tool itself

This is the area where QA discipline matters most. A health tool that reports a false pass does more harm than having no tool.

### Evidence rules

- Parser tests use **real recorded output**, stored in `tests/captures/` with the card, tool version, date, and source.
- Scrub identifiers from captures without changing the values being tested.
- If a capture is unavailable, the code path remains marked **unverified** in the docs and release notes.

### Testing failure paths without faking data

| Path | Real test method |
|---|---|
| Thermal stop | Set the abort limit just below the card's real temperature under load |
| Power throttling | Lower the power limit where supported and confirm the reason is recorded |
| Missing fields | Use a consumer GPU, which really returns `[N/A]` for ECC |
| Tool crash or hang | Kill the real tool process during a run |
| Sensor failure | Stop the real sampler and confirm the tests are stopped |
| Interrupted run | Stop the process and confirm the report says it is incomplete |
| Bad memory or card instability | Needs a truly faulty card or a licensed real log. Tim's GTX 1660 has shown no fault so far, so this stays unverified |
| ECC errors | Needs a suitable faulty card or a licensed real log; stays unverified until then |

### Test plan

- **Repeatability:** Same card and setup, several runs, with the spread reported.
- **Test hygiene (Tim, 2026-11-08):** Run tests from a clean, known OS image where possible. Record the setup with each result, and only compare results whose setups match, so leftovers or background load can't skew comparisons.
- **Compatibility:** Every supported combination of GPU, driver, OS, and tool on the real matrix.
- **False-pass review:** Before each release, ask how each test could report success when it did not actually exercise the card.
- **False-fail review:** Confirm that cooling, adapter, and host problems are not blamed on the GPU.
- **Report review:** Have someone who did not build the tool read the report and explain it back.
- **Known limitation log:** Keep it public and current.

### Bug report standard

Each bug report should include the run folder, tool version, exact command, expected result, and actual result, with private data removed.

---

## 13. Phases

Each phase ends with an exit check. Nothing moves forward until the check passes.

### Phase 0: Decisions and inventory

- Reassemble Noodlecart as the test machine with its GTX 1660 Ti.
- Boot the Linux Mint USB for a first hardware check, following section 15.
- Install Mint beside Windows if there is disk space, record cooling and power supply, and enable remote access if wanted.
- Write down what Tim remembers about the spare GTX 1660's fault before testing it.
- Confirm Windows support for gpu-burn and gpu-fryer, and read LocalScore's submission specification.
- Decide the name and licence.
- **Exit:** Open questions in section 16 are answered or deliberately deferred.

### Phase 1: Inspector

- Build the project skeleton and `gpudoc inspect`. **Started 2026-11-06; see `HANDOFF.md` for what remains.** `--ssh` was added so a headless machine needs no Python. Local mode, WSL2, a direct NVML cross-check, and HTML reports were added on 2026-11-07.
- Capture real output from the GTX 1060 on both Windows and Linux.
- **Exit:** On Noodlecart, unsupported fields appear as unsupported, NVML and `nvidia-smi` agree or differences are explained, and no private data appears in redacted output.

### Phase 2: Runner and safety monitor

- Add the adapter system, sampler, stop logic, and memtest_vulkan.
- Evaluate gpu-burn and DCGM.
- Confirm which tools support the GTX 1060, including the driver and CUDA limits for its generation. DCGM may be limited or unavailable on consumer cards.
- **Exit:** Real thermal, crash, and interruption tests from section 12 pass on Noodlecart.

### Phase 3: Rules and reports

- Add the rules engine, reports, comparison, and export.
- **Exit:** A non-builder can correctly explain a real report, including what was not tested.

### Phase 4: AI benchmarks

- Add managed llama.cpp downloads, `llama-bench`, model pinning, power measurement, and cost calculation.
- Compare results against LocalScore where possible.
- Choose models that fit the card's real memory. Measure this in Phase 4, since larger reference models may not fit entirely on a 6 GB card.
- Add Wattever import and scoreboard-ready output after checking their formats.
- **Exit:** Repeat results stay consistent on the same setup, with the acceptable spread chosen from real measurements. Differences from LocalScore are understood.

### Deferred: V100 test bench

**Not currently planned.** Tim has no budget for hardware right now, and no project phase before this point depends on buying anything. The project can pause here with a working tool for consumer cards.

Revisit it only if money becomes available or someone donates suitable hardware. Buy only if all of these are true:

- [ ] Phases 1 to 4 pass on owned hardware.
- [ ] A suitable host machine is confirmed.
- [ ] Current sold prices have been checked.
- [ ] The board explicitly supports the specific card.
- [ ] A V100 still looks better than a used consumer GPU at the same total price.
- [ ] Tim approves the purchase.

| Item | Rough price (USD) | Evidence |
|---|---|---|
| SXM2-to-PCIe adapter | $57 to $100 | Listings; only one price is dated (May 2026) |
| V100 16 GB SXM2 | About $100 | One build report from May 2026 |
| V100 32 GB SXM2 | About $450 to $520 | One appraisal site; other sources quote higher |
| Fan, shroud, cabling | Unknown until the host is chosen | Not priced |
| **V100 16 GB total** | **About $200 to $300** | Thin evidence; prices may have changed |

Host needs to confirm, from memory unless noted:

- A full-length PCIe slot and physical clearance.
- Enough power. One adapter listing uses dual 8-pin connectors (from the listing); check the V100's power rating.
- A separate display output, since this card has none.
- Motherboard support for large-memory PCIe devices, usually called Above 4G Decoding.
- Strong, dedicated airflow. One buyer called an included heatsink useless (from a listing review).
- Driver and software compatibility from section 11.

### Phase 5: V100 test bench (deferred)

- Assemble in stages, with low-load checks first.
- Publish a real setup guide, including what went wrong.
- **Exit:** A complete report on real V100 hardware, with the cooling setup documented.

### Phase 6: Limited release and public results

**Requires Tim's explicit go-ahead.** Until then, everything stays private and no one is contacted.

- Clean the repo of personal details and invite a small group of testers.
- Publish results as static files from Git.
- **Exit:** People who did not build the tool get usable reports on hardware not owned by Tim.

### Phase 7: Next project

Choose from section 14 using real evidence from earlier phases.

---

## 14. Other ideas and roadmap

| Priority | Idea | What it means | Depends on | Current opinion |
|---|---|---|---|---|
| 1 | Test and grade | The tool in this plan | Nothing | Start here |
| 2 | Real benchmarks | Measured speed, memory, power, and cost per model | Test tool | Build alongside idea 1, without cloning LocalScore |
| 3 | Software packaging | A setup tool that installs compatible software and offers only models that fit | Support matrix | Strong follow-up; the matrix makes it possible |
| 4 | Private AI boxes | Preconfigured local AI for organizations with sensitive data | Ideas 1 to 3 | Promising, but support burden is the main risk |
| 5 | Waste-heat computing | Run batch work when the heat is useful | Reliable batch workloads | Good small pilot, not a first product |
| 6 | GPU donation route | Companies donate retired cards to a charity | Testing process | Depends on a donor and legal setup |
| 7 | Legal support | Push for documentation and support when vendors end support | Evidence from the project | Best as later advocacy |

### Private AI boxes

Run transcription, translation, or document search locally. This fits Case Tech and Compute for Hope, but supporting clinics or seniors over time would be harder than building the box. Older hardware also needs a clear replacement and failure plan.

Law 25 does not ban sending personal information outside Quebec, but it requires an assessment first. Keeping data on site may remove that specific issue, while other privacy duties remain. Get legal advice before marketing this as a compliance benefit. Most online claims on this point come from vendors selling local hosting.

### Waste heat

Nearly all electricity used by a GPU ends up as heat. In a space heated by electric baseboards, that heat can partly replace heating during winter, which lowers the real energy cost of computing. A heat pump changes the math because it delivers more heat per unit of electricity.

The idea works best with batch jobs that can run whenever heat is wanted. Measure it in a real room before making claims. Qarnot's Brescia site is listed as operational with heat going to a district network, but I found no 2026 confirmation. I found nothing current on Heata.

### Heat ledger (idea, 2026-11-06)

Almost all of a GPU's electricity becomes heat, so GPUDoc's power data can double as a heat record in any climate. The app would report measured heat and estimate what it means for the room. This should start as a GPUDoc module, not a separate app. The name FreeHeat has not been checked.

- **Net cost per job:** Electricity used, plus estimated cooling cost in hot weather, or minus useful heating in cold weather.
- **Best time to run:** Move batch work to cooler hours, cheaper rates, or useful heating periods.
- **Room limits:** Warn when a closet or small room is likely to overheat.
- **Cooling history:** Compare a card with its own earlier temperature curve to catch dust or fan problems.
- **Power tuning:** Find the power limit with the best output per watt, which helps in every climate.
- **Hot water, later:** Hot water is needed all year, but this requires real plumbing and safety work.

**Waste-heat sensor experiment (Tim likes this, 2026-11-06):** Power a temperature sensor purely from GPU waste heat through a thermoelectric device. The aim is to build something new, not to beat a USB port on practicality. Measure the power harvested and its effect on GPU temperature, since the device adds thermal resistance. No hardware purchase is planned for now.

### Donation route

Retired cards could go through testing, then to schools, nonprofits, or researchers. Open questions include charity status, tax receipts, data and export rules, shipping, recycling failed cards, and whether receipts are possible. Get legal and tax advice first.

### Legal support

Quebec's Bill 29 introduced planned-obsolescence and repair measures, including access to repair information. The good-working-order warranty was scheduled to begin on October 5, 2026, but I could not confirm that it took effect as scheduled. It is aimed at consumer goods, so data-center GPUs sold to businesses may fall outside it. That scope point is my inference and has not been legally checked.

---

## 15. Hardware available today

| Machine | GPU | Evidence | Planned use |
|---|---|---|---|
| Noodlecart | GTX 1660, 6 GB, in the top slot. Tim plans to add the GTX 1060, 6 GB as a second card | Direct checks and Tim, 2026-11-06 and 07 | **Project test machine**, with Windows, WSL2, and later bare-metal Linux |
| Taichi | Two GTX 1660 Ti cards, which Noodlecart's Windows still remembers | Tim, 2026-11-07 | **Not available for testing**: they run the JAZZ RAG |
| Spare, swapped into Noodlecart 2026-11-06 | GTX 1660, 6 GB. Tim's fault memory is vague: it came during multi-GPU Petals experiments in WSL2, so the card may never have been faulty. Passed the 5-minute memory test with driver 610.88, peaking at 62 C | Direct check and Tim, 2026-11-06 | **No evidence of a fault so far.** Not a known-bad test card |
| PurpleThunder | RTX 4070 | Tim uses it mostly for gaming and some AI work | **Not for this project.** Code writing only |
| BBB | Not checked | Runs live services | Not used |
| Taichi | Not checked | Runs the RAG service | Not used |

### Using the Linux Mint USB

**Needs temporary peripherals.** Noodlecart normally runs with no monitor, keyboard, or mouse, so booting and installing from the USB needs them connected for that session.

**Good for the first check.** Tim already has the USB, so it costs nothing and leaves the installed system alone. Use it to confirm the machine starts, which GPUs are present, that fans spin, and the PCIe link.

**Not suitable for real test runs.** A plain live USB discards changes on reboot, including installed Nvidia drivers, downloads, and results. Installing the driver also normally needs a reboot, so a live session is a poor fit unless it is set up with persistent storage.

- **Save anything important** to another drive or the network before rebooting.
- **If the screen goes black,** try the compatibility boot option, then check Secure Boot and Fast Boot in the BIOS. There is at least one report of this with Mint 22 on an older Nvidia GPU.
- **For real runs,** install Mint to disk.
- **Check the Mint version on the USB,** since an old release may not suit current drivers.

### Noodlecart storage

**Read directly from Noodlecart (2026-11-06):**

- **System:** Windows 11 Pro for Workstations, build 22631, with 32 GB RAM, on an ASRock Z390 Phantom Gaming 4S/ac.
- **Storage:** One 477 GB Team SATA SSD, reported healthy, with 160 GB free on C:.
- **Old data:** `C:\jazz-embed` and `C:\qdrant` are still present. Tim says on 2026-11-06 that this data can be lost, so no backup or comparison with Taichi is needed. Actual deletion still gets confirmed first, and the NVMe plan does not require it.
- **CPU:** Intel Core i5-9600KF, which has no integrated graphics. A working GPU is therefore needed for any screen output, including the BIOS and a Mint USB install.
- **GPU:** GTX 1060 6 GB, working, with driver 560.94, idle at 38 C and 45% fan. It started working after Tim moved it off a PCIe riser into a slot directly and connected its power cable. Both changed together, so the riser has not been proven faulty. Tim confirmed it is a 1060, not the 1660 Ti he remembered. Windows also remembers two GTX 1660 Ti cards from an earlier setup.
- **Old JAZZ tasks:** Scheduled tasks `JazzEmbed` and `Qdrant` exist and showed as Ready, with port 8004 closed earlier that day.
- **Old JAZZ data details:** `C:\qdrant` is 0.78 GB with collections `biofile`, `conversations`, and `memories`; its newest file is dated 06/23/2026. `C:\jazz-embed` is 4.88 GB; its newest file is dated 03/04/2026.
- **User data:** `C:\Users\twwca` is 224.5 GB, and its contents have not been reviewed.

**From published specs, not checked on the machine:** The board has one M.2 slot that supports NVMe and can boot from it, plus two full-length PCIe slots that run at x16/x4 with two cards installed.

The old JAZZ and Qdrant data is expendable. `C:\Users\twwca` has not been reviewed, so that approval does not cover it. A spare 128 GB NVMe may be available from the old Pat desktop being refurbished for Compute for Hope. Neither has been checked.

**Preferred layout:** Mint on the NVMe, with Windows on a separate drive if one is present and works. Separate drives mean a Linux install does not need to touch the Windows drive.

**Before erasing anything:**

1. Review `C:\Users\twwca` before erasing the Noodlecart drive. Tim confirms before anything is erased.
2. Confirm that the Pat desktop does not need the NVMe and that it holds nothing needed for that refurb.
3. Check the board's manual for the M.2 slot's exact drive and SATA-sharing rules.

**Fallback if the NVMe is unavailable:** Shrink C: and install Mint in the free space. This costs nothing, but it changes the Windows drive, so make a backup first.

### What Noodlecart can and cannot prove

**It can test:**
- The inspector, runner, safety stops, reports, and redaction.
- Memory testing and error handling on a consumer card with no ECC reporting.
- Real benchmarks on smaller models, within the memory available.
- The legacy software path, since the GTX 1060 is in the same reported end-of-support group as the V100. This is a useful rehearsal, but it does not prove V100 behaviour.
- Identity reporting, since the tool should show what a card reports. In this case, the owner's memory was what needed correcting.
- Failure detection, if the spare card's fault is real and shows up in testing.

**It cannot test:**
- ECC counters, page retirement, or row remapping on real values. Those rules stay **unverified** until the tool runs on suitable hardware or a real capture is available.
- Data-center features, such as SXM adapters or higher DCGM diagnostic levels.
- Large-model performance.

This changes the first target: version 1 is a tool for **used consumer cards**, with data-center support designed in but marked unproven. The project's later reuse goals for retired data-center GPUs remain, but depend on access to that hardware.

### Protocol for the faulty GTX 1660

A real faulty card is valuable test data, so treat it as a reference sample.

1. **Write down the remembered symptoms first,** so the tool's result can be compared with what was expected.
2. **Inspect it unpowered.** If there is burn damage, a burnt smell, or leaking or bulging components, do not power it on.
3. **Test it alone** in the machine, removing the working card first to reduce risk to it. The CPU has no integrated graphics, so a dead card may leave no screen output. Set up remote access first, and confirm the machine still boots without a screen.
4. **Start with inspection,** then a light memory test, before any heavy load.
   Noodlecart runs headless, so remote checks cannot see display faults or BIOS messages. Connect a monitor if the remembered fault was visual or the machine does not come back on the network.
5. **Save all raw logs** as real test captures, with identifiers removed.
6. **Do not repair it** until its failure has been captured.

**Possible outcomes:** The fault may not reproduce, or may come from a fan, power connection, driver, or host. A clean result here would not prove the card is healthy, and would become an honest test of how the tool reports uncertainty.

---

## 16. Open questions for Tim

1. **Adding the GTX 1060:** Does Noodlecart's power supply have capacity and connectors for both cards? Its GPU budget is zero for the rest of 2026 (Tim, 2026-11-07).
   **Noodlecart storage:** Is the spare 128 GB NVMe in the old Pat desktop available?
2. **Spare GTX 1660:** What do you remember about the fault? Please write this down before any testing.
   **Noodlecart's future role:** If it later becomes the radio machine, testing should move first, because stress runs should not share a machine with a live air chain.
3. **Project ownership:** Should this live under Case Tech, Compute for Hope, or stand alone?
4. **Open source, if it goes public later:** I recommend Apache-2.0 for the tool and CC BY 4.0 for public results. Do you agree?
5. **Commercial intent:** Is this free public infrastructure, or is paid testing for refurbishers a possible future service?
6. **Charity status:** Can Compute for Hope issue official donation receipts today?

---

## 17. Risks

| Risk | Impact | Response |
|---|---|---|
| False pass | A faulty card looks healthy | Before and after checks, memory tests, and clear limits |
| Fake or edited reports | Buyers are misled | Encourage buyer reruns and state the limit plainly |
| No budget for data-center hardware | ECC and data-center rules stay unverified | Mark them unproven, and seek donated hardware or real captures |
| Cheap supply disappears | The V100 path loses appeal | Keep the tool GPU-agnostic |
| Prices change after a market fall | Comparisons go stale | Date all prices and keep them out of core results |
| Software support ends | Old cards stop working with new tools | Support matrix and pinned builds |
| Stress testing damages a card | Financial loss and bad reputation | Stepped tests, stop limits, and clear warnings |
| Another project moves into this space | Duplicate work | Glimmer and Wattever are new and active, so watch them and contribute where it makes sense |
| No known-faulty card on hand; the GTX 1660 has shown no fault | Failure paths stay unverified | Keep the fault protocol, seek other real faulty cards, and label gaps openly |
| Too few public submissions | Benchmarks stay thin | Keep the tool useful for one person with no database |
| Scope spreads across all seven ideas | Nothing ships | Follow the phase gates |

---

## 18. Measures of success

- A person who has never used the tool can get a correct report on a real card without help.
- The same card and setup produce consistent results across repeated runs.
- Every field in a report can be traced to raw evidence.
- Reports state what was not tested.
- At least one person outside this project finds it useful enough to run on their own hardware.
- Eventually, a real used card is reused because of this evidence, or a bad one is caught before purchase.

---

## 19. Verification status

| Claim | Status |
|---|---|
| `nvidia-smi` field names, RTX 4070 data, driver 621.01, `[N/A]` ECC mode | **Verified directly** in a one-time planning check, 2026-11-05 |
| Noodlecart GTX 1060 6 GB, driver 560.94, `[N/A]` ECC | **Verified directly** on Noodlecart and confirmed by Tim, 2026-11-06 |
| GTX 1660 Ti cards still owned | **Unconfirmed**; only Windows device records and older notes |
| Spare GTX 1660 is faulty | **Unconfirmed**; Tim's recollection, with symptoms not yet recorded |
| `gpudoc` availability | Direct PyPI, npm, crates.io, and GitHub account checks, 2026-11-06; trademarks not checked |
| GitHub stars, last push, and licences in `GAPS.md` | **Verified directly** from GitHub, 2026-11-06 |
| llama.cpp build sizes | **Verified directly** from GitHub release data, build `b12144`, 2026-11-06; sizes change with each build |
| Live USB limits, Mint driver steps, and black-screen report | Search summaries of guides and forum posts; test on Noodlecart |
| DCGM levels, level 1 limit for non-data-center cards, memory bandwidth vs integrity | Nvidia docs, seen through search summaries |
| Row remapping from Ampere onward, 64 page retirement maximum, Xid 48/63/64 | Nvidia docs, seen through search summaries |
| R580 and CUDA 12.9 guidance for Volta | Nvidia blog plus secondary reports; confirm exact dates |
| LocalScore features and licence | Project pages through search summaries |
| memtest_vulkan licence and purpose | Arch and related package pages through search summaries |
| Law 25 and Bill 29 points | Mostly law-firm and vendor material; **not legal advice** and in-force status unconfirmed |
| Prices | Thin listing and blog evidence; **recheck before buying** |
| Windows support for gpu-burn and gpu-fryer; DCGM per-product feature data for V100, A100, and 1660 Ti | **Unverified** |
| PyTorch and current llama.cpp support on Volta | **Unverified** |
| Host hardware needs, V100 power rating | **From memory unless noted; verify** |
| Effort, durations, and upfront cost | **Estimates** |

---

## 20. Sources

**Nvidia**
- [DCGM Diagnostics](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html)
- [dcgmi diag reference](https://docs.nvidia.com/datacenter/dcgm/latest/reference/command-line-reference/dcgmi/dcgmi-diag.html)
- [DCGM Memory Bandwidth Plugin](https://docs.nvidia.com/datacenter/dcgm/latest/reference/diagnostics/plugins/memory-bandwidth.html)
- [GPU Memory Error Management: Row Remapping](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/row-remapping.html)
- [GPU Memory Error Management: User Visible Statistics](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/latest/user-visible-statistics.html)
- [Navigating GPU Architecture Support](https://developer.nvidia.com/blog/navigating-gpu-architecture-support-a-guide-for-nvidia-cuda-developers/)

**Driver and CUDA reporting**
- [Tom's Hardware on CUDA support changes](https://www.tomshardware.com/pc-components/gpus/nvidia-to-drop-cuda-support-for-maxwell-pascal-and-volta-gpus-with-the-next-major-toolkit-release)
- [The Register on CUDA deprecation](https://www.theregister.com/2025/01/27/nvidia_deprecates_cuda_support/)
- [Guru3D on driver changes](https://www.guru3d.com/publish/comments/nvidia-gpu-driver-changes-maxwell-pascal-and-volta-unsupported-after-release-580-series/)

**Tools**
- [LocalScore on GitHub](https://github.com/cjpais/LocalScore)
- [LocalScore on Phoronix](https://www.phoronix.com/news/LocalScore-AI-LLM-Benchmark)
- [memtest_vulkan package](https://archlinux.org/packages/extra/x86_64/memtest_vulkan/)
- [memtest_vulkan announcement](https://winraid.level1techs.com/t/announcing-memtest-vulkan-ive-created-opensource-video-memory-stability-test/90263)

**Hardware and pricing**
- [Hackaday V100 PCIe build](https://hackaday.com/2026/05/09/getting-a-proprietary-bus-gpu-onto-pcie-enables-cheaper-local-llms-for-now/)
- [eBay adapter listing](https://www.ebay.com/itm/147455217490)
- [camelcamelcamel adapter history](https://camelcamelcamel.com/product/B0GD839HKV)
- [AM Compute V100 appraisal](https://www.amcompute.com/appraisals/tesla-v100-sxm2-32gb)

**Law**
- [Osler on Bill 29](https://www.osler.com/en/insights/updates/yes-quebec-consumer-protection-laws-actually-can-get-stricter-what-you-need-to-know-about-the-new/)
- [McCarthy on Bill 29 draft regulations](https://www.mccarthy.ca/en/insights/blogs/consumer-markets-perspectives/draft-regulations-clarify-warranty-and-repair-obligations-under-quebecs-bill-29-planned-obsolescence)
- [Law 25 and data transfers](https://private-ai.com/2024/05/13/law25-data-transfer/)

**Waste heat**
- [Qarnot Brescia listing](https://baxtel.com/data-center/qarnot-brescia)
- [Data Center Dynamics on waste heat](https://datacenterdynamics.com/en/analysis/making-the-most-of-your-waste-heat)
