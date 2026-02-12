#!/usr/bin/env python3
"""
Patch app.py to add keyword deduplication.
Run: python patch_app.py app.py

Two changes:
1. Add import of keyword_dedup after ai_middleware imports
2. Add dedup call after keywords building, before project_payload
"""
import sys

def patch(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # ── PATCH 1: Add import ──
    import_marker = "from ai_middleware import ("
    import_end = ")"
    
    # Find the end of the ai_middleware import block
    idx = content.find(import_marker)
    if idx == -1:
        print("ERROR: Could not find 'from ai_middleware import' block")
        sys.exit(1)
    
    # Find the closing paren
    close_idx = content.find(")", idx + len(import_marker))
    if close_idx == -1:
        print("ERROR: Could not find closing paren of ai_middleware import")
        sys.exit(1)
    
    # Insert after the closing paren + newline
    insert_pos = content.find("\n", close_idx) + 1
    import_line = "\nfrom keyword_dedup import deduplicate_keywords\n"
    
    if "from keyword_dedup import" not in content:
        content = content[:insert_pos] + import_line + content[insert_pos:]
        print("✅ PATCH 1: Added keyword_dedup import")
    else:
        print("ℹ️ PATCH 1: keyword_dedup import already present")
    
    # ── PATCH 2: Add dedup call ──
    # Find the keywords log line (right after building keywords list)
    kw_log_marker = 'yield emit("log", {"msg": f"Keywords: {len(keywords)}'
    idx2 = content.find(kw_log_marker)
    if idx2 == -1:
        # Try alternative marker
        kw_log_marker = "Keywords: {len(keywords)}"
        idx2 = content.find(kw_log_marker)
    
    if idx2 == -1:
        print("ERROR: Could not find keywords log line")
        sys.exit(1)
    
    # Find end of that line
    line_end = content.find("\n", idx2) + 1
    
    dedup_code = '''
        # ═══ KEYWORD DEDUP — word-boundary safe target adjustment ═══
        keywords = deduplicate_keywords(keywords, main_keyword)
        yield emit("log", {"msg": f"🔧 Keyword dedup: targets adjusted for overlapping phrases"})

'''
    
    if "deduplicate_keywords" not in content[line_end:line_end+200]:
        content = content[:line_end] + dedup_code + content[line_end:]
        print("✅ PATCH 2: Added keyword dedup call")
    else:
        print("ℹ️ PATCH 2: keyword dedup call already present")
    
    # Write patched file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✅ Patched: {filepath}")
    print("  Changes:")
    print("  1. from keyword_dedup import deduplicate_keywords")
    print("  2. keywords = deduplicate_keywords(keywords, main_keyword)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path_to_app.py>")
        sys.exit(1)
    patch(sys.argv[1])
