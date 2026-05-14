# Build Trusted Search Pipeline: fetch → clean → chunk → rank → cite → verify

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Replace the current regex-scraping search with a multi-stage pipeline that produces verifiable, citable search results.

**Pipeline stages:**

1. **Search** — existing `SearchProvider` interface, now returning `SearchResult` (from issue #23)

2. **Fetch** — `ContentFetcher` downloads full page content for each result:
   - Respects `robots.txt` (cache parsed rules for 1 hour)
   - Honors `X-Robots-Tag` in HTTP headers
   - Uses `validate_url()` for SSRF protection
   - Timeout: 10s per fetch, max 3 concurrent fetches
   - Max content size: 500KB per page

3. **Clean** — `HTMLCleaner` extracts readable text:
   - Removes scripts, styles, nav, footer, ads
   - Uses readability algorithm (simple heuristic: `<p>` density)
   - Preserves heading structure (h1-h3)
   - Output: plain text with structural markers

4. **Chunk** — `TextChunker` splits cleaned text:
   - Target chunk size: 500-1000 characters
   - Splits on paragraph/sentence boundaries
   - Overlapping windows (100 char overlap) to preserve context
   - Each chunk tagged with source URL and position

5. **Rank** — `ChunkRanker` scores chunks by relevance:
   - TF-IDF or simple BM25 against the original query
   - Title match bonus
   - Freshness bonus (newer content ranked higher)
   - De-duplication: near-duplicate chunks (cosine similarity > 0.9) merged

6. **Cite** — `CitationBuilder` produces the final formatted output:
   - Each chunk gets a citation marker `[N]`
   - Sources section at bottom: `[N] Title — URL (fetched YYYY-MM-DD)`
   - Quote spans: when a specific sentence is used, link back to source URL + position

7. **Verify** — `ClaimVerifier` (optional, configurable):
   - Cross-references claims against multiple sources
   - Flags contradictory information
   - Assigns confidence: "verified" (2+ sources agree), "single_source", "unverified"

**`TrustedSearchPipeline`** orchestration:
```python
pipeline = TrustedSearchPipeline(
    provider=get_search_provider("auto"),
    max_results=5,
    max_chunks_per_result=3,
    verify_claims=True,
)
results = pipeline.search("What is DeepSeek's prompt cache pricing?")
# → TrustedSearchOutput(
#     formatted_text="... [1] ... [2] ...",
#     citations=[Citation(...), Citation(...)],
#     verification_notes="2/3 sources confirm ¥0.014/M cached input tokens",
# )
```

## Acceptance criteria

- [ ] Full pipeline: search → fetch → clean → chunk → rank → cite → formatted output
- [ ] `ContentFetcher` respects robots.txt (cached)
- [ ] `ContentFetcher` blocks via `validate_url()` (SSRF protection)
- [ ] `HTMLCleaner` extracts readable text, removes scripts/styles/nav
- [ ] `TextChunker` produces overlapping chunks with source metadata
- [ ] `ChunkRanker` ranks by relevance, de-duplicates near-duplicates
- [ ] `CitationBuilder` produces `[N]` markers with sources footer
- [ ] `ClaimVerifier` flags single-source vs multi-source claims
- [ ] Each pipeline stage is independently testable with known inputs
- [ ] Pipeline degrades gracefully: fetch failure → use snippet only
- [ ] Unit test: full search "DeepSeek API pricing" returns cited, ranked results
- [ ] Unit test: robots.txt disallows → fetch skipped, snippet used
- [ ] Unit test: two near-identical pages → de-duplicated in ranking
- [ ] Unit test: contradictory claims → verification notes flag it

## Blocked by

- Issue #23 (SearchResult with provenance)
- Issue #6 (validate_url for SSRF protection in fetcher)
- Issue #7 (UntrustedContent wrapper for final output)
