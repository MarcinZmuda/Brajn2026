"""Tests for shared_constants consistency."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_constants_exist():
    """All required constants should be defined."""
    from shared_constants import (
        SENTENCE_AVG_TARGET,
        SENTENCE_AVG_TARGET_MIN,
        SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX,
        SENTENCE_HARD_MAX,
        SENTENCE_AVG_MAX_ALLOWED,
        SENTENCE_RETRY_THRESHOLD,
        SENTENCE_MAX_COMMAS,
        KEYWORD_MAIN_MAX_PER_BATCH,
        KEYWORD_MIN_SPACING_WORDS,
    )
    assert all(isinstance(v, int) for v in [
        SENTENCE_AVG_TARGET, SENTENCE_AVG_TARGET_MIN, SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX, SENTENCE_HARD_MAX, SENTENCE_AVG_MAX_ALLOWED,
        SENTENCE_RETRY_THRESHOLD, SENTENCE_MAX_COMMAS,
        KEYWORD_MAIN_MAX_PER_BATCH, KEYWORD_MIN_SPACING_WORDS,
    ])


def test_constants_ranges():
    """Constants should be in sensible ranges."""
    from shared_constants import (
        SENTENCE_AVG_TARGET, SENTENCE_AVG_TARGET_MIN, SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX, SENTENCE_HARD_MAX,
        SENTENCE_AVG_MAX_ALLOWED, SENTENCE_RETRY_THRESHOLD,
    )
    assert SENTENCE_AVG_TARGET_MIN < SENTENCE_AVG_TARGET < SENTENCE_AVG_TARGET_MAX
    assert SENTENCE_SOFT_MAX < SENTENCE_HARD_MAX
    assert SENTENCE_AVG_MAX_ALLOWED < SENTENCE_RETRY_THRESHOLD


def test_constants_match_canonical_values():
    """Constants should match the canonical Brajn2026 values."""
    from shared_constants import (
        SENTENCE_AVG_TARGET, SENTENCE_AVG_TARGET_MIN, SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX, SENTENCE_HARD_MAX,
    )
    assert SENTENCE_AVG_TARGET == 16, "Target should be 16 (publicystyczny styl)"
    assert SENTENCE_AVG_TARGET_MIN == 14
    assert SENTENCE_AVG_TARGET_MAX == 18
    assert SENTENCE_SOFT_MAX == 25
    assert SENTENCE_HARD_MAX == 28


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
