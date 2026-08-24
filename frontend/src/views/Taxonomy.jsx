import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { hours, num, rate } from '../lib/format'
import { ACTION, STANCE, causeColor } from '../lib/vocab'
import { CauseDot, ErrorNote, Loading, Panel, Pill, Table, TD, TH, Button, Input } from '../components/ui'
import {
  ListTree,
  Search,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  AlertCircle,
  Clock,
  ArrowRight,
  Sparkles,
  Layers,
  HelpCircle
} from 'lucide-react'

export default function Taxonomy({ onNavigate }) {
  const matrix = useApi(() => api.policyMatrix(), [])
  const tax = useApi(() => api.taxonomy(), [])
  const [open, setOpen] = useState(null)
  const [query, setQuery] = useState('')

  const rows = useMemo(() => {
    const extra = {}
    for (const t of tax.data?.causes ?? []) extra[t.cause] = t
    return (matrix.data?.matrix ?? []).map((m) => ({ ...m, ...pickExtra(extra[m.cause]) }))
  }, [matrix.data, tax.data])

  const codesByCause = useMemo(() => {
    const grouped = {}
    for (const [code, cause] of Object.entries(tax.data?.decline_codes ?? {})) {
      ;(grouped[cause] ??= []).push(code)
    }
    for (const list of Object.values(grouped)) list.sort()
    return grouped
  }, [tax.data])

  const filteredRows = useMemo(() => {
    if (!query.trim()) return rows
    const q = query.toLowerCase()
    return rows.filter((r) => {
      const nameMatch = r.label.toLowerCase().includes(q) || r.cause.toLowerCase().includes(q)
      const signalMatch = r.signal?.toLowerCase().includes(q)
      const actionMatch = r.primary_action?.toLowerCase().includes(q)
      const codeMatch = (codesByCause[r.cause] ?? []).some((c) => c.toLowerCase().includes(q))
      return nameMatch || signalMatch || actionMatch || codeMatch
    })
  }, [rows, query, codesByCause])

  if (matrix.error) return <ErrorNote error={matrix.error} onRetry={matrix.reload} />
  if (tax.error) return <ErrorNote error={tax.error} onRetry={tax.reload} />
  if (!rows.length) return <Loading what="Loading the diagnostic taxonomy" />

  return (
    <div className="flex flex-col gap-4">
      {/* Overview Banner */}
      <Panel
        title="8-Cause Diagnostic Taxonomy"
        icon={ListTree}
        note="The core IP of the build: Treating diagnosis as the hard problem rather than blindly retrying every failure."
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="max-w-3xl text-[13.5px] leading-relaxed text-ink">
            A failed payment is not a monolithic event. It stems from one of{' '}
            <strong className="font-bold text-navy">{rows.length} distinct root causes</strong>.
            Retry is appropriate for transient system issues, but strictly forbidden for fraud, expired credentials, or 3DS timeouts.
          </p>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-surface border border-rule rounded-lg text-center min-w-28">
              <div className="eyebrow text-ink-faint">Decline Codes</div>
              <div className="mt-1 font-mono text-2xl font-bold text-ink">
                {num(tax.data?.code_count)}
              </div>
            </div>
            <div className="p-3 bg-surface border border-rule rounded-lg text-center min-w-28">
              <div className="eyebrow text-ink-faint">Retry Stances</div>
              <div className="mt-1 font-mono text-2xl font-bold text-ink">
                {new Set(rows.map((r) => r.retry_stance)).size}
              </div>
            </div>
          </div>
        </div>
      </Panel>

      {/* Policy Matrix Table */}
      <Panel
        title="Enforced Policy Matrix"
        icon={ShieldCheck}
        note="Every column is enforced in code. Caps, cooldowns, and retry stances pre-clear or block attempts before dispatch."
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="size-3.5 absolute left-2.5 top-2.5 text-ink-faint" />
              <input
                type="text"
                placeholder="Filter causes & codes…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8 pr-3 py-1 rounded bg-sunk/80 border border-rule text-[12px] font-mono text-ink placeholder:text-ink-faint focus:border-navy focus:outline-none w-48 sm:w-64"
              />
            </div>
          </div>
        }
        bleed
      >
        <Table>
          <thead>
            <tr>
              <TH>Root Cause</TH>
              <TH>Typical Gateway Signal</TH>
              <TH>Retry Stance</TH>
              <TH>Bounded Recovery Action</TH>
              <TH align="right" title="Max charge attempts allowed">Max Tries</TH>
              <TH align="right" title="Minimum cooldown between attempts">Cooldown</TH>
              <TH align="right" title="Case lifetime before abandonment">Lifetime</TH>
              <TH align="right" title="Simulator recovery prior">Prior</TH>
              <TH />
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r) => {
              const expanded = open === r.cause
              const stance = STANCE[r.retry_stance]
              return [
                <tr
                  key={r.cause}
                  onClick={() => setOpen(expanded ? null : r.cause)}
                  className={`cursor-pointer transition-colors ${
                    expanded ? 'bg-sunk/80 font-medium' : 'hover:bg-surface-raised/60'
                  }`}
                >
                  <TD>
                    <span className="flex items-center gap-2">
                      <CauseDot color={causeColor(r.color)} />
                      <span className="font-display text-[13.5px] font-bold text-ink">{r.label}</span>
                      {r.terminal && (
                        <Pill tone="bad" title="No further retry attempts allowed">
                          terminal
                        </Pill>
                      )}
                      {r.requires_repair && (
                        <Pill tone="warn" title="Must repair credential first">
                          repair first
                        </Pill>
                      )}
                    </span>
                  </TD>
                  <TD className="text-ink-soft text-[12.5px]">{r.signal}</TD>
                  <TD>
                    <Pill tone={stance?.tone ?? 'neutral'}>{r.retry_answer}</Pill>
                  </TD>
                  <TD>
                    <span className="text-ink font-medium">{ACTION[r.primary_action]?.label ?? r.primary_action}</span>
                    {r.companion_action && (
                      <span className="text-ink-faint text-[11.5px]">
                        {' + '}
                        {ACTION[r.companion_action]?.label ?? r.companion_action}
                      </span>
                    )}
                  </TD>
                  <TD align="right" mono className="font-semibold">{r.max_attempts}</TD>
                  <TD align="right" mono className="text-ink-soft">
                    {r.cooldown_hours ? hours(r.cooldown_hours) : '—'}
                  </TD>
                  <TD align="right" mono className="text-ink-soft">
                    {r.max_lifetime_days ? `${r.max_lifetime_days} d` : '—'}
                  </TD>
                  <TD align="right" mono className="text-ink-soft">
                    {r.estimated_recovery_prior == null ? '—' : rate(r.estimated_recovery_prior, 0)}
                  </TD>
                  <TD align="right" className="text-ink-faint">
                    {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  </TD>
                </tr>,
                expanded && (
                  <tr key={`${r.cause}-detail`} className="bg-sunk/40">
                    <TD colSpan={9} className="px-0 py-0">
                      <CauseDetail row={r} codes={codesByCause[r.cause] ?? r.codes ?? []} />
                    </TD>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </Table>
      </Panel>

      {/* Decline Code Registry */}
      <Panel
        title="Gateway Decline Code Registry"
        icon={Layers}
        note="Gateways express identical errors in different vocabularies. These codes map deterministically without calling a language model."
        bleed
      >
        <Table>
          <thead>
            <tr>
              <TH>Routes to Cause</TH>
              <TH align="right">Code Count</TH>
              <TH>Inconsistent Gateway Decline Strings</TH>
            </tr>
          </thead>
          <tbody>
            {rows
              .filter((r) => (codesByCause[r.cause] ?? []).length)
              .map((r) => (
                <tr key={r.cause} className="hover:bg-surface-raised/40 transition-colors">
                  <TD>
                    <span className="flex items-center gap-2">
                      <CauseDot color={causeColor(r.color)} />
                      <span className="font-bold text-ink">{r.label}</span>
                    </span>
                  </TD>
                  <TD align="right" mono className="text-ink-soft font-semibold">
                    {codesByCause[r.cause].length}
                  </TD>
                  <TD>
                    <div className="flex flex-wrap gap-1.5 py-1">
                      {codesByCause[r.cause].map((c) => (
                        <code
                          key={c}
                          className="border border-rule bg-surface px-1.5 py-0.5 rounded font-mono text-[11px] text-ink-soft"
                        >
                          {c}
                        </code>
                      ))}
                    </div>
                  </TD>
                </tr>
              ))}
          </tbody>
        </Table>
        <div className="p-4 bg-sunk/40 border-t border-rule text-[12px] text-ink-faint flex items-center justify-between">
          <span>Unregistered strings escalate to the Claude Reasoning Tier for semantic classification.</span>
          <Button size="sm" onClick={() => onNavigate('classify')}>
            Test Decline Strings in Classify →
          </Button>
        </div>
      </Panel>
    </div>
  )
}

function CauseDetail({ row, codes }) {
  return (
    <div className="border-t border-b border-rule-strong p-4 sm:p-5 bg-surface/40">
      {row.description && (
        <p className="max-w-4xl text-[13px] leading-relaxed text-ink">{row.description}</p>
      )}

      <div className="mt-3.5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="border-l-2 border-bad pl-3.5 py-1 bg-bad-soft/40 rounded-r-md">
          <div className="eyebrow text-bad font-bold">Why Blind Retry Fails Here</div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink">{row.why_naive_retry_fails}</p>
        </div>
        <div className="border-l-2 border-baseline pl-3.5 py-1 bg-baseline-soft/40 rounded-r-md">
          <div className="eyebrow text-baseline font-bold">What Blind Retry Does Instead</div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-soft">{row.baseline_behaviour}</p>
        </div>
      </div>

      <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2.5 border-t border-rule pt-3">
        <Fact term="Recovery Approach">{row.recovery_action}</Fact>
        <Fact term="Timing Strategy">{row.timing_strategy}</Fact>
        <Fact term="Network Penalty Weight" mono>
          {row.network_penalty_weight}
          <span className="ml-1 text-ink-faint text-[11.5px]">
            {row.network_penalty_weight >= 1 ? '(heavy penalty)' : ''}
          </span>
        </Fact>
        <Fact term="Severity Tier">{row.severity}</Fact>
        {codes.length > 0 && (
          <Fact term="Mapped Codes">
            <span className="font-mono text-[11.5px] text-navy">{codes.join(', ')}</span>
          </Fact>
        )}
      </dl>
    </div>
  )
}

function Fact({ term, children, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow text-ink-faint">{term}</dt>
      <dd className={`mt-0.5 text-[12.5px] text-ink font-medium ${mono ? 'font-mono' : ''}`}>{children}</dd>
    </div>
  )
}

function pickExtra(t) {
  if (!t) return {}
  return { description: t.description, recovery_action: t.recovery_action, codes: t.codes }
}

