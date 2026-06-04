import { useState, useEffect } from 'react'

export default function FrictionResult({ result, form, onBack }) {
  const [seconds,  setSeconds ] = useState(15 * 60)
  const [barWidth, setBarWidth] = useState(0)

  const confidence = Math.round((result.confidence || 0) * 100)

  // Start 15-minute countdown
  useEffect(() => {
    const t = setInterval(() => {
      setSeconds(s => {
        if (s <= 0) { clearInterval(t); return 0 }
        return s - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [])

  // Animate confidence bar
  useEffect(() => {
    const t = setTimeout(() => setBarWidth(confidence), 300)
    return () => clearTimeout(t)
  }, [confidence])

  const minutes   = Math.floor(seconds / 60)
  const secs      = seconds % 60
  const timerStr  = `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  const expired   = seconds === 0

  return (
    <main className="pt-24 pb-6 px-10 max-w-[1440px] mx-auto fade-in">
      <div className="grid grid-cols-12 gap-5">

        {/* ── LEFT: Invoice / Transaction Details ──────────────────────────── */}
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-5">

          {/* Breadcrumb */}
          <div className="flex items-center gap-1 text-[11px] font-bold tracking-wider text-on-surface-variant uppercase">
            <button onClick={onBack} className="hover:text-primary transition-colors">Transactions</button>
            <span className="material-symbols-outlined text-[16px]">chevron_right</span>
            <span>{form.recipientName?.split(' ').slice(0, 2).join(' ')}</span>
            <span className="material-symbols-outlined text-[16px]">chevron_right</span>
            <span className="text-primary font-bold">Risk Analysis</span>
          </div>

          {/* Main workspace card */}
          <section className="bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
            <div className="flex justify-between items-start mb-8">
              <div>
                <h1 className="text-4xl font-bold text-on-surface mb-1">
                  Invoice Analysis
                </h1>
                <p className="text-sm text-on-surface-variant">
                  Payment request • {form.recipientName}
                </p>
              </div>
              <div className="bg-surface-container-high px-4 py-2 rounded-lg border border-outline-variant">
                <span className="font-mono text-sm text-on-surface-variant">
                  AMT: ${parseFloat(form.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })} USD
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {/* Left: Email preview */}
              <div className="flex flex-col gap-3">
                <h3 className="text-xl font-bold border-b border-outline-variant pb-2">Email Content</h3>
                <div className="bg-surface-container-low rounded-lg p-4 text-xs text-on-surface-variant leading-relaxed font-mono max-h-40 overflow-y-auto whitespace-pre-wrap">
                  {form.emailText}
                </div>
                <div className="bg-surface-container-lowest border border-outline-variant rounded-lg p-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="h-8 w-8 rounded bg-surface-container flex items-center justify-center">
                      <span className="material-symbols-outlined text-primary text-[18px]">mail</span>
                    </div>
                    <span className="text-xs font-bold text-primary">Payment Request Email</span>
                  </div>
                  <span className="text-[11px] text-on-surface-variant">Unverified sender</span>
                </div>
              </div>

              {/* Right: Extracted metadata */}
              <div className="flex flex-col gap-4">
                <h3 className="text-xl font-bold border-b border-outline-variant pb-2">Extracted Metadata</h3>
                <div className="space-y-2">
                  {[
                    ['Vendor Name',     form.recipientName],
                    ['Account Number',  form.accountNumber.slice(-4).padStart(8, '*')],
                    ['Payment Type',    form.paymentType],
                    ['Amount',         `$${parseFloat(form.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}`],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between py-1 border-b border-outline-variant/30">
                      <span className="text-[11px] font-bold tracking-wider text-on-surface-variant">{label}</span>
                      <span className="font-mono text-sm">{value}</span>
                    </div>
                  ))}
                </div>

                {/* System advisory */}
                <div className="mt-4 p-4 bg-[#fcdeb5] rounded-xl border border-[#574425]/20">
                  <div className="flex items-center gap-2 mb-1 text-[#574425]">
                    <span className="material-symbols-filled text-[18px]">info</span>
                    <span className="text-[11px] font-bold uppercase tracking-wider">System Advisory</span>
                  </div>
                  <p className="text-xs text-[#574425] leading-relaxed">
                    {result.recommended_action || 'Verification required. Call recipient to confirm details before timer expires.'}
                  </p>
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* ── RIGHT: Analysis Panel ─────────────────────────────────────── */}
        <aside className="col-span-12 lg:col-span-4 flex flex-col gap-5">
          <div className="bg-surface-container-low border border-outline-variant rounded-xl p-8 shadow-xl sticky top-24">

            {/* FRICTION badge */}
            <div className="flex justify-center mb-8">
              <div className="inline-flex items-center gap-2 bg-[#FFF9C4] border border-[#FBC02D] px-4 py-2 rounded-full">
                <span className="w-3 h-3 bg-[#FBC02D] rounded-full animate-pulse" />
                <span className="text-[11px] font-bold text-[#7B5E00]">🟡 FRICTION — Verification Required</span>
              </div>
            </div>

            {/* Countdown timer */}
            <div className="text-center mb-8">
              <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-3">
                Action Window Remaining
              </span>
              <div
                className={`font-mono text-5xl font-bold tracking-widest ${
                  expired ? 'text-[#ba1a1a] animate-pulse' : seconds < 60 ? 'text-[#ba1a1a] animate-bounce' : 'text-[#ba1a1a]'
                }`}
                style={{ textShadow: '0 0 15px rgba(186,26,26,0.15)' }}
              >
                {expired ? 'EXPIRED' : timerStr}
              </div>
            </div>

            {/* Confidence bar */}
            <div className="mb-8">
              <div className="flex justify-between items-end mb-1">
                <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase">
                  Integrity Confidence
                </span>
                <span className="font-mono text-xl font-bold text-primary">{confidence}%</span>
              </div>
              <div className="h-2 w-full bg-outline-variant rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#FBC02D] transition-all duration-1000 rounded-full"
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>

            {/* Red flags / anomalies */}
            <div className="space-y-3 mb-8">
              <h4 className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase">
                Anomalies Detected
              </h4>
              {(result.red_flags || []).slice(0, 3).map((flag, i) => (
                <div key={i} className="flex items-start gap-2 p-3 bg-white border border-outline-variant rounded-lg">
                  <span className="material-symbols-outlined text-[#ba1a1a] text-[18px]">flag</span>
                  <p className="text-xs">{flag}</p>
                </div>
              ))}
            </div>

            {/* Action buttons */}
            <div className="flex flex-col gap-2">
              <button className="w-full bg-primary text-on-primary py-4 rounded-xl text-[11px] font-bold uppercase tracking-widest hover:opacity-90 active:scale-95 transition-all flex items-center justify-center gap-2">
                <span className="material-symbols-outlined text-[18px]">call</span>
                Log Verification Call
              </button>
              <button className="w-full bg-surface-container-highest text-on-surface py-4 rounded-xl text-[11px] font-bold uppercase tracking-widest hover:bg-surface-variant transition-all border border-outline-variant">
                Request Original Source
              </button>
              <button
                onClick={onBack}
                className="w-full text-[#ba1a1a] text-[11px] font-bold uppercase tracking-widest py-2 hover:bg-[#ffdad6]/30 rounded-xl transition-all"
              >
                Reject &amp; Flag Fraud
              </button>
            </div>
          </div>
        </aside>

      </div>
    </main>
  )
}