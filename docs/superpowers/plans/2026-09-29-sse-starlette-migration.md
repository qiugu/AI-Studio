# SSE Starlette Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Agent and workflow SSE responses on `sse-starlette` while preserving the existing event contract and making the frontend parser compliant with all SSE line endings.

**Architecture:** Add one small backend SSE utility that owns JSON event serialization and production response settings, then route both streaming endpoints through it. Extract the duplicated frontend framing logic into a stateful parser that accepts CRLF, LF, and CR boundaries and ignores heartbeat comments.

**Tech Stack:** FastAPI, sse-starlette 3.4.6, pytest, React/TypeScript, Vitest.

## Global Constraints

- Preserve Agent event names and payloads: `message`, `citations`, `done`, and `error`.
- Preserve workflow event names and JSON payloads.
- Serialize JSON with Unicode characters intact.
- Use a 15-second SSE heartbeat and a 30-second send timeout.
- Do not change citation marker assignment, snapshots, or persistence semantics.
- Do not add a new dependency.

---

### Task 1: Standards-compliant frontend SSE framing

**Files:**
- Create: `frontend/src/utils/sseParser.ts`
- Create: `frontend/src/utils/sseParser.test.ts`
- Modify: `frontend/src/utils/streamRequest.ts`

**Interfaces:**
- Produces: `SSEParser.feed(chunk: string): SSEEvent[]` where `SSEEvent` contains `event` and joined `data` fields.
- Consumes: decoded UTF-8 chunks from both existing fetch streaming functions.

- [x] **Step 1: Write failing parser tests**

```typescript
import { describe, expect, it } from 'vitest'
import { SSEParser } from './sseParser'

describe('SSEParser', () => {
  it('parses CRLF frames split across chunks', () => {
    const parser = new SSEParser()
    expect(parser.feed('event: message\r\ndata: {"content":"中"}\r')).toEqual([])
    expect(parser.feed('\n\r\n')).toEqual([
      { event: 'message', data: '{"content":"中"}' },
    ])
  })

  it('supports LF and CR framing and ignores heartbeat comments', () => {
    const parser = new SSEParser()
    expect(parser.feed(': ping\n\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'done', data: '{}' },
    ])
    expect(parser.feed('event: error\rdata: {"error":"x"}\r\r')).toEqual([
      { event: 'error', data: '{"error":"x"}' },
    ])
  })

  it('joins multiple data fields with LF', () => {
    const parser = new SSEParser()
    expect(parser.feed('event: message\ndata: first\ndata: second\n\n')).toEqual([
      { event: 'message', data: 'first\nsecond' },
    ])
  })
})
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && npm test -- src/utils/sseParser.test.ts`

Expected: FAIL because `./sseParser` does not exist.

- [x] **Step 3: Implement `SSEParser` and replace both duplicated `split('\n\n')` loops**

Implement a buffered parser that detects two consecutive SSE line endings using `(?:\r\n|\r|\n)(?:\r\n|\r|\n)`, ignores comment-only frames, and joins repeated `data` fields with `\n`. Both request functions instantiate one parser and consume `parser.feed(decoder.decode(...))`.

- [x] **Step 4: Run focused and full frontend verification**

Run: `cd frontend && npm test -- src/utils/sseParser.test.ts`

Expected: PASS.

Run: `cd frontend && npm test && npm run build`

Expected: all tests and the production build pass.

### Task 2: Shared backend SSE transport

**Files:**
- Create: `backend/app/utils/sse.py`
- Create: `backend/tests/test_sse_transport.py`
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/api/workflow.py`

**Interfaces:**
- Produces: `json_sse_event(event: str, data: Any) -> JSONServerSentEvent`.
- Produces: `create_sse_response(content: AsyncIterable[Any]) -> EventSourceResponse` configured with `ping=15` and `send_timeout=30`.

- [x] **Step 1: Write failing backend transport tests**

```python
from app.utils.sse import create_sse_response, json_sse_event


def test_json_sse_event_encodes_unicode_and_multiline_content():
    encoded = json_sse_event("message", {"content": "中文\n第二行"}).encode()
    assert b"event: message" in encoded
    assert "中文".encode() in encoded
    assert b'\\n' in encoded


def test_create_sse_response_uses_production_defaults():
    async def events():
        yield json_sse_event("done", {})

    response = create_sse_response(events())
    assert response.ping_interval == 15
    assert response.send_timeout == 30
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `cd backend && pytest tests/test_sse_transport.py -q`

Expected: FAIL because `app.utils.sse` does not exist.

- [x] **Step 3: Implement the shared helper and migrate both routes**

Use `JSONServerSentEvent` for every event and `EventSourceResponse` for both endpoints. Preserve all existing event names, payload fields, persistence timing, and error mapping.

- [x] **Step 4: Run focused backend verification**

Run: `cd backend && pytest tests/test_sse_transport.py tests/test_agent_stream_citations.py -q`

Expected: PASS.

### Task 3: Remove legacy formatter and align documentation

**Files:**
- Delete: `backend/app/schemas/stream.py`
- Modify: `backend/app/utils/llm.py`
- Modify: `CLAUDE.md`
- Modify: `docs/sse-best-practices.md`

**Interfaces:**
- Removes: `StreamChunk` and `encode`, after confirming no production imports remain.
- Documents: `EventSourceResponse`, JSON event serialization, heartbeat, timeout, and line-ending-compatible client parsing.

- [x] **Step 1: Confirm legacy formatter has no remaining consumers**

Run: `rg -n 'StreamChunk|from app\.utils\.llm import encode|encode\(StreamChunk' backend --glob '*.py'`

Expected: only the legacy definitions remain.

- [x] **Step 2: Delete the legacy formatter and update documentation**

Remove the unused dataclass and formatter. Replace the old `StreamingResponse` example and LF-only parsing guidance with the shared `sse-starlette` transport and standards-compliant parser behavior.

- [x] **Step 3: Run complete relevant verification**

Run: `cd backend && pytest tests/test_sse_transport.py tests/test_agent_stream_citations.py -q`

Run: `cd frontend && npm test && npm run build && npm run lint`

Expected: all commands pass without warnings introduced by the migration.

- [x] **Step 4: Review the final diff**

Run: `git diff --check && git status --short && git diff --stat`

Expected: no whitespace errors; only SSE migration, tests, and documentation files are changed.
