---
title: Tag Validator Pro
emoji: 🏷️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: true
---

# Tag Validator Pro

Bulk website tag validation tool with Omnibug-level CDP network interception.

Detects: **Tealium, Adobe Analytics, GTM, GA4** — including POST-based beacons and sendBeacon calls.

## Marketing Pixels — 4 consent scenarios + source

The **Marketing Pixels** mode loads every site under 4 OneTrust consent states —
**Necessary, Performance, Functional, Targeting** — injected via the
`OptanonConsent` cookie (banner accept/reject fallback for other CMPs). Click a
scenario tab to switch. For each pixel it shows the **fire count** and the
**source** that fired it (Tealium / Adobe / GTM / Hardcoded), attributed from the
JS request initiator stack via CDP. Compliance FAILs if any marketing pixel fires
under the Necessary (no-consent) scenario.

## Scheduling email alerts

When creating an automated schedule you can set an **alert email**. After every
scheduled run a summary + the list of failed websites is emailed with the full
Excel report attached. Email uses Gmail SMTP — set on the server:

```
GMAIL_USER=youraddress@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
```

(Generate an App Password: Google Account → Security → 2-Step Verification → App
passwords. A normal Gmail password will not work.) Without these the run still
completes; only the email is skipped. Use **Send Test Email** to verify setup.
