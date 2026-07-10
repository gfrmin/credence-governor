"""test_shadow_report.py — the field-reading CLI's pure core."""

from credence_governor_core.training.shadow_report import collect, percentile, render


def _shadow(eid, form, action, latency=8.0, readouts=None):
    return {"event_type": "membrane-shadow", "in_response_to": eid,
            "utility_form": form, "action": action, "latency_ms": latency,
            "readouts": readouts or {}}


def test_collect_and_render_reading():
    records = [
        {"event_type": "tool-proposed", "event_id": "e1", "features": {}},
        {"event_type": "decision", "in_response_to": "e1", "action": "proceed"},
        {"event_type": "tool-proposed", "event_id": "e2", "features": {}},
        {"event_type": "decision", "in_response_to": "e2", "action": "block"},
        _shadow("e1", "latent@1", "block", 8.2,
                {"p1": 0.5, "residual_mean": 0.40, "sensitivity": False}),
        _shadow("e2", "latent@1", "block", 9.0,
                {"p1": 0.5, "residual_mean": 0.30, "sensitivity": True}),
        _shadow("e1", "table@1", "proceed", 7.5),
        _shadow("e2", "table@1", "block", 7.7),
    ]
    forms = collect(records)
    latent, table = forms["latent@1"], forms["table@1"]
    assert latent["actions"] == {"block": 2}
    assert latent["agreement"]["proceed"]["block"] == 1
    assert latent["agreement"]["block"]["block"] == 1
    assert latent["residual_means"] == [0.40, 0.30]
    assert latent["sensitivity_true"] == 1
    assert table["actions"] == {"proceed": 1, "block": 1}
    text = render(forms)
    assert "ask-rate: 0.0000% (0/2)" in text
    assert "agreement with primary: 100.0% over 2 joined" in text  # table@1
    assert "asks RARELY" in text
    assert "residual_mean  first 0.4000  last 0.3000" in text


def test_render_empty_is_actionable():
    assert "no membrane-shadow records" in render({})


def test_percentile_bounds():
    assert percentile([], 0.5) is None
    assert percentile([1.0], 0.99) == 1.0
    vals = [float(i) for i in range(101)]   # 0..100: q*(n-1) lands exactly
    assert percentile(vals, 0.50) == 50.0
    assert percentile(vals, 0.99) == 99.0
