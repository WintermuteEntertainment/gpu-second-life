# Open-Source Tooling Gaps: Used GPUs in Home Labs

**Date:** 2026-11-06
**Question:** What is missing for testing and benchmarking older or used GPUs in home labs, with a path to larger cards such as the V100 and A100?

## Short answer

Most of the individual parts already exist and many are actively maintained. I found no open-source tool aimed at a home-lab owner that takes one used GPU, adapts its testing to that card, and explains the combined result. GPUDoc should fill that space by running and reading other tools, then share results back to them while keeping its own dataset.

**Confidence: medium to high for the main gap.** The evidence includes direct GitHub data and project READMEs, but GitHub repository search mostly matches names and descriptions, and I reviewed only the top results for each query. A project with different wording could still exist.

## What exists today

GitHub figures were read directly on 2026-11-06. Platform and feature notes come from project READMEs or search summaries.

### Health and stress tools

| Project | Stars | Last push | Licence | What it offers | Limits for this use | Plan |
|---|---|---|---|---|---|---|
| [memtest_vulkan](https://github.com/GpuZelenograd/memtest_vulkan) | 989 | 2026-06-02 | Zlib | VRAM test on Windows and Linux | Memory only | Core adapter |
| [gpu-burn](https://github.com/wilicc/gpu-burn) | 2,383 | 2026-10-02 | BSD-2-Clause | Multi-GPU CUDA stress test | Windows support unverified | Linux load adapter |
| [gpu-fryer](https://github.com/huggingface/gpu-fryer) | 413 | 2026-09-24 | Apache-2.0 | Stress test, throttling and performance check | Linux-focused; compares GPUs with the best in the system, so a single card has no peer | Optional Linux adapter |
| [DCGM](https://github.com/NVIDIA/DCGM) | 813 | 2026-10-27 | Apache-2.0 | Data-center health and diagnostics | Linux; consumer cards get level 1 unless higher support is documented | V100 and A100 adapter |
| [nvbandwidth](https://github.com/NVIDIA/nvbandwidth) | 794 | 2026-07-28 | Apache-2.0 | Bandwidth measurement | Not a health verdict | Possible adapter |
| [GPUd](https://github.com/leptonai/gpud) | 498 | 2026-11-05 | Apache-2.0 | GPU monitoring and diagnostics for production infrastructure | Linux; aimed at clusters | Optional evidence source on Linux |
| [Glimmer Burn-In](https://github.com/baldwinSPC/glimmer-burnin) | 3 | 2026-11-03 | Apache-2.0 | Hardware acceptance verdicts for GPU fleets | Requires Kubernetes; aimed at fleets and interconnects | Borrow ideas; complementary |
| [GPUStressTest](https://github.com/NVIDIA/GPUStressTest) | 128 | 2025-07-08 | Unclear on GitHub | Tesla compute stress | Licence needs checking | Avoid for now |
| StressLab, FurMark 2 | Not checked | Not checked | FurMark licence unconfirmed | General PC or graphics stress | Not compute-focused | Do not depend on them |

### AI benchmark and fit tools

| Project | Stars | Last push | Licence | What it offers | Limits for this use | Plan |
|---|---|---|---|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | 133,504 | 2026-11-06 | MIT | Inference engine and `llama-bench` | Engine, not a used-card report | Core benchmark engine |
| [LocalScore](https://github.com/cjpais/LocalScore) | 137 | 2026-11-01 | Apache-2.0 | Speed benchmark and public database | Single GPU; only its official client submits for now; no health data | Run it and contribute results |
| [Wattever](https://github.com/lpalbou/Wattever) | 1 | 2026-11-04 | MIT | Windows, macOS, and Linux LLM benchmark with optional GPU power and JSON results | New; depends on the user's inference server | Import results; watch the project |
| [llm-bench](https://github.com/nemmusu/llm-bench) | 1 | 2026-10-15 | MIT | Nvidia desktop benchmark with speed, VRAM, and power | Desktop-focused | Watch |
| [local-llm-energy](https://github.com/wskel/local-llm-energy) | 0 | 2026-10-31 | MIT | Energy per token and cost vs hosted models | Narrow scope | Reference for cost method |
| [llmfit](https://github.com/AlexsJones/llmfit) | 38,693 | 2026-11-05 | MIT | Which models fit this hardware | Fit, not health; speed accuracy varies by source | Use for model suggestions |

### Shared results and knowledge

- [llama.cpp CUDA scoreboard](https://github.com/ggml-org/llama.cpp/discussions/15013) and [Vulkan scoreboard](https://github.com/ggml-org/llama.cpp/discussions/10879): Community tables, including some older cards. Tim could post real results.
- [OpenBenchmarking.org](https://openbenchmarking.org/test/pts/llama-cpp-2.5.0): Structured llama.cpp results. Result pages offer JSON exports, and redistribution terms still need checking.
- [GPU Smith checklist](https://gpusmith.com/articles/en/buying-used-refurbished-data-center-gpus-checklist), [Level1Techs reports](https://forum.level1techs.com/t/need-advice-v100-ecc-retired-page-error-exceeds-63-and-corrupted-inforom/201583), and [V100 ECC guides](https://knightli.com/en/2026/04/23/check-tesla-v100-ecc-errors/): Useful used-card knowledge, mostly manual.

## Gaps, strongest first

### 1. Nothing connects consumer cards to data-center cards (Tim's top pick)

**Missing:** One home-lab workflow that adapts to the card in front of it:

| Card type | Memory evidence | Tools |
|---|---|---|
| GTX 1060, 1660, 1660 Ti | Pattern test, since ECC data is not expected | memtest_vulkan, load test, DCGM level 1 if it works |
| V100 | Pattern test, ECC, page retirement | Add DCGM and legacy software path |
| A100 | Pattern test, ECC, row remapping | Add DCGM and current software path |

**Evidence:** Consumer tools stop at memory and stress. DCGM, GPUd, and Glimmer focus on data-center operations. I found nothing that joins them for one used card in a home lab.

### 2. No used-GPU acceptance test for home labs

**Missing:** One run covering identity, history, memory, load, heat, PCIe link, and before-and-after error changes, followed by a plain explanation.

**Evidence:** Searches for used-card health tools returned nothing relevant. Glimmer proves the concept but requires Kubernetes and targets fleets. Its fail-closed rule is worth adopting: a required test that cannot run must never produce a pass.

### 3. Used-card warning signs are not automated

**Missing:** Automated checks for reports such as:

- All-zero lifetime ECC counts on a fleet-retired card, which may have been cleared.
- InfoROM corruption.
- Errors that only appear under load.
- Serial mismatches between the card, `nvidia-smi`, and invoice.

**Evidence:** Searches for ECC and retired-page checking tools returned nothing relevant. Most of this knowledge lives in guides and forum threads. Findings should report the signal without accusing a seller of fraud.

### 4. No check for whether the software still works

**Missing:** A warning that a card's software path is closing, plus tested driver, CUDA, and engine combinations. Fit tools answer "will the model fit?" I saw nothing answering "which versions work on this card?"

**Evidence:** Volta shows the need. Nvidia's guidance keeps V100 builds on driver branch 580 and CUDA Toolkit 12.9. This could become a standalone data file others can use.

### 5. Condition, speed, and energy are not joined across generations

**Missing:** Results that link a specific card's condition, setup, speed, and energy use. LocalScore covers speed, Wattever covers speed and power, and scoreboards cover some older cards.

**Evidence:** This gap is narrower than it first looked. The project should keep its own dataset, while contributing compatible results to the existing projects.

### 6. Windows load testing

**Missing:** A maintained, open-source compute stress test confirmed to work on Windows.

**Evidence:** Linux is well covered by gpu-burn and gpu-fryer, but I did not verify Windows support for either. A sustained llama.cpp run could serve as the Windows load test. It would be a real AI workload, though it may stress the card less than a dedicated tool, and reports must say so.

### Smaller gaps

- **Multiple GPUs:** LocalScore is single-GPU for now. Wattever has multi-GPU studies.
- **Change over time:** Comparing the same card across dates or repairs.
- **Adapter and cooling context:** Keeping SXM adapters and improvised cooling from being mistaken for GPU faults.

## What to adapt rather than build

| Do not build | Use instead |
|---|---|
| VRAM test | memtest_vulkan |
| Stress tools | gpu-burn and gpu-fryer on Linux |
| Data-center diagnostics | DCGM, with GPUd as optional evidence |
| LLM benchmark engine | `llama-bench` |
| Public speed leaderboard | LocalScore |
| Model fit catalogue | llmfit |
| Fleet acceptance system | Glimmer |

## Recommended position

**GPUDoc gives home-lab owners a single report on a used GPU by choosing the right existing tools, interpreting their results, and adding used-card checks and software support data.** Its dataset stays under the project's control, and its results can be shared with LocalScore, llama.cpp scoreboards, and other compatible projects.

Gaps 1 to 3 define version 1. Gap 4 is the first add-on.

## Still to verify

- Test what each tool actually does on the GTX 1060, on both Windows and Linux.
- Check the DCGM per-product feature data for the V100, A100, and GTX 1060.
- Confirm Windows support for gpu-burn and gpu-fryer.
- Check licences and terms before redistributing data from any other project.
- Check `GPUStressTest` licence terms if it becomes useful.
- Read LocalScore's submission specification. Do not contact any maintainers for now (Tim, 2026-11-06).

## Other sources

- [DCGM installation and feature availability](https://docs.nvidia.com/datacenter/dcgm/latest/installation.html)
- [DCGM diagnostics](https://docs.nvidia.com/datacenter/dcgm/latest/learn/modules/dcgm-diagnostics.html)
- [Mozilla's LocalScore announcement](https://builders.mozilla.org/announcing-localscore/)
- [TokenPowerBench](https://www.alphaxiv.org/abs/2512.03024)
- [Consumer GPU energy study](https://arxiv.org/html/2608.00008v2)
