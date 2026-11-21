# Environment configuration
Local development uses ignored root .env, backend/.env and frontend/.env.local.
Staging and production templates are under infrastructure/. Use independent databases and secret stores. Inject backend configuration at runtime and public frontend URL at build time. Templates require approved hosting, DNS and TLS before use.
Client IPs (login and cart rate limits): the API uses the direct peer address. Uvicorn honours `X-Forwarded-For` only from `--forwarded-allow-ips` (env `FORWARDED_ALLOW_IPS`; default `127.0.0.1`; proxy headers are on by default). Behind a reverse proxy, set it to the proxy's own addresses, or every client shares the proxy's bucket; never set it to `*`, which lets clients choose their own address. On a dual-stack IPv6 listener (`--host ::`), IPv4 clients arrive as `::ffff:a.b.c.d` and are still limited per IPv4 address. Never trust forwarding headers from other sources.
Messages (full guide: [email.md](email.md), which emails exist, Gmail setup and switching providers): `NOTIFICATION_PROVIDER=smtp` sends real email through the `SMTP_*` settings (development and staging only; refused in production until ADR-005). It needs outbound access to the SMTP port, and order messages and password resets work by email only. With Gmail, use an app password on a dedicated account, keep it in the secret store and expect a daily sending limit. `scripts/retry_notifications.py` must still run on a schedule.

Temporary Gmail test route (owner approval 2026-11-01): the Render test deployment runs with `APP_ENV=production`, so `TEMPORARY_GMAIL_SMTP_ENABLED=true` lets that deployment send through Gmail for owner testing. **This is temporary: Resend is the planned replacement, and ADR-005 stays open.** It is off by default and needs `NOTIFICATION_PROVIDER=smtp`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`, `SMTP_USERNAME`, `SMTP_PASSWORD` (a Gmail app password, in the host's secret store only) and `SMTP_FROM_EMAIL`; the API refuses to start otherwise. It changes no other production safeguard, and the API logs a warning at every startup. Customers on the deployment receive real email.

**`TEMPORARY_GMAIL_SMTP_ENABLED` must be removed before final launch**, meaning before the store opens to real customers, or earlier if Resend is ready. It is not removed automatically. Remove it in this order, because `NOTIFICATION_PROVIDER=smtp` without this setting stops the API from starting:

1. Set `NOTIFICATION_PROVIDER` to `none`, or to the Resend provider once it exists.
2. Delete `TEMPORARY_GMAIL_SMTP_ENABLED` and the `SMTP_*` variables from the host.
3. Revoke the Gmail app password.
4. Restart, and confirm `Temporary Gmail SMTP is active` no longer appears in the startup logs.
5. Remove the setting and its validation from the code.
Migrations are an explicit reviewed release step with backup and rollback evidence. Never run production migrations from local setup.

## Client IP (ADR-006, 2026-11-13)

The API sees the storefront's server and Render's load balancer, never the shopper. The storefront signs the shopper's address (from Vercel's own headers) on every API call, and the API accepts it only with a valid, fresh signature.

- Render (API): `CLIENT_IP_SOURCE=signed`, `CLIENT_IP_SIGNING_SECRET` (32+ random characters), `CLIENT_IP_SIGNING_SECRET_NEXT` only during a rotation. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers` (never `--forwarded-allow-ips`).
- Vercel (storefront, server-only, never `NEXT_PUBLIC_`): `CLIENT_IP_SOURCE=vercel`, `CLIENT_IP_SIGNING_SECRET` equal to the API's current or next secret. Use a different secret for Preview and Production, each matching the API that environment calls.
- Generate a secret: `python -c "import secrets;print(secrets.token_urlsafe(48))"`. Keep it only in the hosts' secret stores.
- Rotation: 1) set the new secret as the API's `CLIENT_IP_SIGNING_SECRET_NEXT` and redeploy; 2) set it as the storefront's `CLIENT_IP_SIGNING_SECRET` and redeploy; 3) make it the API's `CLIENT_IP_SIGNING_SECRET`, clear `_NEXT`, redeploy.
- Check after deploying: sign in on the storefront and confirm the new session's or audit record's address is your own, not a Vercel or Render address. A refused signature is logged as `Client IP signature refused (<reason>)`.
- Local development needs none of this: the storefront adds nothing and the API uses its transport peer.
