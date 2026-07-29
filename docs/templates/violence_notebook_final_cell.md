# Violence Notebook Final Cell Template

```python
# Final validation cell: run after all violence outputs are written
from pathlib import Path
import json
import subprocess
import sys

run_dir = Path(RUN_CTX["layout"]["base"]).resolve()

cmd = [
    sys.executable,
    "scripts/violence_postrun.py",
    "--run-dir",
    str(run_dir),
]
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    if result.stderr:
        print(result.stderr)
    raise RuntimeError("Violence post-run checks failed.")

summary = json.loads(result.stdout)
print("Post-run status:", summary["status"])
print("Parity report:", summary["outputs"].get("parity_md"))
```
