#!/usr/bin/env bash
# autopoints — one-shot deploy from Mac to NAS via SSH + Portainer.
#
# Reads .env.deploy at the repo root for connection params and runtime config.
# Idempotent: re-running updates the running stack instead of erroring out.
#
# Usage:
#   cp .env.deploy.example .env.deploy
#   $EDITOR .env.deploy
#   ./scripts/deploy.sh
#
# Useful flags:
#   ./scripts/deploy.sh --check     # preflight only, don't touch anything
#   ./scripts/deploy.sh --redeploy  # tear down + recreate the stack (preserves volume)
#   ./scripts/deploy.sh --nuke      # tear down AND delete the volume. Eats watchlists.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env.deploy"

GREEN='\033[32m'; RED='\033[31m'; DIM='\033[2m'; BOLD='\033[1m'; RESET='\033[0m'
say()  { printf "${DIM}…${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
err()  { printf "${RED}✗${RESET} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

MODE="deploy"
case "${1:-}" in
  --check)    MODE="check" ;;
  --redeploy) MODE="redeploy" ;;
  --nuke)     MODE="nuke" ;;
  -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
  "")         ;;
  *) die "unknown flag: $1 (try --help)" ;;
esac

[ -f "$ENV_FILE" ] || die "no $ENV_FILE — copy .env.deploy.example to .env.deploy and edit."
set -a; . "$ENV_FILE"; set +a

require() { [ -n "${!1:-}" ] || die "missing $1 in .env.deploy"; }
for v in NAS_HOST NAS_USER NAS_SSH_PORT NAS_DEPLOY_DIR PORTAINER_URL PORTAINER_API_KEY PORTAINER_ENDPOINT_ID GHCR_IMAGE; do
  require "$v"
done

SSH() { ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -p "$NAS_SSH_PORT" "$NAS_USER@$NAS_HOST" "$@"; }
SCP() { scp -o StrictHostKeyChecking=accept-new -P "$NAS_SSH_PORT" "$@"; }

PORTAINER_HEADERS=(-H "X-API-Key: $PORTAINER_API_KEY" -H "Content-Type: application/json")

# ---------- preflight ----------

preflight() {
  say "Preflight: SSH"
  local ver
  ver="$(SSH 'docker version --format {{.Server.Version}}' 2>&1)" \
    || die "SSH or docker on NAS failed: $ver"
  ok "SSH ok ($NAS_USER@$NAS_HOST), docker server $ver"

  say "Preflight: Portainer"
  local p_ver
  p_ver="$(curl -fsS "${PORTAINER_HEADERS[@]}" "$PORTAINER_URL/api/system/version" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("ServerVersion","?"))' 2>/dev/null)" \
    || die "Portainer auth failed. Check PORTAINER_URL and PORTAINER_API_KEY."
  ok "Portainer ok ($p_ver)"

  say "Preflight: Portainer endpoint $PORTAINER_ENDPOINT_ID"
  local ep_name
  ep_name="$(curl -fsS "${PORTAINER_HEADERS[@]}" "$PORTAINER_URL/api/endpoints/$PORTAINER_ENDPOINT_ID" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("Name","?"))' 2>/dev/null)" \
    || die "Portainer endpoint $PORTAINER_ENDPOINT_ID not found"
  ok "Portainer endpoint: $ep_name"

  say "Preflight: GHCR image"
  if [ "${GHCR_PUBLIC:-true}" = "true" ]; then
    curl -fsSI "https://ghcr.io/v2/${GHCR_IMAGE#ghcr.io/}" >/dev/null 2>&1 \
      || curl -fsS "https://ghcr.io/v2/${GHCR_IMAGE%:*}/manifests/${GHCR_IMAGE##*:}" \
         -H "Accept: application/vnd.docker.distribution.manifest.v2+json" >/dev/null 2>&1 \
      || die "GHCR image $GHCR_IMAGE not reachable (or package isn't public yet — see QUICKSTART step 2)"
    ok "GHCR image reachable (public)"
  else
    [ -n "${GHCR_USERNAME:-}" ] && [ -n "${GHCR_TOKEN:-}" ] \
      || die "GHCR_PUBLIC=false but GHCR_USERNAME/GHCR_TOKEN not set"
    ok "GHCR private mode (NAS will use stored login)"
  fi
}

preflight

if [ "$MODE" = "check" ]; then
  ok "Preflight complete. Rerun without --check to deploy."
  exit 0
fi

# ---------- stage files on NAS ----------

