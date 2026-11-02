# Template (not collected by pytest). Copy into pools/<domain>/test_<domain>_schema.py and set PREFIX, DOMAIN, MIN_ITEMS.
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # append, not insert: pools/math would shadow the stdlib math module
from schema_check import check_pool  # noqa: E402

PREFIX, DOMAIN, MIN_ITEMS = "X", "x", 1


def test_pool_schema():
    rep = check_pool(HERE / "pool.jsonl", PREFIX, DOMAIN, MIN_ITEMS)
    assert rep["ok"], (rep["errors"][:20], rep["duplicates"][:20])
