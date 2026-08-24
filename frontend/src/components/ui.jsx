import { useState } from 'react'
import { num } from '../lib/format'
import {
  Check as CheckIcon,
  Copy,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Shield,
  ShieldAlert,
  Cpu,
  Terminal,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  X,
  ExternalLink
} from 'lucide-react'

/* ================================================================
   CONTAINERS
   ================================================================ */

export function Panel({
  title,
  icon: Icon,
  badge,
  note,
  actions,
  children,
  className = '',
  bleed = false,
}) {
  return (
    <section className={`glass-panel overflow-hidden transition-all duration-200 hover:shadow-[var(--shadow-glow)] ${className}`}>
      {(title || actions || badge) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule/70 bg-surface-raised/40 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2.5 min-w-0">
            {Icon && <Icon className="size-4 text-navy shrink-0 opacity-80" />}
            {title && <h2 className="eyebrow">{title}</h2>}
            {badge && <span>{badge}</span>}
            {note && (
              <p className="hidden md:inline-block text-[11.5px] text-ink-faint truncate max-w-xl font-normal ml-2 leading-relaxed">
                — {note}
              </p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      {note && (
        <div className="md:hidden border-b border-rule/50 bg-sunk/30 px-4 py-1.5 text-[11px] text-ink-soft">
          {note}
        </div>
      )}
      <div className={bleed ? '' : 'p-4 sm:p-5'}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, sub, tone = 'ink', mono = true, icon: Icon, delta, deltaType = 'good' }) {
  const tones = {
    ink: 'text-ink',
    good: 'text-good',
    bad: 'text-bad',
    warn: 'text-warn',
    navy: 'text-navy',
  }

  return (
    <div className="min-w-0 bg-surface/60 border border-rule/50 rounded-lg p-3.5 transition-all duration-200 hover:border-rule-strong hover:bg-surface/80">
      <div className="flex items-center justify-between gap-2">
        <div className="eyebrow truncate flex items-center gap-1.5">
          {Icon && <Icon className="size-3 text-ink-faint shrink-0" />}
          <span>{label}</span>
        </div>
        {delta && (
          <span
            className={`inline-flex items-center gap-0.5 text-[10.5px] font-mono font-semibold px-1.5 py-0.5 rounded-md ${
              deltaType === 'good'
                ? 'text-good bg-good/8'
                : deltaType === 'bad'
                ? 'text-bad bg-bad/8'
                : 'text-ink-soft bg-sunk'
            }`}
          >
            {delta.startsWith('+') ? <ArrowUpRight className="size-3" /> : delta.startsWith('-') ? <ArrowDownRight className="size-3" /> : null}
            {delta}
          </span>
        )}
      </div>
      <div
        className={`mt-2 text-[22px] leading-none ${tones[tone]} ${mono ? 'font-mono' : 'font-display'} font-bold tracking-tight`}
      >
        {value}
      </div>
      {sub && <div className="mt-2 text-[11px] leading-snug text-ink-faint truncate">{sub}</div>}
    </div>
  )
}

/* ================================================================
   ATOMS
   ================================================================ */

export function Pill({ children, tone = 'neutral', title, icon }) {
  const tones = {
    neutral: 'bg-sunk/80 text-ink-soft border-rule/60',
    good: 'bg-good-soft text-good border-good/25',
    bad: 'bg-bad-soft text-bad border-bad/25',
    warn: 'bg-warn-soft text-warn border-warn/25',
    agent: 'bg-agent-soft text-agent border-agent/25',
    baseline: 'bg-baseline-soft text-baseline border-baseline/25',
  }
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[10.5px] font-semibold rounded-md border ${tones[tone]} transition-colors`}
    >
      {icon}
      {children}
    </span>
  )
}

export function CauseDot({ color, className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-2.5 shrink-0 rounded-full ring-1 ring-black/10 ${className}`}
      style={{ background: color }}
    />
  )
}

export function Hash({ value, chars = 10, className = '', copyable = true }) {
  const [copied, setCopied] = useState(false)
  if (!value) return <span className="text-ink-faint">—</span>

  const handleCopy = (e) => {
    e.stopPropagation()
    navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <span className="inline-flex items-center gap-1 group">
      <code
        title={value}
        className={`font-mono text-[11px] text-ink-soft bg-sunk/60 border border-rule/50 px-1.5 py-0.5 rounded-md ${className}`}
      >
        {value.slice(0, chars)}
      </code>
      {copyable && (
        <button
          type="button"
          onClick={handleCopy}
          title={copied ? 'Copied full hash' : 'Copy full hash'}
          className="opacity-0 group-hover:opacity-100 transition-all duration-150 p-0.5 text-ink-faint hover:text-ink cursor-pointer"
        >
          {copied ? <CheckIcon className="size-3 text-good" /> : <Copy className="size-3" />}
        </button>
      )}
    </span>
  )
}

export function Button({
  children,
  onClick,
  tone = 'default',
  disabled,
  type = 'button',
  title,
  icon: Icon,
  size = 'md',
  className = '',
}) {
  const tones = {
    default: 'bg-surface-raised/60 text-ink border-rule hover:bg-surface-raised hover:border-rule-strong',
    primary: 'bg-navy text-white border-navy-dark hover:bg-navy-dark shadow-sm shadow-navy/15 font-semibold',
    danger: 'bg-surface text-bad border-bad/30 hover:bg-bad/8 hover:border-bad/50',
    subtle: 'bg-transparent text-ink-soft border-transparent hover:bg-sunk/60 hover:text-ink',
  }

  const sizes = {
    sm: 'px-2.5 py-1 text-[11px]',
    md: 'px-3.5 py-1.5 text-[12px]',
    lg: 'px-5 py-2 text-[13px]',
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border font-display font-semibold tracking-wide transition-all duration-150 active:scale-[0.97] cursor-pointer disabled:cursor-not-allowed disabled:opacity-35 disabled:active:scale-100 ${sizes[size]} ${tones[tone]} ${className}`}
    >
      {Icon && <Icon className="size-3.5 shrink-0" />}
      {children}
    </button>
  )
}

export function Field({ label, children, hint }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="eyebrow">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-ink-faint leading-relaxed">{hint}</span>}
    </label>
  )
}

export function Input({ value, onChange, type = 'text', placeholder, min, max, step, className = '' }) {
  return (
    <input
      type={type}
      value={value}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`border border-rule bg-sunk/40 px-3 py-1.5 rounded-md font-mono text-[13px] text-ink placeholder:text-ink-faint/60 focus:border-navy focus:bg-surface focus:ring-1 focus:ring-navy/20 focus:outline-none transition-all duration-150 ${className}`}
    />
  )
}

export function Check({ label, checked, onChange, hint }) {
  return (
    <label className="flex items-start gap-2.5 text-[13px] cursor-pointer select-none group">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded accent-navy cursor-pointer"
      />
      <span>
        <span className="font-medium text-ink group-hover:text-navy transition-colors">{label}</span>
        {hint && <span className="block text-[11px] text-ink-faint leading-snug mt-0.5">{hint}</span>}
      </span>
    </label>
  )
}

/* ================================================================
   FEEDBACK STATES
   ================================================================ */

export function Loading({ what = 'Loading' }) {
  return (
    <div className="flex items-center gap-3 px-4 py-10 text-[13px] text-ink-soft justify-center">
      <span className="size-1.5 rounded-full bg-navy animate-ping" />
      <span className="font-display font-medium">{what}…</span>
    </div>
  )
}

export function ErrorNote({ error, onRetry }) {
  return (
    <div className="border border-bad/30 bg-bad-soft rounded-lg p-4">
      <div className="flex items-center gap-2 font-display text-[13px] font-bold text-bad">
        <AlertCircle className="size-4 shrink-0" />
        Request failed
      </div>
      <p className="mt-1.5 font-mono text-[12px] leading-relaxed text-ink-soft break-words">
        {String(error?.message ?? error)}
      </p>
      {onRetry && (
        <div className="mt-3">
          <Button tone="danger" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  )
}

export function Empty({ children }) {
  return (
    <div className="px-4 py-12 text-center text-[13px] text-ink-faint">
      <Layers className="size-7 mx-auto mb-2.5 opacity-30" />
      {children}
    </div>
  )
}

/* ================================================================
   TABLES
   ================================================================ */

export function Table({ children, className = '' }) {
  return (
    <div className="overflow-x-auto">
      <table className={`w-full border-collapse text-[13px] ${className}`}>{children}</table>
    </div>
  )
}

export function TH({ children, align = 'left', className = '', title }) {
  return (
    <th
      title={title}
      className={`eyebrow sticky top-0 z-1 whitespace-nowrap border-b border-rule bg-surface/95 backdrop-blur-sm px-3 py-2.5 font-bold ${
        align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
      } ${className}`}
    >
      {children}
    </th>
  )
}

export function TD({ children, align = 'left', mono = false, className = '', title, colSpan }) {
  return (
    <td
      title={title}
      colSpan={colSpan}
      className={`border-b border-rule/40 px-3 py-2.5 ${mono ? 'font-mono text-[12.5px]' : ''} ${
        align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
      } ${className}`}
    >
      {children}
    </td>
  )
}

/* ================================================================
   COMPARE BARS & LEGENDS
   ================================================================ */

export function CompareBar({ label, agent, baseline, format = num, lowerIsBetter = false, note }) {
  const max = Math.max(Math.abs(agent ?? 0), Math.abs(baseline ?? 0), 1)
  const rows = [
    { arm: 'Agent', value: agent, cls: 'bg-agent', textCls: 'text-agent font-bold' },
    { arm: 'Baseline', value: baseline, cls: 'bg-baseline/80', textCls: 'text-baseline' },
  ]
  return (
    <div className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-display text-[13px] font-bold text-ink">{label}</span>
        <span className="text-[10.5px] text-ink-faint font-mono tracking-tight opacity-60">
          {lowerIsBetter ? '↓ lower is better' : '↑ higher is better'}
        </span>
      </div>
      {note && <p className="mt-0.5 text-[11px] leading-snug text-ink-faint">{note}</p>}
      <div className="mt-2.5 flex flex-col gap-1.5">
        {rows.map((r) => (
          <div key={r.arm} className="flex items-center gap-3">
            <span className="w-16 shrink-0 text-[11px] text-ink-soft font-semibold">{r.arm}</span>
            <div className="relative h-2.5 min-w-0 flex-1 bg-sunk/60 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-out ${r.cls}`}
                style={{ width: `${Math.max((Math.abs(r.value ?? 0) / max) * 100, r.value ? 2 : 0)}%` }}
                role="img"
                aria-label={`${r.arm}: ${format(r.value)}`}
              />
            </div>
            <span className={`w-28 shrink-0 text-right font-mono text-[12px] ${r.textCls}`}>{format(r.value)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Legend({ items }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 py-1">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-2 text-[11.5px] text-ink-soft">
          <span aria-hidden="true" className={`inline-block size-2 rounded-full ${it.cls}`} />
          <span>{it.label}</span>
        </span>
      ))}
    </div>
  )
}

