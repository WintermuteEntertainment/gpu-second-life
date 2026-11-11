"""Reads and sets a card's clock offsets through Nvidia's library (NVML).

An offset shifts the card's whole clock table up or down by a number of MHz. Zero is stock.
Reading works for any user. Setting needs root on Linux (checked on Mint, driver 580.178.04) and worked from
an administrator shell on Windows (driver 581.80).

Two generations of calls exist. The newer nvmlDeviceGetClockOffsets / nvmlDeviceSetClockOffsets pair is tried
first: on Windows 581.80 it works where the older VfOffset calls answer Not Supported, and setting performance
state P0 moved every state together. The older pair is the fallback; it worked on Linux 580.178.04. This file has no imports from the rest of GPUDoc, so it
can be run by path under sudo:  sudo -n python3 clocks.py set 00000000:01:00.0 --gpu 25
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from ctypes import byref, c_char_p, c_int, c_uint, c_void_p, sizeof

GRAPHICS, MEMORY = 0, 2  # NVML clock types
OLD = {GRAPHICS: ("nvmlDeviceGetGpcClkVfOffset", "nvmlDeviceGetGpcClkMinMaxVfOffset", "nvmlDeviceSetGpcClkVfOffset"),
       MEMORY: ("nvmlDeviceGetMemClkVfOffset", "nvmlDeviceGetMemClkMinMaxVfOffset", "nvmlDeviceSetMemClkVfOffset")}


class _ClockOffset(ctypes.Structure):
    # nvmlClockOffset_v1_t from nvml.h
    _fields_ = [("version", c_uint), ("type", c_uint), ("pstate", c_uint), ("offset", c_int), ("min", c_int), ("max", c_int)]


def _info(kind: int, offset: int = 0) -> _ClockOffset:
    i = _ClockOffset()
    i.version, i.type, i.pstate, i.offset = sizeof(_ClockOffset) | (1 << 24), kind, 0, offset
    return i


def _load():
    if sys.platform != "win32":
        return ctypes.CDLL("libnvidia-ml.so.1")
    for path in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"),
                 os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll")):
        if os.path.exists(path):
            return ctypes.WinDLL(path)
    raise OSError("nvml.dll not found")


class _Session:
    """One NVML session with a handle for the card on a given PCI bus ID."""

    def __init__(self, bus_id: str):
        self.lib = _load()
        self.lib.nvmlErrorString.restype = c_char_p
        self.lib.nvmlDeviceGetHandleByPciBusId_v2.argtypes = [c_char_p, c_void_p]
        for fn in ("nvmlDeviceSetGpcClkVfOffset", "nvmlDeviceSetMemClkVfOffset"):
            if hasattr(self.lib, fn):
                getattr(self.lib, fn).argtypes = [c_void_p, c_int]
        self.check(self.lib.nvmlInit_v2(), "init")
        self.handle = c_void_p()
        try:
            self.check(self.lib.nvmlDeviceGetHandleByPciBusId_v2(bus_id.encode(), byref(self.handle)), f"find card at {bus_id}")
        except RuntimeError:
            self.lib.nvmlShutdown()
            raise

    def text(self, code: int) -> str:
        return self.lib.nvmlErrorString(code).decode()

    def check(self, code: int, what: str) -> None:
        if code != 0:
            raise RuntimeError(f"{what}: {self.text(code)}")

    def close(self) -> None:
        self.lib.nvmlShutdown()

    def get(self, kind: int) -> tuple[int, int, int, str]:
        """(offset, min, max, which call answered) for one clock type."""
        if hasattr(self.lib, "nvmlDeviceGetClockOffsets"):
            i = _info(kind)
            if self.lib.nvmlDeviceGetClockOffsets(self.handle, byref(i)) == 0:
                return i.offset, i.min, i.max, "ClockOffsets"
        get, rng, _ = OLD[kind]
        v, lo, hi = c_int(), c_int(), c_int()
        self.check(getattr(self.lib, get)(self.handle, byref(v)), "read offset")
        self.check(getattr(self.lib, rng)(self.handle, byref(lo), byref(hi)), "read offset range")
        return v.value, lo.value, hi.value, "VfOffset"

    def put(self, kind: int, value: int, what: str) -> None:
        if hasattr(self.lib, "nvmlDeviceSetClockOffsets"):
            code = self.lib.nvmlDeviceSetClockOffsets(self.handle, byref(_info(kind, value)))
            if code == 0:
                return
            if not hasattr(self.lib, OLD[kind][2]):
                self.check(code, f"set {what} to {value} MHz")
        self.check(getattr(self.lib, OLD[kind][2])(self.handle, int(value)), f"set {what} to {value} MHz")


def read(bus_id: str) -> dict:
    """Current offsets, the ranges the driver accepts, and the maximum clocks. Never raises; returns {"error": ...} instead."""
    try:
        s = _Session(bus_id)
    except (OSError, AttributeError, RuntimeError) as e:
        return {"error": str(e)}
    try:
        out = {}
        for key, kind in (("gpu", GRAPHICS), ("mem", MEMORY)):
            out[f"{key}_offset_mhz"], out[f"{key}_offset_min_mhz"], out[f"{key}_offset_max_mhz"], out[f"{key}_call"] = s.get(kind)
        for key, kind in (("gpu", GRAPHICS), ("mem", MEMORY)):
            v = c_uint()
            out[f"{key}_clock_max_mhz"] = v.value if s.lib.nvmlDeviceGetMaxClockInfo(s.handle, kind, byref(v)) == 0 else None
        return out
    except (AttributeError, RuntimeError) as e:
        return {"error": str(e)}
    finally:
        s.close()


def set_direct(bus_id: str, gpu: int | None = None, mem: int | None = None) -> dict:
    """Sets offsets in this process. Returns {"ok": bool, "error": str | None}."""
    try:
        s = _Session(bus_id)
    except (OSError, AttributeError, RuntimeError) as e:
        return {"ok": False, "error": str(e)}
    try:
        for value, kind, what in ((gpu, GRAPHICS, "GPU clock offset"), (mem, MEMORY, "memory clock offset")):
            if value is not None:
                s.put(kind, int(value), what)
        return {"ok": True, "error": None}
    except (AttributeError, RuntimeError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        s.close()


def set_offsets(bus_id: str, gpu: int | None = None, mem: int | None = None) -> dict:
    """Sets offsets, going through sudo on Linux when not already root. sudo -n never prompts."""
    if sys.platform.startswith("linux") and os.geteuid() != 0:
        cmd = ["sudo", "-n", sys.executable, "-I", os.path.abspath(__file__), "set", bus_id]
        cmd += ["--gpu", str(int(gpu))] if gpu is not None else []
        cmd += ["--mem", str(int(mem))] if mem is not None else []
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return json.loads(p.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            return {"ok": False, "error": f"sudo call failed: {e}"}
    return set_direct(bus_id, gpu, mem)


def non_stock(state: dict) -> bool | None:
    """True if either offset is not zero, False if both are zero, None if they couldn't be read."""
    if "error" in state:
        return None
    return bool(state["gpu_offset_mhz"] or state["mem_offset_mhz"])


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Read or set Nvidia clock offsets for one card.")
    p.add_argument("action", choices=["read", "set"])
    p.add_argument("bus_id")
    p.add_argument("--gpu", type=int)
    p.add_argument("--mem", type=int)
    a = p.parse_args()
    result = read(a.bus_id) if a.action == "read" else set_direct(a.bus_id, a.gpu, a.mem)
    print(json.dumps(result))
    sys.exit(0 if "error" not in result or result.get("ok") else 1)
