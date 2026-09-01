import { useState } from 'react'
import { Pill, Button } from './ui'
import {
  MessageSquare,
  PhoneCall,
  Mail,
  Smartphone,
  Play,
  Square,
  Volume2,
  CheckCircle2,
  Copy,
  ExternalLink,
  Sparkles
} from 'lucide-react'

export default function CustomerCommunicationPreview({
  plan,
  customerName = 'Rahul Sharma',
  amountFormatted = '₹1,499',
  cause = 'insufficient_funds',
  onOpenPortal
}) {
  const [channel, setChannel] = useState('whatsapp_hinglish')
  const [speaking, setSpeaking] = useState(false)
  const [copied, setCopied] = useState(false)

  const causeLabels = {
    insufficient_funds: 'account me balance kam hone ke kaaran',
    expired_card: 'card ki validity expire hone ke kaaran',
    auth_3ds_failure: 'OTP/3DS verification complete na hone ke kaaran',
    lapsed_mandate: 'auto-pay mandate update required hone ke kaaran',
    gateway_error: 'bank server issue ke kaaran',
  }

  const causeReason = causeLabels[cause] || 'payment issue ke kaaran'

  // Dynamic message templates
  const messages = {
    whatsapp_hinglish: {
      title: 'WhatsApp (Hinglish / Hindi)',
      icon: MessageSquare,
      badge: 'High Conversion (78%)',
      badgeTone: 'good',
      content: `Namaste ${customerName} ji! 🙏

Aapka *${amountFormatted}* ka subscription payment *${causeReason}* complete nahi ho paya.

Fret not! Aap bina kisi late fee ke apna payment yahan 1-tap me complete kar sakte hain:
🔗 https://pay.rzp.io/rcv/8x9f2a

💡 _Tip: Aap UPI AutoPay ya naye card se bhi update kar sakte hain._

Agar aap pehle hi pay kar chuke hain, toh kripya is message ko ignore karein.
— Team Razorpay / RecoverAI`,
    },
    voice_ivr_hinglish: {
      title: 'IVR Voice Call (Female Hindi AI)',
      icon: PhoneCall,
      badge: 'Priya AI Voice Agent',
      badgeTone: 'navy',
      content: `[IVR Ringtone... Call Connected]

Agent (Priya - AI Voice):
"Namaste ${customerName} ji. Main Razorpay RecoverAI se Priya baat kar rahi hoon.

Aapka ${amountFormatted} ka subscription payment ${causeReason} decline ho gaya hai.

Apni service ko uninterrupted continue rakhne ke liye, humne aapke registered WhatsApp aur SMS par ek secure 1-click recovery link send kiya hai.

Kripya link par tap karke apna payment complete karein. Agar aap pehle hi pay kar chuke hain toh is call ko ignore karein. Dhanyawad!"`,
      speechText: `Namaste ${customerName} ji. Main Razorpay RecoverAI se Priya baat kar rahi hoon. Aapka ${amountFormatted} ka subscription payment decline ho gaya hai. Apni service uninterrupted rakhne ke liye, WhatsApp par bheje gaye link par click karke apna payment complete karein. Dhanyawad.`,
    },
    email_en: {
      title: 'Email (Smart English)',
      icon: Mail,
      badge: 'Standard Fallback',
      badgeTone: 'neutral',
      content: `Subject: Action Required: Updating your payment method for ${amountFormatted}

Hi ${customerName},

We attempted to process your scheduled subscription charge of ${amountFormatted}, but your bank declined the transaction.

No service interruption has occurred yet. You can securely retry or update your billing details using the verified link below:

[ Secure 1-Click Payment Link: https://pay.rzp.io/rcv/8x9f2a ]

• Protected by 256-bit encryption
• Supports UPI AutoPay, Credit/Debit Cards, and NetBanking

Best regards,
Billing Operations Team`,
    },
    sms_dlt: {
      title: 'SMS (DLT-Approved Template)',
      icon: Smartphone,
      badge: 'DLT Compliant',
      badgeTone: 'neutral',
      content: `Alert: Payment of ${amountFormatted} for your subscription could not be processed. Avoid service pause by completing it here: https://pay.rzp.io/rcv/8x9f2a - RZPAY`,
    },
  }

  const activeMsg = messages[channel]

  const handleSpeak = () => {
    if (!('speechSynthesis' in window)) {
      alert('Speech synthesis is not supported on this browser.')
      return
    }

    if (speaking) {
      window.speechSynthesis.cancel()
      setSpeaking(false)
      return
    }

    const textToSpeak = messages.voice_ivr_hinglish.speechText
    const utterance = new SpeechSynthesisUtterance(textToSpeak)
    
    // Female natural voice parameters: pitch 1.15, rate 0.92 (warm, clear, polite Indian cadence)
    utterance.rate = 0.92
    utterance.pitch = 1.15

    const voices = window.speechSynthesis.getVoices()
    
    // 1. Look for explicit Female Hindi voices (e.g. Swara, Kalpana, Heera, Google Hindi Female, Neerja, Kavya)
    let femaleHindiVoice = voices.find(v => 
      (v.lang.startsWith('hi') || v.lang.includes('IN')) && 
      (v.name.toLowerCase().includes('swara') || 
       v.name.toLowerCase().includes('kalpana') || 
       v.name.toLowerCase().includes('heera') || 
       v.name.toLowerCase().includes('neerja') || 
       v.name.toLowerCase().includes('kavya') || 
       v.name.toLowerCase().includes('aditi') || 
       v.name.toLowerCase().includes('female') ||
       v.name.toLowerCase().includes('zira') ||
       v.name.toLowerCase().includes('natural') ||
       v.name.includes('हिन्दी'))
    )

    // 2. Fallback to any Hindi voice
    if (!femaleHindiVoice) {
      femaleHindiVoice = voices.find(v => v.lang.startsWith('hi') || v.lang.includes('hi-IN'))
    }

    // 3. Fallback to Indian English Female voice
    if (!femaleHindiVoice) {
      femaleHindiVoice = voices.find(v => 
        (v.lang.includes('en-IN') || v.name.toLowerCase().includes('india')) &&
        (v.name.toLowerCase().includes('female') || v.name.toLowerCase().includes('heera') || v.name.toLowerCase().includes('zira'))
      )
    }

    // 4. Any Indian voice
    if (!femaleHindiVoice) {
      femaleHindiVoice = voices.find(v => v.lang.includes('en-IN') || v.name.toLowerCase().includes('india'))
    }

    // 5. Any female voice with warm pitch
    if (!femaleHindiVoice) {
      femaleHindiVoice = voices.find(v => v.name.toLowerCase().includes('female') || v.name.toLowerCase().includes('zira') || v.name.toLowerCase().includes('samantha'))
    }

    if (femaleHindiVoice) utterance.voice = femaleHindiVoice

    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)

    setSpeaking(true)
    window.speechSynthesis.speak(utterance)
  }

  const handleCopy = () => {
    try {
      navigator.clipboard?.writeText(activeMsg.content).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }).catch(() => {})
    } catch {
      // Clipboard unavailable
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rule bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule/60 pb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-navy" />
          <h4 className="font-display text-[14px] font-bold text-ink">
            Multi-Channel Customer Recovery Interventions
          </h4>
        </div>

        {onOpenPortal && (
          <Button size="sm" tone="primary" icon={ExternalLink} onClick={onOpenPortal}>
            Simulate Customer Recovery Portal
          </Button>
        )}
      </div>

      {/* Channel Switcher Tabs */}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {Object.entries(messages).map(([k, v]) => {
          const Icon = v.icon
          const isSelected = channel === k
          return (
            <button
              key={k}
              type="button"
              onClick={() => {
                if (speaking) {
                  window.speechSynthesis.cancel()
                  setSpeaking(false)
                }
                setChannel(k)
              }}
              className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-[12px] font-medium transition-all cursor-pointer border ${
                isSelected
                  ? 'border-navy bg-navy/10 text-navy font-semibold shadow-xs'
                  : 'border-rule bg-surface hover:bg-surface-raised text-ink-soft'
              }`}
            >
              <Icon className="size-3.5" />
              <span>{v.title}</span>
            </button>
          )
        })}
      </div>

      {/* Active Message Preview Card */}
      <div className="mt-1 relative rounded-lg border border-rule bg-sunk/60 p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow text-ink-faint">Channel Payload</span>
            <Pill tone={activeMsg.badgeTone}>{activeMsg.badge}</Pill>
            {channel === 'voice_ivr_hinglish' && speaking && (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-navy/15 text-navy font-semibold text-[11px] animate-pulse border border-navy/30">
                <Volume2 className="size-3" />
                <span>Priya Speaking (Hindi AI)</span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {channel === 'voice_ivr_hinglish' && (
              <Button
                size="sm"
                tone={speaking ? 'danger' : 'primary'}
                icon={speaking ? Square : PhoneCall}
                onClick={handleSpeak}
              >
                {speaking ? 'End Voice Call' : 'Call Customer (Female Hindi Voice AI)'}
              </Button>
            )}

            <Button size="sm" tone="subtle" icon={copied ? CheckCircle2 : Copy} onClick={handleCopy}>
              {copied ? 'Copied' : 'Copy Text'}
            </Button>
          </div>
        </div>

        {/* Realistic WhatsApp Chat Bubble */}
        {channel === 'whatsapp_hinglish' ? (
          <div className="rounded-lg bg-[#0b141a] p-3 text-white max-w-lg border border-emerald-900/40 shadow-inner">
            <div className="flex items-center gap-2 text-[11px] text-emerald-400 font-semibold mb-1 pb-1 border-b border-emerald-950">
              <MessageSquare className="size-3" /> WhatsApp Official Business Account
            </div>
            <pre className="font-sans text-[12.5px] leading-relaxed whitespace-pre-wrap text-emerald-50">
              {activeMsg.content}
            </pre>
            <div className="mt-2 pt-2 border-t border-emerald-950 flex justify-end">
              <span className="text-[10px] text-emerald-300/60 font-mono">12:34 PM ✓✓</span>
            </div>
          </div>
        ) : (
          <pre className="max-h-60 overflow-auto rounded-md border border-rule/60 bg-surface/90 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink">
            {activeMsg.content}
          </pre>
        )}
      </div>
    </div>
  )
}
