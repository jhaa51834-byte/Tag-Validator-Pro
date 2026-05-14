import warnings
warnings.filterwarnings("ignore")
import asyncio
import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import os
import time
import re
import sys
import json
from urllib.parse import unquote, parse_qs, urlparse

stealth_obj = Stealth()
CONCURRENCY = 8

COOKIE_SELECTORS = [
    '#onetrust-accept-btn-handler',
    '#accept-recommended-btn-handler',
    'button[title="Accept All"]',
    'button[title="Accept"]',
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    '#CybotCookiebotDialogBodyButtonAccept',
    '#truste-consent-button',
    '#didomi-notice-agree-button',
    '.cc-accept', '.cc-btn.cc-allow',
    '#cookie-accept', '#accept-cookies',
    '[data-action="accept"]',
    'button[aria-label="Accept all cookies"]',
    'button[aria-label="Accept cookies"]',
    'button[aria-label="accept and close"]',
]

COOKIE_TEXT_PATTERNS = [
    "Accept All", "Accept all", "ACCEPT ALL",
    "Accept Cookies", "Accept cookies",
    "Allow All", "Allow all",
    "I Accept", "I agree",
    "Agree", "OK", "Got it",
    "Accept & Close", "Accept and close",
    "Consent", "Continue",
]


async def accept_cookies(page):
    """Try to accept cookie consent banners."""
    for sel in COOKIE_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=200):
                await el.click(timeout=2000)
                return True
        except:
            pass
    for text in COOKIE_TEXT_PATTERNS:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=2000)
                return True
        except:
            pass
    # JS fallback — click any visible accept/agree button
    try:
        clicked = await page.evaluate("""
            () => {
                const kw = ['accept', 'agree', 'allow', 'consent', 'got it', 'ok'];
                const btns = [...document.querySelectorAll('button, a[role="button"], [role="button"]')];
                for (const b of btns) {
                    const t = (b.innerText||'').toLowerCase().trim();
                    if (b.offsetParent && t.length < 30 && kw.some(k => t.includes(k))) {
                        b.click(); return true;
                    }
                }
                return false;
            }
        """)
        if clicked:
            return True
    except:
        pass
    return False


def parse_analytics_payload(url, post_data=""):
    """Omnibug-style: parse both URL params and POST body for analytics data."""
    combined = url
    if post_data:
        combined = url + "&" + post_data if "?" in url else url + "?" + post_data

    low = combined.lower()
    result = {
        "is_adobe": False, "adobe_pv": False, "adobe_rsid": "",
        "is_ga4": False, "ga4_pv": False, "ga4_mid": "",
        "is_gtm": False, "gtm_id": "",
        "is_tealium_js": False, "tealium_account": "", "tealium_profile": "", "tealium_env": "",
        "is_tealium_collect": False,
    }

    # --- ADOBE ANALYTICS ---
    # /b/ss/ is the definitive Adobe beacon path
    if "/b/ss/" in low:
        result["is_adobe"] = True
        m = re.search(r'/b/ss/([^/]+)/', url)
        if m:
            result["adobe_rsid"] = m.group(1)
        # PageView = NO 'pe=' parameter (link tracking has pe=lnk_o or pe=lnk_e)
        if "pe=" not in low:
            result["adobe_pv"] = True

    # Adobe library / domain indicators
    if any(x in low for x in [".omtrdc.net", ".2o7.net", "appmeasurement", "s_code", "satellite-", "launch-"]):
        result["is_adobe"] = True

    # Adobe POST-based collection (some sites use /ee/or/v1 or /interact endpoints)
    if any(x in low for x in ["adobedc.net", "adobedc.demdex", "/ee/v", "/interact"]):
        result["is_adobe"] = True
        # Adobe Web SDK (alloy) sends page view via interact endpoint
        if post_data:
            try:
                body = json.loads(post_data)
                events = body.get("events", [])
                for ev in events:
                    xdm = ev.get("xdm", {})
                    if xdm.get("eventType") == "web.webpagedetails.pageViews":
                        result["adobe_pv"] = True
                    web = xdm.get("web", {})
                    if web.get("webPageDetails", {}).get("pageViews", {}).get("value"):
                        result["adobe_pv"] = True
            except:
                pass

    # --- TEALIUM ---
    if "tiqcdn.com" in low and "utag" in low:
        result["is_tealium_js"] = True
        m = re.search(r'tiqcdn\.com/utag/([^/]+)/([^/]+)/([^/]+)/', url, re.I)
        if m:
            result["tealium_account"] = m.group(1)
            result["tealium_profile"] = m.group(2)
            result["tealium_env"] = m.group(3)

    if any(x in low for x in ["tealiumiq.com", "tealium.com/collect", "tealium"]) and any(x in low for x in ["collect", "v.gif", "/event", "/i.gif"]):
        result["is_tealium_collect"] = True

    # --- GTM ---
    if "googletagmanager.com/gtm.js" in low:
        result["is_gtm"] = True
        m = re.search(r'[?&]id=(GTM-[A-Z0-9]+)', url, re.I)
        if m:
            result["gtm_id"] = m.group(1).upper()

    # --- GA4 ---
    # gtag.js load
    if "googletagmanager.com/gtag/js" in low:
        m = re.search(r'[?&]id=(G-[A-Z0-9]+)', url, re.I)
        if m:
            result["ga4_mid"] = m.group(1).upper()
            result["is_ga4"] = True

    # GA4 collect beacon (GET or POST)
    if "/g/collect" in low or (("google-analytics.com" in low or "analytics.google.com" in low) and "collect" in low):
        result["is_ga4"] = True
        m = re.search(r'[?&]tid=(G-[A-Z0-9]+)', combined, re.I)
        if m:
            result["ga4_mid"] = m.group(1).upper()
        # Check for page_view in URL params OR POST body
        if "en=page_view" in low:
            result["ga4_pv"] = True

    # GA4 POST body can have events encoded differently
    if result["is_ga4"] and post_data and not result["ga4_pv"]:
        if "page_view" in post_data.lower():
            result["ga4_pv"] = True

    return result


