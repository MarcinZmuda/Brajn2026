"""
═══════════════════════════════════════════════════════════
BRAJEN KEYWORD DEDUP v1.0 — Word-boundary safe deduplication
═══════════════════════════════════════════════════════════
Prevents double-counting of nested keywords by adjusting targets.

Key principles:
  - WORD-BOUNDARY matching only (no substring within words)
  - NEVER removes keywords — only reduces target_max
  - Works universally across all topics (legal, medical, travel, etc.)
  
False positives prevented:
  "rok" ≠ "wyrok" (different words)
  "dom" ≠ "domowy" (different concepts)  
  "raz" ≠ "wyraz" (no word boundary)
  
Correct reductions:
  "bagaż" ∈ "bagaż podręczny" → bagaż max reduced
  "lista" ∈ "lista rzeczy" → lista max reduced
  "kredyt hipoteczny" ∈ "kredyt hipoteczny kalkulator" → reduced
═══════════════════════════════════════════════════════════
"""

import logging

logger = logging.getLogger(__name__)


def _word_boundary_overlap(short_phrase: str, long_phrase: str) -> str:
    """
    Check if short_phrase is contained in long_phrase at WORD boundaries.
    
    Returns overlap type:
      - "prefix_compound": short is the first word(s) of long ("bagaż" in "bagaż podręczny")
      - "word_inside": all short words appear in long ("ubezwłasnowolnienie" in "wniosek o ubezwłasnowolnienie")
      - "multi_word_prefix": multi-word short is prefix of long ("lista rzeczy" in "lista rzeczy do spakowania")
      - "": no overlap
    """
    short_words = short_phrase.lower().split()
    long_words = long_phrase.lower().split()
    
    if not short_words or not long_words:
        return ""
    
    # Don't compare same-length phrases
    if len(short_words) >= len(long_words):
        return ""
    
    # Check if short is prefix of long (first N words match)
    if long_words[:len(short_words)] == short_words:
        if len(short_words) == 1:
            return "prefix_compound"
        else:
            return "multi_word_prefix"
    
    # Check if all short words appear somewhere in long (as complete words)
    if set(short_words).issubset(set(long_words)):
        return "word_inside"
    
    return ""


def deduplicate_keywords(keywords: list, main_keyword: str = "") -> list:
    """
    Word-boundary safe keyword deduplication.
    
    NEVER removes keywords — only adjusts target_max downward to compensate
    for double-counting that occurs when the backend counts substring matches.
    
    Reduction rules (conservative):
      - prefix_compound: reduce by 1/3 of parent's max (e.g., bagaż + bagaż podręczny)
      - word_inside: reduce by 1/4 of parent's max
      - multi_word_prefix: reduce by 1/3 of parent's max
      - If parent is MAIN keyword: reduce by 1/4 of MAIN's max (MAIN gets heavy use)
    
    Floor: target_max never drops below max(1, target_min).
    
    Args:
        keywords: list of dicts with {keyword, type, target_min, target_max}
        main_keyword: the main keyword string
    
    Returns:
        Modified keywords list (same objects, target_max adjusted in-place)
    """
    if not keywords or len(keywords) < 2:
        return keywords
    
    main_kw_lower = main_keyword.lower().strip()
    adjustments = 0
    
    for i, kw_short in enumerate(keywords):
        short_phrase = kw_short.get("keyword", "").strip()
        short_type = kw_short.get("type", "BASIC")
        
        if not short_phrase:
            continue
        
        # Don't adjust MAIN keyword's targets
        if short_type == "MAIN":
            continue
        
        total_reduction = 0
        found_in_main = False
        
        for j, kw_long in enumerate(keywords):
            if i == j:
                continue
            
            long_phrase = kw_long.get("keyword", "").strip()
            long_type = kw_long.get("type", "BASIC")
            long_max = kw_long.get("target_max", 5)
            
            if not long_phrase:
                continue
            
            overlap = _word_boundary_overlap(short_phrase, long_phrase)
            if not overlap:
                continue
            
            # Calculate reduction based on overlap type
            if overlap == "prefix_compound":
                reduction = max(1, long_max // 3)
            elif overlap == "multi_word_prefix":
                reduction = max(1, long_max // 3)
            elif overlap == "word_inside":
                reduction = max(1, long_max // 4)
            else:
                reduction = 0
            
            if reduction > 0:
                total_reduction += reduction
                logger.info(f"[DEDUP] '{short_phrase}' ∈ '{long_phrase}' ({overlap}) → reduce by {reduction}")
                
                # Track if this keyword is nested in MAIN
                if long_type == "MAIN":
                    found_in_main = True
        
        # Additional MAIN keyword overlap (if not already caught above)
        if not found_in_main and main_kw_lower:
            main_overlap = _word_boundary_overlap(short_phrase, main_kw_lower)
            if main_overlap:
                reduction = max(1, 25 // 4)  # MAIN typically 8-25 uses
                total_reduction += reduction
                logger.info(f"[DEDUP] '{short_phrase}' ∈ MAIN '{main_keyword}' → reduce by {reduction}")
        
        if total_reduction > 0:
            old_max = kw_short.get("target_max", 5)
            floor = max(1, kw_short.get("target_min", 1))
            new_max = max(floor, old_max - total_reduction)
            
            if new_max < old_max:
                kw_short["target_max"] = new_max
                adjustments += 1
                logger.info(f"[DEDUP] '{short_phrase}' target_max: {old_max} → {new_max}")
    
    if adjustments > 0:
        logger.info(f"[DEDUP] Adjusted targets for {adjustments} keywords")
    
    return keywords
