import { useState, useEffect } from 'react'
import { api } from './lib/api'
import { useApi } from './lib/useApi'
import { Hash, Pill, Button, Drawer } from './components/ui'
import Scoreboard from './views/Scoreboard'
import LiveTriage from './views/LiveTriage'
import Taxonomy from './views/Taxonomy'
import Guardrails from './views/Guardrails'
import Ledger from './views/Ledger'
import Classify from './views/Classify'
import Method from './views/Method'
import ROICalculator from './views/ROICalculator'
import {
  Activity,
  BarChart3,
  ListTree,
  ShieldAlert,
  Database,
  Zap,
  BookOpen,
  Calculator,
  Sun,
  Moon,
  HelpCircle,
  ShieldCheck,
  Cpu,
  Sparkles,
  ArrowRight,
  Volume2,
  VolumeX,
} from 'lucide-react'

const VIEWS = [
  { key: 'live', label: 'Live Triage', icon: Activity, component: LiveTriage, note: 'Failures arriving and being sorted in real-time', shortcut: '1' },
  { key: 'scoreboard', label: 'Scoreboard', icon: BarChart3, component: Scoreboard, note: 'Agent versus blind retry benchmarks', shortcut: '2' },
  { key: 'taxonomy', label: 'Root Causes', icon: ListTree, component: Taxonomy, note: 'The diagnosis table & policy matrix', shortcut: '3' },
  { key: 'guardrails', label: 'Guardrails', icon: ShieldAlert, component: Guardrails, note: 'Structural safety rules enforced in code', shortcut: '4' },
  { key: 'ledger', label: 'Ledger', icon: Database, component: Ledger, note: 'Hash-chained cryptographic decision log', shortcut: '5' },
  { key: 'classify', label: 'Classify', icon: Zap, component: Classify, note: 'Test arbitrary decline codes & messages', shortcut: '6' },
  { key: 'method', label: 'Method', icon: BookOpen, component: Method, note: 'Simulation assumptions, gateway specs & config', shortcut: '7' },
  { key: 'roi', label: 'ROI Calculator', icon: Calculator, component: ROICalculator, note: 'Project annual revenue recovery savings', shortcut: '8' },
]

