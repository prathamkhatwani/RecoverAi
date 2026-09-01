import { useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { num, rate, timestamp, formatMinor } from '../lib/format'
import IntegrationSnippets from '../components/IntegrationSnippets'
import CustomerCommunicationPreview from '../components/CustomerCommunicationPreview'
import CustomerRecoveryPortalModal from '../components/CustomerRecoveryPortalModal'
import { ACTION, STANCE, causeColor, tier as tierOf } from '../lib/vocab'
import {
  Button,
  CauseDot,
  Check,
  ErrorNote,
  Field,
  Input,
  Panel,
  Pill,
  Table,
  TD,
  TH,
} from '../components/ui'
import {
  Zap,
  Cpu,
  Sparkles,
  Search,
  MessageSquare,
  Clock,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  Sliders,
  Send,
  HelpCircle
} from 'lucide-react'

export default function Classify({ health }) {
  const examples = useApi(() => api.classifyExamples(), [])
  const gateways = useApi(() => api.gateways(), [])

  const [rawCode, setRawCode] = useState('do_not_honor')
  const [rawMessage, setRawMessage] = useState('Transaction not permitted, ref 54 expired')
  const [gateway, setGateway] = useState('orbitpg')
  const [amount, setAmount] = useState('2499.00')
  const [useLlm, setUseLlm] = useState(true)

  const [result, setResult] = useState(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  const llmAvailable = health?.llm_mode === 'live'

  async function submit(e) {
    e?.preventDefault()
    setPending(true)
    setError(null)
    try {
      const r = await api.classify({
        raw_code: rawCode,
        raw_message: rawMessage,
        gateway: gateway || null,
        amount_minor: Math.round(Number(amount || 0) * 100),
        use_llm: useLlm && llmAvailable,
      })
      setResult(r)
    } catch (e2) {
      setError(e2)
    } finally {
      setPending(false)
    }
  }

  function applyExample(ex) {
    setRawCode(ex.raw_code)
    setRawMessage(ex.raw_message)
    setResult(null)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Input Sandbox Panel */}
      <Panel
        title="Diagnostic Classifier Playground"
        icon={Zap}
        note="Test arbitrary decline codes & messages. Shows how deterministic rules handle unambiguous codes, while ambiguous remainder escalates to the reasoning tier."
      >
        <form onSubmit={submit} className="flex flex-col gap-3.5">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Decline Code" hint="Raw gateway code string">
              <Input value={rawCode} onChange={setRawCode} className="w-48" />
            </Field>
            <Field label="Originating Gateway">
              <select
                value={gateway}
                onChange={(e) => setGateway(e.target.value)}
                className="border border-rule bg-sunk px-2.5 py-1.5 rounded font-mono text-[13px] text-ink cursor-pointer"
              >
                <option value="">(Unspecified)</option>
                {(gateways.data?.gateways ?? []).map((g) => (
                  <option key={g.key} value={g.key}>
                    {g.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Transaction Amount (₹)">
              <Input value={amount} onChange={setAmount} className="w-32" />
            </Field>
            <div className="pb-1">
              <Check
                label="Use Claude Reasoning Tier"
                checked={useLlm && llmAvailable}
                onChange={setUseLlm}
                hint={llmAvailable ? 'Escalates ambiguous cases to Claude' : 'Deterministic reasoner stands in (no API key)'}
              />
            </div>
          </div>

          <Field label="Raw Gateway Decline Message" hint="Free-text response string returned by processor">
            <textarea
              value={rawMessage}
              onChange={(e) => setRawMessage(e.target.value)}
              rows={2}
              className="w-full rounded border border-rule bg-sunk/60 px-3 py-2 font-mono text-[13px] leading-snug text-ink placeholder:text-ink-faint focus:border-navy focus:bg-surface focus:outline-none transition-colors"
            />
          </Field>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-rule/60">
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow text-ink-faint">Hard Presets:</span>
              {(examples.data?.examples ?? []).map((ex) => (
                <button
                  key={ex.label}
                  type="button"
                  onClick={() => applyExample(ex)}
                  title={`${ex.raw_code} — ${ex.raw_message}`}
                  className="px-2 py-1 rounded bg-surface border border-rule text-[11.5px] font-medium text-ink-soft hover:border-navy hover:text-navy cursor-pointer transition-colors"
                >
                  {ex.label}
                </button>
              ))}
            </div>

            <Button tone="primary" type="submit" icon={Send} disabled={pending}>
              {pending ? 'Evaluating Diagnosis…' : 'Classify Decline'}
            </Button>
          </div>
        </form>

        {error && <div className="mt-3"><ErrorNote error={error} onRetry={submit} /></div>}
      </Panel>

      {result && <Result r={result} />}

      {/* API Integration Code Snippets */}
      <IntegrationSnippets
        rawCode={rawCode}
        rawMessage={rawMessage}
        gateway={gateway}
        amount={amount}
      />
    </div>
  )
}

/* ------------------------------------------------------------------- results */

function Result({ r }) {
  const c = r.classification
  const t = tierOf(r.tier_used)
  const escalated = c.escalated_from_rules
  const [portalOpen, setPortalOpen] = useState(false)

  const amountMinor = r.event?.amount_minor || 149900
  const amountFormatted = formatMinor(amountMinor, 'INR')

  return (
    <div className="flex flex-col gap-4 animate-in fade-in">
      {/* Primary Diagnosis Hero */}
      <section className="glass-panel rounded-lg overflow-hidden border border-rule">
        <div className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
          <div className="min-w-0">
            <div className="eyebrow text-navy">Diagnostic Resolution</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-3">
              <CauseDot color={causeColor(r.taxonomy.color)} className="size-3.5" />
              <h2 className="font-display text-2xl font-bold text-ink">
                {r.taxonomy.label}
              </h2>
              <Pill tone={SEVERITY_TONE[r.taxonomy.severity] ?? 'neutral'}>{r.taxonomy.severity}</Pill>
            </div>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-ink-soft bg-sunk/40 p-3 rounded border border-rule/50">
              {c.rationale}
            </p>
          </div>

          <div className="flex shrink-0 gap-6 bg-surface p-3 rounded-lg border border-rule">
            <div>
              <div className="eyebrow text-ink-faint">Diagnostic Confidence</div>
              <div className="mt-1 font-mono text-2xl font-bold text-good">
                {rate(c.confidence)}
              </div>
            </div>
            <div>
              <div className="eyebrow text-ink-faint">Resolved By</div>
              <div className="mt-1 font-display text-lg font-bold text-ink" title={t.note}>
                {t.label}
              </div>
              <div className="mt-0.5 text-[11px] font-mono text-ink-faint">
                {c.model ? c.model : 'Deterministic Rules'}
                {c.latency_ms ? ` · ${num(c.latency_ms)} ms` : ''}
              </div>
            </div>
          </div>
        </div>

        {/* Retry Stance Banner */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule bg-surface-raised/70 px-4 py-3 sm:px-5">
          <span className="eyebrow text-ink-faint">Retry Decision:</span>
          <Pill tone={STANCE[r.taxonomy.retry_stance]?.tone ?? 'neutral'}>
            {r.taxonomy.retry_answer}
          </Pill>
          <span className="text-[13px] text-ink font-medium">{r.taxonomy.recovery_action}</span>
          <span className="ml-auto text-[11.5px] font-mono text-ink-faint">
            Max {r.taxonomy.max_attempts} attempts
            {r.taxonomy.cooldown_hours ? ` · ${r.taxonomy.cooldown_hours}h cooldown` : ''}
            {r.taxonomy.counts_against_network_cap ? ' · counts against network cap' : ''}
          </span>
        </div>
      </section>

      {/* Two-Stage Decision Boundary */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="Stage 1 — Deterministic Rules Pass"
          icon={Cpu}
          note="Instant registry lookup + regex signal extraction. Zero API cost and <1ms latency."
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-display text-[15px] font-bold text-ink">
              Candidate: {r.rules_pass.cause.replace(/_/g, ' ')}
            </span>
            <span className="font-mono text-[13px] font-bold text-ink-soft">{rate(r.rules_pass.confidence)}</span>
          </div>

          <ThresholdTrack
            value={r.rules_pass.confidence}
            act={r.thresholds.act}
            escalate={r.thresholds.escalate}
          />

          <p className="mt-3 text-[12.5px] leading-relaxed text-ink">
            {r.rules_pass.should_escalate ? (
              <>
                <strong className="font-bold text-warn">Ambiguous signal below threshold.</strong>{' '}
                {r.rules_pass.ambiguity_reason
                  ? `Escalated due to ${r.rules_pass.ambiguity_reason}.`
                  : 'Escalated to Stage 2 Reasoning Tier.'}
              </>
            ) : (
              <>
                <strong className="font-bold text-good">Decisive Deterministic Match.</strong> Exceeds confidence threshold; settled without invoking LLM tokens.
              </>
            )}
          </p>

          {r.rules_pass.signals?.length > 0 && (
            <div className="mt-3">
              <div className="eyebrow text-ink-faint">Extracted Context Signals</div>
              <ul className="mt-1.5 flex flex-col gap-1">
                {r.rules_pass.signals.map((s, i) => (
                  <li key={i} className="border-l-2 border-rule-strong pl-2.5 text-[12px] leading-snug text-ink-soft">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {r.rules_pass.normalized_reason && (
            <div className="mt-3 border-t border-rule pt-2">
              <div className="eyebrow text-ink-faint">Normalized Gateway String</div>
              <code className="mt-1 block font-mono text-[12px] text-ink bg-sunk p-2 rounded">
                {r.rules_pass.normalized_reason}
              </code>
            </div>
          )}
        </Panel>

        <Panel
          title={escalated ? 'Stage 2 — Claude Reasoning Tier (Active)' : 'Stage 2 — Reasoning Tier (Bypassed)'}
          icon={Sparkles}
          note={
            escalated
              ? 'Ranks competing hypotheses. Only chooses between causes surfaced by the rules layer.'
              : 'Deterministic match was decisive; reasoning tier invocation was skipped to save cost.'
          }
        >
          <Hypotheses considered={c.considered} chosen={c.root_cause} />
        </Panel>
      </div>

      {/* Resulting Action Plan */}
      <Panel
        title="Executed Recovery Action Plan"
        icon={ArrowRight}
        note={r.note}
      >
        <div className="flex flex-col gap-4">
          <Table>
            <tbody>
              <PlanRow term="Action Type">
                <span className="font-bold text-ink">{ACTION[r.plan.action]?.label ?? r.plan.action}</span>
                <span className="ml-1.5 text-[11.5px] font-mono text-ink-faint">({r.plan.kind})</span>
              </PlanRow>
              <PlanRow term="Timing Strategy">{r.plan.timing_strategy}</PlanRow>
              <PlanRow term="Scheduled Dispatch">
                <span className="font-mono text-ink">{timestamp(r.plan.scheduled_at)}</span>
                {r.plan.delay_hours ? (
                  <span className="ml-1.5 text-[11.5px] text-ink-faint">
                    (+{r.plan.delay_hours.toFixed(1)}h)
                  </span>
                ) : null}
              </PlanRow>
              {r.plan.companion_action && (
                <PlanRow term="Companion Action">
                  {ACTION[r.plan.companion_action]?.label ?? r.plan.companion_action}
                </PlanRow>
              )}
              {r.plan.alternate_route && (
                <PlanRow term="Alternate Route">{r.plan.alternate_route}</PlanRow>
              )}
              <PlanRow term="Expected Success Rate">
                <span className="font-mono font-bold text-good">{rate(r.plan.expected_success_rate)}</span>
              </PlanRow>
              <PlanRow term="Requires Human Review">
                {r.plan.requires_human_signoff ? (
                  <Pill tone="warn">Yes — Pre-dispatch Sign-off Required</Pill>
                ) : (
                  <span className="text-ink-soft">Autonomous Clearance</span>
                )}
              </PlanRow>
            </tbody>
          </Table>
          <p className="text-[12.5px] leading-relaxed text-ink-soft bg-sunk/40 p-2.5 rounded border border-rule/50">{r.plan.reason}</p>

          {/* Multi-Channel Hinglish & Interactive Recovery Preview */}
          <CustomerCommunicationPreview
            plan={r.plan}
            cause={c.root_cause}
            amountFormatted={amountFormatted}
            onOpenPortal={() => setPortalOpen(true)}
          />
        </div>
      </Panel>

      {/* Simulated Customer Recovery Portal Modal */}
      <CustomerRecoveryPortalModal
        open={portalOpen}
        onClose={() => setPortalOpen(false)}
        amountFormatted={amountFormatted}
        cause={c.root_cause}
      />
    </div>
  )
}

function ThresholdTrack({ value, act, escalate }) {
  return (
    <div className="mt-3">
      <div className="relative h-3.5 bg-sunk rounded-sm overflow-hidden border border-rule/50">
        <div
          className={`h-full rounded-r-[3px] transition-all duration-300 ${
            value >= escalate ? 'bg-good' : value >= act ? 'bg-warn' : 'bg-bad'
          }`}
          style={{ width: `${Math.min(Math.max(value, 0), 1) * 100}%` }}
          role="img"
          aria-label={`Rules confidence ${rate(value)}`}
        />
        <span className="absolute -top-1 bottom-[-4px] w-0.5 bg-ink" style={{ left: `${act * 100}%` }} aria-hidden="true" />
        <span
          className="absolute -top-1 bottom-[-4px] w-0.5 bg-ink"
          style={{ left: `${escalate * 100}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="relative mt-1.5 h-7 text-[11px] font-mono text-ink-faint">
        <span className="absolute -translate-x-1/2 text-center leading-tight" style={{ left: `${act * 100}%` }}>
          act: {rate(act, 0)}
        </span>
        <span
          className="absolute -translate-x-1/2 text-center leading-tight"
          style={{ left: `${escalate * 100}%` }}
        >
          escalate: {rate(escalate, 0)}
        </span>
      </div>
    </div>
  )
}

function Hypotheses({ considered, chosen }) {
  const rows = [...(considered ?? [])].sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
  if (!rows.length) return <p className="text-[12.5px] text-ink-faint py-4">No competing hypotheses required evaluation.</p>

  return (
    <ul className="flex flex-col gap-2 py-1">
      {rows.map((h) => {
        const isChosen = h.cause === chosen
        return (
          <li key={h.cause} className="flex items-center gap-3">
            <span
              className={`w-44 shrink-0 truncate text-[13px] ${isChosen ? 'font-bold text-ink' : 'text-ink-soft'}`}
              title={h.cause}
            >
              {h.cause.replace(/_/g, ' ')}
            </span>
            <div className="h-3 min-w-0 flex-1 bg-sunk rounded-sm overflow-hidden border border-rule/40">
              <div
                className={`h-full rounded-r-[3px] transition-all duration-300 ${isChosen ? 'bg-navy' : 'bg-navy/40'}`}
                style={{
                  width: `${Math.min(Math.max(h.confidence ?? 0, 0), 1) * 100}%`,
                }}
                role="img"
                aria-label={`${h.cause}: ${rate(h.confidence)}`}
              />
            </div>
            <span className="w-14 shrink-0 text-right font-mono text-[12px] font-medium text-ink">
              {rate(h.confidence, 0)}
            </span>
            {isChosen ? (
              <Pill tone="good">Selected</Pill>
            ) : (
              <span className="w-[60px]" aria-hidden="true" />
            )}
          </li>
        )
      })}
    </ul>
  )
}

function PlanRow({ term, children }) {
  return (
    <tr>
      <TD className="eyebrow w-44 align-top text-ink-faint">{term}</TD>
      <TD>{children}</TD>
    </tr>
  )
}

const SEVERITY_TONE = { info: 'neutral', warning: 'warn', critical: 'bad' }

