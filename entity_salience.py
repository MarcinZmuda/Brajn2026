"""
═══════════════════════════════════════════════════════════
BRAJEN ENTITY SALIENCE MODULE v1.0
═══════════════════════════════════════════════════════════
Real entity salience measurement via Google Cloud Natural Language API.

NOT simulated — calls the actual API that Google uses internally.
Returns the same salience scores (0.0–1.0) documented in:
  - Dunietz & Gillick (2014) "A New Entity Salience Task"
  - Google Cloud NLP docs: cloud.google.com/natural-language

Requirements:
  - GOOGLE_NLP_API_KEY env var (free tier: 5000 units/month)
  - ~20 units per 3500-word article analysis

Features:
  1. Salience analysis — measures entity salience in final article
  2. Schema.org JSON-LD — generates structured data from real entities
  3. Topical map — entity-based content architecture recommendations
═══════════════════════════════════════════════════════════
"""

import os
import json
import logging
import re

logger = logging.getLogger(__name__)

GOOGLE_NLP_API_KEY = os.environ.get("GOOGLE_NLP_API_KEY", "")
GOOGLE_NLP_ENDPOINT = "https://language.googleapis.com/v1/documents:analyzeEntities"

# Entity types from Google NLP API
ENTITY_TYPE_MAP = {
    "PERSON": "Person",
    "LOCATION": "Place",
    "ORGANIZATION": "Organization",
    "EVENT": "Event",
    "WORK_OF_ART": "CreativeWork",
    "CONSUMER_GOOD": "Product",
    "OTHER": "Thing",
    "UNKNOWN": "Thing",
    "NUMBER": None,  # skip
    "DATE": None,    # skip
    "PRICE": None,   # skip
    "ADDRESS": "Place",
    "PHONE_NUMBER": None,  # skip
}


# ════════════════════════════════════════════════════════════
# 1. GOOGLE NLP API — REAL SALIENCE MEASUREMENT
# ════════════════════════════════════════════════════════════

