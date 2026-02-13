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

    # Add secondary entities if available
    if entities_from_s1:
        must_mention = []
        for ent in entities_from_s1[:8]:
            if isinstance(ent, dict):
                name = ent.get("text", ent.get("entity", ent.get("name", "")))
                if name:
                    must_mention.append(name)
            elif isinstance(ent, str):
                must_mention.append(ent)

        if must_mention:
            ent_list = ", ".join(f'"{e}"' for e in must_mention[:6])
            instructions.append(
                f"\nENCJE WTÓRNE (współwystępujące u konkurencji): {ent_list}\n"
                "Wpleć je naturalnie — ale ZAWSZE jako elementy podrzędne wobec encji głównej."
            )

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


def is_salience_available():
    """Check if Google NLP API key is configured."""
    return bool(GOOGLE_NLP_API_KEY)
