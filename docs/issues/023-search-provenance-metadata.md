# Implement search result provenance metadata

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Replace the raw string list returned by `SearchProvider.search()` with structured results carrying provenance metadata.

**`SearchResult`** model:
```python
@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    source: str              # "duckduckgo", "bing", "bingchina"
    fetched_at: float        # Unix timestamp
    content_hash: str        # SHA256 of snippet
    trust_level: str         # "verified" | "standard" | "unverified"
    freshness: str | None    # "2026-05-14" if parseable, else None
    extraction_method: str   # "html_scrape" | "api_json" | "regex_parse"
```

**`SearchProvider.search()` updated**: returns `list[SearchResult]` instead of `list[str]`. Each provider populates all fields.

**Citation builder**: `format_search_results(results: list[SearchResult]) -> str` formats results for the model with citation markers `[1]`, `[2]`, etc., and a "Sources" footer listing URLs. This replaces the current ad-hoc formatting in each provider.

**Provenance in `UntrustedContent`**: search results are wrapped via Issue #7's `UntrustedContent` with `source="web_search"`, `trusted=False`, `mime="text/plain"`, and provenance dict containing the full `SearchResult` data.

**Backward compatibility**: old providers returning `list[str]` are still accepted by `get_search_provider()` but emit a deprecation warning.

## Acceptance criteria

- [ ] `SearchResult` dataclass defined with all fields
- [ ] `DuckDuckGoProvider.search()` returns `list[SearchResult]`
- [ ] `BingWebSearchProvider.search()` returns `list[SearchResult]`
- [ ] `BingChinaSearchProvider.search()` returns `list[SearchResult]`
- [ ] Each result has URL, timestamp, content_hash, trust_level
- [ ] `format_search_results()` produces numbered citations with sources footer
- [ ] Search results wrapped as `UntrustedContent` before entering model context
- [ ] Old `list[str]` providers work with deprecation warning
- [ ] Unit test: DuckDuckGo result has all fields populated
- [ ] Unit test: `format_search_results([r1, r2])` includes `[1]`, `[2]` markers and URLs

## Blocked by

- Issue #7 (UntrustedContent wrapper — search results use it)

## Depends on for P2

- Issue #28 (Trusted Search Pipeline — builds on provenance metadata)
