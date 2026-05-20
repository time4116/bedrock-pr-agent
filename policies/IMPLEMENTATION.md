# Policy Store — Implementation Plan (Option B)

## Current state

`src/utils/policy_store.py` uses a simple file-loader: it reads all `.md` files in this
directory and passes them verbatim to Claude. This works fine for small policy sets and
requires no additional setup beyond dropping files into this folder.

## Option B: Bedrock Titan Embeddings + numpy cosine similarity

Replace the file-loader with a proper vector retrieval layer so that only the most
relevant policy chunks are surfaced per query — important once the policy set grows
beyond what fits comfortably in the context window.

### Architecture

```
policies/*.md
    └─ chunk() → List[str]          # split on headers / paragraph breaks
         └─ embed() → np.ndarray    # Bedrock Titan Text Embeddings V2
              └─ stored in memory   # simple numpy array, no external service

query_text
    └─ embed() → np.ndarray
         └─ cosine_similarity(query_vec, stored_vecs)
              └─ top_k chunks returned
```

### Implementation steps

1. **Chunking** (`_chunk_policy_file`)
   - Split each `.md` file on `##` headings (one chunk per section)
   - Prepend filename + heading as context: `[Policy: security.md > Network rules]\n...`
   - Target chunk size ~300–500 tokens

2. **Embedding** (`_embed`)
   - Use `boto3.client('bedrock-runtime').invoke_model` with model
     `amazon.titan-embed-text-v2:0`
   - Input: `{"inputText": chunk_text}`
   - Output: `response["embedding"]` (1024-dim float list)
   - Wrap in `np.array(..., dtype=np.float32)`

3. **Cold-start indexing** (`_build_index`)
   - Called once at Lambda cold start (or first query)
   - Embed all chunks, store as `(embeddings: np.ndarray, chunks: List[str])`
   - Cache in module-level variable so subsequent queries within the same
     container reuse the index without re-embedding

4. **Query** (`query`)
   - Embed the query string
   - Compute cosine similarity: `(index @ q_vec) / (norms * q_norm)`
   - Return `chunks[top_k_indices]`

### Key decisions

| Decision | Rationale |
|---|---|
| Bedrock Titan Embeddings (not OpenAI) | No new credentials — project already uses Bedrock |
| In-memory numpy (not ChromaDB/FAISS) | Lambda-friendly, zero cold-start disk overhead |
| Full file re-embedding on cold start | Policy set is small; simpler than persisting to S3 |
| `top_k=5` default | Balances coverage vs. context window cost |

### Files to modify

- `src/utils/policy_store.py` — replace `query()` body with the above
- `requirements.txt` — add `numpy>=1.26.0` (already likely available in Lambda runtime)
- No changes needed to `org_policy_checker.py` — it already calls `policy_store.query()`

### Environment variables

No new env vars needed. Bedrock client uses the Lambda execution role's IAM permissions.
The execution role needs `bedrock:InvokeModel` on `amazon.titan-embed-text-v2:0`.
