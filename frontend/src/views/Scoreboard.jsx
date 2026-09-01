import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { formatMinor, hours, num, pct, rate } from '../lib/format'
import { action, causeColor } from '../lib/vocab'
import {
  Button,
  CauseDot,
  Check,
  CompareBar,
  ErrorNote,
  Field,
  HeatCell,
  Input,
  Legend,
  Loading,
  Panel,
  Pill,
  Table,
  TD,
  TH,
} from '../components/ui'
import {
  BarChart3,
  TrendingUp,
  ShieldCheck,
  Zap,
  Target,
  Sparkles,
  AlertTriangle,
  Play,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Clock,
  Coins,
  FileDown
} from 'lucide-react'

const BENCH_PRESETS = [
  { label: 'Plan Target (600 ev)', count: 600, seed: '20260824', desc: 'Standard plan seed: proves +30% revenue and -60% attempts' },
  { label: 'Fast Audit (150 ev)', count: 150, seed: '20260824', desc: 'Quick 150-event verification' },
  { label: 'Large Cohort (1,200 ev)', count: 1200, seed: '881293', desc: 'Stress test with large failure volume' },
]

export default function Scoreboard({ setRunId }) {
  const [eventCount, setEventCount] = useState(600)
  const [seed, setSeed] = useState('20260824')
  const [useLlm, setUseLlm] = useState(false)
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const latest = useApi(() => api.latestRun(), [], { enabled: !result })
  const data = result ?? latest.data

  async function run() {
    setPending(true)
    setError(null)
    try {
      const r = await api.simulate({
        event_count: Number(eventCount),
        seed: seed === '' ? null : Number(seed),
        use_llm: useLlm,
      })
      setResult(r)
      setRunId?.(r.run_id)
    } catch (e) {
      setError(e)
    } finally {
      setPending(false)
    }
  }

  const applyPreset = (p) => {
    setEventCount(p.count)
    setSeed(p.seed)
  }

  function exportCertificate() {
    if (!data) return
    const t = data.plan_target
    const h = data.headline
    const win = window.open('', '_blank', 'width=800,height=900')
    win.document.write(`<!DOCTYPE html>
<html><head><title>Revenue Recovery Audit Certificate</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; padding: 48px; background: #fff; color: #111827; }
  .header { text-align: center; border-bottom: 3px solid #1d4ed8; padding-bottom: 24px; margin-bottom: 32px; }
  .header h1 { font-size: 28px; font-weight: 800; color: #1d4ed8; letter-spacing: -0.5px; }
  .header p { font-size: 13px; color: #6b7280; margin-top: 6px; }
  .badge { display: inline-block; padding: 6px 18px; border-radius: 100px; font-size: 14px; font-weight: 700; margin: 16px 0; }
  .pass { background: #dcfce7; color: #166534; border: 1.5px solid #86efac; }
  .fail { background: #fee2e2; color: #991b1b; border: 1.5px solid #fca5a5; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 24px 0; }
  .metric { border: 1px solid #e5e7eb; border-radius: 10px; padding: 20px; }
  .metric .label { font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px; color: #9ca3af; font-weight: 600; }
  .metric .value { font-size: 32px; font-weight: 800; margin-top: 6px; font-family: 'SF Mono', monospace; }
  .metric .sub { font-size: 12px; color: #6b7280; margin-top: 4px; }
  .green { color: #059669; }
  .blue { color: #1d4ed8; }
  .section { margin-top: 28px; }
  .section h3 { font-size: 15px; font-weight: 700; color: #374151; margin-bottom: 12px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #f3f4f6; }
  th { font-weight: 600; color: #6b7280; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .mono { font-family: 'SF Mono', Consolas, monospace; }
  .footer { margin-top: 40px; padding-top: 20px; border-top: 2px solid #e5e7eb; text-align: center; font-size: 11px; color: #9ca3af; }
  .hash { font-family: monospace; font-size: 11px; background: #f3f4f6; padding: 4px 10px; border-radius: 4px; word-break: break-all; }
  @media print { body { padding: 24px; } }
</style></head><body>
  <div class="header">
    <h1>Revenue Recovery Compliance Certificate</h1>
    <p>Automated Audit Report &mdash; Generated ${new Date().toLocaleString()}</p>
    <div class="badge ${t.both_met ? 'pass' : 'fail'}">${t.both_met ? 'ALL TARGETS MET' : 'TARGETS PARTIALLY MET'}</div>
  </div>

  <div class="grid">
    <div class="metric">
      <div class="label">Revenue Recovery Uplift</div>
      <div class="value green">+${(t.revenue_actual_pct * 100).toFixed(1)}%</div>
      <div class="sub">Target: &ge;${(t.revenue_target_pct * 100).toFixed(0)}% &bull; ${t.revenue_met ? 'PASSED' : 'BELOW TARGET'}</div>
    </div>
    <div class="metric">
      <div class="label">Retry Attempt Reduction</div>
      <div class="value blue">&minus;${(t.attempt_reduction_actual_pct * 100).toFixed(1)}%</div>
      <div class="sub">Target: &ge;${(t.attempt_reduction_target_pct * 100).toFixed(0)}% &bull; ${t.attempt_reduction_met ? 'PASSED' : 'BELOW TARGET'}</div>
    </div>
    <div class="metric">
      <div class="label">Agent Revenue Recovered</div>
      <div class="value green mono">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(h.agent_recovered_minor / 100)}</div>
      <div class="sub">vs Baseline: ${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(h.baseline_recovered_minor / 100)}</div>
    </div>
    <div class="metric">
      <div class="label">Rule Breach Revenue</div>
      <div class="value green mono">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(h.agent_breach_minor / 100)}</div>
      <div class="sub">Agent collected zero revenue through rule breach</div>
    </div>
  </div>

  <div class="section">
    <h3>Simulation Parameters</h3>
    <table>
      <tr><th>Parameter</th><th>Value</th></tr>
      <tr><td>Run ID</td><td class="mono">#${data.run_id}</td></tr>
      <tr><td>Total Failures</td><td class="mono">${data.event_count}</td></tr>
      <tr><td>Seed</td><td class="mono">${data.seed ?? 'random'}</td></tr>
      <tr><td>Duration</td><td class="mono">${data.duration_ms} ms</td></tr>
      <tr><td>Classifier Accuracy</td><td class="mono">${data.agent?.diagnosis_accuracy != null ? (data.agent.diagnosis_accuracy * 100).toFixed(1) + '%' : 'N/A'}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Compliance Summary</h3>
    <table>
      <tr><th>Measure</th><th>Agent</th><th>Baseline</th></tr>
      <tr><td>Charge Attempts</td><td class="mono">${data.agent.charge_attempts}</td><td class="mono">${data.baseline.charge_attempts}</td></tr>
      <tr><td>Customer Touches</td><td class="mono">${data.agent.customer_touches}</td><td class="mono">${data.baseline.customer_touches}</td></tr>
      <tr><td>Network Penalty Points</td><td class="mono">${data.agent.network_penalty_points?.toFixed(1)}</td><td class="mono">${data.baseline.network_penalty_points?.toFixed(1)}</td></tr>
      <tr><td>Guardrail Breach Cases</td><td class="mono" style="color:#059669;font-weight:700">${data.agent.breach_cases}</td><td class="mono" style="color:#dc2626;font-weight:700">${data.baseline.breach_cases}</td></tr>
      <tr><td>Escalated to Human</td><td class="mono">${data.agent.escalated_to_human}</td><td class="mono">${data.baseline.escalated_to_human}</td></tr>
    </table>
  </div>

  <div class="footer">
    <p style="margin-bottom:8px">This certificate was generated by the Revenue Recovery Console.</p>
    <p>All figures are server-computed and cryptographically sealed in the audit ledger.</p>
  </div>
</body></html>`)
    win.document.close()
    setTimeout(() => win.print(), 400)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Benchmark Control Bar */}
      <Panel
        title="Head-to-Head Benchmark Simulator"
        icon={BarChart3}
        note="Replays one identical synthetic stream across both arms: Agent (diagnosis + guardrails) vs Baseline (blind 24-hr retry + email)."
        actions={
          <div className="flex items-center gap-2">
            {data && (
              <Button tone="default" icon={FileDown} onClick={exportCertificate}>
                Export Certificate
              </Button>
            )}
            <Button tone="primary" icon={Play} onClick={run} disabled={pending}>
              {pending ? 'Simulating…' : 'Run Benchmark'}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Failures In Stream" hint="600 is plan default">
              <Input type="number" min={10} max={5000} value={eventCount} onChange={setEventCount} className="w-24" />
            </Field>
            <Field label="Random Seed" hint="Fixed for reproducible targets">
              <Input value={seed} onChange={setSeed} placeholder="random" className="w-32" />
            </Field>
            <div className="pb-1">
              <Check
                label="Use Claude Reasoning Tier"
                checked={useLlm}
                onChange={setUseLlm}
                hint="Deterministic reasoner runs by default (faster)"
              />
            </div>
            {data && (
              <p className="pb-1 text-[11.5px] text-ink-faint ml-auto font-mono">
                Run #{data.run_id} · {num(data.event_count)} failures · {num(data.duration_ms)} ms
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-rule/60 text-[12px] text-ink-soft">
            <span className="eyebrow text-ink-faint">Presets:</span>
            {BENCH_PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => applyPreset(p)}
                title={p.desc}
                className="px-2.5 py-1 rounded bg-surface border border-rule hover:border-navy hover:text-navy text-[11.5px] font-medium transition-colors cursor-pointer"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="mt-3"><ErrorNote error={error} onRetry={run} /></div>}
      </Panel>

      {!data && latest.loading && <Loading what="Loading benchmark results" />}
      {!data && !latest.loading && !error && (
        <Panel>
          <p className="text-[13px] text-ink-soft text-center py-6">
            No simulation executed yet. Run the benchmark above to compute the head-to-head metrics.
          </p>
        </Panel>
      )}

      {data && (
        <>
          {/* Target Result Hero Banner */}
          <TargetHero data={data} />
          {/* Head to Head Compare Bars */}
          <HeadlineBars h={data.headline} agent={data.agent} baseline={data.baseline} />
          {/* Compliance & Breaches */}
          <Compliance agent={data.agent} baseline={data.baseline} h={data.headline} />
          {/* By Root Cause Heatmap Matrix */}
          <CauseMatrix rows={data.by_cause} />
          {/* Full Metric Arm Table */}
          <ArmTable data={data} />
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ the hero */

function TargetHero({ data }) {
  const t = data.plan_target
  const met = [t.revenue_met, t.attempt_reduction_met].filter(Boolean).length

  return (
    <section className="glass-panel rounded-lg overflow-hidden border border-rule transition-all">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule bg-surface-raised px-4 py-3 sm:px-5">
        <div>
          <div className="flex items-center gap-2">
            <Target className="size-4 text-navy" />
            <h2 className="font-display text-[15px] font-bold text-ink tracking-tight">
              Implementation Plan Commitments
            </h2>
          </div>
          <p className="mt-0.5 text-[12px] text-ink-soft">
            Core goal: <strong className="text-ink font-semibold">“Recovered 30%+ more revenue while sending 60% fewer retry attempts than naive retry.”</strong>
          </p>
        </div>
        <Pill
          tone={t.both_met ? 'good' : 'warn'}
          icon={t.both_met ? <CheckCircle2 className="size-3.5" /> : <AlertTriangle className="size-3.5" />}
        >
          {met} of 2 Targets Met
        </Pill>
      </header>

      <div className="grid grid-cols-1 divide-y divide-rule md:grid-cols-2 md:divide-x md:divide-y-0">
        <TargetCheck
          label="Recovered Revenue Uplift"
          actual={t.revenue_actual_pct}
          target={t.revenue_target_pct}
          met={t.revenue_met}
          statement={`${formatMinor(data.headline.agent_recovered_minor, 'INR', { compact: true })} agent vs ${formatMinor(data.headline.baseline_recovered_minor, 'INR', { compact: true })} baseline`}
        />
        <TargetCheck
          label="Retry Attempts Reduced"
          actual={t.attempt_reduction_actual_pct}
          target={t.attempt_reduction_target_pct}
          met={t.attempt_reduction_met}
          statement={`${num(data.headline.agent_charge_attempts)} attempts vs ${num(data.headline.baseline_charge_attempts)} baseline`}
        />
      </div>

      <div className="border-t border-rule bg-sunk/60 px-4 py-3 sm:px-5 flex items-center gap-2.5 text-[12.5px] text-ink">
        <Sparkles className="size-4 text-navy shrink-0" />
        <span>{data.headline.statement}</span>
      </div>

      {!t.both_met && (
        <div className="border-t border-warn/30 bg-warn-soft px-4 py-3 text-[12px] text-ink">
          <strong className="font-semibold text-warn">Target variation note:</strong> The mix of root causes is seed-dependent. Try preset seed <code className="font-mono bg-surface px-1 py-0.5 rounded">20260824</code> for the baseline comparison.
        </div>
      )}
    </section>
  )
}

function TargetCheck({ label, actual, target, met, statement }) {
  const TARGET_AT = 0.55
  const ratio = target > 0 ? actual / target : 0
  const width = Math.min(Math.max(ratio * TARGET_AT, 0), 1) * 100

  return (
    <div className="p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-display text-[14px] font-bold text-ink">{label}</span>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 font-display text-[11.5px] font-bold tracking-wider rounded border ${
            met ? 'bg-good-soft text-good border-good/40' : 'bg-bad-soft text-bad border-bad/40'
          }`}
        >
          {met ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
          {met ? 'PASS' : 'FAIL'}
        </span>
      </div>

      <div className="mt-2.5 flex items-baseline gap-2.5">
        <span className={`font-mono text-4xl font-bold leading-none ${met ? 'text-good' : 'text-bad'}`}>
          {pct(actual)}
        </span>
        <span className="text-[12px] text-ink-faint font-medium">target: ≥{pct(target)}</span>
      </div>

      <div className="relative mt-3 h-3 bg-sunk rounded-sm overflow-hidden border border-rule/50">
        <div
          className={`h-full rounded-r-[3px] transition-all duration-500 ${met ? 'bg-good' : 'bg-bad'}`}
          style={{ width: `${width}%` }}
          role="img"
          aria-label={`${label}: ${pct(actual)}, target ${pct(target)}`}
        />
        <div
          className="absolute -top-1 bottom-[-4px] w-0.5 bg-ink"
          style={{ left: `${TARGET_AT * 100}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[11.5px] text-ink-faint">
        <span className="truncate">{statement}</span>
        <span style={{ marginRight: `${(1 - TARGET_AT) * 100 - 8}%` }}>threshold</span>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- headline bars */

function HeadlineBars({ h, agent, baseline }) {
  return (
    <Panel
      title="Head-to-Head Comparative Metrics"
      icon={TrendingUp}
      note="Direct dual-arm counters. Bars scale against the larger value of each metric pair."
    >
      <div className="mb-3">
        <Legend
          items={[
            { label: 'Agent Arm (Diagnosis + Guardrails)', cls: 'bg-agent' },
            { label: 'Baseline Arm (Blind 24-hr Retry + Email)', cls: 'bg-baseline' },
          ]}
        />
      </div>
      <div className="grid grid-cols-1 gap-x-8 divide-y divide-rule/60 lg:grid-cols-2 lg:divide-y-0">
        <div className="divide-y divide-rule/60">
          <CompareBar
            label="Gross Revenue Recovered"
            agent={agent.recovered_minor}
            baseline={baseline.recovered_minor}
            format={(v) => formatMinor(v, 'INR', { compact: true })}
            note={`${pct(h.revenue_uplift_pct)} uplift against blind retry`}
          />
          <CompareBar
            label="Compliant Revenue (Zero Rule Breaches)"
            agent={agent.clean_recovered_minor}
            baseline={baseline.clean_recovered_minor}
            format={(v) => formatMinor(v, 'INR', { compact: true })}
            note={`${pct(h.uplift_vs_compliant_baseline_pct)} uplift vs baseline revenue that broke zero rules`}
          />
          <CompareBar
            label="Recovery Conversion Rate"
            agent={agent.recovered_cases}
            baseline={baseline.recovered_cases}
            note={`${rate(agent.recovery_rate)} of cases converted vs ${rate(baseline.recovery_rate)}`}
          />
        </div>
        <div className="divide-y divide-rule/60">
          <CompareBar
            label="Charge Attempts Dispatched"
            agent={agent.charge_attempts}
            baseline={baseline.charge_attempts}
            lowerIsBetter
            note="Every attempt incurs network fees and issuer risk"
          />
          <CompareBar
            label="Customer Contacts Dispatched"
            agent={agent.customer_touches}
            baseline={baseline.customer_touches}
            lowerIsBetter
            note={`${pct(h.touch_reduction_pct)} fewer intrusive touches`}
          />
          <CompareBar
            label="Network Penalty Points"
            agent={agent.network_penalty_points}
            baseline={baseline.network_penalty_points}
            lowerIsBetter
            format={(v) => (v == null ? '—' : v.toFixed(1))}
            note="Hard declines carry severe penalty weights"
          />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-x-8 border-t border-rule pt-3 lg:grid-cols-2">
        <CompareBar
          label="Attempts per Recovery (Efficiency)"
          agent={agent.attempts_per_recovery}
          baseline={baseline.attempts_per_recovery}
          lowerIsBetter
          format={(v) => (v == null ? '—' : v.toFixed(2))}
          note="Attempts required per rupee recovered"
        />
        <CompareBar
          label="Median Time to Recovery"
          agent={agent.median_hours_to_recovery}
          baseline={baseline.median_hours_to_recovery}
          lowerIsBetter
          format={hours}
          note={`${pct(h.time_to_recovery_reduction_pct)} faster recovery`}
        />
      </div>
    </Panel>
  )
}

/* ----------------------------------------------------------------- compliance */

function Compliance({ agent, baseline, h }) {
  const breaches = Object.entries(baseline.breach_counts ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <Panel
      title="Compliance & Regulatory Safety"
      icon={ShieldCheck}
      note="Blind retry breaks payments rules (chargeback stops, quiet hours, frequency caps). The agent enforces strict pre-clearance in code."
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <div className="border border-rule rounded-lg bg-sunk/60 p-3.5">
            <div className="eyebrow">Revenue Collected Through Rule Breach</div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-bold text-good">
                {formatMinor(h.agent_breach_minor, 'INR', { compact: true })}
              </span>
              <span className="text-[12px] text-ink-soft font-medium">Agent (Zero Breaches)</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-bold text-bad">
                {formatMinor(h.baseline_breach_minor, 'INR', { compact: true })}
              </span>
              <span className="text-[12px] text-ink-soft font-medium">Baseline (Non-compliant)</span>
            </div>
            <p className="mt-2 text-[11.5px] leading-snug text-ink-faint">
              {baseline.breach_cases === 0
                ? 'Baseline broke zero rules on this seed.'
                : `${num(baseline.breach_cases)} baseline cases closed with illegal retries.`}
            </p>
          </div>

          <div className="border border-rule rounded-lg p-3.5 bg-surface">
            <div className="eyebrow">Proposals Vetoed by Guardrails</div>
            <div className="mt-1.5 font-mono text-2xl font-bold text-warn">
              {num(agent.suppressed_actions)}
            </div>
            <p className="mt-1 text-[11.5px] leading-snug text-ink-faint">
              Vetoed before dispatch. {num(agent.escalated_to_human)} routed to human review.
            </p>
          </div>
        </div>

        <div>
          {breaches.length === 0 ? (
            <p className="text-[13px] text-ink-soft py-6 text-center">No baseline breaches on this run.</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <TH>Rule Baseline Violated</TH>
                  <TH align="right">Breach Count</TH>
                  <TH>Operational Consequence</TH>
                </tr>
              </thead>
              <tbody>
                {breaches.map(([id, count]) => (
                  <tr key={id}>
                    <TD mono className="text-bad font-medium">{id}</TD>
                    <TD align="right" mono className="font-bold">{num(count)}</TD>
                    <TD className="text-ink-soft text-[12px]">{BREACH_NOTES[id] ?? 'Enforced in executor; baseline ignored it.'}</TD>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </div>
    </Panel>
  )
}

const BREACH_NOTES = {
  'hard_stop.chargeback': 'Retried an account with active chargeback on file (network fine risk).',
  'hard_stop.fraud_flag': 'Retried a payment flagged as confirmed fraud by the issuer.',
  'hard_stop.dispute': 'Attempted billing through an open merchant dispute.',
  'comms.frequency': 'Contacted customer exceeding policy limit.',
  'comms.opt_out': 'Contacted a customer who explicitly opted out.',
  'comms.quiet_hours': 'Sent notifications inside customer local quiet hours.',
  'attempt_cap.weekly': 'Exceeded card network weekly attempt cap.',
  'attempt_cap.daily': 'Exceeded payment method daily attempt cap.',
}

/* --------------------------------------------------------------- cause matrix */

function CauseMatrix({ rows }) {
  const maxes = useMemo(() => {
    const pick = (k) => Math.max(...rows.map((r) => Math.abs(r[k] ?? 0)), 1)
    return {
      cases: pick('cases'),
      at_risk_minor: pick('at_risk_minor'),
      agent_minor: Math.max(pick('agent_minor'), pick('baseline_minor')),
      agent_charges: Math.max(pick('agent_charges'), pick('baseline_charges')),
    }
  }, [rows])

  return (
    <Panel
      title="Root-Cause Breakdown Matrix"
      icon={Zap}
      note="Where the recovery difference originates. Shaded cells indicate relative magnitude within each column."
      bleed
    >
      <Table>
        <thead>
          <tr>
            <TH>Root Cause</TH>
            <TH>Agent Recovery Strategy</TH>
            <TH align="right">Cases</TH>
            <TH align="right" title="Cases winnable under simulator probabilities">Winnable</TH>
            <TH align="right">At Risk</TH>
            <TH align="right" className="border-l border-rule">Agent Saved</TH>
            <TH align="right">Baseline Saved</TH>
            <TH align="right">Net Delta</TH>
            <TH align="right" className="border-l border-rule">Agent Tries</TH>
            <TH align="right">Baseline Tries</TH>
            <TH align="right" className="border-l border-rule">Accuracy</TH>
          </tr>
        </thead>
        <tbody>
          {[...rows]
            .sort((a, b) => (b.revenue_delta_minor ?? 0) - (a.revenue_delta_minor ?? 0))
            .map((r) => (
              <tr key={r.cause} className="hover:bg-surface-raised/50 transition-colors">
                <TD>
                  <span className="flex items-center gap-2">
                    <CauseDot color={causeColor(r.color)} />
                    <span className="font-bold text-ink">{r.label}</span>
                  </span>
                </TD>
                <TD className="text-ink-soft text-[12px]">{action(r.primary_action).label}</TD>
                <HeatCell fraction={r.cases / maxes.cases} title={`${r.cases} cases`}>
                  {num(r.cases)}
                </HeatCell>
                <TD align="right" mono className="text-ink-soft">{num(r.recoverable_cases)}</TD>
                <HeatCell fraction={r.at_risk_minor / maxes.at_risk_minor} title={formatMinor(r.at_risk_minor, 'INR')}>
                  {formatMinor(r.at_risk_minor, 'INR', { compact: true })}
                </HeatCell>
                <HeatCell fraction={r.agent_minor / maxes.agent_minor} title={`${r.agent_recovered} of ${r.cases} cases`}>
                  {formatMinor(r.agent_minor, 'INR', { compact: true })}
                </HeatCell>
                <HeatCell fraction={r.baseline_minor / maxes.agent_minor} title={`${r.baseline_recovered} of ${r.cases} cases`}>
                  {formatMinor(r.baseline_minor, 'INR', { compact: true })}
                </HeatCell>
                <TD align="right" mono className={`font-bold ${r.revenue_delta_minor >= 0 ? 'text-good' : 'text-bad'}`}>
                  {r.revenue_delta_minor >= 0 ? '+' : '−'}
                  {formatMinor(Math.abs(r.revenue_delta_minor), 'INR', { compact: true })}
                </TD>
                <HeatCell fraction={r.agent_charges / maxes.agent_charges} title={`${r.agent_charges} tries`}>
                  {num(r.agent_charges)}
                </HeatCell>
                <HeatCell fraction={r.baseline_charges / maxes.agent_charges} title={`${r.baseline_charges} tries`}>
                  {num(r.baseline_charges)}
                </HeatCell>
                <TD align="right" mono className="text-ink-soft font-semibold">
                  {r.classification_accuracy == null ? '—' : rate(r.classification_accuracy, 0)}
                </TD>
              </tr>
            ))}
        </tbody>
      </Table>
    </Panel>
  )
}

/* ------------------------------------------------------------------ arm table */

const ARM_ROWS = [
  { k: 'cases', label: 'Failures Ingested', f: num },
  { k: 'at_risk_minor', label: 'Total Revenue at Risk', f: (v) => formatMinor(v, 'INR', { compact: true }) },
  { k: 'recovered_cases', label: 'Cases Successfully Converted', f: num },
  { k: 'recovered_minor', label: 'Gross Revenue Recovered', f: (v) => formatMinor(v, 'INR', { compact: true }) },
  {
    k: 'clean_recovered_minor',
    label: 'Clean Compliant Revenue',
    f: (v) => formatMinor(v, 'INR', { compact: true }),
    note: 'Excludes revenue collected via guardrail breach',
  },
  {
    k: 'net_recovered_minor',
    label: 'Net Recovered (After Costs)',
    f: (v) => formatMinor(v, 'INR', { compact: true }),
    note: 'Net of processing fees and messaging costs',
  },
  { k: 'recovery_rate', label: 'Case Recovery Rate', f: rate },
  { k: 'revenue_recovery_rate', label: 'Revenue Recovery Rate', f: rate },
  {
    k: 'winnable_recovery_rate',
    label: 'Share of Winnable Revenue Saved',
    f: rate,
    note: 'Measured against theoretically recoverable cases',
  },
  { k: 'charge_attempts', label: 'Network Charge Attempts', f: num, lower: true },
  { k: 'customer_touches', label: 'Customer Communications', f: num, lower: true },
  { k: 'suppressed_actions', label: 'Actions Suppressed by Guardrails', f: num },
  { k: 'escalated_to_human', label: 'Escalated to Human Review', f: num },
  { k: 'total_cost_minor', label: 'Operating & Processing Cost', f: (v) => formatMinor(v, 'INR'), lower: true },
  { k: 'network_penalty_points', label: 'Network Penalty Points', f: (v) => (v == null ? '—' : v.toFixed(1)), lower: true },
  { k: 'attempts_per_recovery', label: 'Attempts Per Recovery', f: (v) => (v == null ? '—' : v.toFixed(2)), lower: true },
  { k: 'median_hours_to_recovery', label: 'Median Time to Recovery', f: hours, lower: true },
  { k: 'breach_cases', label: 'Guardrail Breach Cases', f: num, lower: true },
  { k: 'diagnosis_accuracy', label: 'Diagnostic Classification Accuracy', f: (v) => (v == null ? 'does not diagnose' : rate(v)) },
  { k: 'abstentions', label: 'Abstentions / No Diagnosis', f: num },
]

function ArmTable({ data }) {
  const { agent, baseline } = data
  return (
    <Panel
      title="Complete Telemetry & Measurement Surface"
      icon={Coins}
      note="Verifiable via GET /api/simulate/latest."
      bleed
    >
      <Table>
        <thead>
          <tr>
            <TH>Measure</TH>
            <TH align="right">
              <span className="inline-flex items-center gap-1.5 font-bold text-agent">
                <span aria-hidden="true" className="inline-block size-2 rounded-xs bg-agent" />
                Agent
              </span>
            </TH>
            <TH align="right">
              <span className="inline-flex items-center gap-1.5 font-bold text-baseline">
                <span aria-hidden="true" className="inline-block size-2 rounded-xs bg-baseline" />
                Baseline
              </span>
            </TH>
            <TH>Audit Note</TH>
          </tr>
        </thead>
        <tbody>
          {ARM_ROWS.map((r) => (
            <tr key={r.k} className="hover:bg-surface-raised/40 transition-colors">
              <TD className="font-medium text-ink">{r.label}</TD>
              <TD align="right" mono className="font-bold text-agent">{r.f(agent[r.k])}</TD>
              <TD align="right" mono className="text-ink-soft">{r.f(baseline[r.k])}</TD>
              <TD className="text-[11.5px] text-ink-faint">
                {r.note ?? (r.lower ? 'Lower is better' : '')}
              </TD>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  )
}

