# Data Flow

Two flows drive the system: **configuration** (user → `config.json`) and
**generation/delivery** (cron → board). They meet only at the shared files.

## 1. Configuration flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit UI
    participant CFG as config module
    participant FILE as config.json
    participant DMN as Scheduler daemon

    User->>UI: log in (bcrypt verify)
    User->>UI: edit creds / device / prompts+cron
    UI->>CFG: save_config(AppConfig)
    CFG->>FILE: atomic write (temp + os.replace, 0o600)
    Note over DMN,FILE: daemon polls every 5s
    DMN->>FILE: read_bytes + SHA-256
    alt hash changed
        DMN->>CFG: load_config
        DMN->>DMN: remove_all_jobs + re-add enabled prompts
    else unchanged
        DMN->>DMN: no-op
    end
```

Config change is detected by hashing **file contents**, not mtime — a same-second
edit can't be missed. No restart needed.

## 2. Generation & delivery flow (`pipeline.run_once`)

Triggered by a cron job in the daemon, or by the UI's "test-send" button.

```mermaid
flowchart TD
    START([cron fire / test-send]) --> LOADP[load config + prompt]
    LOADP --> DEV[resolve DeviceSpec<br/>vestaboard 6×22 / note 3×15]
    DEV --> GEN["llm.generate<br/>device-aware system prompt"]

    GEN -->|LLMError| HASTEXT{any text<br/>from earlier<br/>attempt?}
    GEN -->|text| COMPILE["vbml.compile<br/>→ charset codes, 6×22 grid"]

    COMPILE --> VALID{valid?<br/>content + glyph limits}
    VALID -->|yes| DELIVER
    VALID -->|no, attempts < 3| GEN2[retry: generate shorter]
    GEN2 --> COMPILE
    VALID -->|no, attempts = 3| TRUNC[vbml.truncate_to_fit]

    HASTEXT -->|no| FAILNOTEXT([fail: no message])
    HASTEXT -->|yes| TRUNC

    TRUNC --> COMPILE2[vbml.compile]
    COMPILE2 --> VALID2{valid?}
    VALID2 -->|no| FAILINVALID([fail: cannot produce valid])
    VALID2 -->|yes| DELIVER

    DELIVER["delivery.make_delivery<br/>CloudRW / LocalAPI<br/>.send(grid)"]
    DELIVER -->|DeliveryError / NotImplemented| FAILDEL([fail: delivery error])
    DELIVER -->|2xx| OK([PipelineResult delivered=true])

    OK --> RECORD[daemon: history.append]
    RECORD --> HFILE[(history.json)]

    classDef fail fill:#fdd,stroke:#c44;
    classDef ok fill:#dfd,stroke:#4a4;
    class FAILNOTEXT,FAILINVALID,FAILINVALID,FAILDEL fail;
    class OK ok;
```

### Key behaviors

- **Up to 3 attempts.** Each invalid compile re-prompts the LLM with a
  "make it shorter" suffix before falling back to hard truncation.
- **LLM error short-circuits retries** but does *not* discard usable text from an
  earlier attempt — it falls through to the truncate fallback.
- **Two failure exits** are distinct: `no message` (LLM gave nothing) vs
  `cannot produce valid` (even truncated text won't fit the charset/limits).
- **`run_once` never raises** — returns `PipelineResult`. The daemon inspects
  `.delivered`; APScheduler would otherwise report success on a silent failure.
- **History is best-effort** — written only on success, and a write failure is
  logged but never breaks the already-delivered run.

## 3. History read flow

```mermaid
flowchart LR
    HFILE[(history.json)] --> HIST[history.read]
    HIST --> PHIS[ui pages_history]
    PHIS --> RENDER[render text + grid + timestamp + device]
```

## Secret handling across flows

Every credential (`cloud_key`, `local_key`, `llm.api_key`) is registered with
`logging_setup` on config load and on delivery/LLM client construction, so keys
are redacted from all log output and never appear in tracebacks. The password is
stored only as a bcrypt hash.
