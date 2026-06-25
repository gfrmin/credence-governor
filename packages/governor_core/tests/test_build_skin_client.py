"""build_skin_client() engine resolution — explicit command, dev checkout, zero-config
docker/podman default, and the actionable no-engine error. No real subprocess/SkinClient:
SkinClient is stubbed and subprocess.run / shutil.which are monkeypatched, so each branch
is asserted by the recorded constructor args + the printed provenance line.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

import credence_governor_core as cgc

ENV_VARS = (
    "CREDENCE_SKIN_COMMAND",
    "CREDENCE_ENGINE_DIR",
    "CREDENCE_SKIN_IMAGE",
    "CREDENCE_CONTAINER_RUNTIME",
)


@pytest.fixture
def clean_env(monkeypatch):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


class _RecordingSkinClient:
    """Captures the constructor kwargs instead of spawning an engine."""

    last = None

    def __init__(self, **kwargs):
        type(self).last = kwargs


@pytest.fixture
def skin(monkeypatch):
    # Inject a stub credence_skin_client so build_skin_client()'s in-function
    # `from credence_skin_client import SkinClient` resolves to the recorder —
    # the test runs without the real engine client on PYTHONPATH.
    _RecordingSkinClient.last = None
    stub = types.ModuleType("credence_skin_client")
    stub.SkinClient = _RecordingSkinClient
    monkeypatch.setitem(sys.modules, "credence_skin_client", stub)
    return _RecordingSkinClient


def _logs():
    out: list[str] = []
    return out, out.append


def test_explicit_command_uses_shlex_and_is_verbatim(clean_env, skin):
    # quoted args must survive (shlex, not naive split)
    clean_env.setenv(
        "CREDENCE_SKIN_COMMAND", 'docker run --rm -i "ghcr.io/x/credence skin:tag"'
    )
    lines, log = _logs()
    cgc.build_skin_client(log=log)
    assert skin.last == {
        "command": ["docker", "run", "--rm", "-i", "ghcr.io/x/credence skin:tag"]
    }
    assert any("CREDENCE_SKIN_COMMAND" in line for line in lines)


def test_dev_checkout(clean_env, skin):
    clean_env.setenv("CREDENCE_ENGINE_DIR", "/home/g/git/credence")
    lines, log = _logs()
    cgc.build_skin_client(log=log)
    assert skin.last["project"] == "/home/g/git/credence"
    assert skin.last["server_path"].endswith("/apps/skin/server.jl")
    assert any("dev checkout" in line for line in lines)


def test_zeroconfig_docker_default_image(clean_env, skin, monkeypatch):
    monkeypatch.setattr(cgc.shutil, "which", lambda exe: "/usr/bin/docker" if exe == "docker" else None)
    # image already present -> no pull; --version not podman
    monkeypatch.setattr(
        cgc.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="docker 27", stderr=""),
    )
    lines, log = _logs()
    cgc.build_skin_client(log=log)
    assert skin.last == {
        "command": ["docker", "run", "--rm", "-i", cgc.DEFAULT_SKIN_IMAGE]
    }
    assert any(cgc.DEFAULT_SKIN_IMAGE in line for line in lines)


def test_zeroconfig_image_override(clean_env, skin, monkeypatch):
    clean_env.setenv("CREDENCE_SKIN_IMAGE", "ghcr.io/gfrmin/credence-skin@sha256:deadbeef")
    monkeypatch.setattr(cgc.shutil, "which", lambda exe: "/usr/bin/podman" if exe == "podman" else None)
    monkeypatch.setattr(
        cgc.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    lines, log = _logs()
    cgc.build_skin_client(log=log)
    assert skin.last["command"] == [
        "podman", "run", "--rm", "-i", "ghcr.io/gfrmin/credence-skin@sha256:deadbeef",
    ]


def test_precedence_command_beats_runtime(clean_env, skin, monkeypatch):
    # an incidentally-installed docker must NOT override an explicit command
    clean_env.setenv("CREDENCE_SKIN_COMMAND", "remote-engine --flag")
    monkeypatch.setattr(cgc.shutil, "which", lambda exe: "/usr/bin/docker")
    _, log = _logs()
    cgc.build_skin_client(log=log)
    assert skin.last == {"command": ["remote-engine", "--flag"]}


def test_no_engine_error_names_all_three(clean_env, skin, monkeypatch):
    monkeypatch.setattr(cgc.shutil, "which", lambda exe: None)
    with pytest.raises(RuntimeError) as exc:
        cgc.build_skin_client(log=lambda _m: None)
    msg = str(exc.value)
    assert "CREDENCE_SKIN_COMMAND" in msg
    assert "CREDENCE_ENGINE_DIR" in msg
    assert cgc.DEFAULT_SKIN_IMAGE in msg
    assert "docker or podman" in msg


def test_ensure_image_pulls_when_absent(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # image inspect -> absent (rc 1); pull -> ok (rc 0)
        rc = 1 if argv[:3] == ["docker", "image", "inspect"] else 0
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(cgc.subprocess, "run", fake_run)
    lines, log = _logs()
    cgc._ensure_image("docker", "img:tag", log)
    assert ["docker", "pull", "img:tag"] in calls
    assert any("pulling engine image" in line for line in lines)


def test_runtime_label_detects_podman_shim(monkeypatch):
    monkeypatch.setattr(
        cgc.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="podman version 5.0", stderr=""),
    )
    assert cgc._runtime_label("docker") == "docker (podman shim)"
    # podman binary name -> returned as-is, no probe needed
    assert cgc._runtime_label("podman") == "podman"


def test_subprocess_import_present():
    # guard the module still exposes subprocess/shutil for the monkeypatch surface
    assert isinstance(cgc.subprocess.run, type(subprocess.run))
