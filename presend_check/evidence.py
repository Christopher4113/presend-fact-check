"""Company website -> pages -> ~800-char chunks -> top-k chunks per claim (BM25).

Company websites only: no LinkedIn, no logged-in pages, robots.txt respected.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from rank_bm25 import BM25Okapi
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .models import Claim, Evidence

USER_AGENT = "presend-fact-check/0.1 (send-layer fact checker prototype; reads public company pages only)"
TIMEOUT = 10.0
MAX_PAGES = 15
MAX_SITEMAP_PAGES = 10
CHUNK_CHARS = 800
TOP_K = 4
CACHE_DIR = Path(".cache/pages")

COMMON_PATHS = ["/about", "/company", "/team", "/careers", "/jobs", "/blog", "/news", "/press"]
# Path words worth reading. Funding/announcement words rank first so the round shows up.
PATH_KEYWORDS = [
    ("series", 0), ("raise", 0), ("raised", 0), ("funding", 0), ("seed", 0), ("announc", 0),
    ("about", 1), ("team", 1), ("company", 1), ("careers", 1), ("jobs", 1),
    ("press", 2), ("news", 2), ("blog", 3),
]
KIND_KEYWORDS = {
    "funding": "raised funding round series seed led investors million announce backed",
    "headcount": "team employees people members headcount hiring grow",
    "title": "founder ceo cto head vp director co-founder chief team",
    "product": "product platform launch feature build",
    "customer": "customers trusted by case study companies use",
    "location": "headquartered based office located city",
    "news": "announce launch news today introducing",
    "other": "",
}


class Page:
    def __init__(self, url: str, text: str, links: list[str] | None = None, headline: str = ""):
        self.url, self.text, self.links, self.headline = url, text, links or [], headline


# ---------- HTML -> text ----------

def html_to_text(html: str) -> tuple[str, list[str], str]:
    """(clean visible text, raw hrefs, headline). Headline = title + meta description.

    nav/footer are dropped: they repeat on every page and drown BM25 in menu text.
    """
    tree = HTMLParser(html)
    links = [a.attributes.get("href") or "" for a in tree.css("a[href]")]
    head = []
    if (t := tree.css_first("title")) and t.text(strip=True):
        head.append(t.text(strip=True))
    for sel in ('meta[name="description"]', 'meta[property="og:description"]'):
        if (m := tree.css_first(sel)) and (c := m.attributes.get("content")):
            head.append(c.strip())
    for tag in ("script", "style", "noscript", "svg", "template", "iframe", "nav", "footer"):
        for n in tree.css(tag):
            n.decompose()
    body = tree.body.text(separator="\n") if tree.body else ""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.splitlines()]
    headline = "\n".join(dict.fromkeys(head))
    text = headline + "\n" + "\n".join(ln for ln in lines if ln)
    return text.strip(), links, headline


def chunk(page: Page, size: int = CHUNK_CHARS) -> list[Evidence]:
    """Pack lines into ~size-char chunks. Long lines are split on sentence boundaries."""
    pieces: list[str] = []
    for ln in page.text.splitlines():
        while len(ln) > size:
            cut = ln.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            pieces.append(ln[:cut].strip())
            ln = ln[cut:].strip()
        if ln:
            pieces.append(ln)
    chunks, buf = [], ""
    for p in pieces:
        if buf and len(buf) + len(p) + 1 > size:
            chunks.append(Evidence(url=page.url, text=buf))
            buf = ""
        buf = f"{buf}\n{p}" if buf else p
    if buf:
        chunks.append(Evidence(url=page.url, text=buf))
    return chunks


# ---------- retrieval ----------

def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9$]+", s.lower())


def build_query(claim: Claim) -> str:
    return f"{claim.text} {claim.value} {KIND_KEYWORDS.get(claim.kind, '')}"


def headlines(pages: list[Page]) -> list[Evidence]:
    return [Evidence(url=p.url, text=p.headline) for p in pages if p.headline]


def top_chunks(claim: Claim, chunks: list[Evidence], k: int = TOP_K) -> list[Evidence]:
    if not chunks:
        return []
    bm25 = BM25Okapi([_tokens(c.text) for c in chunks])
    scores = bm25.get_scores(_tokens(build_query(claim)))
    ranked = sorted(zip(scores, range(len(chunks))), key=lambda x: -x[0])[:k]
    return [chunks[i].model_copy(update={"score": float(s)}) for s, i in ranked if s > 0]


HEADLINE_KEYWORDS = {"funding": {"raise", "raises", "raised", "series", "seed", "funding", "round"},
                     "news": {"announce", "announcing", "launch", "launches", "introducing"}}


def top_headlines(claim: Claim, heads: list[Evidence], limit: int = 8) -> list[Evidence]:
    """Page headlines (title + meta description) that announce something of the claim's kind.

    The claim's own words ("Series B") pull up the old Series B post, which is still on the
    site. Headlines ("Clerk raises $50m Series C ...") are where the newest value lives, so the
    judge sees every round the site announces, not only the one the email names.
    """
    words = HEADLINE_KEYWORDS.get(claim.kind)
    if not words:
        return []
    return [h for h in heads if words & set(_tokens(h.text))][:limit]


# ---------- robots + cache ----------

def robots_allows(robots_txt: str | None, url: str) -> bool:
    if not robots_txt:
        return True
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def _cache_path(url: str, cache_dir: Path) -> Path:
    return cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")


def cache_get(url: str, cache_dir: Path = CACHE_DIR) -> dict | None:
    p = _cache_path(url, cache_dir)
    return json.loads(p.read_text()) if p.exists() else None


def cache_put(url: str, entry: dict, cache_dir: Path = CACHE_DIR) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(url, cache_dir).write_text(json.dumps(entry))


# ---------- fetching ----------

class Fetcher:
    """Fetches one domain's pages: robots-checked, cached on disk by URL with fetch time."""

    def __init__(self, domain: str, fresh: bool = False, client: httpx.Client | None = None,
                 cache_dir: Path = CACHE_DIR):
        self.domain = domain.lower().removeprefix("https://").removeprefix("http://").strip("/")
        self.base = f"https://{self.domain}"
        self.fresh, self.cache_dir = fresh, cache_dir
        self.client = client or httpx.Client(
            timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.network_fetches = 0
        self._robots: str | None = None
        self._robots_loaded = False

    def _get(self, url: str) -> tuple[int, str, str]:
        """(status, content_type, body) with disk cache. Status 0 = network error."""
        if not self.fresh and (hit := cache_get(url, self.cache_dir)):
            return hit["status"], hit["content_type"], hit["body"]
        self.network_fetches += 1
        try:
            r = self.client.get(url)
            entry = {"status": r.status_code, "content_type": r.headers.get("content-type", ""),
                     "body": r.text, "final_url": str(r.url), "fetched_at": time.time()}
        except httpx.HTTPError:
            entry = {"status": 0, "content_type": "", "body": "", "fetched_at": time.time()}
        cache_put(url, entry, self.cache_dir)
        return entry["status"], entry["content_type"], entry["body"]

    def robots(self) -> str | None:
        if not self._robots_loaded:
            status, _, body = self._get(f"{self.base}/robots.txt")
            self._robots = body if status == 200 else None
            self._robots_loaded = True
        return self._robots

    def page(self, url: str) -> Page | None:
        if not robots_allows(self.robots(), url):
            return None
        status, ctype, body = self._get(url)
        if status != 200 or "html" not in ctype:
            return None
        text, links, headline = html_to_text(body)
        return Page(url, text, links, headline) if len(text) > 50 else None

    def sitemap_urls(self) -> list[str]:
        """Up to MAX_SITEMAP_PAGES same-domain URLs whose path names something worth reading."""
        status, _, body = self._get(f"{self.base}/sitemap.xml")
        if status != 200:
            return []
        locs = _sitemap_entries(body)
        # One level of sitemap index: read up to 3 child sitemaps.
        if "<sitemapindex" in body:
            locs = []
            for child, _ in _sitemap_entries(body)[:3]:
                s, _, b = self._get(child)
                if s == 200:
                    locs += _sitemap_entries(b)
        return pick_interesting(locs, self.domain, MAX_SITEMAP_PAGES)

    def gather(self, on_page=None) -> list[Page]:
        home = self.page(self.base + "/")
        urls = [self.base + "/"] + [self.base + p for p in COMMON_PATHS]
        urls += self.sitemap_urls()
        if home:  # links on the homepage are often the only route to the funding post
            abs_links = [(urljoin(home.url, h), "") for h in home.links]
            urls += pick_interesting(abs_links, self.domain, 6)
        urls = list(dict.fromkeys(u.rstrip("/") or u for u in urls))[:MAX_PAGES]
        pages: list[Page] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for url, pg in zip(urls, pool.map(self.page, urls)):
                if pg and not any(p.text == pg.text for p in pages):  # redirects to the same page
                    pages.append(pg)
                if on_page:
                    on_page(url, pg is not None)
        return pages


def _sitemap_entries(xml: str) -> list[tuple[str, str]]:
    out = []
    for block in re.findall(r"<(?:url|sitemap)>(.*?)</(?:url|sitemap)>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            out.append((loc.group(1).strip(), mod.group(1).strip() if mod else ""))
    return out


def pick_interesting(entries: list[tuple[str, str]], domain: str, limit: int) -> list[str]:
    """Same-domain URLs whose path matches a keyword; funding words first, then newest lastmod."""
    scored = []
    bare = domain.removeprefix("www.")
    for url, lastmod in entries:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or u.netloc.removeprefix("www.") != bare:
            continue
        path = u.path.lower()
        ranks = [r for kw, r in PATH_KEYWORDS if kw in path]
        if ranks and path not in ("", "/"):
            scored.append((min(ranks), lastmod, url.split("#")[0]))
    scored.sort(key=lambda x: x[1], reverse=True)  # newest first
    scored.sort(key=lambda x: x[0])  # stable: keyword rank, then newest
    return list(dict.fromkeys(u for _, _, u in scored))[:limit]


def gather_evidence(domain: str, fresh: bool = False, on_page=None) -> tuple[list[Page], list[Evidence]]:
    pages = Fetcher(domain, fresh=fresh).gather(on_page=on_page)
    return pages, [c for p in pages for c in chunk(p)]
