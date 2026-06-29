# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Complete. Modules exist under `src/vboard/` (config, charset, device, vbml, llm, delivery, pipeline, daemon, history, ui); scheduler and UI are separate processes sharing a single config file (plus a `history.json` of delivered messages) on a common volume. Run them as systemd services (units in `deploy/`) or as containers (`Dockerfile` + `compose.yml` at the repo root, two services sharing a `/data` volume).

## What this is

A Python backend + Streamlit UI that generates short messages with an OpenAI-compatible LLM and
pushes them to a **Vestaboard** on a schedule. The target device is configurable (see `device.py`):
a full **Vestaboard** (6 lines × 22 chars, 132 chars total) or a **Vestaboard Note** (3 lines × 15
chars, 45 chars total). Designed to run as a systemd service exposed to the internet for
configuration by an authenticated user.

Flow: user prompt → LLM generates message fitting the configured device's constraints → format as
VBML → deliver via Vestaboard API → repeat on cron schedule. Each delivered message is appended to
`history.json` (with its device flag) for the History page.

## Hard constraints (these drive most design decisions)

- **Device-dependent content limit.** The limit comes from the configured device (`device.py`): a
  Note holds 45 chars on a 3×15 grid; a full Vestaboard holds 132 on a 6×22 grid. In both cases the
  full physical 6×22 grid is what's delivered — the device only decides how much of it the content
  uses and how it's centered. LLM output *and* VBML rendering must respect the active device's limit.
  Validate length after generation and after VBML expansion — reject/regenerate if over.
- **Character set is restricted.** Only Vestaboard's supported glyphs render (letters, digits,
  symbols, color chips, ❤️). The Note adds regional currency symbols beyond the Flagship set. Map
  text → character codes; strip or substitute anything unsupported. See
  https://docs.vestaboard.com/docs/characterCodes
- **Output must be VBML.** Layout/alignment/color are expressed in Vestaboard Markup Language. Either
  prompt the LLM to emit VBML directly, or post-process plain text into VBML. See
  https://docs.vestaboard.com/docs/vbml
- **Two delivery backends, both selectable at config time:** Cloud Read/Write API
  (https://docs.vestaboard.com/docs/read-write-api/introduction/) *and* Local API (endpoint + key).
  Code against an abstraction so either is swappable.

## Architecture (target)

Keep these as separable modules so backends/providers are swappable and testable in isolation:

- **Config store** — single JSON file, fully managed through the UI (no hand-editing expected).
  Holds: Vestaboard cloud key and/or local API endpoint+key; the device type; OpenAI-compatible
  endpoint URL, model name, API key; the hashed user password; and per-prompt entries (prompt text +
  cron schedule).
- **Device registry** (`device.py`) — `DeviceSpec`s for the supported devices (Vestaboard 6×22,
  Note 3×15). The single source of truth for lines/cols/content-limit and the centering offsets
  used to lay content onto the physical 6×22 board.
- **LLM client** — talks to any OpenAI-compatible endpoint (configurable base URL, model, key).
  Owns the prompt scaffolding (built from the active `DeviceSpec`) that pushes the model toward
  VBML-ready, length-safe output. Also exposes `check_connection` (used by the UI's "Test
  connection" button) — a tiny request that validates endpoint/key/model without leaking the key.
- **VBML formatter / validator** — converts model output to VBML, maps to character codes, enforces
  the active device's content + charset limits. The last gate before delivery.
- **Vestaboard delivery** — interface with two implementations (cloud, local) chosen by config.
- **Scheduler** — cron-format entries, each pairing a time with a prompt. Fires generation→delivery.
- **History store** (`history.py`) — appends each delivered message (text, device, rendered grid,
  timestamp) to `history.json`; surfaced by the UI's History page.
- **Streamlit UI** — authenticated config surface: credentials (incl. device + "Test connection"
  for the LLM endpoint), prompts, schedules, preview/test-send, and History.
- **Auth** — single user, password verified against a stored hash.

## Security (non-negotiable)

- **Never log API keys** or any credential — not at any log level, not in tracebacks/error surfaces.
- **Password is stored hashed**, never plaintext. Use a real password hash (argon2 or bcrypt), not a
  bare digest.
- The app is internet-exposed for configuration — treat every config endpoint as needing auth.

## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Run UI locally: `VBOARD_CONFIG=./config.json uv run streamlit run src/vboard/ui/app.py`
- Run scheduler daemon: `VBOARD_CONFIG=./config.json uv run python -m vboard.daemon`
- Build + run both services in containers: `docker compose up -d --build` (UI on 127.0.0.1:8501, scheduler + UI share the `vboard-config` volume)
- Build image only: `docker build -t vboard:local .`

## Verification

A task is not done until tests and lint pass. Establish those commands first, then run them before
reporting back.

## Agent Teams notes

- Experimental teams are enabled via `.claude/settings.json`
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Requires Claude Code v2.1.32+.
- Ready-to-paste spawn prompts are in `.claude/TEAM_PROMPTS.md`.
- Launch a team session with `.claude/launch-team.fish` (needs tmux 3.2+ for split panes).
- After creating a team, press `Shift+Tab` to put the lead in coordination-only (delegate) mode.
- For 4+ teammates, give each its own git worktree so they don't collide on files.
- A read-only `security-reviewer` subagent lives in `.claude/agents/` — use it before merging
  changes touching auth, config, secrets, or input handling.
