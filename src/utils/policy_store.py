"""
Policy store for organization policy retrieval.

Current: Simple file-loader — reads all .md files from the policies/ directory
         and returns them as text chunks. No embedding required; works out of the box.

Future: See policies/IMPLEMENTATION.md for the Option B plan using Bedrock Titan
        Embeddings + numpy cosine similarity for semantic retrieval at scale.
"""
from pathlib import Path
from typing import List

_POLICIES_DIR = Path(__file__).parent.parent.parent / 'policies'

_EXCLUDED = {'IMPLEMENTATION.md'}


def query(query_text: str, top_k: int = 5) -> List[str]:
    """
    Return relevant policy chunks for the given query text.

    Currently returns all policy documents as chunks (suitable for small policy sets).
    See policies/IMPLEMENTATION.md to upgrade to vector-based retrieval.
    """
    policy_files = [
        f for f in _POLICIES_DIR.glob('*.md')
        if f.name not in _EXCLUDED
    ]

    chunks = []
    for policy_file in policy_files:
        try:
            content = policy_file.read_text(encoding='utf-8').strip()
            if content:
                chunks.append(f"[Policy: {policy_file.stem}]\n{content}")
        except Exception:
            pass

    return chunks
