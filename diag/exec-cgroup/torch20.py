"""torch in a node cgroup capped at 24576 MB asks for 20 GiB on the GPU (a diagnostic)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgroup_lab as lab  # noqa: E402

CODE = '''
import json, time
started = time.time()
import torch
available = torch.cuda.is_available()
block = torch.empty(20 * 2**30, dtype=torch.uint8, device="cuda")
block.fill_(1)
torch.cuda.synchronize()
with open("/proc/self/status") as handle:
    status = {line.split(":")[0]: line.split(":")[1].strip() for line in handle
              if line.startswith(("VmPeak", "VmHWM", "VmRSS"))}
print(json.dumps({"cuda": available, "gpu_allocated_GiB": round(torch.cuda.memory_allocated() / 2**30, 2),
                  "seconds": round(time.time() - started, 1), **status}))
'''

path, settings = lab.node("torch20", memory_max=24576 << 20)
proc = lab.spawn(path, CODE)
out, err = proc.communicate(timeout=300)
lab.emit("torch20", settings=settings, returncode=proc.returncode, out=out[-800:], err=err[-800:],
         usage=lab.usage(path), remove=lab.remove(path))
