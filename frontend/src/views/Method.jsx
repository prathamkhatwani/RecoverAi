import { useMemo } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { formatMinor, hours, num, rate } from '../lib/format'
import { causeColor } from '../lib/vocab'
import { CauseDot, ErrorNote, Loading, Panel, Pill, Table, TD, TH } from '../components/ui'
import {
  BookOpen,
  Sliders,
  Globe,
  Coins,
  Cpu,
  MessageSquare,
  Terminal,
  ShieldCheck,
  Zap,
  Activity,
  Layers,
  Sparkles
} from 'lucide-react'

export default function Method() {
  const config = useApi(() => api.config(), [])
  const assumptions = useApi(() => api.assumptions(), [])
  const gateways = useApi(() => api.gateways(), [])
  const currency = useApi(() => api.currency(), [])
  const llm = useApi(() => api.llm(), [])
  const messages = useApi(() => api.messages(), [])
  const taxonomy = useApi(() => api.taxonomy(), [])
  const causeColors = useMemo(() => colorMap(taxonomy.data), [taxonomy.data])

  if (config.error) return <ErrorNote error={config.error} onRetry={config.reload} />
  if (!config.data) return <Loading what="Loading methodology and assumptions" />

  const c = config.data

  return (
    <div className="flex flex-col gap-4">
      {/* Methodology Architecture Panel */}
      <Panel
        title="Experimental Methodology & Arm Comparison"
        icon={BookOpen}
        note="Full transparency disclosure: Neither arm sees ground truth; both replay identical failure streams from the same seed."
      >
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <div className="border-l-2 border-agent pl-3.5 py-1 bg-agent-soft/30 rounded-r-md">
            <div className="eyebrow text-agent font-bold">The Agent Arm (Diagnosis-Driven)</div>
            <p className="mt-1 text-[13px] leading-relaxed text-ink">
              Diagnoses the root cause from raw gateway strings, retrieves the corresponding policy parameters, proposes an action, passes through the 6-stage guardrail gauntlet, and logs every step cryptographically to the ledger.
            </p>
          </div>
          <div className="border-l-2 border-baseline pl-3.5 py-1 bg-baseline-soft/30 rounded-r-md">
            <div className="eyebrow text-baseline font-bold">The Baseline Arm (Naive Blind Retry)</div>
            <p className="mt-1 text-[13px] leading-relaxed text-ink">{c.baseline.description}</p>
            <dl className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1.5 text-[12px]">
              <Fact term="Max Retry Attempts">{num(c.baseline.max_attempts)}</Fact>
              <Fact term="Fixed Interval">{hours(c.baseline.interval_hours)}</Fact>
              <Fact term="Emails Dispatched">{c.baseline.sends_email_each_attempt ? 'Every attempt' : 'None'}</Fact>
            </dl>
          </div>
        </div>
      </Panel>

      {/* Simulator Assumptions */}
      <Panel
        title="Underlying Simulation Assumptions"
        icon={Sliders}
        note={assumptions.data?.note || "All recovery probabilities and cost factors applied identically across both arms."}
        bleed
      >
        {assumptions.loading && <div className="px-5 py-6"><Loading /></div>}
        {assumptions.error && <div className="p-4"><ErrorNote error={assumptions.error} onRetry={assumptions.reload} /></div>}
        {assumptions.data && (
          <Table>
            <thead>
              <tr>
                <TH>Simulation Parameter</TH>
                <TH align="right">Value</TH>
                <TH>Unit</TH>
                <TH>Behavior Governed</TH>
              </tr>
            </thead>
            <tbody>
              {assumptions.data.assumptions.map((a) => (
                <tr key={a.key} className="hover:bg-surface-raised/40 transition-colors">
                  <TD mono className="text-navy font-medium">{a.key}</TD>
                  <TD align="right" mono className="font-bold text-ink">
                    {formatAssumption(a)}
                  </TD>
                  <TD className="text-[11.5px] text-ink-faint">{a.unit}</TD>
                  <TD className="text-ink-soft text-[12.5px]">{a.description}</TD>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      {/* Gateway Styles */}
      <Panel
        title="Three Ingested Gateway Vocabularies"
        icon={Globe}
        note="Real payment processors express failures differently. The simulator models Razorpay, Stripe, and OrbitPG styles."
        bleed
      >
        {gateways.data && (
          <Table>
            <thead>
              <tr>
                <TH>Gateway</TH>
                <TH>Decline Style & Format</TH>
                <TH align="right">Traffic Share</TH>
                <TH align="right">Vocabulary Size</TH>
                <TH>HTTP Status</TH>
                <TH>Standard Decline Sample</TH>
                <TH>Ambiguous Sample</TH>
              </tr>
            </thead>
            <tbody>
              {gateways.data.gateways.map((g) => (
                <tr key={g.key} className="hover:bg-surface-raised/40 transition-colors">
                  <TD>
                    <span className="font-bold text-ink">{g.name}</span>
                    <code className="mt-0.5 block font-mono text-[11px] text-ink-faint">{g.key}</code>
                  </TD>
                  <TD className="text-ink-soft text-[12.5px]">{g.style}</TD>
                  <TD align="right" mono className="font-semibold">{rate(g.share, 0)}</TD>
                  <TD align="right" mono className="text-ink-soft">{num(g.vocabulary_size)}</TD>
                  <TD>
                    {g.emits_http_status ? (
                      <Pill tone="good">Included</Pill>
                    ) : (
                      <Pill>Omitted</Pill>
                    )}
                  </TD>
                  <TD>
                    <code className="font-mono text-[11.5px] text-ink bg-sunk px-1.5 py-0.5 rounded">“{g.sample}”</code>
                  </TD>
                  <TD>
                    <code className="font-mono text-[11.5px] text-warn bg-warn/10 px-1.5 py-0.5 rounded">“{g.ambiguous_sample}”</code>
                  </TD>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      {/* Reasoning Tier */}
      <Panel
        title="Reasoning Tier Runtime & Telemetry"
        icon={Cpu}
        note="Deterministic rules handle high-confidence codes; Claude reasoning tier resolves ambiguous edge cases."
      >
        {llm.data && <LlmPanel llm={llm.data} />}
      </Panel>

      {/* Defaults & Currency */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Run Configuration Defaults" icon={Activity}>
          <dl className="grid grid-cols-2 gap-x-5 gap-y-3">
            <Fact term="Failures per Run">{num(c.default_event_count)}</Fact>
            <Fact term="Max Allowed per Run">{num(c.max_event_count)}</Fact>
            <Fact term="Stream Event Pace">{num(c.stream_interval_ms)} ms</Fact>
            <Fact term="Default Target Seed" mono>{num(c.random_seed)}</Fact>
            <Fact term="Base Currency">{c.default_currency}</Fact>
            <Fact term="Console Version">
              {c.app_name} v{c.version} · {c.track}
            </Fact>
          </dl>
        </Panel>

        <Panel title="Monetary Valuation & Units" icon={Coins}>
          {currency.data && (
            <dl className="grid grid-cols-2 gap-x-5 gap-y-3">
              <Fact term="Primary Currency">{currency.data.disclosure.base}</Fact>
              <Fact term="Alternate Reference">{currency.data.disclosure.alternate}</Fact>
              <Fact term="FX Conversion Rate" mono>
                ₹{currency.data.disclosure.inr_per_usd} = $1.00 USD
              </Fact>
              <Fact term="Storage Precision" mono>
                Paise (Integer Minor Units)
              </Fact>
            </dl>
          )}
        </Panel>
      </div>

      {/* Tone & Customer Copy Rules */}
      <Panel
        title="Customer Messaging & Tone Guardrails"
        icon={MessageSquare}
        note="Communications are generated per root cause and must clear tone filters before dispatch. Shaming copy is strictly blocked."
        bleed
      >
        {messages.data && (
          <div className="grid grid-cols-1 divide-y divide-rule lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:divide-x lg:divide-y-0">
            <Table>
              <thead>
                <tr>
                  <TH>Root Cause</TH>
                  <TH>Customer Outreach</TH>
                  <TH>Action Requested from Customer</TH>
                </tr>
              </thead>
              <tbody>
                {messages.data.catalogue.map((m) => (
                  <tr key={m.cause} className="hover:bg-surface-raised/40 transition-colors">
                    <TD>
                      <span className="flex items-center gap-2">
                        <CauseDot color={causeColor(causeColors[m.cause])} />
                        <span className="font-bold text-ink">{m.label}</span>
                      </span>
                    </TD>
                    <TD>
                      {m.customer_contacted ? (
                        <Pill tone="warn">Customer Contacted</Pill>
                      ) : (
                        <Pill tone="good">Handled Silently</Pill>
                      )}
                    </TD>
                    <TD className="text-ink-soft text-[12.5px]">{m.ask}</TD>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Table>
              <thead>
                <tr>
                  <TH>Tone Violation Filter</TH>
                  <TH>Suppressed Phrases & Regex Patterns</TH>
                </tr>
              </thead>
              <tbody>
                {messages.data.tone_rules.map((t) => (
                  <tr key={t.reason} className="hover:bg-surface-raised/40 transition-colors">
                    <TD className="text-bad font-medium text-[12.5px]">{t.reason}</TD>
                    <TD mono className="text-[11px] break-all text-ink-faint">{t.patterns}</TD>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Panel>

      {/* API Endpoints Transparency */}
      <Panel title="Programmatic Audit Endpoints" icon={Terminal}>
        <p className="text-[13px] leading-relaxed text-ink-soft">
          All metrics on this dashboard are served via REST API. Verify directly via curl:
        </p>
        <div className="mt-2.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {[
            { path: '/api/simulate', desc: 'Run head-to-head benchmark' },
            { path: '/api/meta/taxonomy', desc: 'Inspect 8-cause taxonomy' },
            { path: '/api/meta/guardrails', desc: 'Inspect safety rules & config' },
            { path: '/api/ledger/verify', desc: 'Cryptographic chain verification' },
            { path: '/api/classify', desc: 'Decline classification' },
            { path: '/docs', desc: 'FastAPI Interactive Swagger' },
          ].map((ep) => (
            <div key={ep.path} className="p-2.5 rounded bg-sunk/60 border border-rule">
              <code className="font-mono text-navy text-[12px] font-semibold">{ep.path}</code>
              <p className="text-[11.5px] text-ink-faint mt-0.5">{ep.desc}</p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}

function LlmPanel({ llm }) {
  const { config: cfg, runtime, stats } = llm
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <div className="eyebrow text-ink-faint">Operating Mode</div>
          <div className="mt-1">
            <Pill tone={cfg.mode === 'live' ? 'good' : 'neutral'}>
              {cfg.mode === 'live' ? 'Claude Live' : 'Deterministic Reasoner'}
            </Pill>
          </div>
        </div>
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <Fact term="Active Provider">{cfg.provider_label}</Fact>
        </div>
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <Fact term="Target Model" mono>{runtime.active_model ?? cfg.model}</Fact>
        </div>
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <Fact term="Fallback Model" mono>{cfg.fallback_model ?? '—'}</Fact>
        </div>
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <Fact term="Structured Output" mono>{runtime.active_json_mode ?? cfg.json_mode}</Fact>
        </div>
        <div className="p-3 bg-sunk/60 rounded-lg border border-rule">
          <Fact term="Call Budget / Run" mono>
            {num(cfg.max_calls_per_run)}
            {runtime.budget_remaining != null && (
              <span className="ml-1 text-ink-faint">({num(runtime.budget_remaining)} left)</span>
            )}
          </Fact>
        </div>
      </div>

      <div className="p-3.5 bg-surface rounded-lg border border-rule">
        <div className="eyebrow text-ink-faint">Runtime Telemetry & Token Profile</div>
        <div className="mt-2 grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          <Fact term="Calls Attempted" mono>{num(stats.calls_attempted)}</Fact>
          <Fact term="Succeeded" mono>{num(stats.calls_succeeded)}</Fact>
          <Fact term="Failed" mono>{num(stats.calls_failed)}</Fact>
          <Fact term="Cache Hits" mono>{num(stats.cache_hits)}</Fact>
          <Fact term="Budget Exhausted" mono>{num(stats.budget_exhausted)}</Fact>
          <Fact term="Mean Latency" mono>{num(stats.avg_latency_ms)} ms</Fact>
          <Fact term="Prompt Tokens" mono>{num(stats.prompt_tokens)}</Fact>
        </div>
      </div>
    </div>
  )
}

function Fact({ term, children, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow truncate text-ink-faint" title={term}>{term}</dt>
      <dd className={`mt-1 text-[13px] font-bold leading-snug text-ink ${mono ? 'font-mono' : ''}`}>{children}</dd>
    </div>
  )
}

function formatAssumption(a) {
  const v = a.value
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (Array.isArray(v)) return v.map((x) => fmtOne(x, a.unit)).join(' – ')
  return fmtOne(v, a.unit)
}

function fmtOne(v, unit) {
  if (typeof v !== 'number') return String(v)
  if (unit === 'paise') return formatMinor(v, 'INR')
  if (unit?.startsWith('probability')) return rate(v)
  return String(v)
}

function colorMap(taxonomy) {
  const map = {}
  for (const row of taxonomy?.causes ?? []) map[row.cause] = row.color
  return map
}

