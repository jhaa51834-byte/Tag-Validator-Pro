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
    for sel in COOKIE_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=200):
                await el.click(timeout=2000)
                return True
        except: pass
    for text in COOKIE_TEXT_PATTERNS:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=2000)
                return True
        except: pass
    return False

def parse_analytics_payload(url, post_data=""):
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

    if "/b/ss/" in low:
        result["is_adobe"] = True
        m = re.search(r'/b/ss/([^/]+)/', url)
        if m: result["adobe_rsid"] = m.group(1)
        if "pe=" not in low: result["adobe_pv"] = True

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
                    if xdm.get("eventType") == "web.webpagedetails.pageViews": result["adobe_pv"] = True
                    web = xdm.get("web", {})
                    if web.get("webPageDetails", {}).get("pageViews", {}).get("value"): result["adobe_pv"] = True
            except: pass

    if "tiqcdn.com" in low and "utag" in low:
        result["is_tealium_js"] = True
        m = re.search(r'tiqcdn\.com/utag/([^/]+)/([^/]+)/([^/]+)/', url, re.I)
        if m:
            result["tealium_account"] = m.group(1)
            result["tealium_profile"] = m.group(2)
            result["tealium_env"] = m.group(3)

    if "googletagmanager.com/gtm.js" in low:
        result["is_gtm"] = True
        m = re.search(r'[?&]id=(GTM-[A-Z0-9]+)', url, re.I)
        if m: result["gtm_id"] = m.group(1).upper()

    if "googletagmanager.com/gtag/js" in low:
        m = re.search(r'[?&]id=(G-[A-Z0-9]+)', url, re.I)
        if m:
            result["ga4_mid"] = m.group(1).upper()
            result["is_ga4"] = True

    if "/g/collect" in low or (("google-analytics.com" in low or "analytics.google.com" in low) and "collect" in low):
        result["is_ga4"] = True
        m = re.search(r'[?&]tid=(G-[A-Z0-9]+)', combined, re.I)
        if m: result["ga4_mid"] = m.group(1).upper()
        if "en=page_view" in low: result["ga4_pv"] = True

    if result["is_ga4"] and post_data and not result["ga4_pv"]:
        if "page_view" in post_data.lower(): result["ga4_pv"] = True

    return result

