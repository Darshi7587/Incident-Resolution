"""Phase 9 tests: Streamlit dashboard module syntax, helpers, and chart generation."""

from frontend.dashboard import _before_after_chart, _metric_gauge_chart, _severity_badge


def test_dashboard_helpers_and_charts():
    """Verify dashboard chart builders and status badges render valid objects."""
    badge = _severity_badge("CRITICAL")
    assert "CRITICAL" in badge
    assert "#EF4444" in badge

    gauge = _metric_gauge_chart(95.0, 60.0, 55.0)
    assert len(gauge.data) == 1
    assert list(gauge.data[0].y) == [95.0, 60.0, 55.0]

    comp = _before_after_chart(
        {"cpu_usage": 95.0, "memory_usage": 60.0, "disk_usage": 55.0},
        {"cpu_usage": 26.0, "memory_usage": 60.0, "disk_usage": 55.0},
    )
    assert len(comp.data) == 2
    assert list(comp.data[0].y) == [95.0, 60.0, 55.0]
    assert list(comp.data[1].y) == [26.0, 60.0, 55.0]
