"""Tests for CSS/JS garbage filter."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_is_css_garbage_css_properties():
    """CSS properties should be detected as garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("display: flex") is True
    assert _is_css_garbage("font-family: Arial") is True
    assert _is_css_garbage("webkit-transform") is True
    assert _is_css_garbage("align-items") is True


def test_is_css_garbage_ngram_exact():
    """Known CSS n-gram phrases should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("min width") is True
    assert _is_css_garbage("webkit box") is True
    assert _is_css_garbage("text decoration") is True
    assert _is_css_garbage("wp content") is True


def test_is_css_garbage_entity_words():
    """CSS entity words (single lowercase) should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("inline") is True
    assert _is_css_garbage("hover") is True
    assert _is_css_garbage("facebook") is True


def test_is_css_garbage_valid_polish():
    """Valid Polish entities should NOT be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("Kodeks karny") is False
    assert _is_css_garbage("Sąd Najwyższy") is False
    assert _is_css_garbage("Warszawa") is False
    assert _is_css_garbage("Ministerstwo Zdrowia") is False


def test_is_css_garbage_repeated_words():
    """Repeated words should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("list list") is True
    assert _is_css_garbage("heading heading heading") is True
    assert _is_css_garbage("container expand container") is True


def test_is_css_garbage_empty():
    """Empty/short inputs should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("") is True
    assert _is_css_garbage(None) is True
    assert _is_css_garbage("a") is True


def test_is_css_garbage_hex_colors():
    """Hex color codes should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("FF00FF") is True
    assert _is_css_garbage("3B82F6") is True


def test_is_css_garbage_special_chars():
    """Strings with high special char ratio should be garbage."""
    from css_filter import _is_css_garbage
    assert _is_css_garbage("{display:flex}") is True
    assert _is_css_garbage("color:#fff;") is True


def test_filter_entities():
    """Entity list filtering should remove garbage."""
    from css_filter import _filter_entities
    entities = [
        {"text": "Kodeks karny", "type": "ORG"},
        {"text": "display block", "type": "MISC"},
        {"text": "Warszawa", "type": "LOC"},
        {"text": "webkit box", "type": "MISC"},
    ]
    result = _filter_entities(entities)
    texts = [e["text"] for e in result]
    assert "Kodeks karny" in texts
    assert "Warszawa" in texts
    assert "display block" not in texts
    assert "webkit box" not in texts


def test_filter_ngrams():
    """N-gram filtering should remove garbage."""
    from css_filter import _filter_ngrams
    ngrams = [
        {"ngram": "prawo karne"},
        {"ngram": "font weight"},
        {"ngram": "kodeks cywilny"},
        {"ngram": "list list"},
    ]
    result = _filter_ngrams(ngrams)
    texts = [n["ngram"] for n in result]
    assert "prawo karne" in texts
    assert "kodeks cywilny" in texts
    assert "font weight" not in texts
    assert "list list" not in texts


def test_is_brand_entity():
    """Brand detection should catch Polish company names."""
    from css_filter import _is_brand_entity
    assert _is_brand_entity("TAURON") is True
    assert _is_brand_entity("PZU S.A.") is True
    assert _is_brand_entity("Allegro") is True
    assert _is_brand_entity("prawo karne") is False
    assert _is_brand_entity("Kodeks karny") is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
