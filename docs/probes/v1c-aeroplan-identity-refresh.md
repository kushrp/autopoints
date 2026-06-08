# Aeroplan Cognito identity — auto-mint pattern (no manual refresh)

**Status:** historical-document / runbook obsolete. The manual DevTools
refresh that used to live here is no longer needed. As of v1.c-2,
`autopoints/providers/aeroplan.py` mints a fresh IdentityId on every
search via `AWSCognitoIdentityService.GetId`. There is no static
IdentityId to rotate.

## How it works now

Air Canada's web client hardcodes the **IdentityPoolId**
`us-east-2:4a7f6b48-a8ab-499b-9e7f-31e79b54638e` in their main.js bundle.
The pool allows unauthenticated identities, so anyone can mint a fresh
disposable IdentityId with one unauthenticated POST:

```bash
curl -s 'https://cognito-identity.us-east-2.amazonaws.com/' \
  -H 'Content-Type: application/x-amz-json-1.1' \
  -H 'X-Amz-Target: AWSCognitoIdentityService.GetId' \
  --data-raw '{"IdentityPoolId":"us-east-2:4a7f6b48-a8ab-499b-9e7f-31e79b54638e"}'
```

The provider does this in `_get_cognito_identity_id()`, captures the
returned `IdentityId`, then calls `GetCredentialsForIdentity` with that
ephemeral ID. The pool ID is the stable thing; the IdentityId is
disposable.

## What this means operationally

- **No manual refresh.** Old runbook is dead.
- **Pool ID is safe to commit.** It's public in main.js.
- **If the live-checks harness reports 403 from Cognito**, the pool
  itself has changed (Air Canada deployed a new bundle). Re-discover the
  current pool ID via Chrome DevTools on aircanada.com — same Network
  filter `cognito`, but copy the value of `IdentityPoolId` (in the GetId
  request body), not `IdentityId` (in the response).

## Recovering the pool ID if it rotates

The procedure mirrors the old identity-refresh flow, but you copy the
**pool ID** field instead:

1. Open an incognito Chrome window, DevTools → Network, filter `cognito`.
2. Navigate to https://www.aircanada.com/, start an award flight search.
3. Find the POST to `cognito-identity.us-east-2.amazonaws.com/` with
   `X-Amz-Target: AWSCognitoIdentityService.GetId`.
4. Copy the `IdentityPoolId` value from the request payload.
5. Update `_COGNITO_IDENTITY_POOL_ID` in
   `autopoints/providers/aeroplan.py` and commit.

This only happens if Air Canada deploys a new web client bundle with a
new pool — much rarer than a per-identity revocation.