async def validate_tags(browser, url, index, total):
    results = {
        "URL": url,
        "Tealium_Loaded": "FAIL", "Tealium_Account": "", "Tealium_Profile": "",
        "Tealium_Env": "",
        "GTM_Loaded": "FAIL", "GTM_ID": "",
        "GA4_Fired": "FAIL", "GA4_Measurement_ID": "", "GA4_PageView": "FAIL",
        "Adobe_Loaded": "FAIL", "Adobe_ReportSuite": "", "Adobe_PageView": "FAIL",
        "Error": ""
    }

    # Tracking state
    gtm_ids = set()
    ga4_ids = set()
    tealium_accounts = []
    adobe_rsids = set()
    flags = {
        "tealium_js": False, "tealium_collect": False,
        "gtm": False, "ga4": False, "ga4_pv": False,
        "adobe": False, "adobe_pv": False
    }

    # Store all CDP request data for POST body inspection
    cdp_requests = {}  # requestId -> {url, postData}

    context = None
    try:
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_obj.apply_stealth_async(page)

        # ===== CDP SESSION for POST body interception (Omnibug approach) =====
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")

        def on_cdp_request(params):
            req_id = params.get("requestId", "")
            req = params.get("request", {})
            req_url = req.get("url", "")
            post_data = req.get("postData", "")

            cdp_requests[req_id] = {"url": req_url, "postData": post_data}

            parsed = parse_analytics_payload(req_url, post_data)

            if parsed["is_adobe"]:
                flags["adobe"] = True
            if parsed["adobe_pv"]:
                flags["adobe_pv"] = True
            if parsed["adobe_rsid"]:
                adobe_rsids.add(parsed["adobe_rsid"])

            if parsed["is_tealium_js"]:
                flags["tealium_js"] = True
                if parsed["tealium_account"]:
                    tealium_accounts.append({
                        "account": parsed["tealium_account"],
                        "profile": parsed["tealium_profile"],
                        "env": parsed["tealium_env"]
                    })
            if parsed["is_tealium_collect"]:
                flags["tealium_collect"] = True

            if parsed["is_gtm"]:
                flags["gtm"] = True
                if parsed["gtm_id"]:
                    gtm_ids.add(parsed["gtm_id"])

            if parsed["is_ga4"]:
                flags["ga4"] = True
                if parsed["ga4_mid"]:
                    ga4_ids.add(parsed["ga4_mid"])
            if parsed["ga4_pv"]:
                flags["ga4_pv"] = True

        cdp.on("Network.requestWillBeSent", on_cdp_request)

        # Also listen to extra info for redirects
        def on_cdp_extra(params):
            req_id = params.get("requestId", "")
            headers = params.get("headers", {})
            # Some redirected requests carry analytics in headers
            pass

        cdp.on("Network.requestWillBeSentExtraInfo", on_cdp_extra)

        # ===== ALSO keep Playwright request listener as backup =====
        def handle_request(request):
            u = request.url
            parsed = parse_analytics_payload(u, "")
            if parsed["is_adobe"]:
                flags["adobe"] = True
            if parsed["adobe_pv"]:
                flags["adobe_pv"] = True
            if parsed["adobe_rsid"]:
                adobe_rsids.add(parsed["adobe_rsid"])
            if parsed["is_tealium_js"]:
                flags["tealium_js"] = True
                if parsed["tealium_account"] and not tealium_accounts:
                    tealium_accounts.append({
                        "account": parsed["tealium_account"],
                        "profile": parsed["tealium_profile"],
                        "env": parsed["tealium_env"]
                    })
            if parsed["is_tealium_collect"]:
                flags["tealium_collect"] = True
            if parsed["is_gtm"]:
                flags["gtm"] = True
                if parsed["gtm_id"]:
                    gtm_ids.add(parsed["gtm_id"])
            if parsed["is_ga4"]:
                flags["ga4"] = True
                if parsed["ga4_mid"]:
                    ga4_ids.add(parsed["ga4_mid"])
            if parsed["ga4_pv"]:
                flags["ga4_pv"] = True

        page.on("request", handle_request)

        sys.stdout.write(f"[{index}/{total}] Checking: {url}\n")
        sys.stdout.flush()

        # ===== NAVIGATE =====
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            err = str(e)
            results["Error"] = "Timeout" if "Timeout" in err else err[:80]

        # Wait for cookie banner to appear briefly
        await asyncio.sleep(1.5)

        # Accept cookies
        cookie_accepted = await accept_cookies(page)

        # Wait for analytics tags to fire after consent
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except:
            pass

        # Extra wait for late beacons
        await asyncio.sleep(2.5)

        # ===== SCROLL to trigger lazy analytics =====
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(0.5)
            await page.evaluate("window.scrollTo(0, 0)")
        except:
            pass

        # ===== PERFORMANCE API FALLBACK =====
        # Catch sendBeacon/fetch requests that CDP might miss
        try:
            perf_urls = await page.evaluate("""
                () => performance.getEntriesByType('resource')
                    .map(r => ({name: r.name, type: r.initiatorType}))
            """)
            for entry in (perf_urls or []):
                u = entry.get("name", "")
                parsed = parse_analytics_payload(u, "")
                if parsed["is_adobe"]:
                    flags["adobe"] = True
                if parsed["adobe_pv"]:
                    flags["adobe_pv"] = True
                if parsed["adobe_rsid"]:
                    adobe_rsids.add(parsed["adobe_rsid"])
                if parsed["is_ga4"]:
                    flags["ga4"] = True
                    if parsed["ga4_mid"]:
                        ga4_ids.add(parsed["ga4_mid"])
                if parsed["ga4_pv"]:
                    flags["ga4_pv"] = True
                if parsed["is_gtm"]:
                    flags["gtm"] = True
                    if parsed["gtm_id"]:
                        gtm_ids.add(parsed["gtm_id"])
                if parsed["is_tealium_js"]:
                    flags["tealium_js"] = True
        except:
            pass

        # ===== JS OBJECT BACKUP SCAN =====
        # Tealium
        try:
            utag_data = await page.evaluate("""
                (() => {
                    if (typeof window.utag !== 'undefined' && window.utag) {
                        return {
                            exists: true,
                            account: (window.utag.cfg && window.utag.cfg.account) || '',
                            profile: (window.utag.cfg && window.utag.cfg.profile) || '',
                            env: (window.utag.cfg && window.utag.cfg.utid) || ''
                        };
                    }
                    return { exists: false };
                })()
            """)
            if utag_data and utag_data.get("exists"):
                flags["tealium_js"] = True
                if not tealium_accounts and utag_data.get("account"):
                    tealium_accounts.append({
                        "account": utag_data["account"],
                        "profile": utag_data.get("profile", ""),
                        "env": utag_data.get("env", "")
                    })
        except:
            pass

        # GTM
        try:
            gtm_keys = await page.evaluate("""
                (() => {
                    if (window.google_tag_manager) {
                        return Object.keys(window.google_tag_manager).filter(k => k.startsWith('GTM-') || k.startsWith('G-'));
                    }
                    return [];
                })()
            """)
            for k in (gtm_keys or []):
                flags["gtm"] = True
                if k.startswith("GTM-"):
                    gtm_ids.add(k)
                if k.startswith("G-"):
                    ga4_ids.add(k)
        except:
            pass

        # GA4 dataLayer check — if page_view was pushed
        try:
            ga4_dl = await page.evaluate("""
                (() => {
                    if (!window.dataLayer) return {found: false};
                    let hasPV = false;
                    for (const e of window.dataLayer) {
                        if (e.event === 'page_view' || e[0] === 'event' && e[1] === 'page_view') hasPV = true;
                        if (e.event === 'gtm.js') hasPV = true;
                    }
                    return {found: hasPV};
                })()
            """)
            if ga4_dl and ga4_dl.get("found") and flags["ga4"]:
                flags["ga4_pv"] = True
        except:
            pass

        # Adobe — check JS objects
        try:
            adobe_data = await page.evaluate("""
                (() => {
                    let rsids = [];
                    let pvFired = false;
                    // Classic s object
                    if (typeof window.s !== 'undefined' && window.s && window.s.account) {
                        rsids.push(window.s.account);
                    }
                    if (typeof window.s_account !== 'undefined' && window.s_account) {
                        rsids.push(window.s_account);
                    }
                    // Check if s.t() was called (page view)
                    if (typeof window.s !== 'undefined' && window.s && window.s.pageName) {
                        pvFired = true;
                    }
                    // Adobe Web SDK (alloy)
                    if (typeof window.alloy !== 'undefined' || typeof window.__alloyNS !== 'undefined') {
                        pvFired = true;
                    }
                    let hasSatellite = typeof window._satellite !== 'undefined';
                    return { found: rsids.length > 0 || hasSatellite, rsids: rsids, pvFired: pvFired, satellite: hasSatellite };
                })()
            """)
            if adobe_data and adobe_data.get("found"):
                flags["adobe"] = True
                for r in (adobe_data.get("rsids") or []):
                    if r:
                        adobe_rsids.add(r)
                # If s.pageName exists or alloy exists, and adobe is loaded, consider PV fired
                if adobe_data.get("pvFired") and not flags["adobe_pv"]:
                    flags["adobe_pv"] = True
                # If _satellite loaded + adobe loaded but no PV detected yet,
                # check performance entries one more time
                if adobe_data.get("satellite") and not flags["adobe_pv"]:
                    try:
                        bss = await page.evaluate("""
                            () => performance.getEntriesByType('resource')
                                .filter(r => r.name.includes('/b/ss/'))
                                .map(r => r.name)
                        """)
                        for u in (bss or []):
                            if "pe=" not in u.lower():
                                flags["adobe_pv"] = True
                                m = re.search(r'/b/ss/([^/]+)/', u)
                                if m:
                                    adobe_rsids.add(m.group(1))
                    except:
                        pass
        except:
            pass

        # ===== CDP cleanup =====
        try:
            await cdp.detach()
        except:
            pass

        # ===== BUILD RESULTS =====
        results["Tealium_Loaded"] = "PASS" if flags["tealium_js"] else "FAIL"
        if tealium_accounts:
            results["Tealium_Account"] = tealium_accounts[0].get("account", "")
            results["Tealium_Profile"] = tealium_accounts[0].get("profile", "")
            results["Tealium_Env"] = tealium_accounts[0].get("env", "")

        results["GTM_Loaded"] = "PASS" if flags["gtm"] else "FAIL"
        results["GTM_ID"] = ", ".join(sorted(gtm_ids)) if gtm_ids else ""
        results["GA4_Fired"] = "PASS" if flags["ga4"] else "FAIL"
        results["GA4_Measurement_ID"] = ", ".join(sorted(ga4_ids)) if ga4_ids else ""
        results["GA4_PageView"] = "PASS" if flags["ga4_pv"] else "FAIL"

        results["Adobe_Loaded"] = "PASS" if flags["adobe"] else "FAIL"
        results["Adobe_ReportSuite"] = ", ".join(sorted(adobe_rsids)) if adobe_rsids else ""
        results["Adobe_PageView"] = "PASS" if flags["adobe_pv"] else "FAIL"

        tags_found = ", ".join([
            k for k, v in {
                "Tealium": flags["tealium_js"], "Adobe": flags["adobe"],
                "GTM": flags["gtm"], "GA4": flags["ga4"]
            }.items() if v
        ]) or "None"
        rsid_str = f" | RSID: {results['Adobe_ReportSuite']}" if results['Adobe_ReportSuite'] else ""
        pv_str = " | PageView:YES" if flags["adobe_pv"] else " | PageView:NO"
        ga4pv_str = " | GA4_PV:YES" if flags["ga4_pv"] else ""
        sys.stdout.write(f"[{index}/{total}] Done: {url} [{tags_found}]{rsid_str}{pv_str}{ga4pv_str}\n")
        sys.stdout.flush()

        await page.close()
    except Exception as e:
        results["Error"] = f"Fatal: {str(e)[:80]}"
        sys.stdout.write(f"[{index}/{total}] [ERROR] {url}\n")
        sys.stdout.flush()
    finally:
        if context:
            try:
                await context.close()
            except:
                pass

    return results