stage() {
  say "Staging files in $NAS_DEPLOY_DIR"
  SSH "mkdir -p '$NAS_DEPLOY_DIR'"

  # Generate the NAS-side .env from the runtime vars in .env.deploy.
  local nas_env
  nas_env="$(mktemp)"
  cat > "$nas_env" <<EOF
AMADEUS_CLIENT_ID=${AMADEUS_CLIENT_ID:-}
AMADEUS_CLIENT_SECRET=${AMADEUS_CLIENT_SECRET:-}
AMADEUS_HOSTNAME=${AMADEUS_HOSTNAME:-test}
DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-}
DISCORD_GUILD_ID=${DISCORD_GUILD_ID:-}
DISCORD_NOTIFY_CHANNEL_ID=${DISCORD_NOTIFY_CHANNEL_ID:-}
DISCORD_RUN_INTERVAL_MINUTES=${DISCORD_RUN_INTERVAL_MINUTES:-60}
DISCORD_DEMO_MODE=${DISCORD_DEMO_MODE:-}
AUTOPOINTS_CPP_GREAT=${AUTOPOINTS_CPP_GREAT:-2.0}
AUTOPOINTS_CPP_GOOD=${AUTOPOINTS_CPP_GOOD:-1.5}
AUTOPOINTS_CACHE_PATH=/data/cache.db
EOF

  SCP "$ROOT/docker-compose.yml" "$ROOT/docker-compose.prod.yml" \
      "$NAS_USER@$NAS_HOST:$NAS_DEPLOY_DIR/"
  SCP "$nas_env" "$NAS_USER@$NAS_HOST:$NAS_DEPLOY_DIR/.env"
  SSH "chmod 600 '$NAS_DEPLOY_DIR/.env'"
  rm -f "$nas_env"
  ok "compose files + .env staged ($NAS_DEPLOY_DIR/)"

  if [ "${GHCR_PUBLIC:-true}" = "false" ]; then
    say "GHCR private login on NAS"
    SSH "echo '$GHCR_TOKEN' | docker login ghcr.io -u '$GHCR_USERNAME' --password-stdin" \
      | grep -q "Login Succeeded" \
      && ok "GHCR login ok" \
      || die "GHCR login failed on NAS"
  fi
}

# ---------- deploy via SSH (simpler than Portainer API for fresh installs) ----------

bring_up() {
  say "Pulling images on NAS"
  SSH "cd '$NAS_DEPLOY_DIR' && docker compose -f docker-compose.yml -f docker-compose.prod.yml pull"
  ok "images pulled"

  say "Starting stack"
  SSH "cd '$NAS_DEPLOY_DIR' && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
  ok "compose up -d issued"
}

tear_down() {
  say "Bringing stack down"
  SSH "cd '$NAS_DEPLOY_DIR' && docker compose -f docker-compose.yml -f docker-compose.prod.yml down ${1:-}" 2>&1 \
    | sed 's/^/    /'
}

verify() {
  say "Waiting for /api/health on http://$NAS_HOST:8000"
  for i in $(seq 1 30); do
    if curl -fs "http://$NAS_HOST:8000/api/health" >/dev/null 2>&1; then
      ok "web is up: $(curl -s http://$NAS_HOST:8000/api/health)"
      break
    fi
    sleep 1
  done
  if ! curl -fs "http://$NAS_HOST:8000/api/health" >/dev/null 2>&1; then
    err "/api/health never came up. Check 'docker logs autopoints-web' on the NAS."
    exit 2
  fi

  say "Sample search"
  local result
  result="$(curl -fsS -X POST "http://$NAS_HOST:8000/api/search" -H 'content-type: application/json' \
    -d '{"origin":"JFK","destination":"PHX","depart_date":"2026-06-15","demo":true}')"
  local n_rows
  n_rows="$(printf '%s' "$result" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["redemptions"]))')"
  ok "/api/search returned $n_rows redemption rows"

  if [ -n "${DISCORD_BOT_TOKEN:-}" ]; then
    say "Discord bot status"
    local logs
    logs="$(SSH "docker logs --tail 20 autopoints-discord 2>&1 | grep -E 'ready as|error' | tail -3" || true)"
    if echo "$logs" | grep -q "ready as"; then
      ok "discord bot connected: $(echo "$logs" | grep 'ready as')"
    else
      err "discord bot logs don't show 'ready as' yet — check 'docker logs autopoints-discord'"
    fi
  fi
}

case "$MODE" in
  deploy)
    stage
    bring_up
    verify
    echo
    printf "${GREEN}${BOLD}Deployed.${RESET}  ${BOLD}Web UI:${RESET} http://%s:8000\n" "$NAS_HOST"
    [ -n "${DISCORD_BOT_TOKEN:-}" ] && printf "${BOLD}Discord:${RESET} try /search in your server.\n"
    ;;
  redeploy)
    tear_down
    stage
    bring_up
    verify
    ;;
  nuke)
    printf "${RED}This will delete the autopoints-data volume — your watchlists go away.${RESET} Type YES to confirm: "
    read -r confirm
    [ "$confirm" = "YES" ] || { echo "aborted"; exit 1; }
    tear_down "-v"
    ok "stack + volume torn down"
    ;;
esac
