# Deploy: persistent test server + public tunnel

How the nativedev test instance is served (systemd **user** services, so it
survives reboots via linger). The public URL uses a Cloudflare **quick tunnel**,
so it **rotates every time the tunnel restarts/reboots** — for a stable URL you
need a *named* tunnel (Cloudflare account + domain, `cloudflared tunnel login`).

## One-time setup
```sh
# 1. cloudflared binary (no root)
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared

# 2. install the unit files
cp webapp/deploy/mesh2step*.service ~/.config/systemd/user/

# 3. survive logout/reboot, then start
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now mesh2step.service mesh2step-tunnel.service
```

Over SSH/non-interactive shells first export:
`export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`

## Get the current public URL
```sh
journalctl --user -u mesh2step-tunnel --no-pager | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
```

## Ops
```sh
systemctl --user status mesh2step.service mesh2step-tunnel.service
systemctl --user restart mesh2step.service      # after pulling new code (no --reload)
systemctl --user restart mesh2step-tunnel.service   # rotates the public URL
```

Requires `pip install -e ".[web,repair]"` (fastapi/uvicorn/python-multipart + pymeshfix).
