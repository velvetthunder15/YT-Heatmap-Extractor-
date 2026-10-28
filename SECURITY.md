# Security

## How your API key is protected

- **Dashboard** (heatmapify.onrender.com / heatmapify.netlify.app) is a static page with no backend. The key is sent only as an `X-API-Key` header, only to the API URL you entered, and only over https (plain http is refused except for `localhost`).
- The key is kept in the browser only: `sessionStorage` by default (gone when the tab closes), `localStorage` only if you tick *Remember on this device*. *Forget key* wipes both. The field isn't a password input, so password managers don't capture it.
- A link with someone else's `?api=` never receives your saved key.
- Strict Content-Security-Policy (no inline or third-party scripts), `frame-ancestors 'none'`, `no-referrer`. Results from the server are validated before rendering.
- **Server**: keys are stored only as `HMAC-SHA256(API_KEY_PEPPER, key)`; per-key rate limits and daily quotas; CORS limited to the dashboards and localhost (`CORS_ORIGINS`); responses are `Cache-Control: no-store`; the key is never logged.

## If a key leaks

Run `rotate-key.bat` (Windows) or `rotate-key.command` (macOS), restart the server, and paste the new key into the dashboard. The old key stops working.

## Reporting a vulnerability

Please open a private report via GitHub's **Security → Report a vulnerability** on this repository rather than a public issue.
