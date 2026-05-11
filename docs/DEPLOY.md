# Deploying autopoints on a UGREEN NAS (or any Docker host)

This guide gets autopoints running on a UGREEN NAS (DXP4800, DXP6800 Pro, DXP8800, etc. — anything x86_64 running UGOS with Docker). It also works on Synology, QNAP, TrueNAS, Unraid, or a plain Linux box.

The end state: a Discord bot you can talk to as a personal travel agent, plus a LAN-accessible web UI for the times you want a heatmap. Both auto-update from GitHub via Watchtower so you never have to SSH in.

## What you'll need (10 minutes)

1. A UGREEN NAS with **Docker Manager** installed (or any Docker host).
2. A **Discord bot token**: create a bot at <https://discord.com/developers/applications> → New Application → Bot → Reset Token. Copy it somewhere safe.
3. (Optional) **Amadeus free credentials**: <https://developers.amadeus.com/register>. 2,000 calls/month free. If you skip this, the app runs in demo mode with synthetic flight data.
4. The NAS IP on your LAN (e.g., `192.168.1.50`).

## Quickest path: the onboarding wizard

The web app ships a first-run wizard at `/onboard` that walks you through the rest. The fastest path is:

1. Drop the compose file + an empty `.env` on the NAS
2. `docker compose up -d`
3. Open `http://<nas-ip>:8000` — the wizard auto-loads since nothing's configured yet
4. Fill in your tokens; click "Test" on each; download the generated `.env`
5. Put the new `.env` next to the compose file; `docker compose restart`
6. Same URL now shows the search UI; the Discord bot is online in your server

Step-by-step below.

---

## Step 1 — One-time GitHub setup

The image is hosted on GitHub Container Registry (GHCR). To let your NAS pull it without authentication:

1. Push this repo to your own GitHub fork (or use the canonical `kushrp/autopoints` if you have access).
2. After the first push to `main`, GitHub Actions builds the image and publishes it to `ghcr.io/<your-user>/autopoints:latest`. Confirm in the **Actions** tab.
3. Go to your profile → **Packages** → click `autopoints` → **Package settings** → **Change visibility** → **Public**. (This skips the need for a GHCR token on the NAS. If you want to keep it private, see "Private registry" at the bottom.)

The build runs about 3 minutes on first push, ~1 minute on subsequent pushes (GHA cache).

## Step 2 — Set up the NAS

SSH into your NAS (UGREEN exposes SSH in Settings → Network → SSH) or use Docker Manager's File Browser to drop files into the right place.

```sh
# Pick a stable path that survives NAS upgrades
mkdir -p /volume1/docker/autopoints
cd /volume1/docker/autopoints
```

Download the two compose files and the env template into that directory:

```sh
curl -fsSL -O https://raw.githubusercontent.com/kushrp/autopoints/main/docker-compose.yml
curl -fsSL -O https://raw.githubusercontent.com/kushrp/autopoints/main/docker-compose.prod.yml
curl -fsSL -o .env.example https://raw.githubusercontent.com/kushrp/autopoints/main/.env.docker.example
cp .env.example .env    # we'll fill this in via the wizard
```

