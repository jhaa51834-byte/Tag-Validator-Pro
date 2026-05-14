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
    return False


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

    context = None
    try:
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_obj.apply_stealth_async(page)

        # ===== REQUEST LISTENER (attached BEFORE navigation) =====
        def handle_request(request):
            u = request.url
            low = u.lower()

            # --- TEALIUM ---
            if "tiqcdn.com" in low and "utag" in low:
                flags["tealium_js"] = True
                m = re.search(r'tiqcdn\.com/utag/([^/]+)/([^/]+)/([^/]+)/', u, re.I)
                if m:
                    tealium_accounts.append({"account": m.group(1), "profile": m.group(2), "env": m.group(3)})

            if "tealiumiq.com" in low or ("tealium" in low and ("collect" in low or "v.gif" in low or "/event" in low)):
                flags["tealium_collect"] = True

            # --- GTM ---
            if "googletagmanager.com/gtm.js" in low:
                flags["gtm"] = True
                m = re.search(r'[?&]id=(GTM-[A-Z0-9]+)', u, re.I)
                if m:
                    gtm_ids.add(m.group(1).upper())

            # --- GA4 ---
            # gtag/js loads the GA4 library
            if "googletagmanager.com/gtag/js" in low:
                m = re.search(r'[?&]id=(G-[A-Z0-9]+)', u, re.I)
                if m:
                    ga4_ids.add(m.group(1).upper())
                    flags["ga4"] = True

            # /g/collect is the actual GA4 data beacon
            if "/g/collect" in low or (("google-analytics.com" in low or "analytics.google.com" in low) and "collect" in low):
                flags["ga4"] = True
                m = re.search(r'[?&]tid=(G-[A-Z0-9]+)', u, re.I)
                if m:
                    ga4_ids.add(m.group(1).upper())
                if "en=page_view" in low:
                    flags["ga4_pv"] = True

            # --- ADOBE ANALYTICS ---
            # Definitive Adobe beacon: /b/ss/ path (works for both 3rd-party and 1st-party CNAME domains)
            if "/b/ss/" in low:
                flags["adobe"] = True
                m = re.search(r'/b/ss/([^/]+)/', u)
                if m:
                    adobe_rsids.add(m.group(1))
                # PageView = NO 'pe=' parameter. Link tracking has pe=lnk_o or pe=lnk_e
                if "pe=" not in low:
                    flags["adobe_pv"] = True

            # Adobe domains (omtrdc, 2o7) without /b/ss/ (e.g. ID sync calls)
            if (".omtrdc.net" in low or ".2o7.net" in low) and "/b/ss/" not in low:
                flags["adobe"] = True  # Adobe is present, but this is not a PageView beacon

            # Adobe library files
            if "appmeasurement" in low or "s_code" in low or "satellite-" in low or "launch-" in low:
                flags["adobe"] = True

        page.on("request", handle_request)

        sys.stdout.write(f"[{index}/{total}] Checking: {url}\n")
        sys.stdout.flush()

        # ===== NAVIGATE =====
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            err = str(e)
            results["Error"] = "Timeout" if "Timeout" in err else err[:80]

        # Wait for cookie banner
        await asyncio.sleep(2)

        # Accept cookies
        await accept_cookies(page)

        # Wait for analytics tags to fire after consent
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        await asyncio.sleep(5)

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

        # Adobe
        try:
            adobe_data = await page.evaluate("""
                (() => {
                    let rsids = [];
                    if (typeof window.s !== 'undefined' && window.s && window.s.account) {
                        rsids.push(window.s.account);
                    }
                    if (typeof window.s_account !== 'undefined' && window.s_account) {
                        rsids.push(window.s_account);
                    }
                    let hasSatellite = typeof window._satellite !== 'undefined';
                    return { found: rsids.length > 0 || hasSatellite, rsids: rsids };
                })()
            """)
            if adobe_data and adobe_data.get("found"):
                flags["adobe"] = True
                for r in (adobe_data.get("rsids") or []):
                    if r:
                        adobe_rsids.add(r)
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
            k.split("_")[0] for k, v in {
                "Tealium": flags["tealium_js"], "Adobe": flags["adobe"],
                "GTM": flags["gtm"], "GA4": flags["ga4"]
            }.items() if v
        ]) or "None"
        rsid_str = f" | RSID: {results['Adobe_ReportSuite']}" if results['Adobe_ReportSuite'] else ""
        pv_str = " | PageView:YES" if flags["adobe_pv"] else " | PageView:NO"
        sys.stdout.write(f"[{index}/{total}] Done: {url} [{tags_found}]{rsid_str}{pv_str}\n")
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
    rs_found = sum(1 for r in all_results if r["Adobe_ReportSuite"])
    print(f"")
    print(f"=== SUMMARY ===")
    print(f"Total: {total} | Time: {elapsed}s")
    print(f"Tealium: {t_pass} | Adobe: {a_pass} | Adobe PageView: {apv} | Report Suites: {rs_found}")
    print(f"GTM: {g_pass} | GA4: {ga_pass}")
    print(f"Saved: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
