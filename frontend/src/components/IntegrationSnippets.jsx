import { useState } from 'react'
import { Panel, Button, Pill } from './ui'
import { Code, Copy, Check, Terminal, Globe, Braces } from 'lucide-react'

export default function IntegrationSnippets({ 
  rawCode = 'insufficient_funds', 
  rawMessage = 'Your card has insufficient funds.', 
  gateway = 'stripe', 
  amount = 1000 
}) {
  const [activeTab, setActiveTab] = useState('curl')
  const [copied, setCopied] = useState(false)

  // Using amount * 100 for minor units if it's not already
  const amountMinor = amount * 100

  const snippets = {
    curl: `curl -X POST http://localhost:8000/api/classify \\
  -H "Content-Type: application/json" \\
  -d '{
    "raw_code": "${rawCode}",
    "raw_message": "${rawMessage}",
    "gateway": "${gateway}",
    "amount_minor": ${amountMinor}
  }'`,
    python: `import requests

response = requests.post("http://localhost:8000/api/classify", json={
    "raw_code": "${rawCode}",
    "raw_message": "${rawMessage}",
    "gateway": "${gateway}",
    "amount_minor": ${amountMinor}
})

diagnosis = response.json()
print(f"Root cause: {diagnosis['classification']['root_cause']}")
print(f"Action: {diagnosis['plan']['action']}")`,
    node: `const res = await fetch('http://localhost:8000/api/classify', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    raw_code: '${rawCode}',
    raw_message: '${rawMessage}',
    gateway: '${gateway}',
    amount_minor: ${amountMinor}
  })
});

const diagnosis = await res.json();
console.log('Root cause:', diagnosis.classification.root_cause);
console.log('Action:', diagnosis.plan.action);`
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(snippets[activeTab])
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Panel className="flex flex-col gap-4">
      <div className="flex flex-row gap-6 border-b border-rule">
        <button
          className={`pb-2 px-1 flex items-center gap-2 font-medium text-sm transition-colors ${
            activeTab === 'curl' 
              ? 'border-b-2 border-navy text-navy' 
              : 'text-ink-faint hover:text-ink'
          }`}
          onClick={() => setActiveTab('curl')}
        >
          <Pill className={activeTab === 'curl' ? 'bg-navy/10' : ''}>
            <Terminal className="w-3.5 h-3.5" />
          </Pill>
          cURL
        </button>
        <button
          className={`pb-2 px-1 flex items-center gap-2 font-medium text-sm transition-colors ${
            activeTab === 'python' 
              ? 'border-b-2 border-navy text-navy' 
              : 'text-ink-faint hover:text-ink'
          }`}
          onClick={() => setActiveTab('python')}
        >
          <Pill className={activeTab === 'python' ? 'bg-navy/10' : ''}>
            <Globe className="w-3.5 h-3.5" />
          </Pill>
          Python
        </button>
        <button
          className={`pb-2 px-1 flex items-center gap-2 font-medium text-sm transition-colors ${
            activeTab === 'node' 
              ? 'border-b-2 border-navy text-navy' 
              : 'text-ink-faint hover:text-ink'
          }`}
          onClick={() => setActiveTab('node')}
        >
          <Pill className={activeTab === 'node' ? 'bg-navy/10' : ''}>
            <Braces className="w-3.5 h-3.5" />
          </Pill>
          Node.js
        </button>
      </div>

      <div className="relative">
        <pre className="bg-[#0d1117] rounded-lg p-4 overflow-auto font-mono text-[12.5px] text-[#e6edf3] border border-rule/30 whitespace-pre-wrap">
          {snippets[activeTab]}
        </pre>
        <button
          onClick={handleCopy}
          className="absolute top-3 right-3 p-1.5 rounded bg-white/10 hover:bg-white/20 text-white transition-colors"
          title="Copy code"
        >
          {copied ? (
            <Check className="w-4 h-4 text-green-400" />
          ) : (
            <Copy className="w-4 h-4" />
          )}
        </button>
      </div>
    </Panel>
  )
}
