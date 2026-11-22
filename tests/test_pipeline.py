"""No network, no LLM: canned pages and verdicts through the pure functions."""

import httpx

from presend_check.consistency import agreement
from presend_check.decide import decide
from presend_check.evidence import Fetcher, Page, chunk, headlines, html_to_text, robots_allows, top_chunks, top_headlines
from presend_check.models import Claim, ClaimVerdict, Evidence
from presend_check.verify import enforce_quote, later_round_guard


def claim(id, kind, text="x", value="x"):
    return Claim(id=id, text=text, kind=kind, value=value)


def verdict(id, v, **kw):
    return ClaimVerdict(claim_id=id, verdict=v, reason="r", **kw)


# ---------- decide ----------

def test_decide_block_on_any_stale():
    claims = [claim("c1", "funding"), claim("c2", "location")]
    assert decide(claims, [verdict("c1", "stale"), verdict("c2", "supported")]) == "BLOCK"


def test_decide_review_on_unverified_risky_kind():
    claims = [claim("c1", "title"), claim("c2", "funding")]
    assert decide(claims, [verdict("c1", "unverified"), verdict("c2", "supported")]) == "REVIEW"


def test_decide_pass_when_only_low_risk_unverified():
    claims = [claim("c1", "location"), claim("c2", "funding")]
    assert decide(claims, [verdict("c1", "unverified"), verdict("c2", "supported")]) == "PASS"


# ---------- quote must be verbatim ----------

CHUNKS = [Evidence(url="https://acme.com/blog/series-b",
                   text="Today we’re announcing our $40M Series B,\nled by Notable Capital.")]


def test_quote_not_in_chunk_downgrades_to_unverified():
    v = verdict("c1", "stale", corrected_value="Series B", quote="We raised a $50M Series B",
                source_url="https://acme.com")
    out = enforce_quote(v, CHUNKS)
    assert out.verdict == "unverified" and out.corrected_value is None


def test_verbatim_quote_kept_and_source_url_pinned_to_chunk():
    # straight apostrophe + collapsed newline still match; the URL comes from the chunk, not the model
    v = verdict("c1", "stale", corrected_value="Series B",
                quote="we're announcing our $40M Series B, led by Notable", source_url="https://wrong.com")
    out = enforce_quote(v, CHUNKS)
    assert out.verdict == "stale" and out.source_url == "https://acme.com/blog/series-b"


def test_missing_quote_downgrades():
    assert enforce_quote(verdict("c1", "supported"), CHUNKS).verdict == "unverified"


# ---------- BM25 retrieval ----------

PAGES = {
    "https://acme.com/": "<html><head><title>Acme</title></head><body><nav>Home</nav>"
                         "<h1>The data platform for robots</h1><p>Book a demo today.</p>"
                         "<script>var x = 'Series Z';</script></body></html>",
    "https://acme.com/careers": "<html><body><h1>Careers</h1><p>We are hiring engineers in "
                                "London and New York. Great benefits and a friendly team.</p></body></html>",
    "https://acme.com/blog/series-b": "<html><body><h1>Acme raises $60M Series B</h1><p>Today we "
                                      "announced a $60 million Series B round led by Wellington, "
                                      "bringing total funding to $110 million.</p></body></html>",
}


def test_html_to_text_drops_scripts():
    text, _, headline = html_to_text(PAGES["https://acme.com/"])
    assert "Series Z" not in text and "robots" in text and headline == "Acme"
    assert "Home" not in text  # nav dropped


def test_bm25_picks_funding_chunk():
    chunks = [c for url, html in PAGES.items() for c in chunk(Page(url, html_to_text(html)[0]))]
    c = claim("c1", "funding", text="congrats on the Series A", value="Series A")
    top = top_chunks(c, chunks, k=1)
    assert top[0].url == "https://acme.com/blog/series-b"


