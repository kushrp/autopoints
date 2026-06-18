# 1Password Connect on the NAS + Browserbase setup

autopoints' authenticated-session path (v2.a) needs two things: a way to read
credentials/TOTP from 1Password, and Browserbase to drive the one-time logins.
On a laptop the local `op` CLI is enough. On the always-on NAS there is no
interactive `op signin`, so 1Password Connect is required. The code auto-detects
which one is present (`autopoints.auth.op_client.make_backend`).

Run the preflight check first:

```sh
python -c "from autopoints.auth.preflight import preflight; print(preflight().report())"
```

## Laptop (fastest path to the first login + the probe)

1. Install the 1Password CLI and sign in: `op signin`.
2. Create one login item per program, e.g. titled `aeroplan`, with `username`,
   `password`, and (if the account has it) a one-time-password/TOTP field.
3. Set Browserbase env vars in your shell:
   ```sh
   export BROWSERBASE_API_KEY="..."
   export BROWSERBASE_PROJECT_ID="..."
   ```
4. Re-run the preflight check; expect all three OK.

## NAS (always-on)

1. Install 1Password Connect (Docker) and create a Connect token scoped to the
   `autopoints` vault. See 1Password's Connect docs.
2. Set on the NAS:
   ```sh
   export OP_CONNECT_HOST="http://localhost:8080"   # your Connect server
   export OP_CONNECT_TOKEN="..."                      # Connect access token
   export OP_VAULT="autopoints"                        # vault holding the items
   export BROWSERBASE_API_KEY="..."
   export BROWSERBASE_PROJECT_ID="..."
   ```
3. The `ConnectBackend` REST calls are provisional — validate a `read_note` /
   `write_note` round-trip against the live Connect server before trusting the
   daemon's session refresh.

## What the session items look like

- Credentials: one login item per program (title = program slug, lowercase).
- Session blob: a secure note titled `autopoints:session:<program>`, written by
  the login flow. Body is JSON; treat as sensitive (never logged un-redacted).
- Freeze state (R7 auto-freeze) persists in a separate item so it survives
  restarts — wired with the provider in the next increment.
