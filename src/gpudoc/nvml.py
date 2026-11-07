"""Direct NVML read, used as an independent cross-check of nvidia-smi."""
from __future__ import annotations

import ctypes
import os
import sys


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _load():
    if sys.platform != "win32":
        return ctypes.CDLL("libnvidia-ml.so.1")
    candidates = [
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return ctypes.WinDLL(path)
    raise OSError("nvml.dll not found")


def read_nvml() -> dict:
    """Returns driver and per-GPU facts, or an error. Never raises."""
    try:
        lib = _load()
    except OSError as e:
        return {"error": f"NVML could not be loaded: {e}"}

    def check(code, what):
        if code != 0:
            raise RuntimeError(f"{what} returned NVML code {code}")

    try:
        check(lib.nvmlInit_v2(), "init")
    except (AttributeError, RuntimeError) as e:
        return {"error": str(e)}
    try:
        buf = ctypes.create_string_buffer(96)
        check(lib.nvmlSystemGetDriverVersion(buf, 96), "driver version")
        out = {"driver_version": buf.value.decode(), "gpus": []}
        count = ctypes.c_uint()
        check(lib.nvmlDeviceGetCount_v2(ctypes.byref(count)), "device count")
        for i in range(count.value):
            h = ctypes.c_void_p()
            check(lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)), "device handle")
            gpu = {}
            for key, fn in (("name", lib.nvmlDeviceGetName), ("uuid", lib.nvmlDeviceGetUUID),
                            ("vbios_version", lib.nvmlDeviceGetVbiosVersion)):
                check(fn(h, buf, 96), key)
                gpu[key] = buf.value.decode()
            mem = _Memory()
            check(lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)), "memory")
            gpu["memory_total"] = mem.total / (1024 * 1024)
            val = ctypes.c_uint()
            check(lib.nvmlDeviceGetMaxPcieLinkGeneration(h, ctypes.byref(val)), "PCIe generation")
            gpu["pcie_gen_max"] = val.value
            check(lib.nvmlDeviceGetMaxPcieLinkWidth(h, ctypes.byref(val)), "PCIe width")
            gpu["pcie_width_max"] = val.value
            out["gpus"].append(gpu)
        return out
    except (AttributeError, RuntimeError) as e:
        return {"error": str(e)}
    finally:
        lib.nvmlShutdown()