def analyze_entities_google_nlp(text, language="pl"):
    """
    Call Google Cloud Natural Language API to extract entities with salience.
    
    Returns list of entities:
      [{"name": "...", "type": "PERSON", "salience": 0.73, 
        "wikipedia_url": "...", "mid": "/m/...", "mentions": 5}, ...]
    
    Returns empty list if API key missing or call fails.
    """
    if not GOOGLE_NLP_API_KEY:
        logger.warning("GOOGLE_NLP_API_KEY not set — salience analysis skipped")
        return []

    # Google NLP API has 1MB limit; truncate if needed
    max_chars = 500_000
    if len(text) > max_chars:
        text = text[:max_chars]

    try:
        import requests
        response = requests.post(
            f"{GOOGLE_NLP_ENDPOINT}?key={GOOGLE_NLP_API_KEY}",
            json={
                "document": {
                    "type": "PLAIN_TEXT",
                    "language": language,
                    "content": text
                },
                "encodingType": "UTF8"
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.warning(f"Google NLP API error {response.status_code}: {response.text[:200]}")
            return []

        data = response.json()
        entities = []
        
        for ent in data.get("entities", []):
            etype = ent.get("type", "UNKNOWN")
            if ENTITY_TYPE_MAP.get(etype) is None:
                continue  # skip numbers, dates, prices
            
            metadata = ent.get("metadata", {})
            entities.append({
                "name": ent.get("name", ""),
                "type": etype,
                "schema_type": ENTITY_TYPE_MAP.get(etype, "Thing"),
                "salience": round(ent.get("salience", 0.0), 4),
                "wikipedia_url": metadata.get("wikipedia_url", ""),
                "mid": metadata.get("mid", ""),  # Knowledge Graph Machine ID
                "mentions": len(ent.get("mentions", [])),
            })

        # Sort by salience descending
        entities.sort(key=lambda e: e["salience"], reverse=True)
        return entities

    except Exception as e:
        logger.warning(f"Google NLP API call failed: {e}")
        return []


def check_entity_salience(text, main_keyword, language="pl"):
    """
    Analyze article and check if main entity has highest salience.
    
    Returns:
      {
        "enabled": True/False,  # whether API was called
        "entities": [...],      # all entities with salience
        "main_entity": {...},   # the main keyword entity (or None)
        "main_salience": 0.73,  # salience of main entity
        "top_entity": {...},    # entity with highest salience
        "is_main_dominant": True/False,  # main entity has highest salience?
        "issues": [...],        # list of issues found
        "recommendations": [...],  # how to fix
        "score": 85,            # entity salience score (0-100)
      }
    """
    result = {
        "enabled": bool(GOOGLE_NLP_API_KEY),
        "entities": [],
        "main_entity": None,
        "main_salience": 0.0,
        "top_entity": None,
        "is_main_dominant": False,
        "issues": [],
        "recommendations": [],
        "score": 0,
    }

    if not GOOGLE_NLP_API_KEY:
        result["issues"].append("GOOGLE_NLP_API_KEY nie ustawiony — analiza salience niedostępna")
        return result

    entities = analyze_entities_google_nlp(text, language)
    if not entities:
        result["issues"].append("Google NLP API nie zwróciło encji")
        return result

    result["entities"] = entities[:20]  # top 20

    if entities:
        result["top_entity"] = entities[0]

    # Find main keyword entity
    main_kw_lower = main_keyword.lower().strip()
    main_entity = None
    
    for ent in entities:
        ent_name_lower = ent["name"].lower().strip()
        # Match: exact, contains, or contained in
        if (ent_name_lower == main_kw_lower or
            main_kw_lower in ent_name_lower or
            ent_name_lower in main_kw_lower):
            main_entity = ent
            break

    if main_entity:
        result["main_entity"] = main_entity
        result["main_salience"] = main_entity["salience"]
        result["is_main_dominant"] = (main_entity == entities[0])
    else:
        result["issues"].append(
            f'Encja główna "{main_keyword}" nie została rozpoznana przez Google NLP API. '
            f'Google może nie rozumieć tematu Twojego artykułu.'
        )
        result["recommendations"].append(
            f'Umieść "{main_keyword}" jako podmiot gramatyczny w pierwszym zdaniu, H1 i co najmniej 2 nagłówkach H2.'
        )

    # Score calculation (0-100)
    score = 0

    if main_entity:
        salience = main_entity["salience"]
        
        # Main entity salience scoring (max 50 points)
        if salience >= 0.4:
            score += 50
        elif salience >= 0.25:
            score += 35
        elif salience >= 0.15:
            score += 20
        elif salience >= 0.05:
            score += 10

        # Is main entity dominant? (max 20 points)
        if result["is_main_dominant"]:
            score += 20
        elif entities and main_entity["salience"] >= entities[0]["salience"] * 0.7:
            score += 10  # close enough

        # Has Knowledge Graph ID (max 10 points)
        if main_entity.get("mid"):
            score += 10
        if main_entity.get("wikipedia_url"):
            score += 5

    # Entity hierarchy quality (max 15 points)
    if len(entities) >= 3:
        top3_salience = sum(e["salience"] for e in entities[:3])
        if top3_salience >= 0.5:
            score += 10
        if entities[0]["salience"] >= 2 * entities[1]["salience"]:
            score += 5  # clear hierarchy

    result["score"] = min(100, score)

    # Generate issues
    if main_entity and not result["is_main_dominant"]:
        top = entities[0]
        result["issues"].append(
            f'Encja "{top["name"]}" (salience: {top["salience"]:.2f}) '
            f'dominuje nad encją główną "{main_entity["name"]}" (salience: {main_entity["salience"]:.2f}). '
            f'Google może myśleć, że artykuł jest o "{top["name"]}", nie o "{main_keyword}".'
        )
        result["recommendations"].extend([
            f'Przenieś "{main_keyword}" na pozycję podmiotu w kluczowych zdaniach.',
            f'Dodaj więcej wzmianek o "{main_keyword}" na początku akapitów.',
            f'Zredukuj wzmianki o "{top["name"]}" lub przenieś je dalej w tekście.',
        ])

    if main_entity and main_entity["salience"] < 0.15:
        result["issues"].append(
            f'Salience encji głównej ({main_entity["salience"]:.2f}) jest bardzo niska. '
            f'Cel: > 0.25, ideał: > 0.40.'
        )
        result["recommendations"].append(
            'Umieść encję główną w: tytule, H1, pierwszym zdaniu, URL, meta description, alt text obrazów.'
        )

    # Check for topic drift
    if len(entities) >= 5:
        top5_types = set(e["type"] for e in entities[:5])
        if len(top5_types) >= 4:
            result["issues"].append(
                'Wysoka różnorodność typów encji w top 5 — możliwy topic drift. '
                'Skoncentruj treść wokół jednego tematu.'
            )

    return result


# ════════════════════════════════════════════════════════════
# 2. SCHEMA.ORG JSON-LD GENERATION
# ════════════════════════════════════════════════════════════

def generate_article_schema(main_keyword, entities, article_url="", author_name="",
                            author_url="", publisher_name="", publisher_url="",
                            date_published="", date_modified="", h2_list=None):
    """
    Generate Schema.org JSON-LD for Article based on REAL entities from NLP API.
    
    Only includes entities that were actually detected — nothing made up.
    Uses Wikidata/Wikipedia URLs only when returned by the API.
    """
    schema = {
        "@context": "https://schema.org",
        "@graph": []
    }

    # --- Article node ---
    article = {
        "@type": "Article",
        "headline": main_keyword,
    }

    if article_url:
        article["@id"] = f"{article_url}#article"
        article["mainEntityOfPage"] = {
            "@type": "WebPage",
            "@id": article_url
        }

    # Main entity — from NLP analysis
    main_entity_data = None
    if entities:
        # Find main keyword entity
        main_kw_lower = main_keyword.lower()
        for ent in entities:
            if (ent["name"].lower() == main_kw_lower or
                main_kw_lower in ent["name"].lower() or
                ent["name"].lower() in main_kw_lower):
                main_entity_data = ent
                break

    if main_entity_data:
        about = {
            "@type": main_entity_data.get("schema_type", "Thing"),
            "name": main_entity_data["name"],
        }
        # Only add sameAs if API returned real URLs
        same_as = []
        if main_entity_data.get("wikipedia_url"):
            same_as.append(main_entity_data["wikipedia_url"])
            # Derive Wikidata URL from Wikipedia URL
            wiki_title = main_entity_data["wikipedia_url"].split("/wiki/")[-1] if "/wiki/" in main_entity_data["wikipedia_url"] else ""
            if wiki_title:
                about["url"] = main_entity_data["wikipedia_url"]
        if same_as:
            about["sameAs"] = same_as[0] if len(same_as) == 1 else same_as

        article["about"] = about

    # Mentions — secondary entities with real data
    mentions = []
    for ent in (entities or [])[:15]:
        if ent == main_entity_data:
            continue
        if ent.get("salience", 0) < 0.01:
            continue
        schema_type = ent.get("schema_type", "Thing")
        if not schema_type:
            continue
        
        mention = {
            "@type": schema_type,
            "name": ent["name"],
        }
        if ent.get("wikipedia_url"):
            mention["sameAs"] = ent["wikipedia_url"]
        mentions.append(mention)

    if mentions:
        article["mentions"] = mentions[:10]

    # Author
    if author_name:
        author = {
            "@type": "Person",
            "name": author_name,
        }
        if author_url:
            author["url"] = author_url
        article["author"] = author

    # Publisher
    if publisher_name:
        publisher = {
            "@type": "Organization",
            "name": publisher_name,
        }
        if publisher_url:
            publisher["url"] = publisher_url
        article["publisher"] = publisher

    if date_published:
        article["datePublished"] = date_published
    if date_modified:
        article["dateModified"] = date_modified

    schema["@graph"].append(article)

    return schema


def schema_to_html(schema_dict):
    """Convert schema dict to HTML script tag."""
    json_str = json.dumps(schema_dict, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{json_str}\n</script>'


# ════════════════════════════════════════════════════════════
# 3. TOPICAL MAP — ENTITY-BASED CONTENT RECOMMENDATIONS
# ════════════════════════════════════════════════════════════

def generate_topical_map(main_keyword, s1_data, nlp_entities=None):
    """
    Generate entity-based content architecture recommendations.
    
    Based on REAL data from:
    - S1 analysis (content gaps, entity relations, PAA, related searches)
    - NLP entities (if available — Wikidata connections)
    
    Returns:
      {
        "pillar": {"entity": "...", "url_slug": "...", "description": "..."},
        "clusters": [
          {"entity": "...", "type": "...", "relation_to_pillar": "...", 
           "suggested_h1": "...", "source": "content_gap|paa|entity_relation|related_search"},
        ],
        "internal_links": [
          {"from": "...", "to": "...", "anchor_text": "...", "entity_bridge": "..."},
        ],
      }
    """
    result = {
        "pillar": {
            "entity": main_keyword,
            "url_slug": _slugify(main_keyword),
            "description": f"Strona filarowa o {main_keyword}",
        },
        "clusters": [],
        "internal_links": [],
    }

    seen_topics = {main_keyword.lower()}

    # Source 1: Content gaps → cluster pages (highest priority — unique content)
    content_gaps = s1_data.get("content_gaps") or {}
    
    for gap in (content_gaps.get("paa_unanswered") or [])[:5]:
        topic = gap.get("question", gap) if isinstance(gap, dict) else str(gap)
        if topic.lower() not in seen_topics:
            result["clusters"].append({
                "entity": topic,
                "type": "PAA_UNANSWERED",
                "relation_to_pillar": "pytanie użytkowników bez odpowiedzi w top 10",
                "suggested_h1": topic,
                "source": "content_gap",
                "priority": "HIGH",
            })
            seen_topics.add(topic.lower())

    for gap in (content_gaps.get("subtopic_missing") or [])[:5]:
        topic = gap.get("topic", gap.get("subtopic", gap)) if isinstance(gap, dict) else str(gap)
        if topic.lower() not in seen_topics:
            result["clusters"].append({
                "entity": topic,
                "type": "SUBTOPIC_MISSING",
                "relation_to_pillar": f"podtemat {main_keyword} brakujący u konkurencji",
                "suggested_h1": f"{topic} — kompletny przewodnik",
                "source": "content_gap",
                "priority": "HIGH",
            })
            seen_topics.add(topic.lower())

    # Source 2: Entity relations (S-V-O triplets) → cluster pages
    entity_seo = s1_data.get("entity_seo") or {}
    relations = entity_seo.get("relations") or []
    
    for rel in relations[:8]:
        if isinstance(rel, dict):
            obj = rel.get("object", "")
            subj = rel.get("subject", "")
            # The "other" entity in the relation is a potential cluster topic
            other = obj if main_keyword.lower() in subj.lower() else subj
            if other and other.lower() not in seen_topics and len(other) > 3:
                verb = rel.get("verb", rel.get("relation", "→"))
                result["clusters"].append({
                    "entity": other,
                    "type": "ENTITY_RELATION",
                    "relation_to_pillar": f"{main_keyword} {verb} {other}",
                    "suggested_h1": f"{other} — co musisz wiedzieć",
                    "source": "entity_relation",
                    "priority": "MEDIUM",
                })
                seen_topics.add(other.lower())

    # Source 3: PAA questions → cluster pages or FAQ sections
    paa = s1_data.get("paa") or s1_data.get("paa_questions") or []
    serp = s1_data.get("serp_analysis") or {}
    paa = paa or serp.get("paa_questions") or []
    
    for q in paa[:8]:
        question = q.get("question", q) if isinstance(q, dict) else str(q)
        if question.lower() not in seen_topics and len(question) > 10:
            result["clusters"].append({
                "entity": question,
                "type": "PAA",
                "relation_to_pillar": f"pytanie użytkowników o {main_keyword}",
                "suggested_h1": question,
                "source": "paa",
                "priority": "MEDIUM",
            })
            seen_topics.add(question.lower())

    # Source 4: Related searches → cluster pages
    related = s1_data.get("related_searches") or serp.get("related_searches") or []
    for rs in related[:5]:
        topic = rs.get("query", rs) if isinstance(rs, dict) else str(rs)
        if topic.lower() not in seen_topics and len(topic) > 3:
            result["clusters"].append({
                "entity": topic,
                "type": "RELATED_SEARCH",
                "relation_to_pillar": f"powiązane wyszukiwanie Google",
                "suggested_h1": topic,
                "source": "related_search",
                "priority": "LOW",
            })
            seen_topics.add(topic.lower())

    # Source 5: NLP entities with Wikipedia/Wikidata connections
    if nlp_entities:
        for ent in nlp_entities[:10]:
            if (ent.get("wikipedia_url") and 
                ent["name"].lower() not in seen_topics and
                ent.get("salience", 0) >= 0.05 and
                ent["name"].lower() != main_keyword.lower()):
                result["clusters"].append({
                    "entity": ent["name"],
                    "type": ent.get("type", "OTHER"),
                    "relation_to_pillar": f"encja Knowledge Graph (salience: {ent['salience']:.2f})",
                    "suggested_h1": f"{ent['name']} — {_entity_relation_hint(ent, main_keyword)}",
                    "source": "nlp_entity",
                    "priority": "LOW",
                    "wikipedia_url": ent["wikipedia_url"],
                    "mid": ent.get("mid", ""),
                })
                seen_topics.add(ent["name"].lower())

    # Generate internal link suggestions
    for cluster in result["clusters"][:10]:
        result["internal_links"].append({
            "from_page": result["pillar"]["url_slug"],
            "to_page": _slugify(cluster["entity"]),
            "anchor_text": cluster["entity"],
            "entity_bridge": main_keyword,
            "context": f"Link w sekcji o {cluster['relation_to_pillar']}"
        })
        result["internal_links"].append({
            "from_page": _slugify(cluster["entity"]),
            "to_page": result["pillar"]["url_slug"],
            "anchor_text": main_keyword,
            "entity_bridge": cluster["entity"],
            "context": "Link powrotny do strony filarowej"
        })

    # Limit clusters
    result["clusters"] = result["clusters"][:15]
    result["internal_links"] = result["internal_links"][:30]

    return result


# ════════════════════════════════════════════════════════════
# 4. PROMPT INSTRUCTIONS FOR ENTITY SALIENCE
# ════════════════════════════════════════════════════════════

def build_entity_salience_instructions(main_keyword, entities_from_s1=None):
    """
    Build explicit entity salience instructions for the LLM.
    
    Based on research:
    - Dunietz & Gillick (2014) entity salience factors
    - Google NLP API salience scoring
    - Patent US10235423B2 entity metrics
    - Patent US9251473B2 salient items identification
    
    v45.4.1: entities_from_s1 parameter kept for backward compatibility
    but no longer injected into prompt. Secondary entities are now handled
    exclusively by gpt_instructions_v39 "🧠 ENCJE:" section from master API.
    """
    instructions = []

    instructions.append(f"""═══ ENTITY SALIENCE — POZYCJA ENCJI W TEKŚCIE ═══
ENCJA GŁÓWNA: "{main_keyword}"

Google mierzy „salience" (wyrazistość) encji w tekście na skali 0.0–1.0.
Encja główna MUSI mieć najwyższą salience. Oto jak to osiągnąć:

ZASADA 1 — POZYCJA: Umieszczaj "{main_keyword}" NA POCZĄTKU:
  • Pierwszym zdaniu artykułu (obowiązkowe)
  • Pierwszym zdaniu każdego akapitu (gdy naturalnie pasuje)
  • W H1 i w min. 2 nagłówkach H2
  Początek > koniec > środek — pod względem wpływu na salience.

ZASADA 2 — ROLA GRAMATYCZNA: "{main_keyword}" = PODMIOT, nie dopełnienie:
  ✅ „{main_keyword} wymaga..." / „{main_keyword} polega na..."
  ❌ „Ważnym aspektem jest {main_keyword}" / „Do {main_keyword} należy..."
  Podmiot (kto/co?) daje 3-6× wyższą salience niż dopełnienie.

ZASADA 3 — SPÓJNE NAZEWNICTWO: Używaj konsekwentnie jednej formy nazwy.
  NIE przeskakuj między akronimem a pełną nazwą — to rozmywa salience.
  Dopuszczalne warianty: forma odmieniona, zaimek „on/ona/to", forma skrócona.

ZASADA 4 — HIERARCHIA ENCJI: 
  • 1 encja główna (salience > 0.25) — "{main_keyword}"
  • 3-5 encji wtórnych (salience 0.05–0.15 każda)
  • Unikaj „wyrównanej" salience — jedna encja musi dominować.""")

    # v45.4.1: Secondary entities REMOVED from salience instructions.
    # gpt_instructions_v39 already contains curated "🧠 ENCJE:" section
    # with 3 best entities per batch (importance >= 0.7, with HOW hints).
    # Injecting additional entities_from_s1 here caused duplication and
    # introduced CSS/JS garbage that passed through filters.

    return "\n".join(instructions)


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def _slugify(text):
    """Simple Polish-safe slugify."""
    text = text.lower().strip()
    text = re.sub(r'[ąĄ]', 'a', text)
    text = re.sub(r'[ćĆ]', 'c', text)
    text = re.sub(r'[ęĘ]', 'e', text)
    text = re.sub(r'[łŁ]', 'l', text)
    text = re.sub(r'[ńŃ]', 'n', text)
    text = re.sub(r'[óÓ]', 'o', text)
    text = re.sub(r'[śŚ]', 's', text)
    text = re.sub(r'[źŹżŻ]', 'z', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text[:80]


def _entity_relation_hint(entity, main_keyword):
    """Generate a natural relation description."""
    etype = entity.get("type", "")
    if etype == "PERSON":
        return f"rola w kontekście {main_keyword}"
    elif etype == "ORGANIZATION":
        return f"organizacja związana z {main_keyword}"
    elif etype == "LOCATION":
        return f"miejsce związane z {main_keyword}"
    elif etype == "EVENT":
        return f"wydarzenie dotyczące {main_keyword}"
    return f"powiązanie z {main_keyword}"


def analyze_style_consistency(text):
    """
    Anti-Frankenstein analysis — detect style drift across batches.
    
    Measures:
    - Sentence length variation (CV < 0.4 = consistent, > 0.6 = Frankenstein)
    - Paragraph length variation
    - Passive voice ratio (Polish heuristic: "jest/są/został/została" patterns)
    - Formality indicators
    - Repetition patterns
    
    Returns dict with metrics and score (0-100, higher = more consistent).
    """
    if not text or len(text) < 100:
        return {"score": 0, "error": "Text too short"}

    # Split into sentences
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

    # Split into paragraphs
    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]

    # Sentence lengths
    sent_lengths = [len(s.split()) for s in sentences]
    avg_sent_len = sum(sent_lengths) / max(1, len(sent_lengths))
    
    import math
    if len(sent_lengths) > 1 and avg_sent_len > 0:
        variance = sum((x - avg_sent_len) ** 2 for x in sent_lengths) / len(sent_lengths)
        std_dev = math.sqrt(variance)
        cv_sentences = std_dev / avg_sent_len  # coefficient of variation
    else:
        cv_sentences = 0

    # Paragraph lengths
    para_lengths = [len(p.split()) for p in paragraphs]
    avg_para_len = sum(para_lengths) / max(1, len(para_lengths))
    if len(para_lengths) > 1 and avg_para_len > 0:
        p_var = sum((x - avg_para_len) ** 2 for x in para_lengths) / len(para_lengths)
        cv_paragraphs = math.sqrt(p_var) / avg_para_len
    else:
        cv_paragraphs = 0

    # Passive voice (Polish heuristic)
    passive_patterns = [
        r'\bjest\s+\w+[aeioyąę][nm]?[aey]?\b',  # jest + participle
        r'\bsą\s+\w+[aeioyąę][nm]?[aey]?\b',
        r'\bzostał[aoy]?\b', r'\bzostanie\b', r'\bzostają\b',
        r'\bbyło\b', r'\bbył[aoy]?\b',
    ]
    passive_count = 0
    for sent in sentences:
        for pattern in passive_patterns:
            if re.search(pattern, sent, re.IGNORECASE):
                passive_count += 1
                break
    passive_ratio = passive_count / max(1, len(sentences))

    # Transition words (Polish)
    transition_words = [
        'jednak', 'natomiast', 'ponadto', 'podsumowując', 'warto',
        'należy', 'co więcej', 'w związku', 'dlatego', 'bowiem',
        'przede wszystkim', 'w rezultacie', 'z kolei', 'mimo to',
        'w praktyce', 'w konsekwencji', 'co istotne', 'warto podkreślić',
    ]
    transition_count = sum(
        1 for sent in sentences
        if any(sent.lower().startswith(tw) or f' {tw} ' in sent.lower() for tw in transition_words)
    )
    transition_ratio = transition_count / max(1, len(sentences))

    # Repetition: consecutive sentences starting with same word
    repetition_count = 0
    for i in range(1, len(sentences)):
        w1 = sentences[i-1].split()[0].lower() if sentences[i-1].split() else ''
        w2 = sentences[i].split()[0].lower() if sentences[i].split() else ''
        if w1 and w1 == w2 and len(w1) > 2:
            repetition_count += 1
    repetition_ratio = repetition_count / max(1, len(sentences) - 1)

    # Score calculation (0-100, higher = more consistent/natural)
    score = 100

    # Sentence CV: 0.3-0.5 is ideal (natural variation)
    if cv_sentences < 0.2:
        score -= 15  # too monotone
    elif cv_sentences > 0.6:
        score -= 20  # Frankenstein
    elif cv_sentences > 0.5:
        score -= 10

    # Passive voice: < 20% ideal
    if passive_ratio > 0.35:
        score -= 20
    elif passive_ratio > 0.25:
        score -= 10

    # Transitions: 15-30% ideal
    if transition_ratio < 0.05:
        score -= 10  # abrupt
    elif transition_ratio > 0.4:
        score -= 10  # over-connected

    # Repetition: < 5% ideal
    if repetition_ratio > 0.15:
        score -= 15
    elif repetition_ratio > 0.08:
        score -= 8

    # Paragraph consistency
    if cv_paragraphs > 0.7:
        score -= 10

    score = max(0, min(100, score))

    return {
        "score": score,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "avg_sentence_length": round(avg_sent_len, 1),
        "cv_sentences": round(cv_sentences, 3),
        "avg_paragraph_length": round(avg_para_len, 1),
        "cv_paragraphs": round(cv_paragraphs, 3),
        "passive_ratio": round(passive_ratio, 3),
        "passive_count": passive_count,
        "transition_ratio": round(transition_ratio, 3),
        "repetition_ratio": round(repetition_ratio, 3),
        "issues": _style_issues(cv_sentences, passive_ratio, transition_ratio, repetition_ratio, cv_paragraphs, avg_sent_len),
    }


def _style_issues(cv_sent, passive, transitions, repetition, cv_para, avg_len):
    """Generate human-readable style issues."""
    issues = []
    if cv_sent > 0.6:
        issues.append(f"Duża zmienność długości zdań (CV={cv_sent:.2f}) — możliwy efekt Frankenstein między batchami")
    elif cv_sent < 0.2:
        issues.append(f"Zbyt monotonne zdania (CV={cv_sent:.2f}) — brak naturalnej wariacji")
    if passive > 0.3:
        issues.append(f"Wysoki udział strony biernej ({passive:.0%}) — osłabia entity salience")
    if transitions < 0.05:
        issues.append("Brak słów łączących — tekst może być chaotyczny")
    elif transitions > 0.4:
        issues.append("Nadmiar słów łączących — tekst może brzmi sztucznie")
    if repetition > 0.1:
        issues.append(f"Powtarzające się początki zdań ({repetition:.0%}) — widoczny wzorzec AI")
    if cv_para > 0.7:
        issues.append("Duża zmienność długości akapitów — niespójny rytm tekstu")
    if avg_len > 25:
        issues.append(f"Długie zdania (śr. {avg_len:.0f} słów) — trudne w czytaniu")
    elif avg_len < 10:
        issues.append(f"Bardzo krótkie zdania (śr. {avg_len:.0f} słów) — może być zbyt pocięte")
    return issues


def analyze_subject_position(text, main_keyword):
    """
    Measure how often main entity appears as grammatical subject vs object.
    
    Based on Dunietz & Gillick (2014): subject position gives 3-6× higher salience.
    
    Heuristic approach (no dependency parser needed):
    - Subject: entity at START of sentence (first 3 words)
    - Object: entity at END of sentence (last 40% of words)
    - Middle: entity in middle of sentence
    
    Returns:
      {
        "total_sentences": 120,
        "sentences_with_entity": 35,
        "subject_position": 18,  # entity in first 3 words
        "object_position": 8,    # entity in last 40%
        "middle_position": 9,
        "subject_ratio": 0.51,   # subject / sentences_with_entity
        "first_sentence_has_entity": True,
        "h1_has_entity": True,
        "h2_entity_count": 3,
        "paragraph_starts_with_entity": 8,
        "score": 75,  # 0-100
      }
    """
    if not text or not main_keyword:
        return {"total_sentences": 0, "sentences_with_entity": 0, "score": 0}

    # Normalize
    kw_lower = main_keyword.lower().strip()
    kw_variants = {kw_lower}
    # Add common Polish declension patterns (simplified)
    # v57 FIX: Multi-word stem matching — generate stems for EACH word
    kw_words = kw_lower.split()
    kw_stems = []
    _PL_SUFFIXES = ['ości', 'ości', 'iem', 'ami', 'ach', 'ów', 'om', 'ie', 'ę', 'ą', 'u', 'a', 'em', 'y', 'i']
    for word in kw_words:
        stem = word
        if len(word) > 4:
            for suffix in _PL_SUFFIXES:
                if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                    stem = word[:-len(suffix)]
                    break
        kw_stems.append(stem)
    # Legacy single-keyword variant
    if len(kw_lower) > 4:
        for suffix in ['u', 'a', 'em', 'ie', 'ę', 'ą', 'om', 'ami', 'ach', 'ów']:
            if kw_lower.endswith(suffix):
                stem = kw_lower[:-len(suffix)]
                if len(stem) >= 3:
                    kw_variants.add(stem)
                break

    def contains_entity(text_fragment):
        """Check if entity is present — tries exact match first, then stem matching."""
        frag_lower = text_fragment.lower()
        # Fast path: exact match of any variant
        if any(v in frag_lower for v in kw_variants):
            return True
        # Stem path: all stems must appear in text (in order, allowing declension)
        if len(kw_stems) >= 2:
            # For multi-word: check each stem is present
            return all(stem in frag_lower for stem in kw_stems if len(stem) >= 3)
        elif kw_stems:
            # Single word: stem must be present
            return kw_stems[0] in frag_lower if len(kw_stems[0]) >= 3 else False
        return False

    # Split into sentences
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    # Split into paragraphs
    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]

    # Extract H2 headers (supports: "## Title", "h2: Title", "<h2>Title</h2>")
    h2_lines = []
    h2_lines.extend(re.findall(r'^##\s+(.+)$', text, re.MULTILINE))
    h2_lines.extend(re.findall(r'^h2:\s*(.+)$', text, re.MULTILINE))
    h2_lines.extend(re.findall(r'<h2[^>]*>(.*?)</h2>', text, re.IGNORECASE | re.DOTALL))

    result = {
        "total_sentences": len(sentences),
        "sentences_with_entity": 0,
        "subject_position": 0,
        "object_position": 0,
        "middle_position": 0,
        "subject_ratio": 0.0,
        "first_sentence_has_entity": False,
        "h1_has_entity": False,
        "h2_entity_count": 0,
        "paragraph_starts_with_entity": 0,
        "score": 0,
    }

    if not sentences:
        return result

    # Check first sentence
    result["first_sentence_has_entity"] = contains_entity(sentences[0])

    # Check H2s
    result["h2_entity_count"] = sum(1 for h in h2_lines if contains_entity(h))

    # Check H1 (supports: "# Title", "h1: Title", "<h1>Title</h1>")
    h1_lines = re.findall(r'^#\s+(.+)$', text, re.MULTILINE)
    h1_lines.extend(re.findall(r'^h1:\s*(.+)$', text, re.MULTILINE))
    h1_lines.extend(re.findall(r'<h1[^>]*>(.*?)</h1>', text, re.IGNORECASE | re.DOTALL))
    if h1_lines:
        result["h1_has_entity"] = contains_entity(h1_lines[0])

    # Check paragraph starts
    for p in paragraphs:
        first_words = ' '.join(p.split()[:5])
        if contains_entity(first_words):
            result["paragraph_starts_with_entity"] += 1

    # Analyze each sentence
    for sent in sentences:
        if not contains_entity(sent):
            continue
        result["sentences_with_entity"] += 1

        words = sent.split()
        total_words = len(words)
        if total_words < 3:
            result["subject_position"] += 1
            continue

        first_3 = ' '.join(words[:3]).lower()
        last_40pct = ' '.join(words[int(total_words * 0.6):]).lower()

        if any(v in first_3 for v in kw_variants):
            result["subject_position"] += 1
        elif any(v in last_40pct for v in kw_variants):
            result["object_position"] += 1
        else:
            result["middle_position"] += 1

    # Calculate ratios
    with_entity = result["sentences_with_entity"]
    if with_entity > 0:
        result["subject_ratio"] = round(result["subject_position"] / with_entity, 3)

    # Score (0-100)
    score = 0

    # Subject ratio (max 40 pts)
    sr = result["subject_ratio"]
    if sr >= 0.5:
        score += 40
    elif sr >= 0.35:
        score += 30
    elif sr >= 0.2:
        score += 20
    elif sr >= 0.1:
        score += 10

    # First sentence (15 pts)
    if result["first_sentence_has_entity"]:
        score += 15

    # H2 presence (15 pts)
    if result["h2_entity_count"] >= 2:
        score += 15
    elif result["h2_entity_count"] >= 1:
        score += 8

    # Paragraph starts (15 pts)
    para_ratio = result["paragraph_starts_with_entity"] / max(1, len(paragraphs))
    if para_ratio >= 0.3:
        score += 15
    elif para_ratio >= 0.15:
        score += 8

    # Entity presence overall (15 pts)
    ent_ratio = with_entity / max(1, len(sentences))
    if ent_ratio >= 0.25:
        score += 15
    elif ent_ratio >= 0.15:
        score += 10
    elif ent_ratio >= 0.08:
        score += 5

    result["score"] = min(100, score)
    return result


def analyze_ymyl_references(text, legal_context=None, medical_context=None):
    """
    Scan article text for legal references and medical citations.
    Works locally without any API — pure regex/heuristic analysis.
    
    Returns:
      {
        "legal": {
          "acts_found": [...],          # Legal acts mentioned in text
          "judgments_found": [...],       # Case law signatures found
          "articles_cited": [...],       # "art. 13 kc" etc.
          "disclaimer_present": bool,
          "acts_from_context_used": int, # How many backend-provided acts appear
          "judgments_from_context_used": int,
          "score": 0-100,
        },
        "medical": {
          "pmids_found": [...],
          "studies_referenced": [...],   # "badanie z 2023" etc.
          "institutions_found": [...],   # WHO, NIH, etc.
          "disclaimer_present": bool,
          "pubs_from_context_used": int,
          "evidence_indicators": [...],  # "meta-analiza", "RCT" etc.
          "score": 0-100,
        }
      }
    """
    result = {"legal": {}, "medical": {}}
    
    if not text:
        return result
    
    text_lower = text.lower()
    
    # ═══ LEGAL ANALYSIS ═══
    
    # 1. Find legal act references
    act_patterns = [
        r'[Uu]staw[aąy]?\s+(?:z\s+dnia\s+)?\d{1,2}\s+\w+\s+\d{4}',
        r'[Kk]odeks\s+(?:cywilny|karny|postępowania|pracy|rodzinny|spółek|morski)',
        r'[Rr]ozporządzeni[eua]\s+[^.]{10,60}\d{4}',
        r'[Dd]yrektyw[aąy]\s+[^.]{5,40}\d{4}',
        r'[Kk]\.?[cp]\.?(?:\s|$)',  # k.c., k.p., kc, kp
        r'[Kk]\.?[kw]\.?(?:\s|$)',  # k.k. (kodeks karny), k.w. (kodeks wykroczeń)
        r'[Kk]\.?(?:s\.?h|r\.?o|p\.?a|p\.?c|p\.?k)\.?(?:\s|$)',  # k.s.h., k.r.o., k.p.a., k.p.c., k.p.k.
        r'[Oo]rdynacja\s+podatkowa',
        r'[Pp]rawo\s+(?:budowlane|zamówień|bankowe|energetyczne|telekomunikacyjne)',
    ]
    acts_found = []
    for pattern in act_patterns:
        matches = re.findall(pattern, text)
        acts_found.extend([m.strip()[:100] for m in matches])
    acts_found = list(dict.fromkeys(acts_found))  # deduplicate preserving order
    
    # 2. Find judgment signatures (Polish court format)
    judgment_patterns = [
        r'(?:sygn\.?\s*(?:akt\s*)?)?[IVX]{1,4}\s+[A-Z]{1,4}\s+\d{1,5}/\d{2,4}',  # I CSK 123/20
        r'[IVX]{1,4}\s+[A-Z]{1,4}\s+\d+/\d+',
        r'(?:wyrok|uchwała|postanowienie)\s+(?:SN|SA|SO|WSA|NSA|TK)\s+z\s+(?:dnia\s+)?\d{1,2}',
        r'(?:SN|SA|SO|WSA|NSA|TK)\s+z\s+\d{1,2}\s+\w+\s+\d{4}',
    ]
    judgments_found = []
    for pattern in judgment_patterns:
        matches = re.findall(pattern, text)
        judgments_found.extend([m.strip()[:80] for m in matches])
    judgments_found = list(dict.fromkeys(judgments_found))
    
    # 3. Find article/paragraph citations
    article_patterns = [
        r'art\.?\s*\d{1,4}(?:\s*§\s*\d{1,3})?(?:\s*(?:ust|pkt|zd)\.?\s*\d{1,3})*',
        r'§\s*\d{1,4}(?:\s*(?:ust|pkt)\.?\s*\d{1,3})*',
        r'artykuł[u]?\s+\d{1,4}',
    ]
    articles_cited = []
    for pattern in article_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        articles_cited.extend([m.strip()[:60] for m in matches])
    articles_cited = list(dict.fromkeys(articles_cited))
    
    # 4. Disclaimer check
    legal_disclaimer_keywords = [
        'konsultacja z prawnikiem', 'porada prawna', 'nie stanowi porady',
        'charakter informacyjny', 'skonsultuj z adwokatem', 'skonsultuj z radcą',
        'nie zastępuje porady', 'konsultacji z prawnikiem',
    ]
    legal_disclaimer = any(kw in text_lower for kw in legal_disclaimer_keywords)
    
    # 5. Cross-reference with context
    acts_from_ctx = 0
    judgments_from_ctx = 0
    if legal_context:
        ctx_judgments = legal_context.get("top_judgments") or []
        for j in ctx_judgments:
            if isinstance(j, dict):
                sig = (j.get("signature") or j.get("caseNumber") or "").lower()
                if sig and any(sig[:10] in jf.lower() for jf in judgments_found):
                    judgments_from_ctx += 1
        ctx_acts = legal_context.get("legal_acts") or []
        for a in ctx_acts:
            name = (a.get("name") if isinstance(a, dict) else str(a)).lower()[:30]
            if name and name in text_lower:
                acts_from_ctx += 1
    
    # Legal score
    legal_score = 0
    if acts_found: legal_score += min(30, len(acts_found) * 10)
    if judgments_found: legal_score += min(30, len(judgments_found) * 15)
    if articles_cited: legal_score += min(20, len(articles_cited) * 5)
    if legal_disclaimer: legal_score += 20
    legal_score = min(100, legal_score)
    
    result["legal"] = {
        "acts_found": acts_found[:15],
        "judgments_found": judgments_found[:10],
        "articles_cited": articles_cited[:20],
        "disclaimer_present": legal_disclaimer,
        "acts_from_context_used": acts_from_ctx,
        "judgments_from_context_used": judgments_from_ctx,
        "score": legal_score,
    }
    
    # ═══ MEDICAL ANALYSIS ═══
    
    # 1. Find PMID references
    pmids = re.findall(r'PMID[:\s]*(\d{6,9})', text)
    pmids = list(dict.fromkeys(pmids))
    
    # 2. Find DOI references
    dois = re.findall(r'(?:doi[:\s]*|https?://doi\.org/)(\d{2}\.\d{4,}/[^\s,)]+)', text, re.IGNORECASE)
    
    # 3. Find study references
    study_patterns = [
        r'badan(?:ie|ia|iu)\s+(?:z\s+)?\d{4}\s+(?:roku?|r\.?)',
        r'(?:meta-analiz|metaanaliz|przegląd\s+systematic|systematic\s+review|randomiz)',
        r'(?:badanie\s+)?(?:RCT|randomizowane|kohortowe|przekrojowe|retrospektywne|prospektywne)',
        r'(?:trial|study|research)\s+(?:by|from|published)',
        r'opublikowane?\s+w\s+\d{4}',
        r'et\s+al\.\s*[\(,]\s*\d{4}',
    ]
    studies_found = []
    for pattern in study_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        studies_found.extend([m.strip()[:80] for m in matches])
    studies_found = list(dict.fromkeys(studies_found))
    
    # 4. Find medical institutions
    institutions_patterns = [
        r'WHO|World Health Organization|Światow\w+ Organizacj\w+ Zdrowia',
        r'NIH|National Institutes? of Health',
        r'EMA|European Medicines Agency|Europejsk\w+ Agencj\w+ Lek',
        r'FDA|Food and Drug Administration',
        r'CDC|Centers? for Disease Control',
        r'NFZ|Narodow\w+ Fundusz\w+ Zdrowia',
        r'PZH|Państwow\w+ Zakład\w+ Higieny|NIZP',
        r'Cochrane',
        r'(?:Polskie|Europejskie|Amerykańskie)\s+Towarzystwo\s+\w+',
        r'(?:wytyczne|rekomendacje|zalecenia)\s+(?:PTL|PTK|PTP|PTG|PTD|PTE)',
    ]
    institutions_found = []
    for pattern in institutions_patterns:
        matches = re.findall(pattern, text)
        institutions_found.extend([m.strip()[:60] for m in matches])
    institutions_found = list(dict.fromkeys(institutions_found))
    
    # 5. Evidence level indicators
    evidence_keywords = {
        "Ia": ["meta-analiz", "metaanaliz", "przegląd systematyczny", "systematic review"],
        "Ib": ["randomizowane", "RCT", "randomized controlled"],
        "IIa": ["kohortowe", "cohort study", "prospektywne"],
        "IIb": ["case-control", "przekrojowe", "retrospektywne"],
        "III": ["seria przypadków", "case series", "opis przypadku"],
        "IV": ["opinia eksperta", "expert opinion", "konsensus"],
    }
    evidence_found = {}
    for level, keywords in evidence_keywords.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                evidence_found[level] = evidence_found.get(level, 0) + 1
    
    # 6. Medical disclaimer
    medical_disclaimer_keywords = [
        'konsultacja z lekarzem', 'skonsultuj z lekarzem', 'porada medyczna',
        'nie stanowi diagnozy', 'charakter informacyjny', 'nie zastępuje wizyty',
        'skonsultuj ze specjalistą', 'porady lekarskiej',
    ]
    medical_disclaimer = any(kw in text_lower for kw in medical_disclaimer_keywords)
    
    # 7. Cross-reference with context
    pubs_from_ctx = 0
    if medical_context:
        ctx_pubs = medical_context.get("top_publications") or []
        for p in ctx_pubs:
            if isinstance(p, dict):
                pmid = str(p.get("pmid", ""))
                title_frag = (p.get("title", ""))[:25].lower()
                if (pmid and pmid in pmids) or (title_frag and title_frag in text_lower):
                    pubs_from_ctx += 1
    
    # Medical score
    med_score = 0
    if pmids: med_score += min(25, len(pmids) * 10)
    if studies_found: med_score += min(20, len(studies_found) * 7)
    if institutions_found: med_score += min(20, len(institutions_found) * 7)
    if evidence_found: med_score += min(15, len(evidence_found) * 5)
    if medical_disclaimer: med_score += 20
    med_score = min(100, med_score)
    
    result["medical"] = {
        "pmids_found": pmids[:15],
        "dois_found": dois[:10],
        "studies_referenced": studies_found[:15],
        "institutions_found": institutions_found[:10],
        "disclaimer_present": medical_disclaimer,
        "pubs_from_context_used": pubs_from_ctx,
        "evidence_indicators": evidence_found,
        "score": med_score,
    }
    
    return result


def is_salience_available():
    """Check if Google NLP API key is configured."""
    return bool(GOOGLE_NLP_API_KEY)
