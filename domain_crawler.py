"""
Domain crawler for Tag Validator Pro v3.1.
Takes a starting URL, crawls same-domain pages (BFS), normalizes URLs to dedupe
http/https/www variants, writes discovered URL list to crawled_urls.xlsx and
input_sites.xlsx (so the existing bulk_tag_validator.py can validate them).

Usage: python domain_crawler.py <start_url> <max_pages>
"""
import sys
import re
import time
import urllib.request
import urllib.parse
import gzip
from collections import deque
from html.parser import HTMLParser
import pandas as pd

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SKIP_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico', '.bmp',
    '.pdf', '.zip', '.rar', '.tar', '.gz', '.7z',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.css', '.js', '.json', '.xml', '.rss',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
)


def normalize_url(url: str) -> str:
    """https + lowercase host + strip www + drop fragment + drop trailing slash.
    Treats http/https and www/non-www as the same page so they don't duplicate."""
    try:
        url = url.strip()
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        p = urllib.parse.urlparse(url)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.endswith(":80") or host.endswith(":443"):
            host = host.rsplit(":", 1)[0]
        path = p.path or "/"
        path = re.sub(r'/+', '/', path)
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return urllib.parse.urlunparse(("https", host, path, "", p.query, ""))
    except Exception:
        return ""


def get_host(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host.rsplit(":", 1)[0]
    except Exception:
        return ""


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for k, v in attrs:
            if k.lower() == "href" and v:
                self.links.append(v)


def fetch(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return None, resp.geturl()
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        charset = "utf-8"
        m = re.search(r'charset=([\w-]+)', ctype, re.I)
        if m:
            charset = m.group(1)
        try:
            html = data.decode(charset, errors="ignore")
        except Exception:
            html = data.decode("utf-8", errors="ignore")
        return html, resp.geturl()


def crawl(start_url: str, max_pages: int = 50):
    start_norm = normalize_url(start_url)
    if not start_norm:
        print(f"Invalid start URL: {start_url}")
        return []

    target_host = get_host(start_norm)
    print(f"Crawling domain: {target_host} (max pages: {max_pages})")
    sys.stdout.flush()

    visited = set()
    discovered = []
    queue = deque([start_norm])
    queued = {start_norm}

    while queue and len(discovered) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            html, final_url = fetch(url)
            final_norm = normalize_url(final_url) if final_url else url
            if final_norm and final_norm not in discovered:
                if get_host(final_norm) == target_host:
                    discovered.append(final_norm)
                    print(f"[{len(discovered)}/{max_pages}] Found: {final_norm}")
                    sys.stdout.flush()
            if html is None:
                continue
        except Exception as e:
            print(f"[skip] {url} ({str(e)[:60]})")
            sys.stdout.flush()
            continue

        if len(discovered) >= max_pages:
            break

        parser = LinkExtractor()
        try:
            parser.feed(html)
        except Exception:
            continue

        for href in parser.links:
            href = href.strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            abs_url = urllib.parse.urljoin(url, href)
            low = abs_url.lower().split("?")[0]
            if any(low.endswith(ext) for ext in SKIP_EXTENSIONS):
                continue
            n = normalize_url(abs_url)
            if not n:
                continue
            if get_host(n) != target_host:
                continue
            if n not in visited and n not in queued:
                queued.add(n)
                queue.append(n)

        time.sleep(0.1)

    return discovered


def main():
    if len(sys.argv) < 2:
        print("Usage: python domain_crawler.py <start_url> [max_pages]")
        sys.exit(1)
    start_url = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    t0 = time.time()
    urls = crawl(start_url, max_pages)
    elapsed = round(time.time() - t0, 1)

    print(f"\nDiscovered {len(urls)} unique pages in {elapsed}s")

    df = pd.DataFrame({"URL": urls})
    df.to_excel("crawled_urls.xlsx", index=False)
    df.to_excel("input_sites.xlsx", index=False)
    print("Saved: crawled_urls.xlsx (and input_sites.xlsx for validator)")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
