import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { formatMinor, num, rate, timestamp } from '../lib/format'
import { action, causeColor, tier as tierOf } from '../lib/vocab'
import {
  Button,
  CauseDot,
  Check,
  Empty,
  Field,
  Input,
  Panel,
  Pill,
  Stat,
  Drawer,
  Hash,
} from '../components/ui'
import {
  Play,
  Square,
  Activity,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  Zap,
  Sparkles,
  Search,
  Sliders,
  ChevronRight,
  Clock,
  ArrowRight,
  TrendingUp,
  CreditCard,
  Plus
} from 'lucide-react'

const MAX_ROWS = 200

const SCENARIOS = [
  { label: 'Standard Stream', count: 40, pace: 40, seed: '20260824', desc: 'Balanced 40-failure realistic mix (Fast 40ms pace)' },
  { label: 'Payday Surge', count: 80, pace: 20, seed: '881293', desc: 'High volume with insufficient funds spikes (Turbo 20ms pace)' },
  { label: 'Edge-Case Chaos', count: 60, pace: 50, seed: '994411', desc: 'Heavy ambiguous strings & gateway errors' },
]

export default function LiveTriage({ setRunId, onNavigate, health }) {
  const taxonomy = useApi(() => api.taxonomy(), [])
  const causeMeta = useMemo(() => {
    const map = {}
    for (const row of taxonomy.data?.causes ?? []) {
      map[row.cause] = { label: row.label, color: causeColor(row.color) }
    }
    return map
  }, [taxonomy.data])

  const [running, setRunning] = useState(false)
  const [rows, setRows] = useState([])
  const [meta, setMeta] = useState(null)
  const [totals, setTotals] = useState(null)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  const [selectedCase, setSelectedCase] = useState(null)
  const [filterCause, setFilterCause] = useState('')

  const [customOpen, setCustomOpen] = useState(false)
  const [customCode, setCustomCode] = useState('CARD_EXPIRED')
  const [customMessage, setCustomMessage] = useState('Card expiration date passed')
  const [customGateway, setCustomGateway] = useState('orbitpg')
  const [customAmount, setCustomAmount] = useState('1499.00')
  const [customType, setCustomType] = useState('card')
  const [customSubmitting, setCustomSubmitting] = useState(false)

  const [eventCount, setEventCount] = useState(40)
  const [intervalMs, setIntervalMs] = useState(40)
  const [seed, setSeed] = useState('20260824')
  const [useLlm, setUseLlm] = useState(false)

  const esRef = useRef(null)
  const llmAvailable = health?.llm_mode === 'live'

  const stop = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setRunning(false)
  }, [])

  useEffect(() => stop, [stop])

  const handleCustomSubmit = async (e) => {
    e?.preventDefault()
    setCustomSubmitting(true)
    try {
      const amountMinor = Math.round(Number(customAmount || 0) * 100)
      const res = await api.classify({
        raw_code: customCode,
        raw_message: customMessage,
        gateway: customGateway,
        amount_minor: amountMinor,
        use_llm: useLlm && llmAvailable,
      })

      const customEvent = {
        index: rows.length + 1,
        event: {
          id: `custom_${Date.now()}`,
          gateway: customGateway,
          raw_code: customCode,
          raw_message: customMessage,
          occurred_at: new Date().toISOString(),
        },
        amount_minor: amountMinor,
        currency: 'INR',
        method: { type: customType, last4: '9988' },
        truth: res.classification?.root_cause,
        decision: {
          classification: res.classification,
          final_action: res.plan?.action,
          blocked: res.plan?.requires_human_signoff,
          block_reason: res.plan?.requires_human_signoff ? 'Human Sign-off Required' : null,
        },
      }

      setRows((prev) => [customEvent, ...prev])
      setCustomOpen(false)
    } catch (err) {
      alert(`Ingest failed: ${err.message}`)
    } finally {
      setCustomSubmitting(false)
    }
  }

  const start = useCallback(() => {
    stop()
    setRows([])
    setTotals(null)
    setSummary(null)
    setError(null)
    setMeta(null)

    const url = api.streamUrl({
      eventCount: Number(eventCount),
      seed: seed === '' ? null : Number(seed),
      useLlm: useLlm && llmAvailable,
      intervalMs: Number(intervalMs),
    })
    const es = new EventSource(url)
    esRef.current = es
    setRunning(true)

    es.addEventListener('run_start', (e) => {
      const d = JSON.parse(e.data)
      setMeta(d)
      setRunId?.(d.run_id)
    })

    es.addEventListener('case', (e) => {
      const d = JSON.parse(e.data)
      setTotals(d.running_totals)
      setRows((prev) => {
        const next = [d, ...prev]
        return next.length > MAX_ROWS ? next.slice(0, MAX_ROWS) : next
      })
    })

    es.addEventListener('run_end', (e) => {
      setSummary(JSON.parse(e.data))
      stop()
    })

    es.onerror = () => {
      setError('The stream dropped. The backend may have restarted — start it again.')
      stop()
    }
  }, [eventCount, intervalMs, seed, useLlm, llmAvailable, setRunId, stop])

  const applyScenario = (sc) => {
    setEventCount(sc.count)
    setIntervalMs(sc.pace)
    setSeed(sc.seed)
  }

  const judged = rows.filter((r) => r.decision?.classification?.root_cause)
  const correct = judged.filter(
    (r) => r.decision.classification.root_cause === r.truth,
  ).length
  const liveAccuracy = judged.length ? correct / judged.length : null

  const filteredRows = useMemo(() => {
    if (!filterCause) return rows
    return rows.filter((r) => r.decision?.classification?.root_cause === filterCause || r.truth === filterCause)
  }, [rows, filterCause])

  return (
    <div className="flex flex-col gap-4">
      {/* Stream Control Panel */}
      <Panel
        title="Live Ingestion & Diagnostic Triage"
        icon={Activity}
        badge={
          running ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-good bg-good/10 px-2 py-0.5 rounded border border-good/30">
              <span className="size-1.5 rounded-full bg-good pulse-beacon" /> Streaming Live
            </span>
          ) : null
        }
        note="Streams real payment failures from 3 gateways. The classifier diagnoses each failure and routes it to exactly one bounded action under guardrails."
        actions={
          <div className="flex items-center gap-2">
            <Button tone="default" icon={Plus} onClick={() => setCustomOpen(true)}>
              Ingest Custom Failure
            </Button>
            {running ? (
              <Button tone="danger" icon={Square} onClick={stop}>
                Stop Stream
              </Button>
            ) : (
              <Button tone="primary" icon={Play} onClick={start}>
                Start Stream
              </Button>
            )}
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Failures Count">
              <Input type="number" min={1} max={400} value={eventCount} onChange={setEventCount} className="w-24" />
            </Field>
            <Field label="Pace (ms)" hint="Delay per event">
              <Input type="number" min={0} max={5000} step={20} value={intervalMs} onChange={setIntervalMs} className="w-24" />
            </Field>
            <Field label="Random Seed" hint="Fixed for reproducibility">
              <Input value={seed} onChange={setSeed} placeholder="random" className="w-32" />
            </Field>
            <div className="pb-1">
              <Check
                label="Use Claude Reasoning Tier"
                checked={useLlm && llmAvailable}
                onChange={setUseLlm}
                hint={llmAvailable ? 'Live LLM resolves ambiguous remainder' : 'Deterministic reasoner stands in (no API key)'}
              />
            </div>
          </div>

          {/* Quick Scenario Buttons */}
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-rule/60 text-[12px] text-ink-soft">
            <span className="eyebrow text-ink-faint">Presets:</span>
            {SCENARIOS.map((sc) => (
              <button
                key={sc.label}
                type="button"
                onClick={() => applyScenario(sc)}
                title={sc.desc}
                className="px-2.5 py-1 rounded bg-surface border border-rule hover:border-navy hover:text-navy text-[11.5px] font-medium transition-colors cursor-pointer"
              >
                {sc.label} ({sc.count} ev)
              </button>
            ))}
          </div>
        </div>

        {error && <p className="mt-3 border border-bad/30 bg-bad/6 px-3 py-2 text-[12.5px] text-bad rounded">{error}</p>}
      </Panel>

      {/* Real-time KPI Metric Cards */}
      {(meta || totals || rows.length > 0) && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat
            label="Failures Ingested"
            value={num(rows.length)}
            sub={meta ? `of ${num(meta.event_count)} queued` : 'real-time total'}
            icon={CreditCard}
          />
          <Stat
            label="Cases Recovered"
            value={num(totals?.recovered ?? 0)}
            tone="good"
            sub="closed paid"
            icon={CheckCircle2}
            delta={rows.length > 0 ? `${rate((totals?.recovered ?? 0) / rows.length, 0)}` : null}
          />
          <Stat
            label="Revenue Saved"
            value={formatMinor(totals?.recovered_minor ?? 0, 'INR', { compact: true })}
            tone="good"
            sub={meta ? `of ${formatMinor(meta.total_at_risk_minor, 'INR', { compact: true })} at risk` : 'recovered'}
            icon={TrendingUp}
          />
          <Stat
            label="Network Charges"
            value={num(totals?.charges ?? 0)}
            sub="dispatched to issuers"
            icon={Activity}
          />
          <Stat
            label="Actions Suppressed"
            value={num(totals?.suppressed ?? 0)}
            tone="warn"
            sub="guardrail vetoes"
            icon={AlertTriangle}
          />
          <Stat
            label="Live Diagnostic Accuracy"
            value={liveAccuracy === null ? '—' : rate(liveAccuracy)}
            tone={liveAccuracy > 0.85 ? 'good' : 'ink'}
            sub={`${correct}/${judged.length} matched truth`}
            icon={ShieldCheck}
          />
        </div>
      )}

      {/* Stream Complete Banner */}
      {summary && (
        <div className="border border-navy/30 bg-navy/10 rounded-lg p-4 transition-all animate-in fade-in">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span className="eyebrow text-navy flex items-center gap-1.5">
                <CheckCircle2 className="size-4" /> Stream Completed
              </span>
              <p className="mt-1 text-[13.5px] font-medium text-ink">
                Recovered <strong className="text-good">{num(summary.totals.recovered)} cases</strong> (
                {formatMinor(summary.totals.recovered_minor, 'INR', { compact: true })}) · {num(summary.ledger_records)} cryptographic ledger records sealed.
              </p>
            </div>
            <Button tone="primary" icon={ArrowRight} onClick={() => onNavigate('scoreboard')}>
              View Benchmark Scoreboard
            </Button>
          </div>
        </div>
      )}

      {/* Diagnosis Gutter */}
      <Panel
        title="Live Diagnosis Gutter"
        icon={Zap}
        note="Side-by-side: Raw Gateway decline string vs Root-cause diagnosis, reasoning tier, confidence, and cleared recovery action."
        actions={
          rows.length > 0 && (
            <div className="flex items-center gap-2">
              <select
                value={filterCause}
                onChange={(e) => setFilterCause(e.target.value)}
                className="border border-rule bg-sunk px-2 py-1 rounded text-[11.5px] font-mono text-ink"
              >
                <option value="">All Causes ({rows.length})</option>
                {Object.keys(causeMeta).map((c) => (
                  <option key={c} value={c}>
                    {causeMeta[c].label}
                  </option>
                ))}
              </select>
            </div>
          )
        }
        bleed
      >
        {rows.length === 0 ? (
          <Empty>Start the stream above to watch real-time payment triage in action.</Empty>
        ) : (
          <ul className="divide-y divide-rule/60">
            {filteredRows.map((r) => (
              <CaseRow
                key={`${r.event.id}-${r.index}`}
                row={r}
                causeMeta={causeMeta}
                onClick={() => setSelectedCase(r)}
              />
            ))}
          </ul>
        )}
      </Panel>

      {/* Drill-down Inspection Drawer */}
      <Drawer
        open={Boolean(selectedCase)}
        onClose={() => setSelectedCase(null)}
        title={`Payment Event #${selectedCase?.event?.id?.slice(0, 12)}`}
        subtitle={`Ingested from ${selectedCase?.event?.gateway?.toUpperCase()} at ${timestamp(selectedCase?.event?.occurred_at)}`}
      >
        {selectedCase && (
          <div className="flex flex-col gap-4 text-[13px]">
            {/* Amount & Method Summary */}
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-sunk/60 border border-rule">
              <div>
                <span className="eyebrow">Amount</span>
                <div className="font-mono text-lg font-bold text-ink mt-0.5">
                  {formatMinor(selectedCase.amount_minor, selectedCase.currency)}
                </div>
              </div>
              <div>
                <span className="eyebrow">Payment Method</span>
                <div className="font-mono text-sm text-ink mt-0.5">
                  {selectedCase.method.type} {selectedCase.method.last4 && `(••${selectedCase.method.last4})`}
                </div>
              </div>
            </div>

            {/* Gateway raw response */}
            <div className="border border-rule rounded-lg p-3 bg-surface">
              <span className="eyebrow text-ink-faint">Raw Gateway Payload</span>
              <div className="mt-1.5 p-2 bg-sunk rounded font-mono text-[12px] text-ink">
                <div>Decline Code: <strong className="text-bad">{selectedCase.event.raw_code}</strong></div>
                <div>Decline Message: <span className="text-ink-soft">“{selectedCase.event.raw_message}”</span></div>
                {selectedCase.event.http_status && <div>HTTP Status: {selectedCase.event.http_status}</div>}
              </div>
            </div>

            {/* Diagnosis Result */}
            <div className="border border-rule rounded-lg p-3 bg-surface">
              <span className="eyebrow text-navy">Diagnostic Resolution</span>
              <div className="mt-2 flex items-center gap-2">
                <CauseDot color={causeMeta[selectedCase.decision?.classification?.root_cause]?.color ?? causeColor()} />
                <span className="font-display text-base font-bold text-ink">
                  {causeMeta[selectedCase.decision?.classification?.root_cause]?.label ?? selectedCase.decision?.classification?.root_cause}
                </span>
                <Pill tone={selectedCase.decision?.classification?.root_cause === selectedCase.truth ? 'good' : 'bad'}>
                  {selectedCase.decision?.classification?.root_cause === selectedCase.truth ? 'Matches Ground Truth' : `Ground Truth: ${selectedCase.truth}`}
                </Pill>
              </div>
              {selectedCase.decision?.classification?.rationale && (
                <p className="mt-2 text-[12.5px] text-ink-soft leading-relaxed p-2.5 bg-sunk/40 rounded border border-rule/40">
                  {selectedCase.decision.classification.rationale}
                </p>
              )}
            </div>

            {/* Guardrail & Action */}
            <div className="border border-rule rounded-lg p-3 bg-surface">
              <span className="eyebrow text-agent">Executed Action & Policy</span>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Pill tone={selectedCase.decision?.blocked ? 'bad' : 'agent'}>
                  {selectedCase.decision?.blocked ? 'Suppressed by Guardrails' : action(selectedCase.decision?.final_action).label}
                </Pill>
                {selectedCase.decision?.blocked && selectedCase.decision?.block_reason && (
                  <span className="text-bad font-medium text-[12px]">{selectedCase.decision.block_reason}</span>
                )}
              </div>
            </div>

            {/* Cryptographic Ledger Link */}
            {selectedCase.ledger_seq != null && (
              <div className="p-3 rounded-lg bg-navy/5 border border-navy/20 flex items-center justify-between">
                <div>
                  <span className="eyebrow text-navy">Audit Ledger Entry</span>
                  <div className="font-mono text-sm font-bold text-ink">Record #{selectedCase.ledger_seq}</div>
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    setSelectedCase(null)
                    onNavigate('ledger')
                  }}
                >
                  Inspect in Ledger →
                </Button>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* Custom Failure Ingestion Drawer */}
      <Drawer
        open={customOpen}
        onClose={() => setCustomOpen(false)}
        title="Ingest Custom Payment Failure"
        subtitle="Manually input a custom decline string or code to test real-time triage."
      >
        <form onSubmit={handleCustomSubmit} className="flex flex-col gap-4 text-[13px]">
          <Field label="Decline Code" hint="Raw code from payment gateway (e.g. CARD_EXPIRED, 51, RC-91)">
            <Input value={customCode} onChange={setCustomCode} placeholder="CARD_EXPIRED" />
          </Field>

          <Field label="Decline Message" hint="Free-text error message returned by processor">
            <textarea
              value={customMessage}
              onChange={(e) => setCustomMessage(e.target.value)}
              rows={2}
              className="w-full rounded border border-rule bg-sunk/60 px-3 py-2 font-mono text-[13px] text-ink focus:border-navy focus:outline-none"
              placeholder="Transaction failed due to expired card"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Gateway">
              <select
                value={customGateway}
                onChange={(e) => setCustomGateway(e.target.value)}
                className="border border-rule bg-sunk px-2.5 py-1.5 rounded font-mono text-[13px] text-ink cursor-pointer"
              >
                <option value="orbitpg">OrbitPG</option>
                <option value="stripe">Stripe</option>
                <option value="razorpay">Razorpay</option>
              </select>
            </Field>

            <Field label="Amount (₹)">
              <Input value={customAmount} onChange={setCustomAmount} placeholder="1499.00" />
            </Field>
          </div>

          <Field label="Payment Method">
            <select
              value={customType}
              onChange={(e) => setCustomType(e.target.value)}
              className="border border-rule bg-sunk px-2.5 py-1.5 rounded font-mono text-[13px] text-ink cursor-pointer"
            >
              <option value="card">Credit / Debit Card</option>
              <option value="upi">UPI Auto-Pay</option>
              <option value="mandate">E-Mandate / NACH</option>
              <option value="netbanking">Net Banking</option>
            </select>
          </Field>

          <div className="pt-3 border-t border-rule flex justify-end gap-2">
            <Button tone="subtle" onClick={() => setCustomOpen(false)}>
              Cancel
            </Button>
            <Button tone="primary" type="submit" icon={Plus} disabled={customSubmitting}>
              {customSubmitting ? 'Ingesting…' : 'Submit Custom Failure'}
            </Button>
          </div>
        </form>
      </Drawer>
    </div>
  )
}

