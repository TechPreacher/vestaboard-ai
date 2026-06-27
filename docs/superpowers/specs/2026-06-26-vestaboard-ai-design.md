# Vestaboard AI — Design

**Date:** 2026-06-26
**Status:** Approved (design); implementation plan pending.

## Summary

A Python backend + Streamlit UI that generates short messages with an OpenAI-compatible LLM and
pushes them to a Vestaboard Note (3 lines of 15 characters each, 45 characters of total content)
on a cron schedule. Runs as two systemd services on a single host behind a TLS-terminating reverse
proxy.

## Process model

Two independent systemd services sharing one config file. No shared memory, no IPC — they
communicate only through `config.json`.

```
config.json (0600, service user)  <-- single source of truth
   ^  write (atomic: tmp + os.replace)        ^ read (poll mtime every 5s)
   |                                          |
vboard-ui.service                     vboard-scheduler.service
 streamlit run app.py                  python -m vboard.daemon
 (auth + edit config)                  (APScheduler -> generate -> deliver)
```

- **UI** edits config only. It never delivers to the board (except an explicit manual "test send"
  button, which runs the same pipeline on demand).
- **Daemon** owns scheduling and delivery. It never serves web traffic.
- Decoupling lets each service restart independently and keeps the scheduler alive across UI
  reloads.

## Modules

Each module has one purpose, a well-defined interface, and is testable in isolation.

### `config`
- Pydantic model for the whole config; load/save with schema validation.
- **Atomic write:** serialize to a temp file in the same directory, then `os.replace()` onto
  `config.json`. Guarantees the daemon never reads a half-written file.
- Enforces file mode `0600` on write.
- Contents:
  - Vestaboard: cloud Read/Write key **or** local API endpoint + key (backend selector).
  - LLM: base URL, model name, API key.
  - Auth: bcrypt password hash.
  - `prompts[]`: each entry = `{ id, text, cron, color_hints_enabled, enabled }`.

### `llm`
- OpenAI-compatible client over `httpx` (configurable base URL, model, key).
- Owns the prompt scaffolding that pushes the model toward short, glyph-safe plain text plus
  optional inline color hints (e.g. `{red}`).
- Provider-agnostic — anything speaking the OpenAI chat-completions API works.

### `vbml`
- Hybrid compiler + validator. Input: plain text + optional color hints. Output: VBML and the
  resulting character-code grid.
- Maps text → Vestaboard character codes; strips or substitutes unsupported glyphs.
- Enforces the **45-character content limit** and the restricted charset.
- **This is the last gate before delivery.** Pure functions, no I/O — the most heavily unit-tested
  module.

### `delivery`
- `VBoard` interface: `send(codes)`.
- `CloudRW` implementation first (Cloud Read/Write API).
- `Local` implementation second (local endpoint + key). Interface ships in v1, impl follows.
- Concrete impl chosen at runtime from config.

### `pipeline`
- Orchestrates a single fire: generate → compile to VBML → validate → regenerate (≤3) → truncate →
  deliver → log result.
- Shared by the daemon (scheduled) and the UI (manual test send).

### `daemon`
- APScheduler with one cron job per enabled prompt.
- Polls `config.json` mtime every 5 s; on change, reloads config and rebuilds the job set.

### `ui`
- Streamlit app. `streamlit-authenticator` gates every page (login form + session cookie + bcrypt).
- Pages: credentials (Vestaboard + LLM), prompts & schedules (CRUD + cron), preview / test-send.

### `auth`
- bcrypt via `streamlit-authenticator`. Password set/change writes the hash to config.
- Auth gate runs before any config access in the UI.

## Data flow (one scheduled fire)

```
cron trigger
  -> llm.generate(prompt)               # plain text + color hints
  -> vbml.compile(text, hints)          # -> VBML -> char codes
  -> fits 45 chars + charset?
       no  -> regenerate (re-prompt "shorter"), up to 3 attempts
       still no -> truncate at word boundary
  -> delivery.send(codes)
  -> log result (status only; never credentials)
```

## Constraint enforcement

- Length and charset are validated **after** VBML expansion, not on the raw LLM text — VBML markup
  and code mapping can change effective length.
- Recovery: regenerate ×3 with a "make it shorter" re-prompt, then word-boundary truncate as the
  last resort. The pipeline always delivers something valid.

## Security

- `config.json` is mode `0600`, owned by the service user, located outside any web-served directory.
- API keys are stored plaintext but **never logged** at any level — a redaction filter is attached
  to the logger so keys can't leak through tracebacks or error surfaces.
- Password is bcrypt-hashed, never stored plaintext.
- The app speaks plain HTTP on localhost. **TLS is terminated by a reverse proxy (nginx or caddy)
  in front of both services.** The app does not handle certificates.
- Every UI config surface is behind the auth gate.

## Testing

- `vbml` and `pipeline` (with mocked `llm` / `delivery`): pure unit tests — the core of the suite.
- `config`: atomic write + reload round-trip; perms check.
- `delivery`: against a mocked HTTP layer.
- Tooling: `uv` + Python 3.12. "Done" = `uv run pytest` and `ruff` both pass.

## v1 scope

**In:** full config UI, cloud delivery, hybrid VBML, cron scheduling, auth, manual test-send.

**Out (deferred, interfaces left ready):** local delivery implementation, multi-user, key
encryption at rest, message history / analytics.

## Decisions log

| Decision | Choice |
|---|---|
| Process model | Two systemd services sharing `config.json` |
| Tooling / runtime | `uv` + Python 3.12 |
| VBML strategy | Hybrid: LLM emits text + color hints → formatter compiles |
| Over-length / bad glyph | Regenerate ×3, then word-boundary truncate |
| Auth | `streamlit-authenticator` (bcrypt) |
| Config reload | Poll mtime (5 s) + atomic write |
| Delivery first | Cloud Read/Write; Local second |
| Secrets at rest | Plaintext + `0600` perms; never logged |
| TLS | Reverse proxy (nginx/caddy) in front |
