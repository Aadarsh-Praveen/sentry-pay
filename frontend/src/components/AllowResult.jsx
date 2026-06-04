import { useEffect, useState } from 'react'

// Circular SVG confidence meter
function ConfidenceCircle({ percent }) {
  const [animatedPercent, setAnimated] = useState(0)
  const r = 58
  const circumference = 2 * Math.PI * r

  useEffect(() => {
    const t = setTimeout(() => setAnimated(percent), 300)
    return () => clearTimeout(t)
  }, [percent])

  const offset = circumference * (1 - animatedPercent / 100)

  return (
    <div className="relative h-36 w-36 flex items-center justify-center">
      <svg className="absolute inset-0 w-full h-full -rotate-90">
        <circle
          cx="72" cy="72" r={r} fill="transparent"
          className="text-surface-container" stroke="currentColor" strokeWidth="8"
        />
        <circle
          cx="72" cy="72" r={r} fill="transparent"
          className="text-primary" stroke="currentColor" strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 1s ease-out' }}
          strokeLinecap="round"
        />
      </svg>
      <div className="flex flex-col items-center">
        <span className="font-mono text-4xl font-bold">{percent}%</span>
      </div>
    </div>
  )
}

export default function AllowResult({ result, form, onBack }) {
  const confidence = Math.round((result.confidence || 0) * 100)

  return (
    <main className="pt-24 pb-6 px-10 max-w-[1440px] mx-auto fade-in">
      <div className="flex flex-col lg:flex-row gap-5">

        {/* ── LEFT: Transaction Details ─────────────────────────────────── */}
        <div className="flex-1 space-y-5">

          {/* Page header */}
          <section className="flex flex-col gap-1">
            <button
              onClick={onBack}
              className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase hover:text-primary flex items-center gap-1 w-fit transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
              New Analysis
            </button>
            <span className="text-[11px] font-bold tracking-wider text-secondary uppercase">Transaction Analysis</span>
            <h1 className="text-4xl font-bold text-primary">Regular Monthly Invoice</h1>
          </section>

          {/* Bento grid */}
          <div className="grid grid-cols-12 gap-5">

            {/* Invoice summary */}
            <div className="col-span-12 md:col-span-8 bg-white/80 backdrop-blur border border-outline-variant rounded-xl p-6 flex flex-col justify-between min-h-[240px]">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-1">Recipient</p>
                  <p className="text-xl font-bold">{form.recipientName}</p>
                  <p className="text-xs text-secondary mt-0.5">Verified Account</p>
                </div>
                <div className="text-right">
                  <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-1">Amount</p>
                  <p className="font-mono text-2xl font-bold">
                    ${parseFloat(form.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <p className="text-xs text-secondary mt-0.5">USD · {form.paymentType}</p>
                </div>
              </div>

              <div className="mt-8 pt-6 border-t border-outline-variant flex items-center gap-3">
                <div className="h-12 w-12 rounded-lg bg-surface-container flex items-center justify-center">
                  <span className="material-symbols-outlined text-primary">description</span>
                </div>
                <div>
                  <p className="text-xs font-bold text-primary">Payment Request</p>
                  <p className="text-xs text-secondary mt-0.5">Verified via SentryPay agent</p>
                </div>
                <div className="ml-auto text-xs text-on-surface-variant font-mono">
                  {form.accountNumber.slice(-4).padStart(12, '*')}
                </div>
              </div>
            </div>

            {/* Confidence circle */}
            <div className="col-span-12 md:col-span-4 bg-white/80 backdrop-blur border border-outline-variant rounded-xl p-6 flex flex-col justify-center items-center text-center">
              <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-6">
                Internal Confidence Score
              </p>
              <ConfidenceCircle percent={confidence} />
              <p className="text-[11px] font-bold tracking-wider text-primary uppercase mt-4">
                {confidence >= 90 ? 'Exceptional Match' : confidence >= 75 ? 'Strong Match' : 'Match Confirmed'}
              </p>
            </div>

            {/* Verification signals */}
            <div className="col-span-12 bg-white/80 backdrop-blur border border-outline-variant rounded-xl p-6">
              <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-4">
                Authentication Signal Map
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary mt-0.5">domain_verification</span>
                  <div>
                    <p className="text-xs font-bold">Pattern Verification</p>
                    <p className="text-xs text-secondary mt-0.5">
                      {result.typology_matched
                        ? `Low match to scam patterns (threshold not exceeded)`
                        : 'No fraud patterns matched'}
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary mt-0.5">account_balance_wallet</span>
                  <div>
                    <p className="text-xs font-bold">Account Reconciliation</p>
                    <p className="text-xs text-secondary mt-0.5">
                      Known account, not flagged in sanctions database
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary mt-0.5">shield_with_heart</span>
                  <div>
                    <p className="text-xs font-bold">Velocity Assessment</p>
                    <p className="text-xs text-secondary mt-0.5">
                      Amount and vendor consistent with historical behaviour
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── RIGHT: Verdict card ──────────────────────────────────────── */}
        <aside className="w-full lg:w-80 space-y-5">
          <div className="bg-white/80 backdrop-blur border-2 border-primary rounded-xl overflow-hidden">
            {/* Verdict header */}
            <div className="bg-primary p-6 text-white flex flex-col items-center gap-3">
              <div className="h-16 w-16 bg-white rounded-full flex items-center justify-center">
                <span className="material-symbols-filled text-[40px] text-primary">check_circle</span>
              </div>
              <h2 className="text-xl font-bold">🟢 ALLOWED</h2>
              <p className="text-xs opacity-80 text-center">Safe to Proceed with Payment</p>
            </div>

            {/* Reasoning */}
            <div className="p-6 bg-white">
              <div className="mb-6">
                <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-2">Analysis Summary</p>
                <p className="text-sm text-primary leading-relaxed">{result.reasoning}</p>
              </div>

              <button className="w-full bg-primary text-white py-4 rounded-lg text-[11px] font-bold uppercase tracking-widest hover:opacity-90 transition-opacity flex items-center justify-center gap-2 mb-2">
                <span className="material-symbols-outlined text-[18px]">send</span>
                Authorize Release
              </button>
              <button
                onClick={onBack}
                className="w-full border border-outline-variant text-secondary py-3 rounded-lg text-[11px] font-bold uppercase tracking-widest hover:bg-surface-container transition-colors"
              >
                Run Another Check
              </button>
            </div>
          </div>

          {/* Tool latencies */}
          <div className="bg-white/80 backdrop-blur border border-outline-variant rounded-xl p-4">
            <p className="text-[11px] font-bold tracking-wider text-outline uppercase mb-3">Processing Details</p>
            <div className="space-y-2">
              {result.tool_latencies && Object.entries(result.tool_latencies).map(([tool, ms]) => (
                <div key={tool} className="flex justify-between text-xs">
                  <span className="text-on-surface-variant capitalize">{tool.replace(/_/g, ' ')}</span>
                  <span className="font-mono font-bold">{ms}ms</span>
                </div>
              ))}
              <div className="flex justify-between text-xs pt-1 border-t border-outline-variant">
                <span className="text-on-surface-variant">Total</span>
                <span className="font-mono font-bold">{result.processing_ms}ms</span>
              </div>
            </div>
          </div>
        </aside>

      </div>
    </main>
  )
}