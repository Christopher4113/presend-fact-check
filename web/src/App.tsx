import { useEffect, useMemo, useRef, useState } from 'react'

// ---------- types (mirror presend_check/models.py) ----------
type Verdict = 'supported' | 'stale' | 'unverified'
type Decision = 'PASS' | 'REVIEW' | 'BLOCK'
interface Prospect {
  person_name: string; person_title: string | null; company: string; domain: string
  headcount: number | null; funding_stage: string | null; last_enriched: string | null
}
interface Claim { id: string; text: string; kind: string; value: string }
interface ClaimVerdict {
  claim_id: string; verdict: Verdict; corrected_value: string | null
  source_url: string | null; quote: string | null; reason: string
}
interface CheckResult {
  decision: Decision; claims: Claim[]; verdicts: ClaimVerdict[]; fixed_draft: string | null
  fixed_check: CheckResult | null; pages_checked: string[]; latency_ms: number
}
interface Case {
  id: string; name: string; category: string; labelled: string; prospect: Prospect; draft: string
  expected_decision: Decision
}
interface Step { key: string; tool: string; detail: string; state: 'running' | 'done' | 'skipped'; ms?: number; t0: number }
interface Summary {
  decision_accuracy: string; stale_precision: number; stale_recall: number
  median_latency_ms: number; median_pages: number; tp: number; fp: number; fn: number
}
interface Row { case: string; category: string; domain: string; expected: Decision; decision: Decision; ok: boolean; latency_ms: number; pages: number }

// ---------- helpers ----------
const VERDICT_STYLE: Record<Verdict, string> = {
  supported: 'bg-mint text-forest-deep',
  stale: 'bg-brick-soft text-brick',
  unverified: 'bg-amber-soft text-amber-ink',
}
const DECISION_STYLE: Record<Decision, { box: string; label: string; blurb: string }> = {
  PASS: { box: 'bg-mint text-forest-deep border-forest/20', label: 'PASS', blurb: 'Every checked fact matches the company site. Safe to send.' },
  REVIEW: { box: 'bg-amber-soft text-amber-ink border-amber-ink/20', label: 'REVIEW', blurb: 'A funding, headcount or title claim could not be confirmed. Routed to a person.' },
  BLOCK: { box: 'bg-brick-soft text-brick border-brick/20', label: 'BLOCK', blurb: 'The site says something newer. Sent back to the agent with corrections.' },
}

function ageLabel(d: string | null) {
  if (!d) return 'unknown'
  const months = Math.round((Date.now() - new Date(d).getTime()) / (30.4 * 864e5))
  return months >= 12 ? `${(months / 12).toFixed(1)} yr old` : `${months} mo old`
}
const path = (u: string) => { try { const x = new URL(u); return x.pathname === '/' ? x.host : x.pathname } catch { return u } }

/** Word-level diff: returns segments tagged same / del / add. */
function diffWords(a: string, b: string) {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/)
  const dp = Array.from({ length: A.length + 1 }, () => new Array(B.length + 1).fill(0))
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out: { t: 'same' | 'del' | 'add'; s: string }[] = []
  let i = 0, j = 0
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { out.push({ t: 'same', s: A[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: 'del', s: A[i++] })
    else out.push({ t: 'add', s: B[j++] })
  }
  while (i < A.length) out.push({ t: 'del', s: A[i++] })
  while (j < B.length) out.push({ t: 'add', s: B[j++] })
  return out
}

// ---------- small pieces ----------
function Pill({ v }: { v: Verdict }) {
  return <span className={`inline-block rounded-sm px-1.5 py-0.5 text-[11px] ${VERDICT_STYLE[v]}`}>{v}</span>
}

