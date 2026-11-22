"""Pre-send check demo: a stale CRM fact gets blocked, corrected from the company's own site, fixed and re-checked.

    uv run uvicorn presend_check.server:app --port 8000      # terminal 1
    npm --prefix web run dev                                 # terminal 2
    reshoot web tools/demo/storyboard.py takes/web.mp4

Zoom is deliberate, four times only, each on the thing the caption is about:
  1. the CRM record (the stale input)       2. the stale verdict with its quote and source
  3. the fixed-draft diff                    4. the benchmark numbers (decisions, stale precision, recall)
Auto-zoom on clicks is off (scale 1.0); only __demo.zoom() moves the camera.
The live check takes 10-90 s on Groq's free tier; edit.py speeds that stretch up.
"""

URL = "http://localhost:5173/"
SIZE = "1280x720@2"
THEME = "light"
ZOOM = {"scale": 1.0, "lead": 0.5, "watch": False}
SETTLE = 3

PARK = "await __demo.moveTo(1265, 360, 500);"  # cursor out of the zoomed frame
CENTER = "document.querySelector(%r).scrollIntoView({behavior: 'smooth', block: 'center'}); await __demo.sleep(900);"

BEATS = [
    ("intro",
     "await __demo.waitFor('[data-testid=case-modal_stale]', 15000);"
     "__demo.caption('Outreach agents write from stale CRM data', 'Pre-send check verifies every claim first')", 3.0),

    ("pick",
     "__demo.caption(null); await __demo.click('[data-testid=case-modal_stale]');"
     "await __demo.waitFor(() => document.querySelector('[data-testid=crm]')?.textContent.includes('Series C'), 5000)", 0.6),

    ("record",
     CENTER % "[data-testid=crm]" + PARK + "__demo.zoom('[data-testid=crm]', {scale: 1.9});"
     "__demo.caption('The CRM still says Series C', 'last enriched July 2025')", 3.2),

    ("run",
     "__demo.zoomOut(); __demo.caption(null); await __demo.sleep(500);" + CENTER % "[data-testid=run]" +
     "await __demo.click('[data-testid=run]');"
     "await __demo.waitFor('[data-testid=trace]', 10000);"
     "__demo.caption('Each claim is checked against modal.com', 'company site only, robots.txt respected')", 2.5),

    ("wait",
     "await __demo.waitFor('[data-testid=decision]', 240000)", 0.2),

    ("blocked",
     "__demo.caption(null);" + CENTER % "[data-testid=decision]" +
     "__demo.caption('Blocked before it sends')", 1.8),

    ("verdict",
     CENTER % "[data-verdict=stale]" + PARK +
     "__demo.zoom('[data-verdict=stale]', {scale: 1.7});"
     "__demo.caption('The site announces a Series D', 'with the exact quote and the page it came from')", 4.0),

    ("fixed",
     "__demo.zoomOut(); __demo.caption(null); await __demo.sleep(700);" + CENTER % "[data-testid=fixed]" + PARK +
     "__demo.zoom('[data-testid=fixed]', {scale: 1.6});"
     "__demo.caption('Only the stale fact is rewritten', 'then the new draft is checked again')", 3.8),

    ("bench",
     "__demo.zoomOut(); __demo.caption(null); await __demo.sleep(600);"
     "window.scrollTo({top: 0, behavior: 'smooth'}); await __demo.sleep(700);"
     "await __demo.click('[data-testid=tab-results]');"
     "await __demo.waitFor('[data-testid=stats]', 10000); await __demo.sleep(500);"
     "__demo.caption('10 real startups, labelled by hand', 'every decision right, every stale fact caught')", 1.4),

    ("stats",
     PARK + "__demo.zoom('[data-testid=stats] > div:nth-child(2)', {scale: 1.7})", 3.2),  # the whole row is too wide to enlarge; centring on cell 2 frames decisions, precision, recall

    ("end",
     "__demo.zoomOut(); __demo.caption(null); __demo.hide()", 1.2),
]
