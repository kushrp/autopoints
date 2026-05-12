# Quickstart — getting autopoints on your NAS

Read this once before you get home. The whole thing should take **10 minutes of prep work now** + **5 minutes when you walk in the door**.

---

## ✈️  Right now (while you're out)

These are the things you can knock out from any laptop with internet. Once they're done, the at-home flow is "paste one thing into Claude."

### 1. Merge the PR that publishes the Docker image (30 seconds)

Open the PR titled **"Slice 5–7: NAS deploy, onboarding wizard, strategy + Mac runbook"** at https://github.com/kushrp/autopoints/pulls → **Merge**.

This kicks off `.github/workflows/release.yml`. About 3 minutes later, `ghcr.io/kushrp/autopoints:latest` exists. Watch progress at https://github.com/kushrp/autopoints/actions. **Wait for the green check before continuing.**

### 2. Make the GHCR package public (1 minute, one-time)

After the first build succeeds, the package shows up at https://github.com/users/kushrp/packages/container/package/autopoints.

- Click the package → **Package settings** (right sidebar) → scroll to **Danger zone** → **Change visibility** → **Public** → type the package name to confirm.

This means the NAS won't need a GitHub PAT to pull. If you'd rather keep it private, skip this step; the runbook handles the PAT path too.

### 3. Create the Discord bot (3 minutes, one-time)

Open https://discord.com/developers/applications on your phone:

1. **New Application** → name it `autopoints`.
2. Sidebar → **Bot** → **Reset Token** → copy. **Save this in your password manager** — you can't view it again, only reset.
3. Sidebar → **Installation** → unchecked everything except **Guild Install**. Scopes: `bot`, `applications.commands`. Permissions: `Send Messages`, `Embed Links`. Copy the install URL.
4. Open the install URL → pick your Discord server.

That's the bot. It won't do anything until the NAS comes online.

### 4. Get Amadeus API key (3 minutes, optional)

Skip if you're fine with demo cash data for now — you can do this later.

Otherwise: https://developers.amadeus.com/register → sign up → create an app → copy `API Key` + `API Secret`. Save in your password manager.

### 5. Get your NAS values ready (1 minute)

Open a note on your phone, fill in:

```
NAS_HOST=                  # e.g. 192.168.1.42 or ugreen.local
NAS_USER=                  # your UGOS user
NAS_SSH_PORT=22
PORTAINER_URL=             # e.g. http://192.168.1.42:9000
DISCORD_BOT_TOKEN=         # from step 3
DISCORD_GUILD_ID=          # right-click your server icon → Copy Server ID (enable Dev Mode first)
DISCORD_NOTIFY_CHANNEL_ID= # right-click target channel → Copy ID
AMADEUS_CLIENT_ID=         # from step 4, or leave blank
AMADEUS_CLIENT_SECRET=     # from step 4, or leave blank
```

You don't need to know `PORTAINER_API_KEY` or `PORTAINER_ENDPOINT_ID` yet — you'll grab those in 30 seconds at home.

---

## 🏠  When you get home

### Path A — paste-into-Claude (recommended; least typing)

1. On your Mac, `git clone https://github.com/kushrp/autopoints && cd autopoints`.
2. Verify SSH to NAS works passwordlessly:
   ```sh
   ssh -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST 'docker version --format {{.Server.Version}}'
   ```
   If it prompts for password: `ssh-copy-id -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST`, then retry.
3. Open Portainer in a browser (`http://<nas-ip>:9000`) → top-right user icon → **My account** → **Access tokens** → **Add access token** → name it `autopoints-deploy` → copy the token.
4. Open Claude Code in the repo: `claude`.
5. Paste this prompt verbatim, with your values:

````
Read docs/DEPLOY_FROM_MAC.md and deploy autopoints to my UGREEN NAS.

NAS_HOST=<your nas IP>
NAS_USER=<ugos user>
NAS_SSH_PORT=22
NAS_DEPLOY_DIR=/volume1/docker/autopoints

PORTAINER_URL=http://<nas-ip>:9000
PORTAINER_API_KEY=<from step 3>
PORTAINER_ENDPOINT_ID=1

GHCR_IMAGE=ghcr.io/kushrp/autopoints:latest
GHCR_PUBLIC=true

AMADEUS_CLIENT_ID=<or blank>
AMADEUS_CLIENT_SECRET=<or blank>
DISCORD_BOT_TOKEN=<from step 3>
DISCORD_GUILD_ID=<your server id>
DISCORD_NOTIFY_CHANNEL_ID=<your channel id>
DISCORD_RUN_INTERVAL_MINUTES=60

Walk me through preflight, ask before any destructive step, then run.
````

Claude reads `docs/DEPLOY_FROM_MAC.md` and walks the 5-step deploy. ~3 minutes wall-clock.

### Path B — straight bash, no Claude (~2 minutes)

If you'd rather skip Claude and just script it:

```sh
cd autopoints
cp .env.deploy.example .env.deploy
$EDITOR .env.deploy        # fill in your values
./scripts/deploy.sh
```

The script preflights, SCPs the compose files, calls the Portainer API to create the stack, and polls `/api/health` until ready. It's a thin wrapper around the same steps the runbook describes.

Take care: `.env.deploy` is gitignored. Don't commit it.

---

## ✅  Verify it worked (30 seconds)

After either path:

```sh
# 1. Web UI
open http://<nas-ip>:8000      # macOS — opens browser

# 2. Discord bot
# In your Discord server, in any channel where the bot can see you:
/search origin:JFK destination:PHX depart_date_iso:2026-06-15 demo:true
```

If the web UI shows the search form and the Discord bot returns an embed with 9 ranked redemptions within 5 seconds, you're done.

---

## 🔁  Updating, later

Watchtower polls GHCR every 5 minutes. Push a commit to `main` → GitHub Actions builds → image lands on GHCR → ~10 min later your NAS auto-updates both containers. **You never have to be home.**

Watch it live: `ssh nas 'docker logs -f autopoints-watchtower'`.

---

## 🔥  If something's wrong

The full troubleshooting prompt library is in `docs/DEPLOY_FROM_MAC.md § 5`. Common ones inline:

| Symptom | Quick fix |
|---|---|
| Web UI loads but Discord bot offline | `ssh nas 'docker logs autopoints-discord --tail 50'` — usually a bad token, redo `.env` |
| `/api/search` returns 500 | `ssh nas 'docker logs autopoints-web --tail 100'` — read the traceback |
| Watchtower never updates | Check `WATCHTOWER_POLL_INTERVAL`, confirm containers have `com.centurylinklabs.watchtower.enable=true` label |
| Want to start fresh | `ssh nas 'cd /volume1/docker/autopoints && docker compose down -v'` — **wipes watchlists**, only do if you mean it |

---

## 📍  Where things live

| What | Where |
|---|---|
| State (cache.db, watchlists.db) | Docker volume `autopoints-data` on the NAS |
| Compose + .env files | `/volume1/docker/autopoints/` on the NAS |
| Container logs | `docker logs autopoints-{web,discord,watchtower}` |
| Web UI | `http://<nas-ip>:8000` |
| Portainer (manage stack) | `http://<nas-ip>:9000` |
| Source of truth | `https://github.com/kushrp/autopoints` |
| Image registry | `ghcr.io/kushrp/autopoints:latest` |

That's the whole thing.