def test_headlines_surface_newer_round_old_post_would_hide():
    # The claim's words match the old Series A post best; the headline pass adds the Series B page.
    old = Page("https://acme.com/blog/series-a", "Acme raises Series A\n" + "Series A details. " * 40, headline="Acme raises $10M Series A")
    new = Page("https://acme.com/blog/series-b", "Acme raises $60M Series B\nLong post about robots. " * 20, headline="Acme raises $60M Series B led by Wellington")
    chunks = chunk(old) + chunk(new)
    c = claim("c1", "funding", text="congrats on the Series A", value="Series A")
    assert top_chunks(c, chunks, k=1)[0].url.endswith("series-a")
    heads = top_headlines(c, headlines([old, new, Page("https://acme.com/careers", "x", headline="Careers at Acme")]))
    assert [h.url for h in heads] == ["https://acme.com/blog/series-a", "https://acme.com/blog/series-b"]


def test_chunks_stay_near_size():
    long = Page("https://acme.com/", ". ".join(["word " * 30] * 40))
    assert all(len(c.text) <= 820 for c in chunk(long))


# ---------- robots + cache (mock transport, no network) ----------

def make_fetcher(tmp_path, robots="", calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        html = PAGES.get(str(req.url).rstrip("/") + ("/" if req.url.path in ("", "/") else ""))
        if html is None:
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher("acme.com", client=client, cache_dir=tmp_path)


def test_robots_disallow_skips_page(tmp_path):
    robots = "User-agent: *\nDisallow: /careers\n"
    assert not robots_allows(robots, "https://acme.com/careers")
    calls = []
    f = make_fetcher(tmp_path, robots, calls)
    assert f.page("https://acme.com/careers") is None
    assert "https://acme.com/careers" not in calls  # never requested
    assert f.page("https://acme.com/blog/series-b") is not None


def test_cache_hit_on_second_fetch(tmp_path):
    calls = []
    f1 = make_fetcher(tmp_path, calls=calls)
    assert f1.page("https://acme.com/blog/series-b")
    n = len(calls)
    f2 = make_fetcher(tmp_path, calls=calls)  # new fetcher, same cache dir
    assert f2.page("https://acme.com/blog/series-b")
    assert len(calls) == n and f2.network_fetches == 0


def test_fresh_skips_cache(tmp_path):
    calls = []
    make_fetcher(tmp_path, calls=calls).page("https://acme.com/blog/series-b")
    f = make_fetcher(tmp_path, calls=calls)
    f.fresh = True
    f.page("https://acme.com/blog/series-b")
    assert f.network_fetches == 2  # robots.txt + page


# ---------- consistency ----------

def test_agreement_flags_flaky_claim():
    runs = [[("funding:series a", "stale")]] * 4 + [[("funding:series a", "unverified")]]
    r = agreement(runs, ["BLOCK"] * 4 + ["REVIEW"])
    assert r["claims"][0]["agreement"] == "4/5" and r["claims"][0]["flaky"]
    assert r["decision_flaky"]


def test_trailing_period_in_quote_still_matches():
    v = verdict("c1", "stale", corrected_value="Series B", quote="led by Notable Capital.")
    assert enforce_quote(v, CHUNKS).verdict == "stale"


def test_later_round_headline_overrides_supported():
    c = claim("c1", "funding", text="congrats on the $355M Series C", value="$355M Series C")
    heads = [Evidence(url="https://acme.com/blog/c", text="Acme raises $355M Series C"),
             Evidence(url="https://acme.com/blog/d", text="Acme crosses $1B ARR\nWe raised a $750M Series D led by Accel")]
    out = later_round_guard(c, verdict("c1", "supported", quote="x"), heads)
    assert out.verdict == "stale" and out.corrected_value == "$750M Series D"
    assert out.source_url == "https://acme.com/blog/d" and "Series D" in out.quote
    # no later round -> untouched
    assert later_round_guard(c, verdict("c1", "supported"), heads[:1]).verdict == "supported"
