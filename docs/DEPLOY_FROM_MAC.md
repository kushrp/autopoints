# Deploy autopoints to your NAS with Claude Code on Mac

You sit at your Mac. Claude Code SSHes into your UGREEN NAS and talks to Portainer's API to bring up the `autopoints` stack. This doc gives you (a) the prep work, (b) the exact prompt to paste into Claude Code, and (c) reference material Claude will consult during execution.

Estimated wall-clock time: **15 minutes** the first time, **30 seconds** for updates.

---

## 0. What this gets you

After this runs, your NAS will have:

| Container | Purpose | Port |
|---|---|---|
| `autopoints-web` | FastAPI + web UI at `http://<nas-ip>:8000` | 8000 |
| `autopoints-discord` | Discord bot (your personal travel agent) | none |
| `autopoints-watchtower` | Auto-pulls new image versions from GHCR every 5 min | none |

Both `web` and `discord` share the **same** SQLite database at `/data/`, so a `/watchlist add` issued in Discord shows up in the web UI immediately.

Updates happen automatically: every push to `main` → GitHub Actions builds → GHCR → Watchtower pulls → containers recreate. **You never have to be home.**

---

## 1. Prerequisites you gather (one time, ~10 minutes)

Have these values ready before you talk to Claude. Keep them in a temporary scratch file on your Mac.

### 1a. NAS access

| Value | Example | Where to find it |
|---|---|---|
| `NAS_HOST` | `192.168.1.42` or `ugreen.local` | UGREEN UGOS → Network settings |
| `NAS_USER` | `admin` (or your UGOS user) | The user you log into UGOS as |
| `NAS_SSH_PORT` | `22` (default) | UGOS → Control Panel → Terminal & SNMP → SSH |
| SSH key | `~/.ssh/id_ed25519` | If you don't have one: `ssh-keygen -t ed25519` |

Enable SSH on the NAS (UGOS → Control Panel → Terminal & SNMP → enable SSH) and copy your public key over **once**:

```sh
ssh-copy-id -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST
```

Verify it works passwordless:

```sh
ssh -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST 'docker version --format {{.Server.Version}}'
```

If that prints a version number, you're set. If `docker` isn't found, install Docker via UGOS App Center first.

### 1b. Portainer

| Value | Example | Where to find it |
|---|---|---|
| `PORTAINER_URL` | `http://192.168.1.42:9000` | Same NAS IP, port 9000 by default |
| `PORTAINER_API_KEY` | `ptr_abc123...` | Portainer UI → top-right user icon → **My account** → **Access tokens** → **Add access token** |
| `PORTAINER_ENDPOINT_ID` | `1` or `2` | Portainer → Environments → click your NAS → URL ends in `/endpoints/<id>` |

Install Portainer if you don't have it. From UGREEN's Docker app or via SSH:

```sh
ssh $NAS_USER@$NAS_HOST 'docker volume create portainer_data && docker run -d -p 9000:9000 --name portainer --restart=always -v /var/run/docker.sock:/var/run/docker.sock -v portainer_data:/data portainer/portainer-ce:latest'
```

Then visit `http://<nas-ip>:9000`, create the admin user, and add the local Docker environment. Generate an API key under your user profile.

### 1c. GitHub Container Registry

The image lives at **`ghcr.io/kushrp/autopoints:latest`** and is built by `.github/workflows/release.yml` on every push to `main`.