function CaseRow({ row, causeMeta, onClick }) {
  const d = row.decision
  const c = d?.classification
  const cause = c?.root_cause
  const hit = cause && cause === row.truth
  const t = tierOf(c?.tier)
  const blocked = d?.blocked
  const finalAction = action(d?.final_action)
  const named = (key) => causeMeta[key]?.label ?? key?.replace(/_/g, ' ')

  const gatewayBadge = (gw) => {
    const g = String(gw).toLowerCase()
    if (g.includes('razorpay')) return <span className="px-1.5 py-0.2 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10.5px] font-mono font-medium">Razorpay</span>
    if (g.includes('stripe')) return <span className="px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[10.5px] font-mono font-medium">Stripe</span>
    return <span className="px-1.5 py-0.2 rounded bg-teal-500/10 text-teal-400 border border-teal-500/20 text-[10.5px] font-mono font-medium">OrbitPG</span>
  }

  return (
    <li
      onClick={onClick}
      className="row-in grid grid-cols-1 gap-3 px-4 py-3 sm:px-5 hover:bg-surface-raised/80 cursor-pointer transition-colors lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]"
    >
      {/* What the gateway returned */}
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-ink-faint flex items-center gap-1">
            <Clock className="size-3" />
            {timestamp(row.event.occurred_at, { withDate: false })}
          </span>
          {gatewayBadge(row.event.gateway)}
          <span className="font-mono text-[11.5px] text-ink-soft bg-sunk px-1.5 py-0.2 rounded">{row.method.type}</span>
          {row.method.last4 && <span className="font-mono text-[11px] text-ink-faint">••{row.method.last4}</span>}
          <span className="ml-auto font-mono text-[13px] font-semibold text-ink">
            {formatMinor(row.amount_minor, row.currency)}
          </span>
        </div>
        <div className="mt-1.5 border-l-2 border-rule-strong pl-2.5 py-0.5">
          <code className="block font-mono text-[12px] font-medium leading-snug break-words text-ink">
            {row.event.raw_code}
            {row.event.http_status != null && (
              <span className="text-ink-faint font-normal"> · HTTP {row.event.http_status}</span>
            )}
          </code>
          <p className="mt-0.5 font-mono text-[11.5px] leading-snug break-words text-ink-faint italic">
            “{row.event.raw_message}”
          </p>
        </div>
      </div>

      {/* What the system diagnosed & acted on */}
      <div className="min-w-0 lg:border-l lg:border-rule lg:pl-4">
        <div className="flex flex-wrap items-center gap-2">
          {cause ? (
            <>
              <CauseDot color={causeMeta[cause]?.color ?? causeColor()} />
              <span className="font-display text-[13.5px] font-bold text-ink">{named(cause)}</span>
              <Pill tone={hit ? 'good' : 'bad'} title="Scored live against ground truth">
                {hit ? '✓ matches truth' : `truth: ${named(row.truth)}`}
              </Pill>
            </>
          ) : (
            <span className="font-display text-[13.5px] font-semibold text-ink-faint">No diagnosis</span>
          )}
          <span className="ml-auto flex items-center gap-2">
            <Pill title={t.note}>{t.label}</Pill>
            {c?.confidence != null && (
              <span className="font-mono text-[11.5px] text-ink-soft">{rate(c.confidence, 0)}</span>
            )}
          </span>
        </div>

        {c?.rationale && (
          <p className="mt-1 text-[11.5px] leading-snug text-ink-soft line-clamp-1">{c.rationale}</p>
        )}

        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <Pill tone={blocked ? 'bad' : 'agent'} title={finalAction.note}>
            {blocked ? 'Suppressed' : finalAction.label}
          </Pill>
          {d?.modified && <Pill tone="warn">Modified</Pill>}
          {d?.escalated && <Pill tone="warn">Escalated</Pill>}
          {blocked && d?.block_reason && (
            <span className="text-[11px] text-bad font-medium truncate max-w-xs">{d.block_reason}</span>
          )}
          {row.ledger_seq != null && (
            <span className="ml-auto font-mono text-[11px] text-ink-faint">#{row.ledger_seq}</span>
          )}
        </div>
      </div>
    </li>
  )
}

