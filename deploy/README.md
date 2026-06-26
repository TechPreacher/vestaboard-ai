# Deploy

Two systemd services share `/opt/vboard/config.json`. The UI binds to `127.0.0.1:8501`
only; a reverse proxy (nginx or caddy) terminates TLS and forwards to it.

## Install
1. Create user: `sudo useradd --system --home /opt/vboard vboard`
2. Copy the repo to `/opt/vboard`, then: `cd /opt/vboard && uv sync`
3. `sudo chown -R vboard:vboard /opt/vboard`
4. Copy units: `sudo cp deploy/*.service /etc/systemd/system/`
5. `sudo systemctl daemon-reload`
6. `sudo systemctl enable --now vboard-scheduler vboard-ui`

The first time you open the UI it will ask you to set an admin password.
`config.json` is created mode 0600 owned by `vboard`.

## Reverse proxy (caddy example)
```
your.domain {
    reverse_proxy 127.0.0.1:8501
}
```
Caddy obtains and renews TLS automatically. The app itself speaks plain HTTP on localhost.

## nginx example
```
server {
    listen 443 ssl;
    server_name your.domain;
    ssl_certificate     /etc/letsencrypt/live/your.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
