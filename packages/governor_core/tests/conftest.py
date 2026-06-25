"""Make `credence_governor_core` importable without an editable install (the
parity tests touch only the pure extractor/manifest code, which has no engine dep)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
