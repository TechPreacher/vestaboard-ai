# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Complete. Modules exist under `src/vboard/` (config, charset, vbml, llm, delivery, pipeline, daemon, ui); scheduler and UI are separate systemd services sharing a single config file; deploy artifacts (systemd units, container images) live in `deploy/`.

## What this is

A Python backend + Streamlit UI that generates short messages with an OpenAI-compatible LLM and
pushes them to a **Vestaboard Note** (3 lines of 15 characters each, 45 characters of total content) on a schedule. Designed
to run as a systemd service exposed to the internet for configuration by an authenticated user.

Flow: user prompt → LLM generates message fitting Note constraints → format as VBML → deliver via
Vestaboard API → repeat on cron schedule.

## Hard constraints (these drive most design decisions)

- **45-character content limit.** The Note renders ~45 chars of actual content on a 3×15 grid.
  LLM output *and* VBML rendering must respect this. Validate length after generation and after VBML
  expansion — reject/regenerate if over.
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
  Holds: Vestaboard cloud key and/or local API endpoint+key; OpenAI-compatible endpoint URL, model
  name, API key; the hashed user password; and per-prompt entries (prompt text + cron schedule).
- **LLM client** — talks to any OpenAI-compatible endpoint (configurable base URL, model, key).
  Owns the prompt scaffolding that pushes the model toward VBML-ready, length-safe output.
- **VBML formatter / validator** — converts model output to VBML, maps to character codes, enforces
  the 45-char + charset limits. The last gate before delivery.
- **Vestaboard delivery** — interface with two implementations (cloud, local) chosen by config.
- **Scheduler** — cron-format entries, each pairing a time with a prompt. Fires generation→delivery.
- **Streamlit UI** — authenticated config surface: credentials, prompts, schedules.
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
