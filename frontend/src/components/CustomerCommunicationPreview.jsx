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
  const [ivrLang, setIvrLang] = useState('hi') // 'hi' or 'en'
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
      title: 'IVR Voice Call (Hindi & English AI)',
      icon: PhoneCall,
      badge: ivrLang === 'hi' ? 'प्रिया AI (शुद्ध हिंदी IVR)' : 'Priya AI (English IVR)',
      badgeTone: 'navy',
      content: ivrLang === 'hi'
        ? `[IVR Telecom Announcement... Call Connected]

आवाज (प्रिया - टेलीकॉम AI):
"नमस्ते ${customerName} जी। यह रेज़रपे रिकवर एआई से आपके सब्सक्रिप्शन भुगतान के बारे में एक आवश्यक सूचना है।

आपका ${amountFormatted} का सब्सक्रिप्शन भुगतान आपके बैंक द्वारा पूरा नहीं किया जा सका।

अपनी सेवा को बिना किसी रुकावट के जारी रखने के लिए, हमने आपके पंजीकृत व्हाट्सएप और एसएमएस पर एक सुरक्षित वन-क्लिक पेमेंट लिंक भेजा है।

कृपया लिंक पर टैप करके अपना पसंदीदा भुगतान विकल्प चुनें। धन्यवाद!"`
        : `[IVR Telecom Announcement... Call Connected]

Agent (Priya - Corporate AI Voice):
"Hello ${customerName}. This is an automated notification from Razorpay Recover AI regarding your subscription.

Your scheduled payment of ${amountFormatted} could not be processed by your bank.

To prevent any service interruption, we have sent a secure one-click payment link to your registered mobile number and WhatsApp.

Please tap the link to authorize your renewal. Thank you!"`,
      speechText: ivrLang === 'hi'
        ? `नमस्ते ${customerName} जी। यह रेज़रपे रिकवर एआई से आपके सब्सक्रिप्शन भुगतान के बारे में एक आवश्यक सूचना है। आपका ${amountFormatted} का सब्सक्रिप्शन भुगतान आपके बैंक द्वारा पूरा नहीं किया जा सका। अपनी सेवा को बिना किसी रुकावट के जारी रखने के लिए, हमने आपके पंजीकृत व्हाट्सएप और एसएमएस पर एक सुरक्षित वन-क्लिक पेमेंट लिंक भेजा है। कृपया लिंक पर टैप करके अपना भुगतान पूरा करें। धन्यवाद।`
        : `Hello ${customerName}. This is an automated payment update from Razorpay Recover AI. Your scheduled payment of ${amountFormatted} was declined by your bank. We have sent a secure one-click recovery link to your registered WhatsApp and mobile number. Please tap the link to complete your payment. Thank you.`,
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
    const voices = window.speechSynthesis.getVoices()

    if (ivrLang === 'hi') {
      // 🇮🇳 Hindi IVR Configuration
      utterance.lang = 'hi-IN'
      utterance.rate = 0.88 // Fluent, clear telecom announcement speed
      utterance.pitch = 1.08 // Warm, natural female voice pitch

      // Priority: Native Hindi Female voices (Swara, Kalpana, Google हिन्दी, etc.)
      const hindiVoice = voices.find(v => 
        (v.lang.startsWith('hi') || v.lang.includes('IN')) &&
        (v.name.includes('हिन्दी') ||
         v.name.toLowerCase().includes('swara') ||
         v.name.toLowerCase().includes('kalpana') ||
         v.name.toLowerCase().includes('hindi') ||
         v.name.toLowerCase().includes('female'))
      ) || voices.find(v => v.lang.startsWith('hi') || v.lang.includes('hi-IN'))

      if (hindiVoice) utterance.voice = hindiVoice
    } else {
      // 🌐 English IVR Configuration
      utterance.lang = 'en-IN'
      utterance.rate = 0.92
      utterance.pitch = 1.12

      // Priority: Indian English / British / Natural Female voices
      const englishVoice = voices.find(v => 
        (v.lang.includes('en-IN') || v.lang.includes('en-GB') || v.lang.includes('en-US')) &&
        (v.name.toLowerCase().includes('heera') ||
         v.name.toLowerCase().includes('neerja') ||
         v.name.toLowerCase().includes('kavya') ||
         v.name.toLowerCase().includes('aditi') ||
         v.name.toLowerCase().includes('female') ||
         v.name.toLowerCase().includes('zira') ||
         v.name.toLowerCase().includes('samantha'))
      ) || voices.find(v => v.lang.startsWith('en'))

      if (englishVoice) utterance.voice = englishVoice
    }

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
        {channel === 'voice_ivr_hinglish' && (
          <div className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-lg bg-surface border border-rule/80 mb-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow text-ink-faint">IVR Voice Language:</span>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    if (speaking) window.speechSynthesis.cancel()
                    setSpeaking(false)
                    setIvrLang('hi')
                  }}
                  className={`px-3 py-1 rounded-md text-[11.5px] font-semibold transition-all cursor-pointer border ${
                    ivrLang === 'hi'
                      ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 shadow-xs'
                      : 'bg-sunk text-ink-soft border-rule hover:text-ink'
                  }`}
                >
                  🇮🇳 शुद्ध हिंदी (Fluent Hindi IVR)
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (speaking) window.speechSynthesis.cancel()
                    setSpeaking(false)
                    setIvrLang('en')
                  }}
                  className={`px-3 py-1 rounded-md text-[11.5px] font-semibold transition-all cursor-pointer border ${
                    ivrLang === 'en'
                      ? 'bg-navy/15 text-navy border-navy/40 shadow-xs'
                      : 'bg-sunk text-ink-soft border-rule hover:text-ink'
                  }`}
                >
                  🌐 English (Fluent Corporate IVR)
                </button>
              </div>
            </div>
            <span className="text-[11px] font-mono text-ink-faint hidden sm:inline">
              {ivrLang === 'hi' ? 'देवनागरी न्यूरल वॉइस' : 'Corporate Neural Voice'}
            </span>
          </div>
        )}

        <div className="flex items-center justify-between mb-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow text-ink-faint">Channel Payload</span>
            <Pill tone={activeMsg.badgeTone}>{activeMsg.badge}</Pill>
            {channel === 'voice_ivr_hinglish' && speaking && (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-navy/15 text-navy font-semibold text-[11px] animate-pulse border border-navy/30">
                <Volume2 className="size-3" />
                <span>{ivrLang === 'hi' ? 'प्रिया बोल रही हैं (हिंदी AI)' : 'Priya Speaking (English AI)'}</span>
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
                {speaking ? 'End Call' : ivrLang === 'hi' ? '🔊 कॉल करें (शुद्ध हिंदी AI)' : '🔊 Call Customer (English AI)'}
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