export default function App() {
  const [view, setView] = useState('live')
  const [runId, setRunId] = useState(null)
  const [theme, setTheme] = useState(() => localStorage.getItem('rr_theme') || 'dark')
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem('rr_sound') !== 'off')
  const [guideOpen, setGuideOpen] = useState(false)
  const health = useApi(() => api.health(), [])

  // Sync theme attribute on document root
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('rr_theme', theme)
  }, [theme])

  // Persist sound preference
  useEffect(() => {
    localStorage.setItem('rr_sound', soundEnabled ? 'on' : 'off')
  }, [soundEnabled])

  // Keyboard shortcut listener (1-7)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      const found = VIEWS.find((v) => v.shortcut === e.key)
      if (found) setView(found.key)
      if (e.key === '?') setGuideOpen((prev) => !prev)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const Current = VIEWS.find((v) => v.key === view).component
  const h = health.data

  return (
    <div className="min-h-screen flex flex-col">
      {/* ━━━ Sticky Header ━━━ */}
      <header className="sticky top-0 z-40 border-b border-rule/70 bg-surface/85 backdrop-blur-lg transition-colors duration-200">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-5 py-2.5 sm:px-6">

          {/* Brand */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="relative flex size-8 items-center justify-center rounded-lg bg-navy/10 border border-navy/20">
              <ShieldCheck className="size-4.5 text-navy" />
              <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-good pulse-beacon" />
            </div>
            <div className="hidden sm:block">
              <div className="flex items-center gap-2">
                <h1 className="font-display text-[16px] font-bold tracking-tight text-ink">
                  Revenue Recovery
                </h1>
                <span className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-widest rounded-md bg-navy/8 text-navy font-bold border border-navy/15">
                  Console
                </span>
              </div>
              <p className="text-[10.5px] text-ink-faint font-medium -mt-0.5">Diagnosis-Driven Payment Recovery</p>
            </div>
          </div>

          {/* System Status Chips */}
          <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
            {h && (
              <>
                <div className="flex items-center gap-1.5 bg-sunk/50 border border-rule/50 px-2 py-1 rounded-md">
                  <span
                    className={`size-1.5 rounded-full ${h.ok ? 'bg-good shadow-[0_0_4px] shadow-good/50' : 'bg-bad shadow-[0_0_4px] shadow-bad/50'}`}
                    aria-hidden="true"
                  />
                  <span className="font-semibold text-[10.5px] text-ink">{h.ok ? 'API Active' : 'Offline'}</span>
                </div>

                <Pill
                  tone={h.llm_mode === 'live' ? 'good' : 'neutral'}
                  icon={h.llm_mode === 'live' ? <Sparkles className="size-3" /> : <Cpu className="size-3" />}
                >
                  {h.llm_mode === 'live' ? 'Claude Live' : 'Deterministic'}
                </Pill>

                <div className="hidden lg:flex items-center gap-1.5 text-[10.5px] bg-sunk/50 border border-rule/50 px-2 py-1 rounded-md">
                  <Database className="size-3 text-ink-faint" />
                  <span className="text-ink-faint">Ledger:</span>
                  <strong className="font-mono font-bold text-ink">{h.ledger_records}</strong>
                </div>
              </>
            )}

            {health.error && (
              <span className="text-bad font-mono text-[10.5px] bg-bad-soft px-2 py-1 rounded-md border border-bad/25">
                Backend offline
              </span>
            )}

            <div className="flex items-center gap-1.5 ml-1">
              <Button
                tone="subtle"
                size="sm"
                icon={HelpCircle}
                onClick={() => setGuideOpen(true)}
                title="6-step demo walkthrough (Press ?)"
              >
                Guide
              </Button>

              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} theme`}
                className="p-1.5 rounded-md border border-rule/50 bg-surface-raised/40 text-ink-soft hover:text-ink hover:bg-surface-raised cursor-pointer transition-all duration-150"
              >
                {theme === 'dark' ? <Sun className="size-3.5 text-warn" /> : <Moon className="size-3.5 text-navy" />}
              </button>

              <button
                type="button"
                onClick={() => setSoundEnabled(!soundEnabled)}
                title={soundEnabled ? 'Mute recovery chimes' : 'Enable recovery chimes'}
                className={`p-1.5 rounded-md border border-rule/50 bg-surface-raised/40 hover:bg-surface-raised cursor-pointer transition-all duration-150 ${
                  soundEnabled ? 'text-good' : 'text-ink-faint'
                }`}
              >
                {soundEnabled ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />}
              </button>
            </div>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="mx-auto max-w-[1600px] px-5 sm:px-6">
          <ul className="-mb-px flex gap-0.5 overflow-x-auto">
            {VIEWS.map((v) => {
              const active = v.key === view
              const Icon = v.icon
              return (
                <li key={v.key}>
                  <button
                    type="button"
                    onClick={() => setView(v.key)}
                    title={`${v.note} (Press ${v.shortcut})`}
                    aria-current={active ? 'page' : undefined}
                    className={`group relative flex items-center gap-1.5 border-b-2 px-3 py-2 font-display text-[12.5px] font-semibold tracking-wide transition-all duration-150 cursor-pointer whitespace-nowrap ${
                      active
                        ? 'border-navy text-navy'
                        : 'border-transparent text-ink-faint hover:text-ink-soft hover:border-rule'
                    }`}
                  >
                    <Icon className={`size-3.5 transition-transform duration-150 ${active ? 'text-navy' : 'text-ink-faint group-hover:text-ink-soft'}`} />
                    <span>{v.label}</span>
                    <kbd className="hidden lg:inline text-[9px] font-mono opacity-30 px-1 py-0.5 rounded bg-sunk/60 leading-none">
                      {v.shortcut}
                    </kbd>
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>
      </header>

      {/* ━━━ Content ━━━ */}
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-5 py-5 sm:px-6">
        <Current runId={runId} setRunId={setRunId} onNavigate={setView} health={h} soundEnabled={soundEnabled} />
      </main>

      {/* ━━━ Footer ━━━ */}
      <footer className="border-t border-rule/50 bg-surface/30 mt-auto">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-5 py-2.5 sm:px-6 text-[10.5px] text-ink-faint">
          <p className="leading-relaxed">
            All figures server-computed via FastAPI · Ledger Head: {h ? <Hash value={h.db?.ledger_head} chars={12} /> : '—'}
          </p>
          <div className="flex items-center gap-2 opacity-60">
            <span>Synthetic failure stream</span>
            <span>·</span>
            <span className="font-mono">v{h?.version || '1.0.0'}</span>
          </div>
        </div>
      </footer>

      {/* ━━━ Demo Script Drawer ━━━ */}
      <Drawer
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
        title="Demo Narrative Script"
        subtitle="Follow this 6-step sequence for maximum impact."
      >
        <div className="flex flex-col gap-3.5 text-[13px]">
          <div className="p-3.5 bg-navy/8 border border-navy/20 rounded-lg">
            <h4 className="font-bold text-navy flex items-center gap-1.5 text-[13px]">
              <Sparkles className="size-3.5" /> The Core Bet
            </h4>
            <p className="mt-1.5 text-[12px] text-ink-soft leading-relaxed">
              This console treats <strong className="text-ink">diagnosis as the hard problem</strong>: 8 root causes, guardrails enforced in code, and a hash-chained audit log.
            </p>
          </div>

          <ol className="flex flex-col gap-2.5">
            {[
              {
                step: '1',
                view: 'live',
                title: 'Stream Failures Live',
                desc: 'Show raw decline strings being sorted into root causes in real-time.',
              },
              {
                step: '2',
                view: 'scoreboard',
                title: 'Head-to-Head Scoreboard',
                desc: 'Point out +30% recovered revenue while cutting retries by 60%.',
              },
              {
                step: '3',
                view: 'taxonomy',
                title: '8-Cause Taxonomy',
                desc: 'Explain why retry is correct for transient issues but forbidden for fraud.',
              },
              {
                step: '4',
                view: 'guardrails',
                title: 'Guardrails in Code',
                desc: 'Walk through the 6-tier gauntlet: quiet hours, exposure limits, frequency caps.',
              },
              {
                step: '5',
                view: 'ledger',
                title: 'Tamper & Verify',
                desc: 'Alter a record and watch the cryptographic chain break live.',
              },
              {
                step: '6',
                view: 'classify',
                title: 'Decline Scratchpad',
                desc: 'Type an ambiguous decline string. Watch deterministic + LLM reasoning.',
              },
            ].map((s) => (
              <li
                key={s.step}
                onClick={() => {
                  setView(s.view)
                  setGuideOpen(false)
                }}
                className="group flex items-center gap-3 p-3 rounded-lg border border-rule/50 bg-surface-raised/30 hover:border-navy/40 hover:bg-navy/5 cursor-pointer transition-all duration-150"
              >
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-navy text-white text-[11px] font-bold">
                  {s.step}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="font-display font-bold text-[13px] text-ink">{s.title}</span>
                  <p className="text-[11.5px] text-ink-faint leading-snug mt-0.5 truncate">{s.desc}</p>
                </div>
                <ArrowRight className="size-3.5 text-ink-faint group-hover:text-navy group-hover:translate-x-0.5 transition-all shrink-0" />
              </li>
            ))}
          </ol>
        </div>
      </Drawer>
    </div>
  )
}
