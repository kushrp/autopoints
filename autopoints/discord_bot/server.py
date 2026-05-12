from __future__ import annotations

import os
import sys


def run() -> None:
    """Boot the Discord bot. Reads config from env vars:
      DISCORD_BOT_TOKEN          required
      DISCORD_GUILD_ID           optional; faster command-sync within one server
      DISCORD_NOTIFY_CHANNEL_ID  optional; if set with DISCORD_RUN_INTERVAL_MINUTES,
                                 starts a background loop posting new hits here
      DISCORD_RUN_INTERVAL_MINUTES   optional; minutes between watchlist re-runs
      DISCORD_DEMO_MODE          optional; "1" forces all searches into demo mode
    """
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(
            "error: DISCORD_BOT_TOKEN not set. Create a bot at "
            "https://discord.com/developers/applications, get its token, then "
            "export DISCORD_BOT_TOKEN=...",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from autopoints.discord_bot.bot import make_bot
    except ImportError as e:
        print(f"error: discord.py not installed. Run `uv pip install -e \".[discord]\"`\n{e}", file=sys.stderr)
        sys.exit(1)

    guild_id = _maybe_int("DISCORD_GUILD_ID")
    channel_id = _maybe_int("DISCORD_NOTIFY_CHANNEL_ID")
    interval = _maybe_int("DISCORD_RUN_INTERVAL_MINUTES")
    demo = os.getenv("DISCORD_DEMO_MODE") == "1"

    bot = make_bot(
        guild_id=guild_id,
        notify_channel_id=channel_id,
        run_interval_minutes=interval,
        demo_mode=demo,
    )
    bot.run(token)


def _maybe_int(name: str) -> int | None:
    val = os.getenv(name)
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


if __name__ == "__main__":
    run()
