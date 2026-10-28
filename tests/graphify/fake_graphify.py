#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "invocation.json").write_text(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ)}, sort_keys=True))
(out / "graph.json").write_text(os.environ.get("FAKE_GRAPH", "{}"))
print("fake stdout")
print("fake stderr", file=sys.stderr)