/** Sequential ramp for magnitude in the per-cause matrix */
const SEQ = ['#1a2240', '#1e3a6e', '#1d4ed8', '#3b82f6', '#60a5fa']

export function HeatCell({ fraction, children, title }) {
  const f = Number.isFinite(fraction) ? Math.min(Math.max(fraction, 0), 1) : 0
  const step = f === 0 ? 0 : Math.min(SEQ.length - 1, Math.floor(f * SEQ.length))
  return (
    <td
      title={title}
      className={`border-b border-rule/40 px-3 py-2.5 text-right font-mono text-[12.5px] transition-colors ${
        step >= 2 ? 'text-white font-bold' : 'text-ink'
      }`}
      style={{ background: f === 0 ? 'transparent' : SEQ[step] }}
    >
      {children}
    </td>
  )
}

export function seqSwatches() {
  return SEQ
}

/* ================================================================
   DRAWER / SIDE PANEL
   ================================================================ */

export function Drawer({ open, onClose, title, subtitle, children }) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end transition-opacity"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm fade-up" />

      {/* Panel */}
      <div className="relative w-full max-w-2xl bg-surface border-l border-rule shadow-[var(--shadow-elevated)] flex flex-col h-full overflow-hidden">
        <header className="flex items-center justify-between border-b border-rule/70 px-5 py-4 bg-surface-raised/50">
          <div>
            <h3 className="font-display text-[15px] font-bold text-ink tracking-tight">{title}</h3>
            {subtitle && <p className="text-[12px] text-ink-soft mt-0.5 leading-relaxed">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-ink-faint hover:text-ink hover:bg-sunk/60 cursor-pointer transition-colors"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}
