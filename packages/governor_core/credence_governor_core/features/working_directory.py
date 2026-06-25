"""working_directory.py — classify session.cwd against session.project_root into
wd-relative-space: project-root | subdirectory | outside-project | no-path.
Port of extension/src/features/working_directory.ts.
"""

from __future__ import annotations

import re

from ..schema import AgentToolEvent, Session

_TRAILING_SEP = re.compile(r"/+$")


def extract_working_directory_relative(_event: AgentToolEvent, session: Session) -> str:
    if not session.cwd or not session.project_root:
        return "no-path"
    root = _TRAILING_SEP.sub("", session.project_root)
    cwd = _TRAILING_SEP.sub("", session.cwd)
    if cwd == root:
        return "project-root"
    if cwd.startswith(root + "/"):
        return "subdirectory"
    return "outside-project"
