# Flood Notebook Final Cell Template

```python
# Final validation cell: run after all flood outputs are written
from pathlib import Path
import json
import subprocess
import sys

run_dir = Path(DIRS["base"]).resolve()

cmd = [
    sys.executable,
    "scripts/flood_postrun.py",
    "--run-dir",
    str(run_dir),
]
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    if result.stderr:
        print(result.stderr)
    raise RuntimeError("Flood post-run checks failed.")

summary = json.loads(result.stdout)
print("Post-run status:", summary["status"])
print("Parity report:", summary["outputs"].get("parity_md"))
```
