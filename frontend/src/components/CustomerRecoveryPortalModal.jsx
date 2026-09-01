import { useState } from 'react'
import { Drawer, Button, Pill } from './ui'
import {
  ShieldCheck,
  CheckCircle2,
  Smartphone,
  CreditCard,
  Building2,
  QrCode,
  ArrowRight,
  Lock,
  Clock,
  Sparkles,
  Zap
} from 'lucide-react'

export default function CustomerRecoveryPortalModal({
  open,
  onClose,
  amountFormatted = '₹1,499.00',
  planName = 'Pro Monthly Subscription',
  customerName = 'Rahul Sharma',
  cause = 'insufficient_funds',
  onSuccess
}) {
  const [selectedMethod, setSelectedMethod] = useState('upi')
  const [upiId, setUpiId] = useState('rahul@okaxis')
  const [processing, setProcessing] = useState(false)
  const [completed, setCompleted] = useState(false)

  const causeDescriptions = {
    insufficient_funds: 'Temporary balance shortfall at the scheduled retry time.',
    expired_card: 'The card on file expired and requires an updated expiry date or new card.',
    auth_3ds_failure: 'Previous transaction timed out during SMS/OTP authentication.',
    lapsed_mandate: 'Auto-debit mandate limit or validity needs a quick re-authorization.',
    gateway_error: 'Bank processing network experienced a momentary outage.',
  }

  const handlePay = () => {
    setProcessing(true)
    setTimeout(() => {
      setProcessing(false)
      setCompleted(true)
      onSuccess?.()
    }, 1400)
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Customer Recovery Portal (Simulated Experience)"
      subtitle="The exact seamless 1-click recovery screen presented to the customer via SMS/WhatsApp."
    >
      <div className="flex flex-col gap-4 text-[13px]">
        {completed ? (
          <div className="flex flex-col items-center justify-center p-8 text-center bg-good/10 border border-good/30 rounded-xl animate-in zoom-in-95 duration-200">
            <div className="size-14 rounded-full bg-good text-white flex items-center justify-center shadow-lg shadow-good/30 mb-4">
              <CheckCircle2 className="size-8" />
            </div>
            <h3 className="font-display text-2xl font-bold text-ink">Payment Successful!</h3>
            <p className="mt-1 font-mono text-xl font-bold text-good">{amountFormatted}</p>
            <p className="mt-2 text-[12.5px] text-ink-soft max-w-sm">
              Your subscription for <strong className="text-ink">{planName}</strong> has been renewed. Mandate updated successfully with zero interruption.
            </p>
            <div className="mt-6 flex gap-2">
              <Button tone="primary" onClick={onClose}>
                Back to Console
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Merchant Header */}
            <div className="p-4 rounded-xl bg-surface border border-rule shadow-xs flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="size-10 rounded-lg bg-navy/10 border border-navy/20 flex items-center justify-center text-navy font-bold font-display">
                  RA
                </div>
                <div>
                  <h4 className="font-display font-bold text-[14px] text-ink">{planName}</h4>
                  <p className="text-[11.5px] text-ink-faint">Billed to {customerName}</p>
                </div>
              </div>
              <div className="text-right">
                <div className="eyebrow text-ink-faint">Amount Due</div>
                <div className="font-mono text-xl font-bold text-ink">{amountFormatted}</div>
              </div>
            </div>

            {/* Plain English Reason Banner */}
            <div className="p-3 bg-warn-soft border border-warn/30 rounded-lg flex items-start gap-2.5">
              <Sparkles className="size-4 text-warn shrink-0 mt-0.5" />
              <div className="text-[12px] text-ink">
                <strong className="font-semibold text-warn">Why did the previous charge pause?</strong>
                <p className="mt-0.5 text-ink-soft">{causeDescriptions[cause] || causeDescriptions.insufficient_funds}</p>
              </div>
            </div>

            {/* Payment Method Selector */}
            <div>
              <div className="eyebrow text-ink-faint mb-2">Select Instant Recovery Method</div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {[
                  { key: 'upi', label: 'UPI Instant Pay', icon: Smartphone, desc: 'GPay / PhonePe / Paytm' },
                  { key: 'card', label: 'Credit / Debit Card', icon: CreditCard, desc: 'Visa / Mastercard / RuPay' },
                  { key: 'netbanking', label: 'Net Banking', icon: Building2, desc: '50+ Indian Banks' },
                ].map((m) => {
                  const Icon = m.icon
                  const isSel = selectedMethod === m.key
                  return (
                    <button
                      key={m.key}
                      type="button"
                      onClick={() => setSelectedMethod(m.key)}
                      className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                        isSel
                          ? 'border-navy bg-navy/10 text-navy font-bold shadow-xs'
                          : 'border-rule bg-surface hover:bg-surface-raised text-ink-soft'
                      }`}
                    >
                      <Icon className="size-4 mb-1" />
                      <div className="font-semibold text-[12.5px] text-ink">{m.label}</div>
                      <div className="text-[10.5px] text-ink-faint">{m.desc}</div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* UPI Form */}
            {selectedMethod === 'upi' && (
              <div className="p-3.5 bg-sunk/60 border border-rule rounded-lg flex flex-col gap-2">
                <label className="eyebrow text-ink-faint">Virtual Payment Address (VPA)</label>
                <div className="flex gap-2">
                  <input
                    value={upiId}
                    onChange={(e) => setUpiId(e.target.value)}
                    className="flex-1 rounded border border-rule bg-surface px-3 py-1.5 font-mono text-[13px] text-ink focus:border-navy focus:outline-none"
                    placeholder="yourname@upi"
                  />
                  <span className="px-2 py-1.5 rounded bg-surface border border-rule text-[11.5px] font-medium text-good flex items-center gap-1">
                    <CheckCircle2 className="size-3" /> AutoPay Ready
                  </span>
                </div>
              </div>
            )}

            {/* Card Form */}
            {selectedMethod === 'card' && (
              <div className="p-3.5 bg-sunk/60 border border-rule rounded-lg flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[12.5px] font-bold text-ink">•••• •••• •••• 4242</span>
                  <span className="text-[11px] text-navy font-semibold">Update Expiry</span>
                </div>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <input
                    defaultValue="08/29"
                    className="rounded border border-rule bg-surface px-3 py-1.5 font-mono text-[13px] text-ink"
                    placeholder="MM/YY"
                  />
                  <input
                    defaultValue="•••"
                    className="rounded border border-rule bg-surface px-3 py-1.5 font-mono text-[13px] text-ink"
                    placeholder="CVV"
                  />
                </div>
              </div>
            )}

            {/* Security Guarantee & Pay Button */}
            <div className="pt-2 flex flex-col gap-3">
              <div className="flex items-center justify-between text-[11px] text-ink-faint">
                <span className="flex items-center gap-1">
                  <Lock className="size-3 text-good" /> 256-Bit SSL Encrypted Razorpay Gateway
                </span>
                <span>PCI-DSS Level 1</span>
              </div>

              <Button
                tone="primary"
                className="w-full py-2.5 text-[14px] font-bold shadow-md shadow-navy/20"
                icon={Zap}
                disabled={processing}
                onClick={handlePay}
              >
                {processing ? 'Processing Secure AutoPay…' : `Pay ${amountFormatted} & Resume Subscription`}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Drawer>
  )
}
