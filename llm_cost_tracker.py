"""
LLM Cost Tracker — monitors token usage and estimated costs per workflow.

Usage:
    from llm_cost_tracker import cost_tracker

    # Track a call
    cost_tracker.record(
        job_id="abc123",
        model="claude-sonnet-4-6",
        input_tokens=3000,
        output_tokens=1500,
        step="batch_generation"
    )

    # Get summary for a job
    summary = cost_tracker.get_job_summary("abc123")
    # {"total_cost": 0.045, "total_input_tokens": ..., "total_output_tokens": ..., "calls": [...]}

    # Log all active job costs
    cost_tracker.log_summary("abc123")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Approximate pricing per 1M tokens (as of 2025-Q4)
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
MODEL_PRICING = {
    # Anthropic Claude
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    # Google Gemini
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}

# Default fallback for unknown models
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


@dataclass
class LLMCall:
    """Record of a single LLM API call."""
    model: str
    input_tokens: int
    output_tokens: int
    step: str
    timestamp: float
    cost: float


@dataclass
class JobCostTracker:
    """Tracks all LLM costs for a single job/workflow."""
    calls: List[LLMCall] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def total_cost(self) -> float:
        return sum(c.cost for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def to_dict(self) -> dict:
        return {
            "total_cost_usd": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "call_count": self.call_count,
            "breakdown": self._breakdown_by_step(),
        }

    def _breakdown_by_step(self) -> Dict[str, dict]:
        steps = {}
        for c in self.calls:
            if c.step not in steps:
                steps[c.step] = {"cost": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
            steps[c.step]["cost"] = round(steps[c.step]["cost"] + c.cost, 4)
            steps[c.step]["calls"] += 1
            steps[c.step]["input_tokens"] += c.input_tokens
            steps[c.step]["output_tokens"] += c.output_tokens
        return steps


class CostTracker:
    """Global cost tracker — tracks costs across all jobs."""

    def __init__(self, max_jobs: int = 100):
        self._jobs: Dict[str, JobCostTracker] = {}
        self._max_jobs = max_jobs

    def record(self, job_id: str, model: str, input_tokens: int, output_tokens: int,
               step: str = "unknown") -> float:
        """Record an LLM call and return its estimated cost."""
        if job_id not in self._jobs:
            self._cleanup_old_jobs()
            self._jobs[job_id] = JobCostTracker()

        pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        call = LLMCall(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            step=step,
            timestamp=time.time(),
            cost=cost,
        )
        self._jobs[job_id].calls.append(call)

        logger.info(
            f"[COST] job={job_id[:8]} step={step} model={model} "
            f"in={input_tokens} out={output_tokens} cost=${cost:.4f} "
            f"total=${self._jobs[job_id].total_cost:.4f}"
        )
        return cost

    def get_job_summary(self, job_id: str) -> Optional[dict]:
        """Get cost summary for a specific job."""
        tracker = self._jobs.get(job_id)
        if not tracker:
            return None
        return tracker.to_dict()

    def log_summary(self, job_id: str):
        """Log a summary of costs for a job."""
        summary = self.get_job_summary(job_id)
        if summary:
            logger.info(
                f"[COST_SUMMARY] job={job_id[:8]} "
                f"total=${summary['total_cost_usd']:.4f} "
                f"calls={summary['call_count']} "
                f"tokens_in={summary['total_input_tokens']} "
                f"tokens_out={summary['total_output_tokens']}"
            )

    def remove_job(self, job_id: str):
        """Remove tracking data for a completed job."""
        self._jobs.pop(job_id, None)

    def _cleanup_old_jobs(self):
        """Remove oldest jobs if over max."""
        if len(self._jobs) >= self._max_jobs:
            oldest = sorted(self._jobs.items(), key=lambda x: x[1].created_at)
            for job_id, _ in oldest[:len(oldest) // 2]:
                del self._jobs[job_id]


# Global singleton
cost_tracker = CostTracker()
