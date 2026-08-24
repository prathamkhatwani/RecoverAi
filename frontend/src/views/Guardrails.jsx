import { useMemo } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { formatMinor, hours, num } from '../lib/format'
import { GUARDRAIL_CATEGORIES, action, verdict as verdictOf } from '../lib/vocab'
import { Empty, ErrorNote, Loading, Panel, Pill, Table, TD, TH, Button } from '../components/ui'
import {
  ShieldAlert,
  ShieldCheck,
  Ban,
  Clock,
  Sliders,
  AlertTriangle,
  UserCheck,
  FileCheck,
  CheckCircle2,
  XCircle,
  Eye,
  Coins
} from 'lucide-react'

const SAMPLE_LIMIT = 500

export default function Guardrails({ runId, onNavigate }) {
  const cat = useApi(() => api.guardrails(), [])
  const latest = useApi(() => api.latestRun(), [], { enabled: !runId })
  const activeRun = runId ?? latest.data?.run_id

  const decisions = useApi(
    () => api.decisions(activeRun, { arm: 'agent', limit: SAMPLE_LIMIT }),
    [activeRun],
    { enabled: Boolean(activeRun) },
  )
  const blocked = useApi(
    () => api.decisions(activeRun, { arm: 'agent', blocked_only: true, limit: 50 }),
    [activeRun],
    { enabled: Boolean(activeRun) },
  )

  const tally = useMemo(() => {
    const acc = {}
    let verdicts = 0
    const rows = decisions.data?.decisions ?? []
    for (const d of rows) {
      for (const g of d.guardrails ?? []) {
        const bucket = (acc[g.id] ??= { pass: 0, block: 0, modify: 0, not_applicable: 0, total: 0 })
        bucket[g.verdict] = (bucket[g.verdict] ?? 0) + 1
        bucket.total += 1
        verdicts += 1
      }
    }
    return { acc, verdicts, sampled: rows.length, total: decisions.data?.total ?? 0 }
  }, [decisions.data])

  if (cat.error) return <ErrorNote error={cat.error} onRetry={cat.reload} />
  if (!cat.data) return <Loading what="Loading the guardrail catalogue" />

  const { catalogue, config, note } = cat.data
  const grouped = GUARDRAIL_CATEGORIES.map((c) => ({
    ...c,
    rules: catalogue.filter((r) => r.category === c.key),
  }))
  const ungrouped = catalogue.filter(
    (r) => !GUARDRAIL_CATEGORIES.some((c) => c.key === r.category),
  )

  return (
    <div className="flex flex-col gap-4">
      {/* Overview Banner */}
      <Panel
        title="Structural Safety Engine"
        icon={ShieldAlert}
        note="Enforced in code, not prompts: Every action proposal must clear the gauntlet before dispatch."
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="max-w-3xl text-[13.5px] leading-relaxed text-ink">
            <strong className="font-bold text-navy">{catalogue.length} structural rules</strong> execute in strict sequential order before any charge or customer touch. A veto is final: no confidence score can override a hard check in code.
          </p>
          {tally.verdicts > 0 && (
            <div className="p-3 bg-surface border border-rule rounded-lg text-center min-w-36">
              <div className="eyebrow text-ink-faint">Verdicts Evaluated</div>
              <div className="mt-1 font-mono text-2xl font-bold text-good">
                {num(tally.verdicts)}
              </div>
              <div className="mt-0.5 text-[11px] text-ink-faint">
                across {num(tally.sampled)} decisions
              </div>
            </div>
          )}
        </div>
        {note && <p className="mt-3 border-t border-rule pt-2.5 text-[12px] leading-relaxed text-ink-soft">{note}</p>}
      </Panel>

      {/* Config Dials Grid */}
      <Panel
        title="Safety Parameters & Thresholds"
        icon={Sliders}
        note="Read directly from /api/meta/guardrails. Immutable by the autonomous agent."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {CONFIG_ROWS.map((r) => (
            <div key={r.label} className="p-3 bg-sunk/60 rounded-lg border border-rule/60 hover:border-rule-strong transition-colors">
              <div className="eyebrow truncate text-ink-faint" title={r.label}>{r.label}</div>
              <div className="mt-1 font-mono text-lg font-bold text-ink">
                {r.read(config)}
              </div>
              {r.note && <div className="mt-1 text-[11px] text-ink-faint leading-snug">{r.note}</div>}
            </div>
          ))}
        </div>
      </Panel>

      {/* The Gauntlet Pipeline */}
      <Panel
        title="The 6-Stage Gauntlet Pipeline"
        icon={ShieldCheck}
        note={
          activeRun
            ? `Verdict counts from Run #${activeRun} · ${num(tally.sampled)} decisions sampled.`
            : 'Run a benchmark to observe live verdict counts across each rule.'
        }
        bleed
      >
        {decisions.loading && <div className="px-5 py-3"><Loading what="Counting verdicts" /></div>}
        <Table>
          <thead>
            <tr>
              <TH>Guardrail Rule</TH>
              <TH>Policy Enforcement Check</TH>
              <TH title="Which rules this can override">Overrides</TH>
              <TH className="w-[220px]">Verdict Composition</TH>
              <TH align="right">Veto Count</TH>
            </tr>
          </thead>
          <tbody>
            {[...grouped, ...(ungrouped.length ? [{ key: 'other', label: 'Other', note: '', rules: ungrouped }] : [])]
              .filter((g) => g.rules.length)
              .map((g, gi) => [
                <tr key={g.key} className="bg-surface-raised/80">
                  <TD colSpan={5} className="border-t border-rule font-bold">
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-navy px-1.5 py-0.2 rounded bg-navy/10">
                        STAGE {String(gi + 1).padStart(2, '0')}
                      </span>
                      <span className="font-display text-[13.5px] font-bold text-ink">{g.label}</span>
                      <span className="text-[12px] text-ink-faint font-normal">— {g.note}</span>
                    </span>
                  </TD>
                </tr>,
                ...g.rules.map((r) => {
                  const t = tally.acc[r.id]
                  return (
                    <tr key={r.id} className="hover:bg-surface-raised/40 transition-colors">
                      <TD>
                        <span className="font-bold text-ink">{r.name}</span>
                        <code className="mt-0.5 block font-mono text-[11px] text-ink-faint">{r.id}</code>
                      </TD>
                      <TD className="max-w-md text-ink-soft text-[12.5px]">{r.description}</TD>
                      <TD className="text-[11.5px] text-ink-faint font-mono">{r.overrides ?? '—'}</TD>
                      <TD>{t ? <VerdictBar counts={t} /> : <span className="text-ink-faint">—</span>}</TD>
                      <TD align="right" mono className={t?.block ? 'text-bad font-bold' : 'text-ink-faint'}>
                        {t ? num(t.block) : '—'}
                      </TD>
                    </tr>
                  )
                }),
              ])}
          </tbody>
        </Table>
      </Panel>

      {/* Refused Actions */}
      <Panel
        title="Enforced Refusals & Suppressions"
        icon={Ban}
        note="Every action vetoed outright by code, proving safe production autonomy."
        bleed
      >
        {!activeRun ? (
          <Empty>
            No run loaded.{' '}
            <button
              type="button"
              onClick={() => onNavigate('scoreboard')}
              className="text-navy underline decoration-navy/40 underline-offset-2 font-medium"
            >
              Run a benchmark
            </button>{' '}
            to populate veto telemetry.
          </Empty>
        ) : blocked.loading ? (
          <Loading what="Loading blocked decisions" />
        ) : blocked.error ? (
          <div className="p-4"><ErrorNote error={blocked.error} onRetry={blocked.reload} /></div>
        ) : (blocked.data?.decisions ?? []).length === 0 ? (
          <Empty>No actions were blocked on this run.</Empty>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <TH>Payment ID</TH>
                  <TH align="right">Amount</TH>
                  <TH>Root Cause</TH>
                  <TH>Proposed Action</TH>
                  <TH>Veto Reason</TH>
                  <TH align="right">Ledger</TH>
                </tr>
              </thead>
              <tbody>
                {blocked.data.decisions.map((d) => (
                  <tr key={d.id} className="hover:bg-surface-raised/40 transition-colors">
                    <TD mono className="text-ink font-medium">{d.payment_id}</TD>
                    <TD align="right" mono className="font-bold">{formatMinor(d.amount_minor, d.currency)}</TD>
                    <TD>
                      <span className="font-medium text-ink">
                        {d.classification?.root_cause?.replace(/_/g, ' ') ?? '—'}
                      </span>
                    </TD>
                    <TD className="text-ink-soft text-[12px]">{action(d.proposed?.action).label}</TD>
                    <TD className="max-w-md">
                      <span className="inline-flex items-center gap-1.5 text-bad font-medium text-[12px] bg-bad-soft px-2 py-0.5 rounded border border-bad/30">
                        <Ban className="size-3 shrink-0" />
                        {d.block_reason ?? firstBlock(d)}
                      </span>
                    </TD>
                    <TD align="right" mono className="text-navy font-bold">#{d.ledger_seq}</TD>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="p-3.5 bg-sunk/40 border-t border-rule text-[12px] text-ink-faint flex items-center justify-between">
              <span>Showing {num(blocked.data.decisions.length)} of {num(blocked.data.total)} blocked decisions.</span>
              <Button size="sm" onClick={() => onNavigate('ledger')}>
                Inspect Audit Ledger →
              </Button>
            </div>
          </>
        )}
      </Panel>
    </div>
  )
}

function VerdictBar({ counts }) {
  const order = ['block', 'modify', 'pass', 'not_applicable']
  const total = counts.total || 1
  const bg = { block: 'bg-bad', modify: 'bg-warn', pass: 'bg-good', not_applicable: 'bg-rule-strong' }
  return (
    <div>
      <div className="flex h-3 gap-0.5 bg-sunk rounded-sm overflow-hidden border border-rule/50">
        {order
          .filter((v) => counts[v])
          .map((v) => (
            <div
              key={v}
              className={`${bg[v]} transition-all duration-300`}
              style={{ width: `${Math.max((counts[v] / total) * 100, 3)}%` }}
              role="img"
              aria-label={`${verdictOf(v).label}: ${counts[v]}`}
              title={`${verdictOf(v).label}: ${counts[v]}`}
            />
          ))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-2.5 text-[11px] font-mono">
        {order
          .filter((v) => counts[v])
          .map((v) => (
            <span key={v} className={verdictOf(v).fg}>
              {verdictOf(v).mark} {num(counts[v])}
            </span>
          ))}
      </div>
    </div>
  )
}

function firstBlock(d) {
  return d.guardrails?.find((g) => g.verdict === 'block')?.detail ?? 'Blocked'
}

const CONFIG_ROWS = [
  {
    label: 'Attempts / Method / Week',
    read: (c) => num(c.max_attempts_per_method_per_week),
  },
  {
    label: 'Attempts / Method / Day',
    read: (c) => num(c.max_attempts_per_method_per_day),
  },
  {
    label: 'Autonomous Exposure Ceiling',
    read: (c) => formatMinor(c.autonomous_exposure_ceiling_minor, 'INR', { compact: true }),
    note: 'Above this requires human sign-off',
  },
  {
    label: 'Daily Autonomous Budget',
    read: (c) => formatMinor(c.daily_autonomous_budget_minor, 'INR', { compact: true }),
    note: 'Max total value agent may act on per day',
  },
  {
    label: 'Customer Quiet Hours',
    read: (c) => `${pad2(c.quiet_hours_start)}–${pad2(c.quiet_hours_end)}`,
    note: 'No touches inside customer local window',
  },
  {
    label: 'Max Nudges / Customer / Week',
    read: (c) => num(c.max_nudges_per_customer_per_week),
  },
  {
    label: 'Min Gap Between Nudges',
    read: (c) => hours(c.min_hours_between_nudges),
  },
  {
    label: 'Escalate After Failed Tries',
    read: (c) => `${c.escalate_after_failed_attempts} attempts`,
    note: 'Then routes to person',
  },
]

function pad2(h) {
  return h == null ? '—' : `${String(h).padStart(2, '0')}:00`
}

