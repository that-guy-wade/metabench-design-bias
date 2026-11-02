import sys
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
from metabench.pool import build_pilot_pool
items = build_pilot_pool(Path("/path/to/metabench/run/data/pool_pilot.jsonl"))
import collections
print(len(items), collections.Counter(i["category"] for i in items))