async def run_batch(browser, urls_batch, start_index, total):
    tasks = [validate_tags(browser, url, start_index + i, total) for i, url in enumerate(urls_batch)]
    return await asyncio.gather(*tasks)


async def main():
    start_time = time.time()
    print("Script initialized. Loading Excel...")
    input_file = "input_sites.xlsx"
    output_file = "validation_results.xlsx"

    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        pd.DataFrame({"URL": ["https://www.google.com"]}).to_excel(input_file, index=False)
        print(f"Template created: {input_file}")
        return

    df = pd.read_excel(input_file)
    url_col = None
    for col in df.columns:
        if any(n in str(col).lower() for n in ['url', 'link', 'website', 'site', 'address']):
            url_col = col
            break
    if not url_col:
        print(f"Error: No URL column. Columns: {list(df.columns)}")
        return

    urls = [("https://" + str(u).strip() if not str(u).strip().startswith("http") else str(u).strip()) for u in df[url_col] if pd.notna(u)]
    total = len(urls)
    print(f"Column: '{url_col}' | Sites: {total} | Parallel: {CONCURRENCY}")

    all_results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage'
            ]
        )
        for i in range(0, total, CONCURRENCY):
            batch = urls[i:i + CONCURRENCY]
            all_results.extend(await run_batch(browser, batch, i + 1, total))
        await browser.close()

    pd.DataFrame(all_results).to_excel(output_file, index=False)
    elapsed = round(time.time() - start_time, 1)

    # Summary
    t_pass = sum(1 for r in all_results if r["Tealium_Loaded"] == "PASS")
    a_pass = sum(1 for r in all_results if r["Adobe_Loaded"] == "PASS")
    g_pass = sum(1 for r in all_results if r["GTM_Loaded"] == "PASS")
    ga_pass = sum(1 for r in all_results if r["GA4_Fired"] == "PASS")
    apv = sum(1 for r in all_results if r["Adobe_PageView"] == "PASS")
    ga4pv = sum(1 for r in all_results if r["GA4_PageView"] == "PASS")
    rs_found = sum(1 for r in all_results if r["Adobe_ReportSuite"])
    print(f"")
    print(f"=== SUMMARY ===")
    print(f"Total: {total} | Time: {elapsed}s")
    print(f"Tealium: {t_pass} | Adobe: {a_pass} | Adobe PageView: {apv} | Report Suites: {rs_found}")
    print(f"GTM: {g_pass} | GA4: {ga_pass} | GA4 PageView: {ga4pv}")
    print(f"Saved: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
