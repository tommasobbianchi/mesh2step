# Deploy: persistent test server + public URL

How the nativedev test instance is served (systemd **user** services, so it
survives reboots via linger).

## Branded URL (share this one)

**https://mesh2step.nativemedica.it/**

A cPanel subdomain on the Netsons hosting of nativemedica.it (cPanel user
`alqpatit`, docroot `public_html/mesh2step`) whose `.htaccess` 302-redirects to
the origin below. Publicly reachable, Let's Encrypt cert issued and renewed by
cPanel AutoSSL. It is a **redirect**, not a proxy: the address bar ends up on
the `ts.net` origin. DNS needed no new record — `*.nativemedica.it` already
wildcards to the hosting IP.

To retarget it, edit `public_html/mesh2step/.htaccess` in cPanel. The redirect
is deliberately 302, so the target can move without poisoning browser caches.

## Origin (stable public URL)

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

## The native engine is a hard dependency

`webapp/server.py` raises `NativeUnavailable` at import if the `stl2step` binary is not
found, so a misconfigured unit fails at startup instead of serving 500s. Resolution order
is `$MESH2STEP_NATIVE` → `refs/stl2step/RUN.sh` → `stl2step` on `PATH`.

The deployed instance points at a **frozen** copy — binary plus its 31 OCCT `.so` files —
so a FreeCAD/OCCT refresh on the host cannot silently change conversion output:

```
~/.local/share/mesh2step-native/{stl2step,run.sh,lib/}
~/.config/systemd/user/mesh2step.service.d/native.conf
  Environment=MESH2STEP_NATIVE=%h/.local/share/mesh2step-native/run.sh
```

`run.sh` sets `LD_LIBRARY_PATH` to that `lib/`. Rebuilding the reference does not update
the frozen copy; re-freeze deliberately and re-run the corpus when you do.
