# Transactional email

Status (2026-11-02): emails are sent through Gmail SMTP for development and owner testing. The design does not depend on Gmail, so a production provider (Resend, Brevo or Amazon SES) can replace it. ADR-005, the provider decision, is still open.

## Which emails exist

Every message is recorded in the same database transaction as the business change it reports, in the `notification_logs` outbox, and is sent after that transaction commits. If an email fails, the order, payment, registration or review it belongs to is **never** rolled back.

| Email | Sent when | To | Button |
| --- | --- | --- | --- |
| Order received (items, discount, delivery, total, payment method, address) | checkout creates the order | the customer | signed in: `/account/orders/{number}`; guest: `/track?order={number}` |
| New order alert (as above, plus the customer's contact details) | checkout creates the order | every address in `STAFF_ORDER_ALERT_EMAILS` | `/admin/orders/{id}` |
| Payment received | a mobile-money success is verified; cash on delivery is recorded as paid (on delivery, or confirmed by staff) | the customer | order page |
| Order confirmed / on its way / delivered / cancelled | staff change the status; an unpaid order times out; a late payment cancels the order | the customer | order page |
| Email verification link | registration with an email; a resend (ADR-006 amendment 2026-11-12) | the address registered | `/verify-email#token=…` (expires in `EMAIL_VERIFICATION_TTL_HOURS`) |
| Welcome | the email is verified; phone-only registration has no email and gets none | the new customer | `/products` |
| Quote request received | a Contact page quote request with an email | the buyer | `/products` (or `/rw/products` for Kinyarwanda) |
| Review thank-you | a review is submitted | the email the order was placed with | the product page |
| Password reset code | a reset is requested | the account's email (or SMS) | none |

The verification link and the reset code are **not** in the outbox: they hold a secret, so they are sent once, after the commit, straight through the provider, and are never stored or logged. A failed delivery is logged by error type only; the customer asks for a new link (`POST /api/v1/auth/email/verification/resend`). They need a provider that reaches people (`console` in development, `smtp`) and, for the link, `SITE_URL`; without them registration with an email and resend answer 503 `email_verification_unavailable`.

Customer order emails follow §7 Q22: with an SMS-capable provider, the customer receives a one-line SMS, otherwise an email. `NOTIFICATION_PROVIDER=smtp` can only send email, so it emails the address on the order. An order without an email address gets no message.

### Pending integrations (templates only)

These templates exist in `backend/app/services/email_templates.py` and are tested. Nothing sends them yet, because the business workflow behind them does not exist. No event was invented for them.

- **Refund acknowledgement**: no workflow records a refund. The `refunded` and `partially_refunded` payment statuses exist but are never set. To build it: record the message when a refund is recorded, in the same transaction.

## Content and links

- Each email is HTML with a plain-text alternative (`multipart/alternative`). The layout uses tables and inline styles, so it works in email clients and reads as one column on a phone.
- Content is rendered when the email is sent, from the current record. No message text is stored. Password reset codes and verification tokens are never stored or logged.
- Every value is HTML-escaped.
- Buttons and links use `SITE_URL`, the storefront origin. When it is not set, emails have no buttons or links, rather than pointing at a wrong host.

## Delivery, retries and duplicates

- After the HTTP response, a background task sends the emails that request recorded.
- `scripts/retry_notifications.py` (cron) sends anything still due.
- Each email gets at most 3 attempts: the second 5 minutes after the first, the third 30 minutes after that.
- A permanent refusal, such as an invalid recipient, ends the retries at once.
- Only a short error code is stored, never provider text.
- `dedupe_key` is unique per event, subject and recipient. A replayed checkout or a repeated event records nothing new.
- Staff can see every message, with masked recipients, at `GET /api/v1/staff/notifications`, and retry it with `POST /api/v1/staff/notifications/{id}/retry`.

## Configure Gmail SMTP

1. Use a dedicated Gmail account. Turn on 2-Step Verification, then create an **app password** (Google Account → Security → App passwords). Never use the account password.
2. Put these settings in `backend/.env` (git-ignored) or in the host's secret store, **never in committed files**:

   ```
   NOTIFICATION_PROVIDER=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USE_TLS=true
   SMTP_USERNAME=the.account@gmail.com
   SMTP_PASSWORD=<16-character app password>
   SMTP_FROM_EMAIL=the.account@gmail.com
   SMTP_FROM_NAME=3 Sixty Technologies
   SITE_URL=http://localhost:3000
   EMAIL_ALLOWED_RECIPIENTS=you@example.com,teammate@example.com
   STAFF_ORDER_ALERT_EMAILS=you@example.com
   ```

3. `SMTP_FROM_NAME` (optional, one line, at most 64 characters) is the sender name inboxes show, as in `3 Sixty Technologies <the.account@gmail.com>`. A bare address looks less trustworthy to spam filters.
4. `SMTP_USE_TLS=true` is required with credentials. The connection uses STARTTLS with a verified certificate and never falls back to plain text.
5. **Development safety:** with `APP_ENV=development` and `NOTIFICATION_PROVIDER=smtp`, the API refuses to start unless `EMAIL_ALLOWED_RECIPIENTS` is set. Email to any other address is recorded as `failed` with `recipient_not_allowed` and is never handed to Gmail. A seeded database full of `@seed.3sixty.local` customers therefore cannot email anyone by mistake.
6. Gmail limits daily sending (about 500 messages a day for a personal account). It is for testing, not for launch.

On the Render test deployment (`APP_ENV=production`), Gmail also needs `TEMPORARY_GMAIL_SMTP_ENABLED=true` (see [README.md](README.md)). There:

- Leave `EMAIL_ALLOWED_RECIPIENTS` empty if real customers must receive email; set it to restrict sending.
- Set `SITE_URL` to the public `https://` storefront.

## Switch to a production provider

Providers implement `NotificationProvider` in `backend/app/integrations/notifications/__init__.py`: `send(OutboundMessage) -> message id`, where the message carries `subject`, `text`, `html` and `idempotency_key`. To add Resend, Brevo or SES:

1. Add a provider class that sends `text` and `html` through the provider's API with a timeout, sends `idempotency_key` as the provider's idempotency key (then set `idempotent_delivery = True`), and maps failures to `DeliveryError` codes (`retryable=False` for permanent refusals). It must never put the recipient, the message or credentials in an error.
2. Add its name to `NOTIFICATION_PROVIDER`, its settings to `app/core/config.py` (secrets as `SecretStr`), and a case in `get_notification_provider`.
3. Set the new provider on the host, then remove the Gmail route as [README.md](README.md) describes.

Templates, events, the outbox, retries and the allowlist stay as they are.

## Tests

Automated tests never send email:

- `tests/conftest.py` forces `NOTIFICATION_PROVIDER=none` and clears the email settings.
- Email tests replace the provider with the capture double in `tests/support/messages.py`, which keeps every message, HTML included.
- The SMTP provider is tested against a local fake server (`tests/support/fake_smtp.py`).

Relevant test files:

- `tests/unit/test_email_templates.py`: content, totals, links and escaping.
- `tests/integration/test_transactional_emails.py`: events, duplicates, the allowlist and failures.
- `tests/integration/test_notification_outbox_migration.py`: the migration.
- `tests/unit/test_smtp_provider.py`: SMTP and settings.
