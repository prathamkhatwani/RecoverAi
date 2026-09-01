import { useState, useEffect } from 'react'
import {
  ArrowRight,
  Ban,
  Clock,
  Sliders,
  Shield,
  CheckCircle2,
  ChevronRight,
  Zap
} from 'lucide-react'

const STAGES = [
  { id: 0, title: 'Ingest & Parse', desc: 'Raw decline string received and parsed', icon: ArrowRight },
  { id: 1, title: 'Hard Stop Veto', desc: 'Fraud flags, open chargebacks, disputes', icon: Ban },
  { id: 2, title: 'Quiet Hours Filter', desc: 'Customer local timezone check (22:00–07:00)', icon: Clock },
  { id: 3, title: 'Frequency & Velocity Caps', desc: 'Weekly/daily attempt limits per method', icon: Sliders },
  { id: 4, title: 'Exposure Ceiling', desc: 'Autonomous budget and amount limits', icon: Shield },
  { id: 5, title: 'Dispatch & Seal', desc: 'Action cleared, executed, and ledger-sealed', icon: CheckCircle2 }
]

export default function GauntletWaterfall({
  activeStage: propsActiveStage,
  animating = false,
  compact = false
}) {
  const [currentStage, setCurrentStage] = useState(propsActiveStage ?? -1)

  useEffect(() => {
    if (propsActiveStage !== undefined && !animating) {
      setCurrentStage(propsActiveStage)
    }
  }, [propsActiveStage, animating])

  useEffect(() => {
    if (!animating) return

    setCurrentStage(-1)
    let step = 0
    
    const interval = setInterval(() => {
      setCurrentStage(step)
      step++
      if (step > STAGES.length) {
        step = -1 // loop back
      }
    }, 800)

    return () => clearInterval(interval)
  }, [animating])

  return (
    <div className={`w-full flex flex-col md:flex-row items-stretch md:items-start justify-between gap-2 md:gap-0 ${compact ? 'text-sm' : ''}`}>
      {STAGES.map((stage, idx) => {
        const Icon = stage.icon
        const isActive = currentStage === stage.id
        const isPast = currentStage > stage.id
        
        let boxStyle = 'border-rule bg-surface text-ink-faint'
        let iconStyle = 'text-ink-faint'
        
        if (isActive) {
          boxStyle = 'border-navy bg-navy/10 text-navy shadow-[0_0_15px_rgba(0,0,0,0.05)]' // fallback shadow
          iconStyle = 'text-navy'
        } else if (isPast) {
          boxStyle = 'border-good bg-good/10 text-good'
          iconStyle = 'text-good'
        }

        return (
          <div key={stage.id} className="flex flex-col md:flex-row items-center flex-1">
            <div 
              className={`flex-1 w-full flex flex-col items-center text-center p-3 md:p-4 rounded-xl border transition-all duration-300 ${boxStyle} ${compact ? 'min-h-[100px]' : 'min-h-[140px]'}`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`flex items-center justify-center w-5 h-5 rounded-full font-mono text-[10px] border ${
                  isActive ? 'border-navy bg-navy text-white' : 
                  isPast ? 'border-good bg-good text-white' : 
                  'border-rule bg-surface text-ink-soft'
                }`}>
                  {isPast ? <CheckCircle2 size={12} /> : stage.id + 1}
                </span>
                <Icon size={compact ? 16 : 20} className={iconStyle} />
              </div>
              <div className={`font-display font-medium leading-tight mb-1 ${
                isActive || isPast ? 'text-ink' : 'text-ink-soft'
              }`}>
                {stage.title}
              </div>
              {!compact && (
                <div className={`text-xs leading-snug ${
                  isActive || isPast ? 'text-ink-soft' : 'text-ink-faint'
                }`}>
                  {stage.desc}
                </div>
              )}
            </div>
            
            {idx < STAGES.length - 1 && (
              <div className="hidden md:flex flex-col justify-center text-rule px-1 lg:px-2 h-full">
                <ChevronRight size={20} className={isPast ? 'text-good' : 'text-rule'} />
              </div>
            )}
            {idx < STAGES.length - 1 && (
              <div className="md:hidden flex flex-col items-center justify-center text-rule py-1">
                <div className={`h-4 w-px ${isPast ? 'bg-good' : 'bg-rule'}`}></div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
