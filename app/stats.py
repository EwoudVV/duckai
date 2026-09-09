"""GPU + queue stats. nvidia-smi if present, else zeros. No extra deps."""
import shutil
import subprocess

def gpu():
    if not shutil.which("nvidia-smi"):
        return {"present": False, "util": 0, "mem_used": 0, "mem_total": 0, "temp": 0}
    try:
        q = "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"
        out = subprocess.run(["nvidia-smi"] + q.split(), capture_output=True, text=True, timeout=5)
        u, mu, mt, t = [x.strip() for x in out.stdout.strip().split(",")]
        return {"present": True, "util": int(u), "mem_used": int(mu), "mem_total": int(mt), "temp": int(t)}
    except Exception:
        return {"present": False, "util": 0, "mem_used": 0, "mem_total": 0, "temp": 0}
