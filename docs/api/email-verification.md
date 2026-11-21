# Email verification (API contract)

Backend only, implemented 2026-11-12 (ADR-006 amendment "email verification of new customer accounts"). The storefront pages it needs are **not** built yet; see "Frontend integration" below.

Every error uses the API's usual body: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Who has to verify

| Account | Verification |
| --- | --- |
| Customer registering with an email (with or without a phone) | Required before password login. Created unverified, no session. |
| Customer registering with a phone only | None (no email to verify). Signed in at registration, as before. |
| Account that existed before migration `e6b1d4a8c2f7` | Already verified (marked at its creation time). |
| Customer created by Continue with Google | Verified at creation (Google's `email_verified` claim is required). |
| Staff | Never asked to verify. Staff sign-in is unchanged. |

## `POST /api/v1/auth/register`

Request: unchanged (`email` and/or `phone`, `full_name`, `password`).

**201** response (`RegisterResponse`):

```json
{
  "user": { "id": "…", "email": "aline@example.com", "phone": null, "full_name": "Aline Uwase",
            "is_active": true, "is_staff": false, "roles": ["customer"], "created_at": "…" },
  "session_token": null,
  "token_type": null,
  "expires_at": null,
  "verification_required": true
}
```

- With an email address, `verification_required` is `true` and the three session fields are `null`. A verification link is emailed after the response.
- With a phone only, `verification_required` is `false`, and `session_token`, `token_type: "bearer"` and `expires_at` are set as before.

| Status | Code | When |
| --- | --- | --- |
| 409 | `email_taken` / `phone_taken` | Unchanged. |
| 422 | `validation_error` | Unchanged. |
| 503 | `email_verification_unavailable` | An email was given but no email can be delivered (`NOTIFICATION_PROVIDER` is `none` or `mock`, or `SITE_URL` is unset). Nothing is created. |

## `POST /api/v1/auth/email/verify`

Request (`VerifyEmailRequest`; extra fields refused):

```json
{ "token": "the value after #token= in the link" }
```

**200**: `{"message": "Your email address is verified. You can now sign in."}`

- The token is used once. The account's email becomes verified, the account's other links are revoked, and the welcome email is sent.
- It does **not** sign in: the customer signs in with their password afterwards.

| Status | Code | When |
| --- | --- | --- |
| 422 | `verification_token_invalid` | Unknown or malformed token, a link superseded by a newer one, or the account's address has changed. |
| 422 | `verification_token_expired` | Older than `EMAIL_VERIFICATION_TTL_HOURS` (24). |
| 422 | `verification_token_used` | Already used, including by a concurrent request. |
| 422 | `validation_error` | Missing or empty `token`, wrong type, or extra fields. |
| 429 | `rate_limited` | More than 30 failed attempts from one client network in 15 minutes. `Retry-After` gives the seconds to wait. |
| 503 | `login_unavailable` | The rate-limit store (Redis) is down (fails closed). |

## `POST /api/v1/auth/email/verification/resend`

Request (`ResendVerificationRequest`; extra fields refused):

```json
{ "email": "aline@example.com" }
```

**202**, always the same: `{"message": "If an account with this email address is waiting for verification, a new link has been sent."}`

- A new link is sent only when the address belongs to an active, unverified customer and the last link is older than the cooldown. The new link revokes the older ones.
- The reply is identical when the address is unknown, already verified, staff, inactive, or still cooling down.

| Status | Code | When |
| --- | --- | --- |
| 422 | `validation_error` | Not an email address, or extra fields. |
| 429 | `rate_limited` | More than 5 requests for one address, or 20 from one IP, in an hour. Every request counts, whether or not an account exists. `Retry-After` gives the seconds to wait. |
| 503 | `email_verification_unavailable` | No email can be delivered. Checked before any lookup, so it reveals nothing about accounts. |
| 503 | `login_unavailable` | The rate-limit store is down. |

## `POST /api/v1/auth/login` (changed)

A customer whose email is not verified gets **403 `email_not_verified`**, whether they sign in by email or by phone.

- This is checked only after the password is correct. A wrong password still gives 401 `invalid_credentials`, so someone without the password learns nothing.
- It does not count as a failed attempt.
- No session is created.

## The email

- **From:** the configured provider. **Subject:** "Confirm your email address for 3 Sixty Technologies".
- **Content:** it explains that the address was used to register and that the link expires in 24 hours, with the button "Confirm my email". It contains no password or other account detail.
- **Link:** `SITE_URL/verify-email#token=<token>`. The token is in the URL fragment, which browsers never send to servers or in the `Referer` header.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NOTIFICATION_PROVIDER` | `none` | Must be `console` (development only; prints the email, link included, to the API's terminal) or `smtp` for verification to work. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_TIMEOUT_SECONDS` | — | The existing SMTP settings (`docs/deployment/email.md`). |
| `SITE_URL` | unset | The storefront origin for the link (https outside development). Required. |
| `EMAIL_ALLOWED_RECIPIENTS` | empty | When set, only those addresses receive email (development testing). Other addresses get no link and stay unverified. |
| `EMAIL_VERIFICATION_TTL_HOURS` | 24 | Link lifetime (1–168). |
| `EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` | 60 | Minimum time between links for one account. |
| `EMAIL_VERIFICATION_RESEND_MAX_PER_EMAIL` / `_MAX_PER_IP` / `_WINDOW_SECONDS` | 5 / 20 / 3600 | Resend limits. |
| `EMAIL_VERIFICATION_MAX_FAILURES_PER_IP` / `_FAILURE_WINDOW_SECONDS` | 30 / 900 | Failed verification attempts per client network. |

Delivery to a real inbox has **not** been verified: the tests use a recording sender, and the live-stack tests use the console provider. Real email needs `NOTIFICATION_PROVIDER=smtp` with SMTP credentials and `SITE_URL`.

## Frontend integration (not implemented)

1. **Registration.**
   - When `verification_required` is `true`, show a "check your email" screen, with the address, and offer resend. Don't treat it as signed in.
   - Today the BFF `/api/auth/register` only sets the session cookie when `session_token` is present, so it already sets nothing. The page must stop redirecting into the account area in that case.
   - Handle 503 `email_verification_unavailable`.
2. **The `/verify-email` page** (both locales; the email links to the English path).
   - Read the token from `location.hash`, then remove it from the URL with `history.replaceState`.
   - POST it to `/api/v1/auth/email/verify`. It is a public endpoint, and the general proxy may forward it.
   - Show success with a "Sign in" link, or the invalid, expired or used state with a resend form.
   - Don't send the token in a query string, log it, or store it.
3. **Login.** On 403 `email_not_verified`, explain it and offer resend for the address typed. Don't retry the login automatically.
4. **Resend form.** POST `{"email"}` to `/api/v1/auth/email/verification/resend` and always show the generic message. On 429, show the wait from `Retry-After`.
5. **Guest checkout "create account"** and the e2e tests that register with an email need the same changes.
