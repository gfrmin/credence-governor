"""features/ — extractor dispatch and feature-dict assembly.

Registry keys are kebab-case BDSL feature names verbatim (match
data/bdsl/features.bdsl); manifest.verify_features checks every declared feature
against this set at startup. Port of extension/src/features/index.ts.
"""

from __future__ import annotations

from collections.abc import Callable

from ..schema import AgentToolEvent, FeatureDict, Session
from .identical_call import extract_recent_identical_call_count
from .parent_tool import extract_parent_tool_call_name
from .repetition import extract_recent_repetition_count
from .time_since_user import extract_time_since_last_user_message
from .tool_name import extract_tool_name
from .working_directory import extract_working_directory_relative

Extractor = Callable[[AgentToolEvent, Session], str]

extractors: dict[str, Extractor] = {
    "tool-name": extract_tool_name,
    "working-directory-relative": extract_working_directory_relative,
    "parent-tool-call-name": extract_parent_tool_call_name,
    "recent-repetition-count": extract_recent_repetition_count,
    "recent-identical-call-count": extract_recent_identical_call_count,
    "time-since-last-user-message": extract_time_since_last_user_message,
}


def extract_features(event: AgentToolEvent, session: Session) -> FeatureDict:
    return {name: fn(event, session) for name, fn in extractors.items()}
