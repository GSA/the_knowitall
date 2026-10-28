import re
from pathlib import Path

from knowitall_graphify.adapter import PINNED_DISTRIBUTIONS


ROOT = Path(__file__).resolve().parents[2]


def test_pinned_distributions_match_the_complete_hash_locked_closure():
    lock = (ROOT / "requirements" / "graphify.lock").read_text()
    locked = dict(re.findall(r"^([^#\s][^=]+)==([^\s]+) \\$", lock, re.MULTILINE))

    assert locked == dict(PINNED_DISTRIBUTIONS)
    assert lock.count("--hash=sha256:") == len(locked)
