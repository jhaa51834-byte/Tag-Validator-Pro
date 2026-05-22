# Tag Validator Pro — App Overview (Simple English)

## 1. What this app does

You give it a list of websites (an Excel file). It opens each website like a
real browser, watches every network request, and tells you:

- Which **analytics tags** are installed — Tealium, Adobe Analytics, GTM, GA4.
- Which **marketing pixels** fire — Meta/Facebook, Google Ads, Floodlight,
  LinkedIn, TikTok, X, Pinterest, Snap, Bing, Criteo, Reddit, Quora, Taboola,
  Outbrain, Amazon, Yahoo.
- For each pixel: its **ID**, how many times it **fired**, and the **source**
  that fired it (Tealium / Adobe / GTM / hardcoded on the site).
- It does this under **5 consent scenarios** (Accept All, Reject All,
  Performance, Functional, Targeting) so you can check the site respects cookie
  consent.
- It can **run on a schedule** and **email** a pass/fail report automatically.

It is a privacy & analytics QA tool for marketing/data teams.

---

## 2. The technology stack and why

| Layer | Technology | Why this one |
|------|------------|--------------|
| Browser automation | **Python + Playwright** | Playwright drives a real Chromium browser. Tracking pixels only fire in a real browser with real JavaScript — a simple HTTP request would miss them. Playwright also exposes the **CDP (Chrome DevTools Protocol)**, which lets us see *who* triggered each request (the initiator), which is how we tell if a pixel came from GTM, Tealium, Adobe, or was hardcoded. |
| Stealth | **playwright-stealth** | Many sites block obvious bots. This makes the automated browser look like a normal user so pixels behave normally. |
| Consent simulation | **OneTrust `OptanonConsent` cookie injection** | OneTrust is the most common cookie banner. Instead of clicking buttons (slow, unreliable), we set the consent cookie directly to force each scenario (Accept All, Reject All, etc.). For other banners we fall back to clicking accept/reject. |
| Data handling | **pandas + openpyxl** | Reads the input Excel list of URLs and writes the results back to an Excel report. Industry-standard, reliable Excel handling in Python. |
| Web server / API | **Node.js + Express** | Serves the web UI and the REST API (upload file, start run, get results, download report, manage schedules, email settings). Express is lightweight and the most common Node web framework. |
| Run the Python from Node | **child_process.spawn** | The browser work is in Python; the server is in Node. Node launches the Python script as a sub-process and streams its progress logs live to the UI. |
| Excel read/write (server) | **xlsx** (SheetJS) | Lets the Node server read the result Excel to build the email failure summary and serve the download. |
| Scheduling | **node-cron** | Runs validations automatically on a schedule (hourly / daily / weekly / monthly). Standard cron syntax, simple and dependable. |
| Email alerts | **Brevo HTTP API** | Sends the report by email after each scheduled run. Uses Brevo's transactional email API over HTTPS:443, so it works on hosts (e.g. Hugging Face Spaces) that block outbound SMTP ports 465/587. |
| Unique IDs | **uuid** | Gives each saved schedule a unique ID. |
| Frontend | **Plain HTML + CSS + vanilla JavaScript** | No framework. The UI is small (tables, tabs, forms), so plain JS keeps it fast, dependency-free, and easy to maintain — nothing to build or compile. |
| Packaging | **Docker** | Bundles Node, Python, Chromium and all dependencies into one image so it runs the same everywhere. |
| Hosting | **Hugging Face Spaces** (Docker) | Free Docker hosting; the `README.md` front-matter configures the Space. |

---

## 3. How it works (flow)

```
User uploads Excel of URLs ──► Node/Express saves it
        │
        ▼
User clicks Run ──► Node spawns Python (bulk_tag_validator.py)
        │
        ▼
Python (Playwright) opens each site, for EACH of 5 consent scenarios:
   • injects the consent cookie
   • loads the page in headless Chromium
   • records every network request + its initiator (via CDP)
   • detects tags & marketing pixels, extracts pixel IDs
   • traces the initiator chain to find the true source
        │
        ▼
Python writes:  validation_results.xlsx  (table)
                validation_results.json  (rich per-scenario data)
        │
        ▼
UI polls status, then shows results in tabs:
   Tealium | GA4/Adobe | Marketing Pixels (with scenario sub-tabs)
        │
        ▼
(Optional) A schedule runs the same flow on a timer and
the Brevo API emails the report + failed-site list.
```

---

## 4. Why split Python + Node?

- **Python** has the best, most reliable browser-automation + CDP tooling
  (Playwright) and the best Excel/data libraries (pandas). The hard part —
  accurately detecting pixels and their source — lives here.
- **Node/Express** is the best fit for a lightweight web server, live log
  streaming, scheduling, and email.
- Each language is used for what it is strongest at; Node simply runs the
  Python script when needed. This keeps each part simple and replaceable.

---

## 5. Key files

| File | Role |
|------|------|
| `bulk_tag_validator.py` | The engine — Playwright automation, scenario simulation, tag/pixel detection, source attribution, Excel/JSON output. |
| `server.js` | Express server — API, file upload, run control, results, scheduling, email alerts, Gmail config. |
| `public/index.html` | The web UI (layout + styling). |
| `public/app.js` | UI logic — uploads, progress, rendering tables, scenario tabs, schedule & email forms. |
| `Dockerfile` | Builds the all-in-one container (Node + Python + Chromium). |
| `requirements.txt` / `package.json` | Python / Node dependencies. |

---

## 6. Features summary

- Bulk validation of many sites from one Excel file.
- 3 audit views: **Tealium+Adobe**, **GTM+GA4**, **Marketing Pixels**.
- Marketing Pixels checked under **5 consent scenarios** (separate tab per
  scenario) with **Pixel ID**, **fire count**, and **source**.
- **Compliance** flag — fails if pixels fire after *Reject All*.
- Live progress log and downloadable Excel report.
- **Automated schedules** with **email alerts** (Gmail), configurable inside
  the app (no server env vars needed).
