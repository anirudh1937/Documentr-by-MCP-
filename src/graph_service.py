"""
Graph Service to build node-link topology from document references.
Parses Obsidian-style wiki links [[Target Note]] and standard links.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set
from .storage import store

async def build_graph() -> Dict[str, List[Dict[str, Any]]]:
    """
    Scans all documents, parses wiki-links and returns a list of nodes and links.
    Detects ghost nodes (links to notes that don't exist yet).
    """
    # 1. Fetch all documents
    docs_meta = await store.list_all()
    
    docs = []
    for meta in docs_meta:
        doc = await store.get(meta.id)
        if doc:
            docs.append(doc)
            
    # 2. Build lookup maps
    title_to_id: Dict[str, str] = {}
    id_to_doc: Dict[str, Dict[str, Any]] = {}
    
    for doc in docs:
        title_to_id[doc.title.lower().strip()] = doc.id
        id_to_doc[doc.id] = {
            "id": doc.id,
            "title": doc.title,
            "pinned": doc.pinned,
            "is_draft": doc.is_draft,
            "exists": True
        }
        
    nodes_map: Dict[str, Dict[str, Any]] = {doc.id: id_to_doc[doc.id] for doc in docs}
    links: List[Dict[str, str]] = []
    
    # 3. Regex for Obsidian-style wiki links: [[Target Note]] or [[Target Note|Display Name]]
    wiki_pattern = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]")
    
    # Also look for raw links like ?doc=doc_id
    url_pattern = re.compile(r"\?doc=([a-zA-Z0-9_-]+)")
    
    for doc in docs:
        if not doc.content:
            continue
            
        seen_targets: Set[str] = set()
        
        # 3.1. Parse wiki-links
        wiki_matches = wiki_pattern.findall(doc.content)
        for match in wiki_matches:
            target_str = match.strip()
            if not target_str or target_str in seen_targets:
                continue
            seen_targets.add(target_str)
            
            target_id = None
            
            # Match by ID directly
            if target_str in id_to_doc:
                target_id = target_str
            # Match by Title case-insensitively
            elif target_str.lower() in title_to_id:
                target_id = title_to_id[target_str.lower()]
            else:
                # Ghost note (non-existent note link)
                ghost_id = f"ghost:{target_str.lower()}"
                target_id = ghost_id
                if ghost_id not in nodes_map:
                    nodes_map[ghost_id] = {
                        "id": ghost_id,
                        "title": target_str,
                        "pinned": False,
                        "is_draft": False,
                        "exists": False
                    }
                    
            # Avoid self links
            if target_id != doc.id:
                links.append({
                    "source": doc.id,
                    "target": target_id
                })
                
        # 3.2. Parse standard HTML/Markdown links pointing to ?doc=doc_id
        url_matches = url_pattern.findall(doc.content)
        for match in url_matches:
            target_id = match.strip()
            # If target exists and not already linked
            if target_id in id_to_doc and target_id != doc.id and target_id not in seen_targets:
                seen_targets.add(target_id)
                links.append({
                    "source": doc.id,
                    "target": target_id
                })
                
    return {
        "nodes": list(nodes_map.values()),
        "links": links
    }
