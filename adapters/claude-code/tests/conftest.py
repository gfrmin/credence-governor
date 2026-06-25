"""Make `credence_governor_claude_code` importable without an editable install."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
