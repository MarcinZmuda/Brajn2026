"""
═══════════════════════════════════════════════════════════
BRAJEN KEYWORD DEDUP v2.0 — Word-boundary safe deduplication
═══════════════════════════════════════════════════════════
Prevents double-counting of nested keywords by adjusting targets.

Key principles:
  - WORD-BOUNDARY matching only (no substring within words)
  - NEVER removes keywords — only reduces target_max
  - Works universally across all topics (legal, medical, travel, etc.)
  
v2.0 changes:
  - remove_subsumed works on BASIC AND EXTENDED (not just BASIC)
  - deduplicate_keywords reduces targets of phrases nested in MAIN
  - Accounts for cascading overlaps (MAIN → BASIC → sub-BASIC)
  
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


def remove_subsumed_basic(keywords: list, main_keyword: str = "") -> list:
    """
    v67 FIX: Remove BASIC AND EXTENDED keywords that are fully contained 
    in another longer BASIC/ENTITY/EXTENDED keyword.
    
    v60 only checked BASIC → missed all demoted BASIC→EXTENDED.
    v67 checks both BASIC and EXTENDED.
    
    Rules:
      - Removes BASIC and EXTENDED keywords (never MAIN, ENTITY)
      - The "parent" (longer phrase) must be BASIC, ENTITY, EXTENDED, or MAIN
      - Uses word-boundary matching
      - Never removes the main keyword or its exact synonyms
      - Only removes if short phrase has ≤2 words (single words and 2-word fragments)
    """
    if not keywords or len(keywords) < 2:
        return keywords
    
    main_kw_lower = main_keyword.lower().strip()
    
    # Build lookup of all potential parent phrases (any type)
    parent_phrases = []
    for kw in keywords:
        phrase = kw.get("keyword", "").strip().lower()
        if phrase and len(phrase.split()) >= 2:  # parents must be 2+ words
            parent_phrases.append(phrase)
    
    # Also include MAIN keyword as parent
    if main_kw_lower:
        parent_phrases.append(main_kw_lower)
    
    to_remove = set()
    
    for kw in keywords:
        kw_type = kw.get("type", "BASIC")
        # v67: Check BASIC and EXTENDED (not just BASIC)
        if kw_type not in ("BASIC", "EXTENDED"):
            continue
        
        short_phrase = kw.get("keyword", "").strip().lower()
        if not short_phrase:
            continue
        
        # Never remove main keyword
        if short_phrase == main_kw_lower:
            continue
        
        # Only remove short fragments (1-2 words) subsumed by longer phrases
        # Don't remove 3+ word phrases — they're specific enough to matter
        if len(short_phrase.split()) > 2:
            continue
        
        short_words = set(short_phrase.split())
        
        for parent in parent_phrases:
            if parent == short_phrase:
                continue  # same keyword
            
            parent_words = parent.split()
            if len(short_phrase.split()) >= len(parent_words):
                continue  # short is not actually shorter
            
            # Check: are ALL words of short contained in parent?
            if short_words.issubset(set(parent_words)):
                to_remove.add(short_phrase)
                logger.info(f"[DEDUP_REMOVE] '{short_phrase}' ⊂ '{parent}' → REMOVING ({kw_type})")
                break  # one parent match is enough
    
    if to_remove:
        original_count = len(keywords)
        keywords = [kw for kw in keywords 
                    if not (kw.get("type") in ("BASIC", "EXTENDED") 
                            and kw.get("keyword", "").strip().lower() in to_remove)]
        logger.info(f"[DEDUP_REMOVE] Removed {original_count - len(keywords)} subsumed keywords: {to_remove}")
    
    return keywords


def _fuzzy_word_match(word_a: str, word_b: str) -> bool:
    """
    Check if two Polish words are likely the same lemma.
    Handles inflection: czarnuszka ≈ czarnuszki, oleju ≈ olej, etc.
    
    Uses shared prefix ratio: words must share ≥75% prefix.
    For short words (≤3 chars): exact match only (prevents 'rok' ≈ 'rol').
    """
    if word_a == word_b:
        return True
    a, b = word_a.lower(), word_b.lower()
    min_len = min(len(a), len(b))
    max_len = max(len(a), len(b))
    if min_len <= 3:
        return False  # short words: exact only
    # Length difference > 3 chars is suspicious (different words)
    if max_len - min_len > 3:
        return False
    # Find common prefix length
    common = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            common += 1
        else:
            break
    # Must share ≥75% of the shorter word as prefix
    return common >= max(4, int(min_len * 0.75))


def cascade_deduct_targets(keywords: list, main_keyword: str = "") -> list:
    """
    v68: CASCADE DEDUCTION — Inclusion-Exclusion Principle.
    
    When phrase A contains phrase B, every occurrence of A is automatically 
    an occurrence of B. So B's standalone target should be reduced by A's target.
    
    Formula:
      adj_min(K) = max(0, raw_min(K) - Σ raw_max(children))
      adj_max(K) = max(0, raw_max(K) - Σ raw_min(children))
    
    Where "children" = longer phrases that CONTAIN K.
    
    Example:
      MAIN "olej z czarnuszki dla dzieci" [4,7] contains "olej z czarnuszki" [1,3]
      → adj("olej z czarnuszki") = [max(0, 1-7), max(0, 3-4)] = [0, 0]
      → GPT knows: don't add "olej z czarnuszki" separately, MAIN covers it.
    
    NEVER removes keywords. Sets adj_min/adj_max and saves originals as
    raw_target_min/raw_target_max for audit trail.
    """
    if not keywords or len(keywords) < 2:
        return keywords
    
    main_kw_lower = main_keyword.lower().strip()
    
    # Build phrase → keyword mapping
    kw_map = {}
    for kw in keywords:
        phrase = kw.get("keyword", "").strip().lower()
        if phrase:
            kw_map[phrase] = kw
    
    # For each keyword, find all "children" (longer phrases that contain it)
    deductions = 0
    for kw in keywords:
        phrase = kw.get("keyword", "").strip().lower()
        kw_type = kw.get("type", "BASIC")
        if not phrase:
            continue
        
        # MAIN keyword is the top of hierarchy — don't deduct from it
        if kw_type == "MAIN":
            continue
        
        phrase_words = set(phrase.split())
        
        # Find children: longer phrases that CONTAIN all words of this phrase
        children_sum_min = 0
        children_sum_max = 0
        children_found = []
        
        for other_kw in keywords:
            other_phrase = other_kw.get("keyword", "").strip().lower()
            if not other_phrase or other_phrase == phrase:
                continue
            
            other_words = other_phrase.split()
            # Child must be LONGER
            if len(other_words) <= len(phrase.split()):
                continue
            
            # Check containment: all words of phrase appear in other
            # Use fuzzy matching for Polish morphology (czarnuszka ≈ czarnuszki)
            all_match = True
            for pw in phrase_words:
                found = False
                for ow in other_words:
                    if pw == ow or _fuzzy_word_match(pw, ow):
                        found = True
                        break
                if not found:
                    all_match = False
                    break
            
            if all_match:
                children_sum_min += other_kw.get("target_min", 1)
                children_sum_max += other_kw.get("target_max", 5)
                children_found.append(other_phrase)
        
        if not children_found:
            continue
        
        # Apply Inclusion-Exclusion formula
        raw_min = kw.get("target_min", 1)
        raw_max = kw.get("target_max", 5)
        
        adj_min = max(0, raw_min - children_sum_max)
        adj_max = max(0, raw_max - children_sum_min)
        
        # Ensure adj_min <= adj_max
        if adj_min > adj_max:
            adj_min = adj_max
        
        if adj_min != raw_min or adj_max != raw_max:
            # Save originals for audit trail
            kw["raw_target_min"] = raw_min
            kw["raw_target_max"] = raw_max
            kw["target_min"] = adj_min
            kw["target_max"] = adj_max
            kw["_cascade_deducted"] = True
            kw["_cascade_children"] = children_found[:5]
            deductions += 1
            logger.info(
                f"[CASCADE] '{phrase}' deducted: [{raw_min},{raw_max}]→[{adj_min},{adj_max}] "
                f"(children: {', '.join(children_found[:3])})"
            )
    
    if deductions > 0:
        logger.info(f"[CASCADE] Deducted targets for {deductions} keywords")
    
    return keywords


def deduplicate_keywords(keywords: list, main_keyword: str = "") -> list:
    """
    Word-boundary safe keyword deduplication.
    
    NEVER removes keywords — only adjusts target_max downward to compensate
    for double-counting that occurs when the backend counts substring matches.
    
    v67 FIX: Also reduces targets of phrases nested in MAIN keyword.
    When MAIN="olej z czarnuszki dla dzieci" has target 9, every use of MAIN
    also counts as use of "olej z czarnuszki" and "czarnuszka".
    So "olej z czarnuszki" target should be reduced by MAIN's target.
    
    Reduction rules (conservative):
      - prefix_compound: reduce by 1/3 of parent's max
      - word_inside: reduce by 1/4 of parent's max
      - multi_word_prefix: reduce by 1/3 of parent's max
      - Nested in MAIN: reduce by 2/3 of MAIN's max (MAIN gets heavy use)
    
    Floor: target_max never drops below max(1, target_min).
    """
    if not keywords or len(keywords) < 2:
        return keywords
    
    main_kw_lower = main_keyword.lower().strip()
    main_max = 0
    for kw in keywords:
        if kw.get("type") == "MAIN":
            main_max = kw.get("target_max", 9)
            break
    
    adjustments = 0
    
    for i, kw_short in enumerate(keywords):
        short_phrase = kw_short.get("keyword", "").strip()
        short_type = kw_short.get("type", "BASIC")
        
        if not short_phrase:
            continue
        
        # v67 FIX: Don't skip non-MAIN keywords for MAIN overlap check
        # But still skip adjusting MAIN keyword itself
        if short_type == "MAIN":
            continue
        
        total_reduction = 0
        found_in_main = False
        
        # Check overlap with MAIN keyword FIRST (biggest source of double-counting)
        if main_kw_lower:
            main_overlap = _word_boundary_overlap(short_phrase, main_kw_lower)
            if main_overlap:
                found_in_main = True
                # v67: MAIN overlap is the PRIMARY source of over-optimization
                # Every use of MAIN counts as +1 for this sub-phrase
                # So reduce by ~2/3 of MAIN's target (MAIN will be used heavily)
                reduction = max(1, main_max * 2 // 3)
                total_reduction += reduction
                logger.info(f"[DEDUP] '{short_phrase}' ∈ MAIN '{main_keyword}' → reduce by {reduction} (main_max={main_max})")
        
        # Check overlap with other keywords
        for j, kw_long in enumerate(keywords):
            if i == j:
                continue
            
            long_phrase = kw_long.get("keyword", "").strip()
            long_type = kw_long.get("type", "BASIC")
            long_max = kw_long.get("target_max", 5)
            
            if not long_phrase:
                continue
            
            # Skip MAIN (already handled above)
            if long_type == "MAIN":
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
        
        if total_reduction > 0:
            old_max = kw_short.get("target_max", 5)
            floor = max(1, kw_short.get("target_min", 1))
            new_max = max(floor, old_max - total_reduction)
            
            if new_max < old_max:
                kw_short["target_max"] = new_max
                # Also reduce target_min if it's now above target_max
                if kw_short.get("target_min", 1) > new_max:
                    kw_short["target_min"] = max(1, new_max)
                adjustments += 1
                logger.info(f"[DEDUP] '{short_phrase}' target_max: {old_max} → {new_max}")
    
    if adjustments > 0:
        logger.info(f"[DEDUP] Adjusted targets for {adjustments} keywords")
    
    return keywords
