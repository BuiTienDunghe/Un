from __future__ import annotations

import subprocess


def system_metrics() -> dict[str, object]:
    try:
        import psutil
        memory = psutil.virtual_memory()
        result: dict[str, object] = {"cpu_percent": psutil.cpu_percent(interval=None), "ram_percent": memory.percent, "ram_used_bytes": memory.used, "ram_total_bytes": memory.total}
    except ImportError:
        result = {"cpu_percent": None, "ram_percent": None, "gpu_available": False, "warning": "psutil is not installed"}
    try:
        output = subprocess.check_output(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"], text=True, timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip().splitlines()[0]
        utilization, used, total = [item.strip() for item in output.split(",")]
        result.update({"gpu_available": True, "gpu_utilization_percent": float(utilization), "vram_used_mb": float(used), "vram_total_mb": float(total)})
    except (FileNotFoundError, subprocess.SubprocessError, IndexError, ValueError):
        result.update({"gpu_available": False, "gpu_message": "GPU metrics unavailable (nvidia-smi was not available)"})
    return result
