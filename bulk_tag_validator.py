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
import argparse
from urllib.parse import unquote, parse_qs, urlparse

stealth_obj = Stealth()
CONCURRENCY = 3

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
    }

    # --- ADOBE ANALYTICS ---
    if "/b/ss/" in low:
        result["is_adobe"] = True
        m = re.search(r'/b/ss/([^/]+)/', url)
        if m:
            result["adobe_rsid"] = m.group(1)
        if "pe=" not in low:
            result["adobe_pv"] = True

    if any(x in low for x in [".omtrdc.net", ".2o7.net", "appmeasurement", "s_code", "satellite-", "launch-"]):
        result["is_adobe"] = True

    if any(x in low for x in ["adobedc.net", "adobedc.demdex", "/ee/v", "/interact"]):
        result["is_adobe"] = True
        if post_data:
            try:
                body = json.loads(post_data)
                events = body.get("events", [])
                for ev in events:
                    xdm = ev.get("xdm", {})
                    if xdm.get("eventType") == "web.webpagedetails.pageViews":
                        result["adobe_pv"] = True
                    web = xdm.get("xdm", {}).get("web", {})
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

    # --- GTM ---
    if "googletagmanager.com/gtm.js" in low:
        result["is_gtm"] = True
        m = re.search(r'[?&]id=(GTM-[A-Z0-9]+)', url, re.I)
        if m:
            result["gtm_id"] = m.group(1).upper()

    # --- GA4 ---
    if "googletagmanager.com/gtag/js" in low:
        m = re.search(r'[?&]id=(G-[A-Z0-9]+)', url, re.I)
        if m:
            result["ga4_mid"] = m.group(1).upper()
            result["is_ga4"] = True

    if "/g/collect" in low or (("google-analytics.com" in low or "analytics.google.com" in low) and "collect" in low):
        result["is_ga4"] = True
        m = re.search(r'[?&]tid=(G-[A-Z0-9]+)', combined, re.I)
        if m:
            result["ga4_mid"] = m.group(1).upper()
        if "en=page_view" in low:
            result["ga4_pv"] = True

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

    gtm_ids = set()
    ga4_ids = set()
    tealium_accounts = []
    adobe_rsids = set()
    flags = {
        "tealium_js": False, 
        "gtm": False, "ga4": False, "ga4_pv": False,
        "adobe": False, "adobe_pv": False
    }

    context = None
    try:
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_obj.apply_stealth_async(page)

        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")

        def on_cdp_request(params):
            req = params.get("request", {})
            req_url = req.get("url", "")
            post_data = req.get("postData", "")
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

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            err = str(e)
            results["Error"] = "Timeout" if "Timeout" in err else err[:80]

        await asyncio.sleep(2)
        await accept_cookies(page)

        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except:
            pass

        await asyncio.sleep(6)

        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(2)
        except:
            pass

        # BUILD RESULTS
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", help="Mode of audit: 'tealium' or 'ga4'")
    args = parser.parse_args()

    start_time = time.time()
    print(f"Script initialized (Mode: {args.mode}). Loading Excel...")
    input_file = "input_sites.xlsx"
    output_file = "validation_results.xlsx"

    if not os.path.exists(input_file):
        pd.DataFrame({"URL": ["https://www.google.com"]}).to_excel(input_file, index=False)
        return

    df = pd.read_excel(input_file)
    url_col = next((col for col in df.columns if any(n in str(col).lower() for n in ['url', 'link', 'website', 'site', 'address'])), None)
    if not url_col: return

    urls = [("https://" + str(u).strip() if not str(u).strip().startswith("http") else str(u).strip()) for u in df[url_col] if pd.notna(u)]
    total = len(urls)

    all_results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        for i in range(0, total, CONCURRENCY):
            batch = urls[i:i + CONCURRENCY]
            all_results.extend(await run_batch(browser, batch, i + 1, total))
        await browser.close()

    res_df = pd.DataFrame(all_results)
    
    # FILTER COLUMNS BASED ON MODE
    if args.mode == 'tealium':
        cols = ['URL', 'Tealium_Loaded', 'Tealium_Account', 'Tealium_Profile', 'Tealium_Env', 'Error']
        res_df = res_df[[c for c in cols if c in res_df.columns]]
    elif args.mode == 'ga4':
        cols = ['URL', 'GTM_Loaded', 'GTM_ID', 'GA4_Fired', 'GA4_Measurement_ID', 'GA4_PageView', 'Adobe_Loaded', 'Adobe_ReportSuite', 'Adobe_PageView', 'Error']
        res_df = res_df[[c for c in cols if c in res_df.columns]]

    res_df.to_excel(output_file, index=False)
    print(f"Saved: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
