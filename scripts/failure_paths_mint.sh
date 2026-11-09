#!/bin/bash
# Real failure-path tests for `gpudoc test` (PLAN.md section 12), run on Noodlecart's Mint install from ~/gpudoc.
# Each test briefly stresses one card. Tim approved running these on 2026-11-08.
# On exit, for any reason, it restores the card's power limit and stops any leftover memtest_vulkan.
set -u
cd ~/gpudoc
TOOL=~/gpudoc/tools/memtest_vulkan-v0.5.0/memtest_vulkan
GPU=${GPU:-00000000:01:00.0}
OUT=~/gpudoc/gpudoc-runs/failure-paths-$(date -u +%Y%m%d-%H%M%S)
[ -e "$OUT" ] && { echo "ABORT: $OUT exists"; exit 3; }
mkdir -p "$OUT"
DEFAULT_PL=$(nvidia-smi --id="$GPU" --query-gpu=power.default_limit --format=csv,noheader,nounits | xargs)
MIN_PL=$(nvidia-smi --id="$GPU" --query-gpu=power.min_limit --format=csv,noheader,nounits | xargs)
gpudoc() { PYTHONPATH=src exec python3 -m gpudoc test --tool-path "$TOOL" --gpu "$GPU" --yes --out "$OUT/$1" "${@:2}"; }

cleanup() {
    now=$(nvidia-smi --id="$GPU" --query-gpu=power.limit --format=csv,noheader,nounits | xargs)
    [ "${now%.*}" != "${DEFAULT_PL%.*}" ] && sudo nvidia-smi -i "$GPU" -pl "$DEFAULT_PL" >/dev/null && echo "cleanup: power limit restored to $DEFAULT_PL W"
    n=$(pgrep -c -x memtest_vulkan || true)
    [ "$n" != "0" ] && { echo "cleanup: stopping $n leftover memtest_vulkan"; pkill -9 -x memtest_vulkan; }
    echo "cleanup done: power limit $(nvidia-smi --id="$GPU" --query-gpu=power.limit --format=csv,noheader), memtest left $(pgrep -c -x memtest_vulkan || true)"
}
trap cleanup EXIT

cool() {  # wait for the card to drop to 45 C or below, at most 3 minutes
    for _ in $(seq 1 36); do
        t=$(nvidia-smi --id="$GPU" --query-gpu=temperature.gpu --format=csv,noheader,nounits | xargs)
        [ "$t" -le 45 ] && break
        sleep 5
    done
    echo "start temperature: $t C"
}
wait_for_tool() { for _ in $(seq 1 120); do pgrep -x memtest_vulkan >/dev/null && return 0; sleep 1; done; return 1; }
leftovers() { echo "memtest_vulkan processes now: $(pgrep -c -x memtest_vulkan || true)"; }

echo "### card $GPU, power limit default $DEFAULT_PL W, min $MIN_PL W, results in $OUT"

echo; echo "### 1. Temperature stop: limit set to 50 C, below this card's load temperature"
cool; ( gpudoc 1_temperature_stop --temp-limit 50 ); leftovers

echo; echo "### 2. Tool crash: memtest_vulkan's main process killed with SIGKILL 20 s into the run"
cool; ( gpudoc 2_tool_killed ) & G=$!
if wait_for_tool; then sleep 20; pkill -9 -o -x memtest_vulkan && echo "killed the oldest memtest_vulkan"; fi
wait $G; leftovers

echo; echo "### 3. Interrupted run: GPUDoc sent SIGTERM 20 s into the run"
cool; ( gpudoc 3_gpudoc_sigterm ) & G=$!
if wait_for_tool; then sleep 20; kill -TERM $G && echo "sent SIGTERM to gpudoc pid $G"; fi
wait $G; leftovers

echo; echo "### 4. GPUDoc killed outright: SIGKILL 20 s into the run, so it can't clean up or write a result"
cool; ( gpudoc 4_gpudoc_sigkill ) & G=$!
if wait_for_tool; then sleep 20; kill -KILL $G && echo "sent SIGKILL to gpudoc pid $G"; fi
wait $G 2>/dev/null; sleep 3; leftovers

echo; echo "### 5. Power cap: limit lowered to $MIN_PL W for a 60 s run"
cool; sudo nvidia-smi -i "$GPU" -pl "$MIN_PL"
( gpudoc 5_power_cap --max-seconds 60 ); leftovers
sudo nvidia-smi -i "$GPU" -pl "$DEFAULT_PL"

echo; echo "### Results"
for f in $(find "$OUT" -name test.json | sort); do
    python3 - "$f" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
s = r.get("summary", {})
print(f"{sys.argv[1].split('/')[-4]}: {r['state']}, stop {s.get('stop_reason')}, peak {s.get('peak_temp')} C, "
      f"tool stopped {r['tool_exit'].get('stopped')} ({r['tool_exit'].get('method')}, leftovers {r['tool_exit'].get('leftovers')}), "
      f"driver log {'read' if r.get('driver_log') is not None else 'not read'}")
for x in r["findings"]:
    if x["state"] != "NOTE" or x["rule"] in ("PWR-001", "THM-003"):
        print(f"  - {x['state']} {x['rule']}: {x['text']}")
EOF
done
for d in "$OUT"/*/; do [ -z "$(find "$d" -name test.json)" ] && echo "$(basename "$d"): no result written"; done
exit 0
