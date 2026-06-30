# Architecture

Vestaboard AI runs as **two independent processes** that share state through two
files on a common volume — a `config.json` (managed by the UI) and a
`history.json` (appended by the scheduler). There is no message bus or database:
the shared files *are* the integration point.

- **Streamlit UI** — authenticated configuration surface. Writes `config.json`,
  reads `history.json`, can preview/test-send on demand.
- **Scheduler daemon** — headless. Reads `config.json`, fires generation →
  delivery on cron schedules, appends to `history.json`.

The daemon detects config changes by hashing the file contents (SHA-256), so a
UI save is picked up on the next poll without a restart.

## Component diagram

```mermaid
graph TB
    subgraph external["External services"]
        LLMAPI["OpenAI-compatible<br/>LLM endpoint"]
        VBAPI["Vestaboard API<br/>(Cloud RW / Local)"]
        BOARD["Vestaboard device<br/>(6×22 board or 3×15 Note)"]
    end

    subgraph ui_proc["UI process (Streamlit)"]
        APP["app.py<br/>auth gate + router"]
        PCFG["pages_config<br/>credentials, prompts"]
        PPRE["pages_preview<br/>preview / test-send"]
        PHIS["pages_history<br/>delivered log"]
        APP --> PCFG
        APP --> PPRE
        APP --> PHIS
    end

    subgraph daemon_proc["Scheduler process (daemon)"]
        DMN["daemon.Daemon<br/>APScheduler + poll-reload"]
    end

    subgraph core["Shared core modules (vboard)"]
        PIPE["pipeline.run_once<br/>generate→compile→deliver"]
        LLM["llm<br/>OpenAI-compatible client"]
        VBML["vbml<br/>compile + validate + truncate"]
        CHAR["charset<br/>glyph map"]
        DEV["device<br/>DeviceSpec registry"]
        DELV["delivery<br/>CloudRW / LocalAPI"]
        CFG["config<br/>load/save AppConfig"]
        HIST["history<br/>append/read entries"]
        LOG["logging_setup<br/>secret redaction"]
    end

    subgraph store["Shared volume"]
        CONFIG[("config.json")]
        HISTORY[("history.json")]
    end

    PCFG -->|read/write| CFG
    PPRE -->|test-send| PIPE
    PHIS -->|read| HIST
    CFG <--> CONFIG

    DMN -->|poll + hash| CONFIG
    DMN -->|on cron fire| PIPE
    DMN -->|on success| HIST
    HIST <--> HISTORY
    PHIS -.read.-> HISTORY

    PIPE --> LLM
    PIPE --> VBML
    PIPE --> DEV
    PIPE --> DELV
    VBML --> CHAR
    VBML --> DEV
    LLM --> DEV
    LLM -->|HTTPS| LLMAPI
    DELV -->|HTTPS| VBAPI
    VBAPI --> BOARD

    LLM -.redact keys.-> LOG
    DELV -.redact keys.-> LOG
    CFG -.register secrets.-> LOG

    classDef ext fill:#fde,stroke:#b59;
    classDef file fill:#ffd,stroke:#aa3;
    class LLMAPI,VBAPI,BOARD ext;
    class CONFIG,HISTORY file;
```

## Module responsibilities

| Module | Role |
|--------|------|
| `config` | Single JSON store. Pydantic `AppConfig`: Vestaboard creds + device, LLM endpoint, password hash, prompt entries. Atomic write (temp file + `os.replace`, `0o600`). |
| `device` | `DeviceSpec` registry — lines/cols/content-limit + centering offsets for `vestaboard` (6×22, 132) and `note` (3×15, 45). Source of truth for limits. |
| `llm` | OpenAI-compatible client. Builds device-aware system prompt, `generate()` + `check_connection()`. Never leaks the key. |
| `vbml` | Plain text → VBML → 6×22 code grid. Maps to charset, enforces content + glyph limits, `truncate_to_fit` fallback. Last gate before delivery. |
| `charset` | Vestaboard glyph code map; `is_supported()`. |
| `delivery` | `VBoard` protocol + `CloudRW` (live) and `LocalAPI` (deferred). Backend chosen by config. |
| `pipeline` | `run_once`: generate → compile → (retry shorter ×3) → truncate fallback → deliver. Returns `PipelineResult` (never raises). |
| `daemon` | APScheduler `BackgroundScheduler`. `sync_jobs` from config, `maybe_reload` on content-hash change, `_fire` per prompt, records history on success. |
| `history` | Append/read `HistoryEntry` (text, device, grid, timestamp) to `history.json`. Best-effort — write failure never breaks a delivered run. |
| `logging_setup` | Secret registration + redaction. Keys never logged at any level. |
| `ui/*` | Streamlit auth gate (bcrypt) + Credentials / Prompts / Preview / History pages. |

## Deployment

Two services share one volume — run as systemd units (`deploy/`) or containers
(`Dockerfile` + `compose.yml`, UI on `127.0.0.1:8501`, both mounting
`vboard-config` at `/data`).

```mermaid
graph LR
    subgraph host["Host / container runtime"]
        UISVC["vboard-ui<br/>(Streamlit :8501)"]
        SCHSVC["vboard-scheduler<br/>(daemon)"]
        VOL[("/data volume<br/>config.json<br/>history.json")]
        UISVC --- VOL
        SCHSVC --- VOL
    end
    USER["Authenticated user"] -->|HTTPS| UISVC
    SCHSVC -->|cron| EXT["LLM + Vestaboard APIs"]
```
