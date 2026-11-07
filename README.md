# GPUDoc

GPUDoc produces evidence-based reports on used GPUs. It's an early, private project, and nothing here is a health verdict or a guarantee about a card.

## Current status

- `gpudoc inspect` reads a card's identity, settings, and error history without stressing it.
- `gpudoc test` is a Phase 2 draft and hasn't been run on real hardware yet.
- See [HANDOFF.md](HANDOFF.md) for current status, [PLAN.md](PLAN.md) for the plan, [GAPS.md](GAPS.md) for existing tools, and [NOTES.md](NOTES.md) for lessons and open items.

## Run it

Git Bash, from this folder, using no third-party packages:

```bash
PYTHONPATH=src python -m gpudoc inspect --ssh USER@HOST --redact
```

Run it without `--ssh` on the machine that has the GPU. That also adds a direct NVML cross-check.

Each run writes a new folder under `gpudoc-runs/`. Only share the `inspect.redacted.*` files. Everything else there may contain identifiers.

## Test it

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Tests use real captured output, with only identifiers scrubbed. See [tests/captures/README.md](tests/captures/README.md).