function Panel({ title, right, children, testid }: { title: string; right?: React.ReactNode; children: React.ReactNode; testid?: string }) {
  return (
    <section data-testid={testid} className="rounded-sm border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="text-[12px] text-muted">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}

function Spinner() {
  return <span aria-hidden className="spin inline-block h-3 w-3 rounded-full border-[1.5px] border-forest/30 border-t-forest" />
}

/** Tool-call trace, modeled on Frontrunner's own "Research… search_web 1.5s" list. */
function Trace({ steps, running, total }: { steps: Step[]; running: boolean; total?: number }) {
  const pages = steps.filter(s => s.tool === 'fetch_page')
  const fetched = pages.filter(s => s.state === 'done').length
  const other = steps.filter(s => s.tool !== 'fetch_page')
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-[12px]">
        {running ? <Spinner /> : <span className="h-2 w-2 rounded-full bg-forest" />}
        <span>{running ? 'Checking…' : 'Checked'}</span>
        {total != null && <span className="text-muted">{(total / 1000).toFixed(1)}s</span>}
      </div>
      <ol className="space-y-1.5" aria-live="polite">
        {other.map((s, i) => (
          <li key={s.key} className="flex items-baseline gap-3">
            <span className="w-4 text-right text-muted">{i + 1}.</span>
            <code className="rounded-sm bg-page px-1.5 py-0.5 text-[12px]">{s.tool}</code>
            <span className="min-w-0 flex-1 truncate text-muted">{s.detail}</span>
            <span className="text-muted tabular-nums">{s.state === 'running' ? <Spinner /> : s.ms != null ? `${(s.ms / 1000).toFixed(1)}s` : ''}</span>
          </li>
        ))}
      </ol>
      {pages.length > 0 && (
        <details className="mt-3 border-t border-line pt-3">
          <summary className="cursor-pointer text-[12px] text-muted">fetch_page · {fetched} of {pages.length} URLs on the company site returned a page</summary>
          <ul className="mt-2 space-y-1 text-[12px]">
            {pages.map(p => (
              <li key={p.key} className={p.state === 'done' ? '' : 'text-muted line-through'}>{p.detail}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function HighlightedDraft({ draft, claims, verdicts }: { draft: string; claims: Claim[]; verdicts: ClaimVerdict[] }) {
  const byId = Object.fromEntries(verdicts.map(v => [v.claim_id, v]))
  const marks = claims
    .map(c => ({ c, at: draft.indexOf(c.text), v: byId[c.id] }))
    .filter(m => m.at >= 0 && m.v)
    .sort((a, b) => a.at - b.at)
  const parts: React.ReactNode[] = []
  let pos = 0
  for (const m of marks) {
    if (m.at < pos) continue
    parts.push(draft.slice(pos, m.at))
    parts.push(<mark key={m.c.id} title={`${m.v.verdict}: ${m.v.reason}`} className={`rounded-sm px-0.5 ${VERDICT_STYLE[m.v.verdict]}`}>{m.c.text}</mark>)
    pos = m.at + m.c.text.length
  }
  parts.push(draft.slice(pos))
  return <p className="whitespace-pre-wrap font-sans text-[14px] leading-6">{parts}</p>
}

function Verdicts({ claims, verdicts }: { claims: Claim[]; verdicts: ClaimVerdict[] }) {
  const byId = Object.fromEntries(claims.map(c => [c.id, c]))
  if (!verdicts.length) return <p className="text-muted">No factual claims found in this draft.</p>
  return (
    <ul className="divide-y divide-line">
      {verdicts.map(v => {
        const c = byId[v.claim_id]
        return (
          <li key={v.claim_id} data-verdict={v.verdict} className="py-3 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <Pill v={v.verdict} />
              <span className="text-[11px] text-muted">{c?.kind}</span>
              <span className="font-sans text-[14px]">“{c?.text}”</span>
            </div>
            {v.corrected_value && (
              <p className="mt-2 text-[13px]"><span className="text-muted">site says → </span><strong className="text-brick">{v.corrected_value}</strong></p>
            )}
            {v.quote && (
              <blockquote className="mt-2 border-l-2 border-forest/40 pl-3 font-sans text-[13px] text-ink/80">
                “{v.quote}”
                {v.source_url && <a href={v.source_url} target="_blank" rel="noreferrer" className="ml-2 font-mono text-[12px] text-forest underline underline-offset-2">{path(v.source_url)}</a>}
              </blockquote>
            )}
            <p className="mt-1.5 text-[12px] text-muted">{v.reason}</p>
          </li>
        )
      })}
    </ul>
  )
}

function Results() {
  const [data, setData] = useState<{ summary: Summary; rows: Row[] } | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => { fetch('/api/results').then(r => r.ok ? r.json() : Promise.reject()).then(setData).catch(() => setErr(true)) }, [])
  if (err) return <p className="text-muted">No benchmark yet. Run <code>uv run python cli.py --all</code>.</p>
  if (!data) return <p className="text-muted">Loading…</p>
  const s = data.summary
  const stats = [
    ['Decisions correct', s.decision_accuracy],
    ['Stale precision', `${Math.round(s.stale_precision * 100)}%`],
    ['Stale recall', `${Math.round(s.stale_recall * 100)}%`],
    ['Median latency', `${(s.median_latency_ms / 1000).toFixed(1)}s`],
    ['Median pages', String(s.median_pages)],
  ]
  return (
    <div>
      <dl data-testid="stats" className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-sm border border-line bg-line sm:grid-cols-5">
        {stats.map(([k, v]) => (
          <div key={k} className="bg-panel px-3 py-2.5"><dt className="text-[11px] text-muted">{k}</dt><dd className="mt-0.5 font-sans text-[20px]">{v}</dd></div>
        ))}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12px]">
          <thead className="text-muted"><tr>{['case', 'category', 'expected', 'decision', 'latency', 'pages'].map(h => <th key={h} className="border-b border-line py-1.5 pr-4 font-normal">{h}</th>)}</tr></thead>
          <tbody>
            {data.rows.map(r => (
              <tr key={r.case} className="border-b border-line last:border-0">
                <td className="py-1.5 pr-4">{r.domain}</td>
                <td className="pr-4 text-muted">{r.category}</td>
                <td className="pr-4">{r.expected}</td>
                <td className="pr-4"><span className={`rounded-sm px-1.5 py-0.5 ${DECISION_STYLE[r.decision].box}`}>{r.decision}</span>{!r.ok && <span className="ml-2 text-brick">✕</span>}</td>
                <td className="pr-4 tabular-nums">{(r.latency_ms / 1000).toFixed(1)}s</td>
                <td className="tabular-nums">{r.pages}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-muted">Live run against each company's own site. Labels dated 2026-11-22.</p>
    </div>
  )
}

// ---------- app ----------
export default function App() {
  const [cases, setCases] = useState<Case[]>([])
  const [sel, setSel] = useState<Case | null>(null)
  const [prospect, setProspect] = useState<Prospect | null>(null)
  const [draft, setDraft] = useState('')
  const [autoFix, setAutoFix] = useState(true)
  const [steps, setSteps] = useState<Step[]>([])
  const [result, setResult] = useState<CheckResult | null>(null)
  const [checkedDraft, setCheckedDraft] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'check' | 'results'>('check')
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    fetch('/api/cases').then(r => r.json()).then((cs: Case[]) => { setCases(cs); pick(cs.find(c => c.id === 'browserbase_stale') ?? cs[0]) })
      .catch(() => setError('Backend not reachable. Start it with: uv run uvicorn presend_check.server:app --port 8000'))
  }, [])

  function pick(c: Case) {
    abort.current?.abort()
    setSel(c); setProspect(c.prospect); setDraft(c.draft); setResult(null); setSteps([]); setError(null); setRunning(false)
  }

  async function run() {
    if (!prospect) return
    abort.current?.abort()
    const ac = new AbortController(); abort.current = ac
    setRunning(true); setResult(null); setError(null); setCheckedDraft(draft)
    const now = () => performance.now()
    const live: Step[] = []
    const upsert = (s: Partial<Step> & { key: string }) => {
      const i = live.findIndex(x => x.key === s.key)
      if (i >= 0) live[i] = { ...live[i], ...s } as Step
      else live.push({ state: 'running', detail: '', tool: s.key, t0: now(), ...s } as Step)
      setSteps([...live])
    }
    const finish = (key: string) => {
      const s = live.find(x => x.key === key)
      if (s && s.state === 'running') upsert({ key, state: 'done', ms: now() - s.t0 })
    }
    try {
      const res = await fetch('/api/check/stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ac.signal,
        body: JSON.stringify({ prospect, draft, fix: autoFix }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
      let verified = 0, claimCount = 0
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.trim()) continue
          const e = JSON.parse(line)
          if (e.type === 'step' && e.step === 'extract_claims') upsert({ key: 'extract_claims', detail: 'Pulled factual claims out of the draft' })
          if (e.type === 'step' && e.step === 'gather_evidence') upsert({ key: 'gather_evidence', tool: 'fetch_site', detail: `Read ${e.domain}: home, about, careers, blog, press` })
          if (e.type === 'page') upsert({ key: `page:${e.url}`, tool: 'fetch_page', detail: path(e.url), state: e.ok ? 'done' : 'skipped' })
          if (e.type === 'claims') { finish('extract_claims'); claimCount = e.claims.length; upsert({ key: 'extract_claims', detail: `Found ${claimCount} factual claim${claimCount === 1 ? '' : 's'}` }) }
          if (e.type === 'step' && e.step === 'verify_claims') { finish('gather_evidence'); upsert({ key: 'verify_claims', tool: 'verify_claim', detail: `Judging each claim against the top 4 page chunks (BM25)` }) }
          if (e.type === 'verdict') { verified++; upsert({ key: 'verify_claims', detail: `${verified} of ${claimCount} claims judged` }) }
          if (e.type === 'step' && e.step === 'fix_draft') { finish('verify_claims'); upsert({ key: 'fix_draft', detail: 'Rewriting only the stale spans, then re-verifying' }) }
          if (e.type === 'result') { live.filter(s => s.state === 'running').forEach(s => finish(s.key)); setResult(e.result) }
          if (e.type === 'error') throw new Error(e.message)
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message)
    } finally {
      if (abort.current === ac) setRunning(false)
    }
  }

  const fixedDiff = useMemo(() => result?.fixed_draft ? diffWords(checkedDraft, result.fixed_draft) : null, [result, checkedDraft])
  const edited = sel && draft !== sel.draft

  return (
    <div className="mx-auto max-w-[1240px] px-4 pb-16 sm:px-6">
      {/* top bar */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-4">
        <div className="flex items-center gap-3">
          <span aria-hidden className="grid h-6 w-6 place-items-center rounded-sm bg-forest text-[11px] text-page">✓</span>
          <span className="font-sans text-[15px]">Pre-send check</span>
          <span className="hidden text-[12px] text-muted sm:inline">a send-layer guardrail for stale facts</span>
        </div>
        <nav className="flex gap-1 text-[12px]" aria-label="View">
          {(['check', 'results'] as const).map(t => (
            <button key={t} data-testid={`tab-${t}`} onClick={() => setTab(t)} aria-pressed={tab === t}
              className={`rounded-sm px-2.5 py-1 ${tab === t ? 'bg-ink text-page' : 'text-muted hover:text-ink'}`}>
              {t === 'check' ? 'Check a draft' : 'Benchmark'}
            </button>
          ))}
        </nav>
      </header>

      <div className="py-8">
        <h1 className="max-w-3xl font-sans text-[32px] leading-[1.15] tracking-tight sm:text-[40px]">
          Catch the stale fact <span className="text-forest">before</span> the email sends.
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          Every claim in an agent-written draft is checked against the prospect's live website.
          Stale facts block the send, with the correction and the page it came from.
          PipelineBench found stale data is the #1 way models lose pipeline.
        </p>
      </div>

      {error && <div role="alert" className="mb-4 rounded-sm border border-brick/20 bg-brick-soft px-4 py-3 text-brick">{error}</div>}

      {tab === 'results' ? <Panel title="Live run · 10 labelled cases"><Results /></Panel> : (
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
          {/* left: input */}
          <div className="space-y-4">
            <Panel title="Prospects">
              <ul className="-m-1 space-y-0.5">
                {cases.map(c => (
                  <li key={c.id}>
                    <button data-testid={`case-${c.id}`} onClick={() => pick(c)} aria-current={sel?.id === c.id}
                      className={`flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left ${sel?.id === c.id ? 'bg-page' : 'hover:bg-page/60'}`}>
                      <span className="flex items-center gap-2">
                        <img src={`https://www.google.com/s2/favicons?domain=${c.prospect.domain}&sz=32`} alt="" className="h-4 w-4 rounded-sm" />
                        <span>{c.prospect.company}</span>
                      </span>
                      <span className="text-[11px] text-muted">{c.category}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>

            {prospect && (
              <Panel testid="crm" title="CRM record" right={<span className="text-[11px] text-muted">may be stale</span>}>
                <dl className="grid grid-cols-[110px_1fr] gap-y-1.5 text-[12px]">
                  <dt className="text-muted">person</dt><dd>{prospect.person_name}</dd>
                  <dt className="text-muted">title</dt><dd>{prospect.person_title ?? '—'}</dd>
                  <dt className="text-muted">domain</dt><dd>{prospect.domain}</dd>
                  <dt className="text-muted">funding</dt><dd>{prospect.funding_stage ?? '—'}</dd>
                  <dt className="text-muted">headcount</dt><dd>{prospect.headcount ?? '—'}</dd>
                  <dt className="text-muted">last enriched</dt>
                  <dd>{prospect.last_enriched ?? '—'} <span className={`ml-1 rounded-sm px-1 text-[11px] ${ageLabel(prospect.last_enriched).includes('yr') ? 'bg-amber-soft text-amber-ink' : 'text-muted'}`}>{ageLabel(prospect.last_enriched)}</span></dd>
                </dl>
              </Panel>
            )}
          </div>

          {/* right: draft + result */}
          <div className="space-y-4">
            <Panel title={`Draft from the outreach agent → ${prospect?.person_name ?? ''}`}
              right={edited ? <button onClick={() => sel && setDraft(sel.draft)} className="text-[11px] text-muted underline">reset</button> : null}>
              <label htmlFor="draft" className="sr-only">Draft email</label>
              <textarea id="draft" value={draft} onChange={e => setDraft(e.target.value)} rows={7}
                className="w-full resize-y rounded-sm border border-line bg-page/50 p-3 font-sans text-[14px] leading-6 outline-none focus:border-forest" />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-[12px] text-muted">
                  <input type="checkbox" checked={autoFix} onChange={e => setAutoFix(e.target.checked)} className="accent-forest" />
                  Auto-fix stale facts and re-check
                </label>
                <button data-testid="run" onClick={run} disabled={running || !draft.trim()}
                  className="inline-flex items-center gap-2 rounded-sm bg-forest px-4 py-2 text-page hover:bg-forest-deep disabled:opacity-50">
                  {running && <Spinner />}{running ? 'Checking' : 'Run pre-send check'}
                </button>
              </div>
            </Panel>

            {steps.length > 0 && <Panel testid="trace" title="Agent trace"><Trace steps={steps} running={running} total={result?.latency_ms} /></Panel>}

            {result && (
              <>
                <div data-testid="decision" className={`rounded-sm border px-4 py-3 ${DECISION_STYLE[result.decision].box}`} role="status">
                  <div className="flex flex-wrap items-baseline gap-3">
                    <span className="font-sans text-[22px] tracking-tight">{DECISION_STYLE[result.decision].label}</span>
                    <span className="text-[12px]">{DECISION_STYLE[result.decision].blurb}</span>
                    {sel && !edited && <span className="ml-auto text-[11px] opacity-70">expected {sel.expected_decision}</span>}
                  </div>
                </div>

                <Panel testid="claims" title="Claims in the draft">
                  <HighlightedDraft draft={checkedDraft} claims={result.claims} verdicts={result.verdicts} />
                  <div className="mt-4 border-t border-line pt-4"><Verdicts claims={result.claims} verdicts={result.verdicts} /></div>
                </Panel>

                {fixedDiff && (
                  <Panel testid="fixed" title="Fixed draft · only stale spans changed"
                    right={result.fixed_check && <span className={`rounded-sm px-1.5 py-0.5 text-[11px] ${DECISION_STYLE[result.fixed_check.decision].box}`}>re-check: {result.fixed_check.decision}</span>}>
                    <p className="whitespace-pre-wrap font-sans text-[14px] leading-6">
                      {fixedDiff.map((d, i) => d.t === 'same' ? d.s
                        : d.t === 'del' ? <del key={i} className="mr-0.5 bg-brick-soft text-brick">{d.s}</del>
                        : <ins key={i} className="bg-mint text-forest-deep no-underline">{d.s}</ins>)}
                    </p>
                    <button onClick={() => { setDraft(result.fixed_draft!); setResult(null); setSteps([]) }}
                      className="mt-3 text-[12px] text-forest underline underline-offset-2">Use fixed draft</button>
                  </Panel>
                )}

                <p className="text-[11px] text-muted">
                  {result.pages_checked.length} pages read from {prospect?.domain} · company website only, robots.txt respected · {(result.latency_ms / 1000).toFixed(1)}s
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
