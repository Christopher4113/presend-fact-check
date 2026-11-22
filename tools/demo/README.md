# Demo video

A ~45 s walkthrough of the web UI on the Modal case: stale CRM record, live check, BLOCK with the quote and source,
minimal fix, benchmark numbers. Recorded with [reshoot](https://pypi.org/project/reshoot/) in headless Chrome, so
only the page is captured.

```bash
uv run uvicorn presend_check.server:app --port 8000     # terminal 1
npm --prefix web run dev                                # terminal 2
reshoot web tools/demo/storyboard.py takes/web.mp4      # record (live LLM calls; the take used LLM_PROVIDER=anthropic)
reshoot edit tools/demo/edit.py takes/web.mp4           # -> takes/presend-demo.mp4
reshoot check takes/web.assets.json takes/presend-demo.mp4 --review takes/review   # privacy sheets
```

Zoom is manual and limited to four moments (CRM record, stale verdict, fixed-draft diff, benchmark stats); auto-zoom
on clicks is switched off. The live check (10-90 s on Groq's free tier) is played fast in the cut, and the UI's own
timer still shows the real time. `RESHOOT_PREVIEW=1 reshoot web ...` records a quick low-res preview.

The prospects are made-up people at real companies; company facts come from each company's public website.
`takes/` is git-ignored.
