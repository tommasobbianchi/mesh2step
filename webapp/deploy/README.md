# Deploy: persistent test server + public URL

How the nativedev test instance is served (systemd **user** services, so it
survives reboots via linger).

## Stable public URL (use this one)

**https://nativedev.tail7d3518.ts.net/mesh2step/**

Tailscale Funnel (:443) → Caddy path router (`~/.config/caddy/Caddyfile`) →
`127.0.0.1:8000`. The hostname is tied to the tailnet node, so it never
rotates. Publicly reachable — visitors do *not* need Tailscale.

Caddy block (already installed):
```
redir /mesh2step /mesh2step/ permanent
handle_path /mesh2step/* {
	reverse_proxy 127.0.0.1:8000 {
		transport http { read_timeout 30m  write_timeout 30m }
	}
}
```
`handle_path` strips the prefix, so the frontend must use **relative** URLs
(`api/convert`, not `/api/convert`) — `webapp/static/app.js` does. Keep it that
way or the app breaks under the prefix while still working on :8000.

Reload after editing the Caddyfile: `caddy reload --config ~/.config/caddy/Caddyfile`.

## Cloudflare quick tunnel (ephemeral fallback)

`mesh2step-tunnel.service` runs `cloudflared tunnel --url` — a *quick* tunnel,
so its `*.trycloudflare.com` URL **rotates on every restart/reboot**. Only useful
for a throwaway link; a stable Cloudflare URL would need a *named* tunnel
(Cloudflare account + domain + `cloudflared tunnel login`).

```sh
journalctl --user -u mesh2step-tunnel --no-pager | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
```

## One-time setup
```sh
# 1. install the unit files
cp webapp/deploy/mesh2step*.service ~/.config/systemd/user/

# 2. survive logout/reboot, then start
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now mesh2step.service

# 3. optional ephemeral tunnel (needs ~/.local/bin/cloudflared)
systemctl --user enable --now mesh2step-tunnel.service
```

Over SSH/non-interactive shells first export:
`export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`

## Ops
```sh
systemctl --user status mesh2step.service
systemctl --user restart mesh2step.service   # after pulling new code (no --reload)
curl -sI https://nativedev.tail7d3518.ts.net/mesh2step/ | head -1
```

Requires `pip install -e ".[web,repair]"` (fastapi/uvicorn/python-multipart + pymeshfix).
