"""Cut the web take into the final demo: title card, the take with the live LLM wait sped up, end card.

    reshoot edit tools/demo/edit.py takes/web.mp4

Writes takes/presend-demo.mp4 and takes/presend-demo.srt. The wait is shown, not hidden: it plays fast
(so the trace visibly runs) and the UI's own timer still shows the real seconds.
"""
import shutil, sys, tempfile
from pathlib import Path

from reshoot import cut

CREAM, INK, GREY, FOREST = (249, 248, 246), (10, 10, 10), (107, 107, 102), (10, 87, 55)
WAIT_SHOWN = 2.0  # seconds the sped-up wait lasts on screen


def main(web):
    web = Path(web)
    b = cut.beats(web)
    W, H, _ = cut.probe(web)
    out = web.parent
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        title = (cut.Card(W, H, CREAM).text(None, int(H * .36), "Pre-send check", int(H * .085), 700, INK)
                 .text(None, int(H * .50), "Blocks outreach drafts with stale facts,", int(H * .036), 500, GREY)
                 .text(None, int(H * .56), "checked against the prospect's own website.", int(H * .036), 500, GREY))
        parts = [cut.still(title.save(t / "title.png"), 2.4, t / "title.mp4", fade_in=0)]

        wait = b["blocked"] - b["wait"]
        parts.append(cut.trim(web, 0, b["wait"], t / "a.mp4"))
        if wait > WAIT_SHOWN + 0.5:
            parts.append(cut.speed(web, b["wait"], b["blocked"], wait / WAIT_SHOWN, t / "wait.mp4"))
        else:
            parts.append(cut.trim(web, b["wait"], b["blocked"], t / "wait.mp4"))
        parts.append(cut.trim(web, b["blocked"], b["end"] + 0.6, t / "b.mp4"))

        end = (cut.Card(W, H, CREAM).text(None, int(H * .38), "A send-layer guardrail for stale facts", int(H * .055), 700, INK)
               .text(None, int(H * .50), "check(prospect, draft) -> PASS | REVIEW | BLOCK", int(H * .034), 500, FOREST)
               .text(None, int(H * .57), "runs next to suppression, DNC and open-deal checks", int(H * .032), 500, GREY))
        parts.append(cut.still(end.save(t / "end.png"), 3.2, t / "end.mp4", fade_in=0))
        cut.concat(parts, out / "presend-demo.mp4")
    print(f"  {out / 'presend-demo.mp4'}  {cut.duration(out / 'presend-demo.mp4'):5.1f}s  (wait {wait:.1f}s shown as {min(wait, WAIT_SHOWN):.1f}s)")


if __name__ == "__main__":
    main(*(sys.argv[1:] or ["takes/web.mp4"]))
