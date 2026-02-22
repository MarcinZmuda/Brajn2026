"""Tests for LLM cost tracker."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from llm_cost_tracker import CostTracker, MODEL_PRICING


def test_record_and_summary():
    """Recording calls should produce correct summaries."""
    tracker = CostTracker()
    tracker.record("job1", "claude-haiku-4-5-20251001", 1000, 500, step="ymyl_detection")
    tracker.record("job1", "claude-sonnet-4-6", 3000, 1500, step="batch_generation")

    summary = tracker.get_job_summary("job1")
    assert summary is not None
    assert summary["call_count"] == 2
    assert summary["total_input_tokens"] == 4000
    assert summary["total_output_tokens"] == 2000
    assert summary["total_cost_usd"] > 0


def test_cost_calculation():
    """Cost should be calculated correctly based on model pricing."""
    tracker = CostTracker()
    # Haiku: $0.80/1M input, $4.00/1M output
    cost = tracker.record("job2", "claude-haiku-4-5-20251001", 1_000_000, 1_000_000, step="test")
    expected = 0.80 + 4.00  # $4.80
    assert abs(cost - expected) < 0.01


def test_unknown_model_uses_default():
    """Unknown models should use default pricing."""
    tracker = CostTracker()
    cost = tracker.record("job3", "unknown-model-v99", 1000, 500, step="test")
    assert cost > 0  # Should not crash


def test_job_removal():
    """Removing a job should clear its data."""
    tracker = CostTracker()
    tracker.record("job4", "claude-haiku-4-5-20251001", 100, 50, step="test")
    assert tracker.get_job_summary("job4") is not None
    tracker.remove_job("job4")
    assert tracker.get_job_summary("job4") is None


def test_breakdown_by_step():
    """Cost breakdown should group by step name."""
    tracker = CostTracker()
    tracker.record("job5", "claude-sonnet-4-6", 1000, 500, step="batch")
    tracker.record("job5", "claude-sonnet-4-6", 2000, 1000, step="batch")
    tracker.record("job5", "claude-haiku-4-5-20251001", 500, 200, step="ymyl")

    summary = tracker.get_job_summary("job5")
    assert "batch" in summary["breakdown"]
    assert "ymyl" in summary["breakdown"]
    assert summary["breakdown"]["batch"]["calls"] == 2
    assert summary["breakdown"]["ymyl"]["calls"] == 1


def test_model_pricing_complete():
    """All expected models should have pricing."""
    expected_models = [
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "gpt-4.1",
        "gpt-4.1-mini",
    ]
    for model in expected_models:
        assert model in MODEL_PRICING, f"Missing pricing for {model}"
        assert "input" in MODEL_PRICING[model]
        assert "output" in MODEL_PRICING[model]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