**First-time setup — make the package public** (so the NAS doesn't need a GHCR token):

1. Push at least one commit to `main` to trigger the workflow.
2. Wait ~3 minutes for the first build to publish.
3. On GitHub → your `autopoints` repo → **Packages** (right sidebar) → click `autopoints` → **Package settings** → scroll to **Danger zone** → **Change visibility** → **Public**.

If you want to keep it private, you'll also need a `read:packages` PAT and `docker login ghcr.io` on the NAS — Claude will prompt for it if needed.

### 1d. Secrets to inject

Have these ready (or leave blank — the app degrades gracefully):

| Var | Required? | Where to get it |
|---|---|---|
| `DISCORD_BOT_TOKEN` | required to use Discord | https://discord.com/developers/applications → New App → Bot → Reset Token |
| `DISCORD_GUILD_ID` | optional (faster sync) | In Discord enable Dev Mode → right-click your server → Copy ID |
| `DISCORD_NOTIFY_CHANNEL_ID` | optional (auto-runs) | Right-click target channel → Copy ID |
| `DISCORD_RUN_INTERVAL_MINUTES` | optional, default 60 | minutes between automated re-runs |

**Invite the bot to your server** once: Discord developer portal → your app → **OAuth2** → **URL Generator** → scopes `bot` + `applications.commands`, permissions `Send Messages` + `Embed Links` → open the generated URL in your browser → pick your server.

---

## 2. The prompt — paste this into Claude Code on your Mac

Open Claude Code in your terminal (`claude` if you have it installed, or `npx @anthropic-ai/claude-code`). Paste **this entire block**, with placeholders filled in:

````
Deploy autopoints to my UGREEN NAS using SSH and the Portainer API. The
deploy runbook is at /path/to/autopoints/docs/DEPLOY_FROM_MAC.md — read
it first, then proceed step by step.

## Inputs

NAS_HOST=192.168.1.42
NAS_USER=admin
NAS_SSH_PORT=22
NAS_DEPLOY_DIR=/volume1/docker/autopoints

PORTAINER_URL=http://192.168.1.42:9000
PORTAINER_API_KEY=ptr_abc123...
PORTAINER_ENDPOINT_ID=1

GHCR_IMAGE=ghcr.io/kushrp/autopoints:latest
GHCR_PUBLIC=true     # set false if the package is private; Claude will ask for a PAT

## Secrets (paste these too, redact in conversation history if sharing screenshots)

DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_NOTIFY_CHANNEL_ID=
DISCORD_RUN_INTERVAL_MINUTES=60

## Execution policy

- Do NOT push anything to GitHub during this deploy.
- Do NOT modify any files outside ~/.ssh/known_hosts and the NAS_DEPLOY_DIR
  on the NAS.
- Before each destructive step (volume creation, stack delete, container
  recreate), tell me what you're about to do and wait for confirmation
  unless I tell you to YOLO it.
- Confirm health checks pass before declaring success.
````

Claude will read this doc, the local `docker-compose.yml`, `docker-compose.prod.yml`, and `.env.docker.example`, then walk through Section 3 step-by-step.

---

## 3. Step-by-step (this is what Claude executes — reference for both of you)

### Step 1 — preflight (read-only)

Claude verifies:

```sh
# SSH works passwordlessly
ssh -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST 'whoami && docker version --format {{.Server.Version}}'

# Portainer API is reachable and the key is valid
curl -s -H "X-API-Key: $PORTAINER_API_KEY" $PORTAINER_URL/api/system/version

# Endpoint ID exists and is a Docker host
curl -s -H "X-API-Key: $PORTAINER_API_KEY" $PORTAINER_URL/api/endpoints/$PORTAINER_ENDPOINT_ID | jq '{Name, Type, Status}'

# GHCR is reachable (and the image is public if claimed)
curl -s -I https://ghcr.io/v2/kushrp/autopoints/manifests/latest | head -1
```

If any of these fail, Claude will pause and report which.

### Step 2 — stage files on the NAS

Claude SCPs the deploy files into `$NAS_DEPLOY_DIR`:

```sh
ssh -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST "mkdir -p $NAS_DEPLOY_DIR"

# Compose files
scp -P $NAS_SSH_PORT docker-compose.yml \
    docker-compose.prod.yml \
    $NAS_USER@$NAS_HOST:$NAS_DEPLOY_DIR/

# .env is generated locally with the user's secrets, never committed to git
# then copied over with strict permissions
ssh -p $NAS_SSH_PORT $NAS_USER@$NAS_HOST "cat > $NAS_DEPLOY_DIR/.env && chmod 600 $NAS_DEPLOY_DIR/.env" < /tmp/autopoints.env.tmp
rm /tmp/autopoints.env.tmp
```

### Step 3 — create the stack via Portainer API

This is the "talk to Portainer" half of what you asked for. Claude POSTs to the Portainer **stacks** endpoint, which knows how to merge the two compose files and pull the GHCR image:

```sh
# Read the merged compose YAML (compose.yml + compose.prod.yml) into a JSON-safe string
COMPOSE_BODY=$(ssh ... "docker compose -f $NAS_DEPLOY_DIR/docker-compose.yml -f $NAS_DEPLOY_DIR/docker-compose.prod.yml config")
ENV_VARS=$(jq -n --arg ... ...)  # build {name, value} array from .env

# POST /api/stacks?type=2&method=string&endpointId=<id>
curl -s -X POST \
  -H "X-API-Key: $PORTAINER_API_KEY" \
  -H "Content-Type: application/json" \
  "$PORTAINER_URL/api/stacks/create/standalone/string?endpointId=$PORTAINER_ENDPOINT_ID" \
  -d "$(jq -n \
    --arg name "autopoints" \
    --arg compose "$COMPOSE_BODY" \
    --argjson env "$ENV_VARS" \
    '{Name: $name, StackFileContent: $compose, Env: $env}')"
```

(Portainer's API has shifted between v2.x versions — Claude will fall back to `POST /api/stacks/create/standalone/file` with a multipart upload if the JSON endpoint isn't recognized.)

### Step 4 — verify health

Claude polls until both containers are up and `/api/health` returns 200:

```sh
# Wait up to 60s for web container to be healthy
for i in $(seq 1 30); do
  STATUS=$(curl -s -H "X-API-Key: $PORTAINER_API_KEY" \
    "$PORTAINER_URL/api/endpoints/$PORTAINER_ENDPOINT_ID/docker/containers/json?filters=%7B%22name%22%3A%5B%22autopoints-web%22%5D%7D" \
    | jq -r '.[0].State')
  [ "$STATUS" = "running" ] && break
  sleep 2
done

# Round-trip the API
curl -s http://$NAS_HOST:8000/api/health
curl -s -X POST http://$NAS_HOST:8000/api/search \
  -H 'content-type: application/json' \
  -d '{"origin":"JFK","destination":"PHX","depart_date":"2026-06-15","demo":true}' \
  | jq '.redemptions | length'

# Confirm Discord bot connected (looks for "ready as" in logs)
ssh ... "docker logs --tail 20 autopoints-discord 2>&1 | grep -E 'ready as|error'"
```

If any of these fail, Claude reports the relevant container logs and pauses.

### Step 5 — report

Claude prints a final summary:

```
✓ autopoints stack deployed on 192.168.1.42
  web:        http://192.168.1.42:8000   (healthy, version v0.1.0)
  discord:    ready as autopoints#1234   (connected to 1 guild)
  watchtower: polling ghcr.io every 5min

  state:    /volume1/docker/autopoints/  (compose + .env)
  volume:   autopoints-data              (cache.db + watchlists.db)

  next: try `/search origin:JFK destination:PHX depart_date_iso:2026-06-15 demo:true` in Discord
```

---

## 4. Updating later

Two paths.

### Path A: automatic (default)

Watchtower polls GHCR every 5 minutes. When you push to `main`, GitHub Actions builds a new image and pushes `ghcr.io/kushrp/autopoints:latest`. Within ~10 minutes the NAS pulls and recreates the containers. **Nothing to do from your Mac.**

Watch the rollover live:

```
ssh nas 'docker logs -f autopoints-watchtower'
```

### Path B: force an update on demand

If you want the new version *now*, paste this into Claude Code:

```
Force-update the autopoints stack on my NAS:
  NAS_HOST=192.168.1.42
  NAS_USER=admin
ssh in and run:
  cd /volume1/docker/autopoints
  docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
Then curl http://$NAS_HOST:8000/api/health and confirm it's the new sha.
```

---

## 5. Common things that break, and prompts to fix them

| Symptom | Paste this into Claude |
|---|---|
| `Permission denied (publickey)` on SSH | `My NAS SSH is broken. Test SSH to $NAS_USER@$NAS_HOST with verbose output, identify whether it's a key, port, or known_hosts issue, and fix it.` |
| Portainer API returns 401 | `Portainer API key auth is failing. Curl POST /api/auth with my password instead, get a JWT, and use that for one deploy. Then prompt me to regenerate an API key in the UI.` |
| Image pull fails with 401 / unauthorized | `GHCR pull is failing. The package is private. Walk me through (a) creating a read:packages PAT, then (b) running 'docker login ghcr.io' on the NAS. Then re-pull.` |
| `autopoints-discord` keeps restarting | `Show me 'docker logs autopoints-discord' from the NAS. If it's complaining about DISCORD_BOT_TOKEN, prompt me for a new one and update .env without recreating the web container.` |
| `/api/search` returns 500 | `Show me 'docker logs autopoints-web --tail 100' from the NAS. Diagnose the traceback. Don't restart the container yet — confirm the fix with me first.` |
| Watchtower isn't pulling | `Watchtower hasn't updated the image. Check (1) the container has the com.centurylinklabs.watchtower.enable=true label, (2) watchtower can reach ghcr.io, (3) WATCHTOWER_POLL_INTERVAL is set. Fix what's wrong.` |
| You want to reset everything | `Tear down the autopoints stack on my NAS, including the autopoints-data volume. Confirm with me before deleting the volume — that nukes my watchlists.` |

---

## 6. Backing up

The state lives in the `autopoints-data` Docker volume (`cache.db` + `watchlists.db`). Quick snapshot:

```sh
ssh nas 'docker run --rm -v autopoints-data:/data -v /tmp:/backup alpine tar czf /backup/autopoints-$(date +%F).tgz -C /data .'
scp nas:/tmp/autopoints-*.tgz ~/backups/
```

You can drop the same call into Claude as a recurring task on your Mac via `launchd` if you want it automated.

---

## 7. Notes on what Claude will NOT do

Some guardrails worth knowing about. Claude will refuse or pause for confirmation if asked to:

- **Push to GitHub from your Mac during deploy.** GHCR images are built by CI, not by you. If you want a new image, push a commit to `main` first and let Actions build it.
- **Delete the `autopoints-data` volume** without an explicit `yes, nuke it`.
- **Open ports beyond your LAN** (e.g., `0.0.0.0:8000` exposed via port-forwarding). The compose config binds to all interfaces on the NAS, but your router controls the LAN-vs-internet boundary. If you want public access, route through Tailscale or Cloudflare Tunnel — Claude will prompt for that as a separate step.
- **Store your Discord bot token in your shell history.** Claude reads the secrets from the prompt block once, writes them straight to `.env` on the NAS with `chmod 600`, and clears the local temp file.

---

## 8. Quick reference

| Where | What |
|---|---|
| `docs/DEPLOY_FROM_MAC.md` (this file) | The runbook Claude follows |
| `docs/DEPLOY.md` | Manual-deploy version, if you'd rather click through the Portainer UI yourself |
| `Dockerfile` | Multi-stage build, runs as UID 1000, `/data` volume, `:8000` |
| `docker-compose.yml` | `web` + `discord`, shared `autopoints-data` volume |
| `docker-compose.prod.yml` | Adds Watchtower; tells compose to pull from GHCR instead of building |
| `.env.docker.example` | Template for the env file Claude generates |
| `.github/workflows/release.yml` | Builds + pushes the image to GHCR on every `main` push |

Total recurring cost: **$0/month.** The NAS is hardware you already own; everything else (Google Flights, GHCR, Discord) is free for personal use.