async def validate_tags(browser, url, index, total):
    results = {
        "URL": url,
        "Tealium_Loaded": "FAIL", "Tealium_Account": "", "Tealium_Profile": "", "Tealium_Env": "",
        "GTM_Loaded": "FAIL", "GTM_ID": "",
        "GA4_Fired": "FAIL", "GA4_Measurement_ID": "", "GA4_PageView": "FAIL",
        "Adobe_Loaded": "FAIL", "Adobe_ReportSuite": "", "Adobe_PageView": "FAIL",
        "Error": ""
    }

    gtm_ids, ga4_ids, adobe_rsids = set(), set(), set()
    tealium_accounts = []
    flags = {"tealium_js": False, "gtm": False, "ga4": False, "ga4_pv": False, "adobe": False, "adobe_pv": False}

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
            parsed = parse_analytics_payload(req.get("url", ""), req.get("postData", ""))
            if parsed["is_adobe"]: flags["adobe"] = True
            if parsed["adobe_pv"]: flags["adobe_pv"] = True
            if parsed["adobe_rsid"]: adobe_rsids.add(parsed["adobe_rsid"])
            if parsed["is_tealium_js"]:
                flags["tealium_js"] = True
                if parsed["tealium_account"]:
                    tealium_accounts.append({"account": parsed["tealium_account"], "profile": parsed["tealium_profile"], "env": parsed["tealium_env"]})
            if parsed["is_gtm"]:
                flags["gtm"] = True
                if parsed["gtm_id"]: gtm_ids.add(parsed["gtm_id"])
            if parsed["is_ga4"]:
                flags["ga4"] = True
                if parsed["ga4_mid"]: ga4_ids.add(parsed["ga4_mid"])
            if parsed["ga4_pv"]: flags["ga4_pv"] = True

        cdp.on("Network.requestWillBeSent", on_cdp_request)

        def handle_request(request):
            parsed = parse_analytics_payload(request.url, "")
            if parsed["is_adobe"]: flags["adobe"] = True
            if parsed["adobe_pv"]: flags["adobe_pv"] = True
            if parsed["adobe_rsid"]: adobe_rsids.add(parsed["adobe_rsid"])
            if parsed["is_tealium_js"]:
                flags["tealium_js"] = True
                if parsed["tealium_account"] and not tealium_accounts:
                    tealium_accounts.append({"account": parsed["tealium_account"], "profile": parsed["tealium_profile"], "env": parsed["tealium_env"]})
            if parsed["is_gtm"]:
                flags["gtm"] = True
                if parsed["gtm_id"]: gtm_ids.add(parsed["gtm_id"])
            if parsed["is_ga4"]:
                flags["ga4"] = True
                if parsed["ga4_mid"]: ga4_ids.add(parsed["ga4_mid"])
            if parsed["ga4_pv"]: flags["ga4_pv"] = True

        page.on("request", handle_request)

        sys.stdout.write(f"[{index}/{total}] Checking: {url}\n")
        sys.stdout.flush()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            results["Error"] = "Timeout" if "Timeout" in str(e) else str(e)[:80]

        await asyncio.sleep(2)
        await accept_cookies(page)
        try: await page.wait_for_load_state("networkidle", timeout=12000)
        except: pass
        await asyncio.sleep(8) # Robust wait for late tags

        # --- FALLBACK: Performance API ---
        try:
            perf_urls = await page.evaluate("performance.getEntriesByType('resource').map(r => r.name)")
            for u in (perf_urls or []):
                p = parse_analytics_payload(u, "")
                if p["is_adobe"]: flags["adobe"] = True
                if p["adobe_pv"]: flags["adobe_pv"] = True
                if p["adobe_rsid"]: adobe_rsids.add(p["adobe_rsid"])
                if p["is_ga4"]: flags["ga4"] = True
                if p["ga4_mid"]: ga4_ids.add(p["ga4_mid"])
                if p["ga4_pv"]: flags["ga4_pv"] = True
                if p["is_tealium_js"]: flags["tealium_js"] = True
        except: pass

        # --- FALLBACK: JS Objects ---
        try:
            js_data = await page.evaluate("""
                (() => {
                    let res = { utag: !!window.utag, gtm: !!window.google_tag_manager, s: !!window.s, alloy: !!window.alloy };
                    if (window.utag && window.utag.cfg) {
                        res.teal_acc = window.utag.cfg.account;
                        res.teal_prof = window.utag.cfg.profile;
                    }
                    if (window.google_tag_manager) {
                        res.gtm_ids = Object.keys(window.google_tag_manager).filter(k => k.startsWith('GTM-') || k.startsWith('G-'));
                    }
                    if (window.dataLayer) {
                        res.dl_pv = window.dataLayer.some(e => e.event === 'page_view' || e.event === 'gtm.js');
                    }
                    return res;
                })()
            """)
            if js_data.get("utag"): flags["tealium_js"] = True
            if js_data.get("gtm"): flags["gtm"] = True
            if js_data.get("s") or js_data.get("alloy"):
                flags["adobe"] = True
                flags["adobe_pv"] = True
            if js_data.get("gtm_ids"):
                for k in js_data["gtm_ids"]:
                    if k.startswith("GTM-"): gtm_ids.add(k)
                    if k.startswith("G-"): ga4_ids.add(k); flags["ga4"] = True
            if js_data.get("dl_pv"): flags["ga4_pv"] = True
        except: pass

        # BUILD RESULTS
        results["Tealium_Loaded"] = "PASS" if flags["tealium_js"] else "FAIL"
        if tealium_accounts:
            results["Tealium_Account"] = tealium_accounts[0]["account"]
            results["Tealium_Profile"] = tealium_accounts[0]["profile"]
            results["Tealium_Env"] = tealium_accounts[0]["env"]
        results["GTM_Loaded"] = "PASS" if flags["gtm"] else "FAIL"
        results["GTM_ID"] = ", ".join(sorted(gtm_ids)) if gtm_ids else ""
        results["GA4_Fired"] = "PASS" if flags["ga4"] else "FAIL"
        results["GA4_Measurement_ID"] = ", ".join(sorted(ga4_ids)) if ga4_ids else ""
        results["GA4_PageView"] = "PASS" if flags["ga4_pv"] else "FAIL"
        results["Adobe_Loaded"] = "PASS" if flags["adobe"] else "FAIL"
        results["Adobe_ReportSuite"] = ", ".join(sorted(adobe_rsids)) if adobe_rsids else ""
        results["Adobe_PageView"] = "PASS" if flags["adobe_pv"] else "FAIL"

        sys.stdout.write(f"[{index}/{total}] Done: {url} | PageView: {'YES' if flags['adobe_pv'] or flags['ga4_pv'] else 'NO'}\n")
        sys.stdout.flush()
        await page.close()
    except Exception as e:
        results["Error"] = f"Fatal: {str(e)[:80]}"
    finally:
        if context: await context.close()
    return results

async def run_batch(browser, urls_batch, start_index, total):
    tasks = [validate_tags(browser, url, start_index + i, total) for i, url in enumerate(urls_batch)]
    return await asyncio.gather(*tasks)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", help="Mode of audit: 'tealium' or 'ga4'")
    args = parser.parse_args()

    input_file, output_file = "input_sites.xlsx", "validation_results.xlsx"
    if not os.path.exists(input_file): return
    df = pd.read_excel(input_file)
    url_col = next((col for col in df.columns if any(n in str(col).lower() for n in ['url', 'link', 'website', 'site', 'address'])), None)
    if not url_col: return
    urls = [("https://" + str(u).strip() if not str(u).strip().startswith("http") else str(u).strip()) for u in df[url_col] if pd.notna(u)]
    total = len(urls)

    all_results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        for i in range(0, total, CONCURRENCY):
            all_results.extend(await run_batch(browser, urls[i:i + CONCURRENCY], i + 1, total))
        await browser.close()

    res_df = pd.DataFrame(all_results)
    if args.mode == 'tealium':
        cols = ['URL', 'Tealium_Loaded', 'Tealium_Account', 'Tealium_Profile', 'Tealium_Env', 'Adobe_Loaded', 'Adobe_ReportSuite', 'Adobe_PageView', 'Error']
    elif args.mode == 'ga4':
        cols = ['URL', 'GTM_Loaded', 'GTM_ID', 'GA4_Fired', 'GA4_Measurement_ID', 'GA4_PageView', 'Error']
    else: cols = res_df.columns
    res_df[[c for c in cols if c in res_df.columns]].to_excel(output_file, index=False)

if __name__ == "__main__":
    asyncio.run(main())
