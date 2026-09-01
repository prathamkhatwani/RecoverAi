import { useState, useMemo } from 'react'
import { Panel, Field, Input, Button } from '../components/ui'
import { num } from '../lib/format'
import {
  Calculator,
  TrendingUp,
  IndianRupee,
  Users,
  Shield,
  Sparkles,
  ArrowRight,
  Percent
} from 'lucide-react'

export default function ROICalculator() {
  const [gmv, setGmv] = useState(5000000)
  const [failureRate, setFailureRate] = useState(15)
  const [improvement, setImprovement] = useState(48.7)
  const [retryReduction, setRetryReduction] = useState(75.6)

  const stats = useMemo(() => {
    const monthlyFailuresAtRisk = gmv * (failureRate / 100)
    const baselineMonthlyRecovery = monthlyFailuresAtRisk * 0.35
    const agentMonthlyRecovery = baselineMonthlyRecovery * (1 + improvement / 100)
    
    const additionalMonthlyRevenue = agentMonthlyRecovery - baselineMonthlyRecovery
    const annualAdditionalRevenue = additionalMonthlyRevenue * 12

    const annualFailures = monthlyFailuresAtRisk * 12
    const fewerAnnualRetries = annualFailures * (retryReduction / 100)
    const annualNetworkPenaltySavings = fewerAnnualRetries * 3.5
    
    // Assumes average subscription value is ₹500
    const annualCustomerRetention = (additionalMonthlyRevenue / 500) * 12

    return {
      annualAdditionalRevenue,
      annualNetworkPenaltySavings,
      annualCustomerRetention,
      fewerAnnualRetries
    }
  }, [gmv, failureRate, improvement, retryReduction])

  const formatCurrency = (val) => {
    if (val >= 100000) {
      return `₹${(val / 100000).toFixed(2)} Lakhs`
    }
    return `₹${Math.round(val).toLocaleString()}`
  }

  const formatNumber = (val) => Math.round(val).toLocaleString()

  return (
    <Panel 
      title="Revenue Recovery ROI Projector" 
      icon={Calculator}
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Side: Inputs */}
        <div className="space-y-6">
          <div className="space-y-4">
            <h3 className="eyebrow text-ink-soft">Business Metrics</h3>
            
            <div className="space-y-2">
              <Field label="Monthly GMV (₹)">
                <div className="flex gap-4 items-center">
                  <Input 
                    type="number" 
                    value={gmv} 
                    onChange={(e) => setGmv(Number(e.target.value))}
                    className="flex-1 font-mono"
                  />
                </div>
                <input 
                  type="range" 
                  min="100000" 
                  max="100000000" 
                  step="100000"
                  value={gmv}
                  onChange={(e) => setGmv(Number(e.target.value))}
                  className="w-full accent-navy"
                />
              </Field>
            </div>

            <div className="space-y-2">
              <Field label="Average Failure Rate (%)">
                <div className="flex gap-4 items-center">
                  <Input 
                    type="number" 
                    value={failureRate} 
                    onChange={(e) => setFailureRate(Number(e.target.value))}
                    className="flex-1 font-mono"
                    max="100"
                  />
                </div>
                <input 
                  type="range" 
                  min="1" 
                  max="50" 
                  step="0.1"
                  value={failureRate}
                  onChange={(e) => setFailureRate(Number(e.target.value))}
                  className="w-full accent-navy"
                />
              </Field>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="eyebrow text-ink-soft">Agent Performance Assumptions</h3>
            
            <div className="space-y-2">
              <Field label="Recovery Improvement (%)">
                <div className="flex gap-4 items-center">
                  <Input 
                    type="number" 
                    value={improvement} 
                    onChange={(e) => setImprovement(Number(e.target.value))}
                    className="flex-1 font-mono"
                    max="100"
                  />
                </div>
                <input 
                  type="range" 
                  min="0" 
                  max="100" 
                  step="0.1"
                  value={improvement}
                  onChange={(e) => setImprovement(Number(e.target.value))}
                  className="w-full accent-navy"
                />
              </Field>
            </div>

            <div className="space-y-2">
              <Field label="Retry Reduction (%)">
                <div className="flex gap-4 items-center">
                  <Input 
                    type="number" 
                    value={retryReduction} 
                    onChange={(e) => setRetryReduction(Number(e.target.value))}
                    className="flex-1 font-mono"
                    max="100"
                  />
                </div>
                <input 
                  type="range" 
                  min="0" 
                  max="100" 
                  step="0.1"
                  value={retryReduction}
                  onChange={(e) => setRetryReduction(Number(e.target.value))}
                  className="w-full accent-navy"
                />
              </Field>
            </div>
          </div>
        </div>

        {/* Right Side: Results */}
        <div className="bg-sunk rounded-xl border border-rule p-6 flex flex-col gap-6">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-5 h-5 text-good" />
            <h3 className="eyebrow text-ink">Projected Annual Impact</h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Primary Stat */}
            <div className="col-span-1 sm:col-span-2 bg-surface border border-rule rounded-lg p-5">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-good" />
                <div className="eyebrow text-ink-soft">Additional Annual Revenue</div>
              </div>
              <div className="text-4xl font-mono font-medium text-good mb-1">
                {formatCurrency(stats.annualAdditionalRevenue)}
              </div>
              <div className="text-sm text-ink-faint">
                Top-line growth from recovered failed transactions
              </div>
            </div>

            {/* Secondary Stats */}
            <div className="bg-surface border border-rule rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Shield className="w-4 h-4 text-navy" />
                <div className="eyebrow text-ink-soft">Network Penalty Savings</div>
              </div>
              <div className="text-2xl font-mono text-navy mb-1">
                {formatCurrency(stats.annualNetworkPenaltySavings)}
              </div>
              <div className="text-xs text-ink-faint">
                Saved from avoided auth retries
              </div>
            </div>

            <div className="bg-surface border border-rule rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Users className="w-4 h-4 text-navy" />
                <div className="eyebrow text-ink-soft">Subscriptions Retained Annually</div>
              </div>
              <div className="text-2xl font-mono text-navy mb-1">
                {formatNumber(stats.annualCustomerRetention)}
              </div>
              <div className="text-xs text-ink-faint">
                Assuming ₹500 avg. subscription
              </div>
            </div>

            <div className="col-span-1 sm:col-span-2 bg-surface border border-rule rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Calculator className="w-4 h-4 text-good" />
                <div className="eyebrow text-ink-soft">Fewer Annual Retry Attempts</div>
              </div>
              <div className="text-2xl font-mono text-good mb-1">
                {formatNumber(stats.fewerAnnualRetries)}
              </div>
              <div className="text-xs text-ink-faint">
                Reduced load on your payment gateway
              </div>
            </div>
          </div>
          
          <div className="mt-auto pt-4 border-t border-rule flex items-start gap-3">
            <div className="bg-surface p-2 rounded-full border border-rule shrink-0">
              <IndianRupee className="w-4 h-4 text-ink-soft" />
            </div>
            <p className="text-sm text-ink-soft leading-relaxed">
              Based on your monthly GMV of <span className="font-mono">{formatCurrency(gmv)}</span> and a <span className="font-mono">{failureRate}%</span> failure rate, AI recovery agent can add approximately <span className="font-mono text-good">{formatCurrency(stats.annualAdditionalRevenue)}</span> to your annual bottom line while reducing network costs.
            </p>
          </div>
        </div>
      </div>
    </Panel>
  )
}
