# Vestaboard AI

Generate short messages with an OpenAI-compatible LLM and push them to a
[Vestaboard](https://www.vestaboard.com/) on a cron schedule. A small Python backend plus a
Streamlit UI let an authenticated user manage credentials, prompts, and schedules from the browser.
Built to run as two systemd services behind a TLS-terminating reverse proxy (nginx or caddy).

```
prompt → LLM generates message → compile to VBML + char codes
       → validate (45 chars / 3×15 / charset) → deliver to board → repeat on schedule
```

## Features

- **OpenAI-compatible LLM client** — point it at any endpoint (OpenAI, a local server, etc.) via
  base URL, model, and key.
- **Hard constraint enforcement** — the Vestaboard Note renders 45 characters of content across
  3 lines of 15. Output is validated *after* VBML expansion; over-length messages are regenerated up
  to 3 times, then word-boundary truncated as a last resort. Unsupported glyphs are rejected.
- **Two delivery backends behind one interface** — Cloud Read/Write API (built) and a Local API
  stub (interface ready, implementation deferred), selectable from config.
- **Scheduling** — one cron entry per prompt, fired by an APScheduler daemon that hot-reloads when
  the config changes.
- **Authenticated config UI** — single-user, bcrypt-hashed password; every page is behind the gate.
- **Secrets stay secret** — API keys are never logged (a redaction filter scrubs all log output),
  and `config.json` is written atomically with `0600` permissions.

## Architecture

Two independent processes share a single `config.json` — they never talk directly.

```
config.json (0600, service user)  ← single source of truth
   ▲ write (atomic: temp + os.replace)        ▲ read (poll mtime every 5s)
   │                                          │
vboard-ui.service                     vboard-scheduler.service
 streamlit run app.py                  python -m vboard.daemon
 (auth + edit config)                  (APScheduler → generate → deliver)
```

The UI only edits config (plus an on-demand "test send"); the daemon owns scheduling and delivery.
This keeps the scheduler alive across UI reloads and lets each service restart independently.

Modules (`src/vboard/`):

| Module | Responsibility |
|---|---|
| `config` | Pydantic models; atomic `0600` load/save |
| `logging_setup` | Logger + secret-redaction filter |
| `charset` | Text → Vestaboard character codes |
| `vbml` | Compile text + color hints → VBML/code grid; the 45-char + charset gate |
| `llm` | OpenAI-compatible client + prompt scaffolding |
| `delivery` | `VBoard` interface, `CloudRW` impl, `Local` stub, factory |
| `pipeline` | generate → compile → regenerate → truncate → deliver |
| `daemon` | APScheduler + mtime-poll reload |
| `ui/` | Streamlit auth gate, config editors, preview/test-send |

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- A Vestaboard with a [Cloud Read/Write API](https://docs.vestaboard.com/docs/read-write-api/introduction/) key
- An OpenAI-compatible LLM endpoint (URL, model name, API key)

## Quick start (local)

```bash
git clone <your-repo-url> vestaboard-ai
cd vestaboard-ai
uv sync

# Launch the UI (first run prompts you to set an admin password)
VBOARD_CONFIG=./config.json uv run streamlit run src/vboard/ui/app.py

# In another terminal, run the scheduler against the same config
VBOARD_CONFIG=./config.json uv run python -m vboard.daemon
```

Open the UI (default <http://localhost:8501>), set a password, then fill in:

1. **Credentials** — Vestaboard backend + key, and your LLM base URL / model / key.
2. **Prompts & Schedules** — add prompts, each with a 5-field cron expression.
3. **Preview / Test** — preview the rendered grid and send a one-off message to verify the setup.

The daemon picks up config changes within ~5 seconds — no restart needed.

`VBOARD_CONFIG` selects the config file path (defaults to `./config.json`). See
[`config.example.json`](config.example.json) for the file shape — though in practice you manage it
entirely through the UI. **Do not commit your real `config.json`; it holds secrets and is
git-ignored.**

## Development

```bash
uv run pytest          # run the test suite
uv run ruff check .    # lint
```

The core (`vbml`, `pipeline`) is pure-function and heavily unit-tested; `llm` and `delivery` are
tested against mocked HTTP.

## Deployment

Designed to run as two systemd services on one host, behind a reverse proxy that terminates TLS. The
app speaks **plain HTTP on localhost only** — it never handles certificates itself.

The unit files in [`deploy/`](deploy/) assume the app lives at `/opt/vboard`, runs as a dedicated
`vboard` user, and reads `/opt/vboard/config.json`.

### 1. Install the app

```bash
# Dedicated, unprivileged service user
sudo useradd --system --home /opt/vboard vboard

# Place the code and install dependencies
sudo git clone <your-repo-url> /opt/vboard
cd /opt/vboard
sudo -u vboard uv sync          # creates /opt/vboard/.venv
sudo chown -R vboard:vboard /opt/vboard
```

### 2. Install the systemd services

```bash
sudo cp deploy/vboard-scheduler.service deploy/vboard-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vboard-scheduler vboard-ui
```

The UI binds to `127.0.0.1:8501`. On first visit you'll be asked to set the admin password;
`config.json` is created mode `0600` owned by `vboard`.

Check status / logs:

```bash
systemctl status vboard-ui vboard-scheduler
journalctl -u vboard-ui -f
```

### 3. Put a reverse proxy in front (TLS)

Pick **one** of the following. Both forward HTTPS traffic to the UI on `127.0.0.1:8501`. The
WebSocket upgrade headers matter — Streamlit relies on them.

#### Option A — Caddy

Caddy obtains and renews Let's Encrypt certificates automatically. `/etc/caddy/Caddyfile`:

```caddy
your.domain {
    reverse_proxy 127.0.0.1:8501
}
```

```bash
sudo systemctl reload caddy
```

That's it — Caddy handles WebSocket upgrades and TLS with no extra config.

#### Option B — nginx

Obtain a certificate first (e.g. `sudo certbot --nginx -d your.domain`), then use a server block
like this:

```nginx
server {
    listen 443 ssl;
    server_name your.domain;

    ssl_certificate     /etc/letsencrypt/live/your.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;

        # Required for Streamlit's WebSocket connection
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect plain HTTP to HTTPS
server {
    listen 80;
    server_name your.domain;
    return 301 https://$host$request_uri;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Security notes

- Keep the UI bound to `127.0.0.1` — never expose port 8501 directly; let the proxy handle the
  public TLS endpoint.
- `config.json` holds plaintext API keys, protected by `0600` permissions and a dedicated service
  user. Keys are never written to logs.
- The admin password is bcrypt-hashed, never stored or logged in plaintext.

## Roadmap

Deferred, with interfaces already in place:

- Local API delivery implementation
- Multi-user accounts
- Encryption of secrets at rest
- Message history / analytics

## License

[MIT](LICENSE)