(If you're using your own fork, change the URLs accordingly.)

## Step 3 — Update the image references

The published compose file points at `ghcr.io/kushrp/autopoints:latest`. If you're using your own fork, edit `docker-compose.yml` and replace `kushrp` with your GitHub username on both `image:` lines.

## Step 4 — First boot

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

This pulls the prebuilt image (no local build needed), starts `web`, `discord` (will fail until you add a token, that's fine), and `watchtower`.

Check:

```sh
docker compose ps
# Expect: autopoints-web running + healthy, autopoints-watchtower running.
# autopoints-discord may be restart-looping until a token is set — fine for now.
```

## Step 5 — Run the wizard

Open `http://<nas-ip>:8000` in any browser on your LAN.

The wizard greets you because nothing is configured yet. Walk through:

1. **Welcome** — pick "Set up for NAS Docker deployment."
2. **Services** — check Web UI + Discord bot + (optional) Watchlist auto-runs.
3. **Cash data** — if you have Amadeus keys, paste them and hit "Test connection"; otherwise pick "Demo mode."
4. **Discord** — paste your bot token; hit "Test connection" to confirm the bot's username comes back. If you set Watchlist auto-runs, add a channel ID and a check interval.
5. **Seed watchlists** (optional) — pick a template or skip.
6. **Done** — copy the generated `.env` contents.

On the NAS:

```sh
nano /volume1/docker/autopoints/.env   # paste the wizard output
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

Reload `http://<nas-ip>:8000` — now you see the search UI. In Discord, run `/search origin:JFK destination:PHX depart_date_iso:2026-06-15 demo:true` — you should get an embed within a few seconds.

## Step 6 — Confirm auto-updates work

Every push to `main` of the upstream repo triggers a new image. Watchtower polls GHCR every 5 minutes and recreates the containers on a new digest.

```sh
docker logs -f autopoints-watchtower
```

Force a check now without waiting:

```sh
docker exec autopoints-watchtower /watchtower --run-once --label-enable
```

When a real update lands, you'll see Watchtower log a `Found new image` line and gracefully restart the affected container.

## Day-2 operations

### Inviting the bot to your server

Discord requires you to invite the bot manually one time. In the [Developer Portal](https://discord.com/developers/applications) → your app → OAuth2 → URL Generator, check **bot** + **applications.commands**, then under permissions check at minimum **Send Messages** and **Embed Links**. Open the resulting URL in a browser and pick your server.

### Backing up state

Both SQLite databases (cache + watchlists) live in the `autopoints-data` Docker volume. Snapshot it:

```sh
docker run --rm \
  -v autopoints-data:/data \
  -v "$(pwd)":/backup \
  alpine sh -c "cd /data && tar czf /backup/autopoints-$(date +%F).tgz ."
```

Restore by unpacking into the volume the same way.

### Looking at logs

```sh
docker logs -f autopoints-web        # FastAPI / uvicorn
docker logs -f autopoints-discord    # the bot
docker compose logs                  # both, interleaved
```

### Updating manually (skipping Watchtower)

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Re-running the wizard

Visit `http://<nas-ip>:8000/onboard` directly — the wizard stays accessible at that URL even after initial setup. To force `/` to show the wizard again, delete the sentinel inside the volume:

```sh
docker exec autopoints-web rm -f /data/.onboarded
```

## NAS-specific gotchas

- **Volume ownership.** The container runs as UID 1000. If the bind-mount or volume has different ownership on the host, you'll get permission errors. The default Docker named volume (`autopoints-data`) handles this automatically; only worry about it if you switch to a host path mount.
- **Port 8000 in use.** Some NAS apps already bind 8000. In `docker-compose.yml`, change `"8000:8000"` to `"8088:8000"` (or any free port) and reload.
- **Outbound firewall.** Some NAS distros ship with restrictive outbound rules. The bot + Amadeus + GHCR all need outbound HTTPS. Ensure `ghcr.io`, `discord.com`, `api.amadeus.com`, and `test.api.amadeus.com` are reachable from the host.
- **System clock.** Aeroplan and Amadeus signed requests rely on accurate time. `docker exec autopoints-web date` should be within a few seconds of reality. NAS units that have been off for a while sometimes drift; restart `ntpd` if you see auth failures.
- **NAS sleep.** Aggressive disk sleep makes the first request after idle slow but is otherwise fine. Watchtower's regular poll keeps the disk warm enough.

## Private registry (advanced)

If you'd rather keep the image private:

1. Generate a GitHub PAT with `read:packages` scope.
2. On the NAS: `docker login ghcr.io -u <your-github-user>` and paste the PAT.
3. Watchtower will pick up the saved credentials automatically.

## Tearing down

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker volume rm autopoints-data   # also wipes watchlists + cache
```

## Resource expectations

Tiny. At idle the whole stack uses ~120 MB of RAM total and essentially 0% CPU. During a search the web container spikes for a few hundred milliseconds. The image is ~80 MB. Disk usage grows by maybe 10 MB per year of cache + watchlist activity.
