import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { num, timestamp } from '../lib/format'
import { Button, Empty, ErrorNote, Hash, Loading, Panel, Pill } from '../components/ui'
import {
  Database,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RotateCcw,
  CheckCircle2,
  XCircle,
  FileCode,
  Layers,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Zap,
  Lock,
  Unlock,
  KeyRound
} from 'lucide-react'

const PAGE = 40

export default function Ledger({ runId }) {
  const [offset, setOffset] = useState(0)
  const [kind, setKind] = useState('')
  const [scoped, setScoped] = useState(false)
  const [page, setPage] = useState(null)
  const [verification, setVerification] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [p, v] = await Promise.all([
        api.ledger({
          offset,
          limit: PAGE,
          kind: kind || undefined,
          run_id: scoped && runId ? runId : undefined,
        }),
        api.ledgerVerify('memory'),
      ])
      setPage(p)
      setVerification(v)
    } catch (e) {
      setError(e)
    }
  }, [offset, kind, scoped, runId])

  useEffect(() => {
    load()
  }, [load])

  async function tamper() {
    if (!page?.records?.length) return
    const target = page.records[Math.floor(page.records.length / 2)]
    setBusy(true)
    try {
      await api.ledgerTamper(target.seq, 'smart_retry')
      await load()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  async function restore() {
    setBusy(true)
    try {
      await api.ledgerRestore()
      await load()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  const broken = verification && verification.valid === false
  const brokenAt = verification?.first_broken_seq ?? null
  const tamperedSeqs = useMemo(
    () => new Set(verification?.tampered_seqs ?? []),
    [verification],
  )

  const total = page?.total ?? 0
  const kinds = useMemo(() => {
    const seen = new Set(page?.records?.map((r) => r.kind) ?? [])
    return [...KNOWN_KINDS, ...[...seen].filter((k) => !KNOWN_KINDS.includes(k))]
  }, [page])

  return (
    <div className="flex flex-col gap-4">
      {/* Verification Status Banner */}
      <VerifyBanner v={verification} onRestore={restore} busy={busy} />

      {/* Interactive Tamper & Verify Sandbox */}
      <Panel
        title="Cryptographic Tamper Sandbox"
        icon={broken ? Unlock : Lock}
        note="Demonstrates immutable tamper-evidence. Altering any single decision record immediately breaks all subsequent hash links."
        actions={
          <div className="flex gap-2">
            <Button
              tone="danger"
              icon={AlertTriangle}
              onClick={tamper}
              disabled={busy || broken || !page?.records?.length}
            >
              {broken ? 'Chain Altered (Broken)' : 'Simulate Database Tamper'}
            </Button>
            <Button
              tone="primary"
              icon={RotateCcw}
              onClick={restore}
              disabled={busy || !broken}
            >
              Restore & Heal Chain
            </Button>
          </div>
        }
      >
        <p className="text-[13px] leading-relaxed text-ink-soft">
          Each record hash is computed as <code className="font-mono text-ink bg-sunk px-1.5 py-0.5 rounded border border-rule">SHA-256(prev_hash + canonical_json(payload))</code>.
          Tampering with record <span className="font-mono font-bold text-ink">#n</span> invalidates its own stored hash and causes all subsequent records to fail their predecessor integrity checks.
        </p>
        {error && <div className="mt-3"><ErrorNote error={error} onRetry={load} /></div>}
      </Panel>

      {/* The Blockchain Spine */}
      <Panel
        title="Hash-Chained Audit Ledger"
        icon={Database}
        note="Append-only cryptographic timeline. Click any record to inspect the exact payload, predecessor hash, and live verification."
        actions={
          <div className="flex flex-wrap items-center gap-3">
            {runId && (
              <label className="flex items-center gap-1.5 text-[12px] text-ink-soft cursor-pointer">
                <input
                  type="checkbox"
                  checked={scoped}
                  onChange={(e) => {
                    setScoped(e.target.checked)
                    setOffset(0)
                  }}
                  className="size-3.5 accent-navy rounded cursor-pointer"
                />
                <span>Current Run Only</span>
              </label>
            )}
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value)
                setOffset(0)
              }}
              className="border border-rule bg-sunk px-2.5 py-1 rounded font-mono text-[12px] text-ink cursor-pointer"
            >
              <option value="">All Record Types</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {k.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>
        }
        bleed
      >
        {!page ? (
          <div className="px-5 py-6"><Loading what="Loading cryptographic ledger" /></div>
        ) : page.records.length === 0 ? (
          <Empty>No ledger records found for this filter.</Empty>
        ) : (
          <>
            <ol className="px-5 py-3">
              {page.records.map((r, i) => (
                <ChainLink
                  key={r.seq}
                  record={r}
                  prev={page.records[i - 1]}
                  first={i === 0}
                  last={i === page.records.length - 1}
                  broken={brokenAt != null && r.seq >= brokenAt}
                  isBreak={brokenAt != null && r.seq === brokenAt}
                  tampered={tamperedSeqs.has(r.seq)}
                  open={expanded === r.seq}
                  onToggle={() => setExpanded(expanded === r.seq ? null : r.seq)}
                />
              ))}
            </ol>

            {/* Pagination */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule px-5 py-3 bg-surface-raised/40">
              <span className="text-[12px] text-ink-soft">
                Showing records{' '}
                <span className="font-mono font-bold text-ink">
                  {num(page.offset + 1)}–{num(page.offset + page.records.length)}
                </span>{' '}
                of <span className="font-mono font-bold text-ink">{num(total)}</span>
              </span>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}>
                  ← Earlier
                </Button>
                <Button
                  size="sm"
                  onClick={() => setOffset(offset + PAGE)}
                  disabled={offset + PAGE >= total}
                >
                  Later →
                </Button>
                <Button
                  size="sm"
                  onClick={() => setOffset(Math.max(0, (Math.ceil(total / PAGE) - 1) * PAGE))}
                  disabled={offset + PAGE >= total}
                >
                  Chain Head
                </Button>
              </div>
            </div>
          </>
        )}
      </Panel>

      {/* Verification Instructions */}
      <Panel title="Independent Client-Side Verification" icon={KeyRound}>
        <p className="text-[13px] leading-relaxed text-ink-soft">
          Verify the full ledger independently via <code className="font-mono text-navy bg-sunk px-1.5 py-0.5 rounded border border-rule">GET /api/ledger/export</code>.
          Genesis block hash is 64 zeroes. Query individual entries via <code className="font-mono text-navy bg-sunk px-1.5 py-0.5 rounded border border-rule">GET /api/ledger/{'{seq}'}</code> to inspect cryptographic proofs without trusting UI state.
        </p>
      </Panel>
    </div>
  )
}

const KNOWN_KINDS = ['run_open', 'decision', 'attempt', 'run_close']

/* ---------------------------------------------------------------- the banner */

function VerifyBanner({ v, onRestore, busy }) {
  if (!v) return <div className="border border-rule bg-surface p-4 rounded-lg"><Loading what="Verifying cryptographic integrity" /></div>
  const ok = v.valid

  return (
    <section
      className={`glass-panel p-4 sm:p-5 rounded-lg border transition-all ${
        ok ? 'border-good/40 bg-good-soft/30' : 'border-bad/50 bg-bad-soft/40 animate-pulse'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            {ok ? <CheckCircle2 className="size-5 text-good shrink-0" /> : <XCircle className="size-5 text-bad shrink-0" />}
            <h2 className={`font-display text-base font-bold ${ok ? 'text-good' : 'text-bad'}`}>
              {ok ? 'Cryptographic Chain Integrity Verified' : 'Cryptographic Integrity Violation Detected'}
            </h2>
            <Pill tone={ok ? 'good' : 'bad'}>{v.algorithm}</Pill>
          </div>
          <p className="mt-1 text-[13px] text-ink-soft leading-relaxed max-w-3xl">{v.statement}</p>
          {!ok && (
            <p className="mt-1.5 text-[12.5px] text-bad font-medium">
              Broken at Record <span className="font-mono font-bold">#{v.first_broken_seq}</span>
              {v.break_count > 1 && <> · {num(v.break_count)} subsequent downstream records invalidated</>}.
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-6">
          <div className="text-right">
            <div className="eyebrow text-ink-faint">Sealed Records</div>
            <div className="mt-0.5 font-mono text-xl font-bold text-ink">
              {num(v.records)}
            </div>
          </div>
          <div className="text-right min-w-0">
            <div className="eyebrow text-ink-faint">Ledger Head</div>
            <div className="mt-0.5">
              <Hash value={v.head_hash} chars={16} />
            </div>
          </div>
          {!ok && (
            <Button tone="primary" icon={RotateCcw} onClick={onRestore} disabled={busy}>
              Restore Chain
            </Button>
          )}
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ the spine */

function ChainLink({ record: r, first, last, broken, isBreak, tampered, open, onToggle }) {
  const [detail, setDetail] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  useEffect(() => {
    if (!open || detail) return
    let live = true
    setLoadingDetail(true)
    api
      .ledgerRecord(r.seq)
      .then((d) => live && setDetail(d))
      .catch(() => live && setDetail({ error: true }))
      .finally(() => live && setLoadingDetail(false))
    return () => {
      live = false
    }
  }, [open, detail, r.seq])

  return (
    <li className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-3">
      {/* Chain Spine Line */}
      <div className="relative flex justify-center" aria-hidden="true">
        {!first && (
          <span
            className={`absolute top-0 h-[16px] w-0.5 transition-colors ${
              broken && !isBreak ? 'bg-bad/30' : broken ? 'bg-bad' : 'bg-rule-strong'
            }`}
          />
        )}
        <span
          className={`absolute top-[16px] size-2.5 rounded-full ring-2 transition-all ${
            isBreak
              ? 'chain-snap bg-bad ring-bad/40 scale-125'
              : broken
              ? 'bg-surface ring-bad/50'
              : 'bg-navy ring-navy/30'
          }`}
        />
        {!last && (
          <span
            className={`absolute top-[26px] bottom-0 w-0.5 transition-colors ${
              isBreak ? 'bg-transparent' : broken ? 'bg-bad/30' : 'bg-rule-strong'
            }`}
          />
        )}
        {isBreak && (
          <span className="absolute top-[28px] font-mono text-[13px] font-bold text-bad">
            ⁄⁄
          </span>
        )}
      </div>

      {/* Record Row */}
      <div className={`min-w-0 border-b border-rule/50 py-2.5 ${broken ? 'opacity-95' : ''}`}>
        <button
          type="button"
          onClick={onToggle}
          className="flex w-full flex-wrap items-center gap-x-2.5 gap-y-1 text-left cursor-pointer group"
          aria-expanded={open}
        >
          <span className="font-mono text-[12px] font-bold text-ink-soft group-hover:text-navy transition-colors">
            #{r.seq}
          </span>
          <Pill tone={KIND_TONE[r.kind] ?? 'neutral'}>{r.kind.replace(/_/g, ' ')}</Pill>
          {r.arm && (
            <Pill tone={r.arm === 'agent' ? 'agent' : 'baseline'}>{r.arm}</Pill>
          )}
          <span className="min-w-0 flex-1 truncate text-[13px] text-ink font-medium">{r.summary}</span>
          <span className="font-mono text-[11px] text-ink-faint">
            {timestamp(r.recorded_at, { withDate: false })}
          </span>
          <Hash value={r.entry_hash} chars={10} copyable={false} />
          {tampered && <Pill tone="bad">Tampered</Pill>}
          {isBreak && <Pill tone="bad">Chain Broken Here</Pill>}
          {broken && !isBreak && <Pill tone="warn">Invalidated Downstream</Pill>}
          {open ? <ChevronDown className="size-4 text-ink-faint" /> : <ChevronRight className="size-4 text-ink-faint" />}
        </button>

        {open && (
          <div className="mt-2.5 border border-rule rounded-lg bg-surface-raised/80 p-3.5 animate-in fade-in">
            {loadingDetail ? (
              <Loading what="Fetching cryptographic record proof" />
            ) : detail?.error ? (
              <p className="text-[12px] text-bad">Could not load record #{r.seq}.</p>
            ) : (
              <>
                <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-3 bg-sunk/60 rounded-lg border border-rule mb-3">
                  <HashFact term="Predecessor Hash" value={r.prev_hash} />
                  <HashFact term="Stored Hash" value={r.entry_hash} />
                  <HashFact term="Live Recomputed Hash" value={detail?.recomputed_hash} />
                  <div>
                    <dt className="eyebrow text-ink-faint">Cryptographic Match</dt>
                    <dd className="mt-1">
                      <Pill tone={detail?.matches ? 'good' : 'bad'}>
                        {detail?.matches ? '✓ Hash Agrees' : '✕ Hash Mismatch'}
                      </Pill>
                    </dd>
                  </div>
                </dl>

                <div>
                  <div className="flex items-center justify-between">
                    <span className="eyebrow text-ink-faint flex items-center gap-1.5">
                      <FileCode className="size-3.5" /> Sealed Payload (Canonical JSON)
                    </span>
                  </div>
                  <pre className="mt-1.5 max-h-72 overflow-auto rounded-lg border border-rule bg-sunk p-3 font-mono text-[11.5px] leading-relaxed text-ink">
                    {JSON.stringify(detail?.record?.payload ?? {}, null, 2)}
                  </pre>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

function HashFact({ term, value, chars = 16 }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow text-ink-faint">{term}</dt>
      <dd className="mt-1">
        <Hash value={value} chars={chars} className="text-[11.5px]" />
      </dd>
    </div>
  )
}

const KIND_TONE = {
  run_open: 'neutral',
  run_close: 'neutral',
  decision: 'agent',
  attempt: 'warn',
}

