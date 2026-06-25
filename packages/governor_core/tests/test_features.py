"""Parity tests for the neutral feature extractors — ported from credence-openclaw
openclaw-plugin/tests/features.test.ts. The OpenClaw FeatureTracker kept per-run
history internally; here we construct the equivalent Session.messages (the proposed
call is NOT in messages) and assert the same bucket outcomes.
"""

from credence_governor_core.features import extract_features
from credence_governor_core.features.identical_call import extract_recent_identical_call_count
from credence_governor_core.features.time_since_user import extract_time_since_last_user_message
from credence_governor_core.features.working_directory import extract_working_directory_relative
from credence_governor_core.schema import AgentToolEvent, Message, Session


def ev(tool, inp=None):
    return AgentToolEvent(tool_name=tool, input=inp if inp is not None else {})


def tc(tool, inp=None):
    return Message(role="tool_call", tool_name=tool, input=inp if inp is not None else {})


def feats(event, session):
    return extract_features(event, session)


def test_tool_name_buckets_known_verbatim_unknown_other():
    s = Session()
    assert feats(ev("bash"), s)["tool-name"] == "bash"
    # exec/process/apply_patch are first-class categories, not "other".
    assert feats(ev("exec"), s)["tool-name"] == "exec"
    assert feats(ev("Exec"), s)["tool-name"] == "exec"
    assert feats(ev("process"), s)["tool-name"] == "process"
    assert feats(ev("apply_patch"), s)["tool-name"] == "apply_patch"
    assert feats(ev("WeirdTool"), s)["tool-name"] == "other"


def test_parent_and_repetition_from_history():
    f = feats(ev("bash"), Session())
    assert f["parent-tool-call-name"] == "none"
    assert f["recent-repetition-count"] == "rep-0"

    f = feats(ev("bash"), Session(messages=[tc("bash")]))
    assert f["parent-tool-call-name"] == "bash"
    assert f["recent-repetition-count"] == "rep-1"

    assert feats(ev("bash"), Session(messages=[tc("bash"), tc("bash")]))["recent-repetition-count"] == "rep-2"
    assert feats(ev("bash"), Session(messages=[tc("bash"), tc("bash"), tc("bash")]))["recent-repetition-count"] == "rep-3plus"


def test_identical_loop_vs_distinct_args():
    def loop(n_prior):
        s = Session(messages=[tc("exec", {"command": "ls"}) for _ in range(n_prior)])
        return extract_recent_identical_call_count(ev("exec", {"command": "ls"}), s)

    assert loop(0) == "ident-0"
    assert loop(1) == "ident-1"
    assert loop(2) == "ident-2"
    assert loop(3) == "ident-3plus"

    # same tool, different args -> rep climbs, ident stays low
    s = Session(messages=[tc("exec", {"command": "ls a"})])
    f = feats(ev("exec", {"command": "ls b"}), s)
    assert f["recent-repetition-count"] == "rep-1"
    assert f["recent-identical-call-count"] == "ident-0"


def test_identical_key_order_invariant():
    s = Session(messages=[tc("exec", {"a": 1, "b": 2})])
    assert extract_recent_identical_call_count(ev("exec", {"b": 2, "a": 1}), s) == "ident-1"


def test_identical_long_prefix_no_collision():
    head = "cat << 'EOF' > f.py\n" + "x = 1  # padding " * 40
    s = Session(messages=[tc("exec", {"command": head + "\nprint('A')"})])
    f = extract_recent_identical_call_count(ev("exec", {"command": head + "\nprint('B')"}), s)
    assert f == "ident-0"


def test_identical_counted_session_wide():
    msgs = [tc("exec", {"command": "make"})]
    msgs += [tc("exec", {"command": f"step-{i}"}) for i in range(8)]
    f = extract_recent_identical_call_count(ev("exec", {"command": "make"}), Session(messages=msgs))
    assert f == "ident-1"  # the distant repeat is seen


def test_identical_non_informative_never_loop():
    # lone field echoing the tool name carries no evidence
    s = Session(messages=[tc("exec", {"command": "exec"})])
    assert extract_recent_identical_call_count(ev("exec", {"command": "exec"}), s) == "ident-0"
    # empty args likewise
    s2 = Session(messages=[tc("read", {})])
    assert extract_recent_identical_call_count(ev("read", {}), s2) == "ident-0"


def test_time_since_user_bucketing_injected_clock():
    base_iso = "2020-01-01T00:00:00+00:00"
    base_ms = extract_time_since_last_user_message.__globals__["_parse_ms"](base_iso)
    s = Session(messages=[Message(role="user", timestamp=base_iso)])

    def at(delta_ms):
        return extract_time_since_last_user_message(ev("bash"), s, now_ms=base_ms + delta_ms)

    assert extract_time_since_last_user_message(ev("bash"), Session(), now_ms=base_ms) == "gt-10m"
    assert at(10_000) == "lt-30s"
    assert at(60_000) == "lt-2m"
    assert at(300_000) == "lt-10m"
    assert at(1_200_000) == "gt-10m"


def test_working_directory_relative():
    root = "/home/u/proj"
    assert extract_working_directory_relative(ev("bash"), Session(cwd="", project_root=root)) == "no-path"
    assert extract_working_directory_relative(ev("edit"), Session(cwd="/home/u/proj/src/a.ts", project_root=root)) == "subdirectory"
    assert extract_working_directory_relative(ev("read"), Session(cwd="/etc/passwd", project_root=root)) == "outside-project"
    assert extract_working_directory_relative(ev("ls"), Session(cwd="/home/u/proj", project_root=root)) == "project-root"
