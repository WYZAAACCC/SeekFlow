# Implement file attachment size/page/token limits + PDF bomb protection

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

Harden `seekflow.files` with comprehensive limits on file processing to prevent resource exhaustion, excessive token consumption, and PDF-based attacks.

1. **Per-file size limit**: `read_file_as_text()` and `embed_files_into_message()` accept `max_file_bytes: int = 5_000_000` (5MB). Files exceeding this return an error string instead of being embedded.

2. **Total size limit**: `embed_files_into_message()` accepts `max_total_bytes: int = 20_000_000` (20MB). Cumulative size across all files in a call is checked before embedding.

3. **Token limit**: after reading file content, estimate token count (via tiktoken or char/4 fallback). Files contributing more than `max_file_tokens: int = 100_000` may be truncated with a note, or rejected based on a `truncate_large_files: bool` flag.

4. **PDF page limit**: `_read_pdf()` accepts `max_pages: int = 50`. Pages beyond this are not extracted. A note like `[... truncated after 50 pages]` is appended.

5. **PDF zip bomb protection**: check the raw file size BEFORE opening with PyPDF2. If PDF is unusually large relative to its page count (suspicious compression ratio), reject it. Check for excessive indirect objects in the PDF structure.

6. **Binary/image encoding control**: `_encode_image()` and `_encode_binary()` accept `max_image_bytes: int = 2_000_000` (2MB for images, as base64 inflates size). Images above this return `[Image too large: {name} ({size} bytes)]`. Add a `allow_binary_base64: bool = False` flag — when False, binary files are described but not base64-encoded.

7. **Deep-copy confirmation**: verify issue #13's deep-copy fix in `embed_files_into_message()` is working correctly with the new limits.

## Acceptance criteria

- [ ] File > 5MB → rejected with descriptive error in tool output
- [ ] Multiple files > 20MB total → rejected
- [ ] PDF > 50 pages → truncated with note
- [ ] Zip bomb PDF (small file, massive decompressed content) → rejected
- [ ] Image > 2MB → described but not base64-encoded (when allow_binary_base64=False)
- [ ] `allow_binary_base64=True` → images encoded as before
- [ ] Token limit enforced when tiktoken available
- [ ] All limit errors include the file name and which limit was exceeded
- [ ] `embed_files_into_message()` returns new dict (does not mutate input)
- [ ] Regression test: 100MB file → rejected
- [ ] Regression test: PDF with 500 pages → only first 50 extracted
- [ ] Regression test: zip bomb PDF → rejected before extraction

## Blocked by

- Issue #5 (safe_join — ensures files are within workspace before limits are checked)

## Depends on for full integration

- Issue #13 (deep copy — verified here)
