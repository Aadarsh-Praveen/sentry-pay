import { useEffect, useState } from 'react'

export default function BlockResult({ result, form, onBack }) {
  const [barWidth, setBarWidth] = useState(0)

  useEffect(() => {
    const t = setTimeout(() => setBarWidth(Math.round((result.confidence || 0) * 100)), 300)
    return () => clearTimeout(t)
  }, [result.confidence])

  const confidence = Math.round((result.confidence || 0) * 100)
  const txnId      = result.decision_id?.slice(0, 8).toUpperCase() || 'UNKNOWN'

  async function handleSarDownload() {
    try {
      const res = await fetch(result.sar_pdf_url, {
        headers: { 'X-API-Key': import.meta.env.VITE_API_KEY || 'sentry-pay-dev-key-2026' }
      })
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `SAR_${result.decision_id.slice(0, 8).toUpperCase()}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('SAR download failed:', err)
    }
  }

  return (
    <main className="pt-24 pb-6 px-10 max-w-[1440px] mx-auto fade-in">

      {/* Page header */}
      <div className="mb-6 flex justify-between items-end">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <button
              onClick={onBack}
              className="text-xs text-on-surface-variant hover:text-primary flex items-center gap-1 transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
              New Analysis
            </button>
          </div>
          <h1 className="text-4xl font-bold text-primary">Analysis Result</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Detailed audit of transaction{' '}
            <span className="font-mono text-primary">#{txnId}-BEC</span>
          </p>
        </div>
        {result.sar_pdf_url && (
          <button
            onClick={handleSarDownload}
            className="flex items-center gap-2 bg-surface-container-lowest border border-outline-variant px-4 py-2 rounded-lg hover:bg-surface-container-low transition-all text-sm font-semibold"
          >
            <span className="material-symbols-outlined text-primary">download</span>
            Download SAR
          </button>
        )}
      </div>

      {/* Bento grid */}
      <div className="grid grid-cols-12 gap-5">

        {/* LEFT: Transaction Context */}
        <section className="col-span-12 lg:col-span-5 flex flex-col gap-5">

          <div className="bg-surface-container-lowest border border-outline-variant p-6 rounded-xl shadow-sm">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">description</span>
              Transaction Context
            </h2>
            <div className="space-y-4">
              <div className="p-4 bg-surface-container-low border-l-4 border-primary rounded-r-lg">
                <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-1">
                  Original Email Payload
                </span>
                <p className="text-xs italic text-on-surface-variant leading-relaxed line-clamp-4">
                  "{form.emailText.slice(0, 280)}{form.emailText.length > 280 ? '...' : ''}"
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div>
                  <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-1">Amount</span>
                  <div className="font-mono text-xl font-bold text-primary">
                    ${parseFloat(form.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-1">Recipient</span>
                  <div className="text-sm font-bold text-primary">{form.recipientName}</div>
                </div>
                <div>
                  <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-1">Account</span>
                  <div className="font-mono text-sm text-on-surface">
                    {result.account_masked || `****${form.accountNumber.slice(-4)}`}
                  </div>
                </div>
                <div>
                  <span className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase block mb-1">Payment Type</span>
                  <div className="text-sm text-on-surface">{form.paymentType}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface-container-lowest border border-outline-variant p-6 rounded-xl shadow-sm">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">psychology</span>
              Fraud Classification
            </h2>
            <div className="space-y-3">
              {[
                ['Pattern Identified',  result.typology_matched || 'Unknown'],
                ['Confidence Score',    `${confidence}%`],
                ['SAR Required',        result.sar_required ? 'Yes' : 'No'],
                ['Processing Time',     `${(result.processing_ms / 1000).toFixed(1)}s`],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-center py-2 border-b border-outline-variant last:border-0">
                  <span className="text-sm text-on-surface-variant">{label}</span>
                  <span className="font-mono text-sm font-bold">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* RIGHT: Verdict */}
        <section className="col-span-12 lg:col-span-7 flex flex-col gap-5">

          {/* BLOCKED banner */}
          <div className="bg-[#ffdad6]/30 border-2 border-[#ba1a1a] p-6 rounded-xl relative overflow-hidden">
            <div className="absolute top-0 right-0 p-6 opacity-10">
              <span className="material-symbols-outlined text-[80px] text-[#ba1a1a]"
                    style={{ fontVariationSettings: "'FILL' 1" }}>
                gpp_maybe
              </span>
            </div>
            <div className="flex flex-col gap-4">
              <div className="inline-flex items-center self-start gap-2 px-4 py-1.5 bg-[#ba1a1a] text-white rounded-full text-[11px] font-bold uppercase tracking-widest">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
                </span>
                Blocked — {result.typology_matched || 'Fraud Detected'}
              </div>
              <div>
                <div className="flex justify-between items-end mb-1">
                  <span className="text-2xl font-bold text-[#93000a]">High Risk Alert</span>
                  <span className="font-mono text-xl font-bold text-[#93000a]">{confidence}% Confidence</span>
                </div>
                <div className="w-full bg-[#ba1a1a]/20 h-3 rounded-full overflow-hidden">
                  <div
                    className="bg-[#ba1a1a] h-full rounded-full transition-all duration-1000"
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Red Flags + Analysis Logic */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="bg-surface-container-lowest border border-outline-variant p-6 rounded-xl shadow-sm">
              <h3 className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase mb-4">
                Red Flags Detected
              </h3>
              <ul className="space-y-3">
                {(result.red_flags || []).slice(0, 5).map((flag, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="material-symbols-outlined text-[#ba1a1a] text-[20px] mt-0.5">report</span>
                    <span className="text-sm font-medium">{flag}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="bg-surface-container-lowest border border-outline-variant p-6 rounded-xl shadow-sm">
              <h3 className="text-[11px] font-bold tracking-wider text-on-surface-variant uppercase mb-4">
                Analysis Logic
              </h3>
              <p className="text-xs text-on-surface-variant leading-relaxed">{result.reasoning}</p>
            </div>
          </div>

          {/* Recommended Actions */}
          <div className="bg-primary text-on-primary p-6 rounded-xl shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <span className="material-symbols-outlined">fact_check</span>
              <h2 className="text-xl font-bold">Recommended Analyst Actions</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {[
                ['Phase 1', 'Contact Vendor via Phone'],
                ['Phase 2', 'Verify Account via Bank'],
                ['Phase 3', 'Initiate IC3 Report'],
              ].map(([phase, action]) => (
                <div key={phase} className="bg-white/10 hover:bg-white/20 border border-white/20 p-4 rounded-lg">
                  <div className="text-[10px] font-bold uppercase mb-1 opacity-70">{phase}</div>
                  <div className="text-sm font-bold">{action}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* Footer */}
      <footer className="mt-8 pt-4 border-t border-outline-variant flex flex-wrap justify-between items-center gap-4">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-[11px] font-bold tracking-wider text-on-surface-variant">System Status: Active</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-on-surface-variant text-[18px]">speed</span>
            <span className="font-mono text-xs text-on-surface-variant">
              ElasticSearch:{' '}
              <span className="text-primary font-bold">
                {Math.max(
                  result.tool_latencies?.search_scam_typologies || 0,
                  result.tool_latencies?.check_beneficiary_account || 0,
                  result.tool_latencies?.check_payment_velocity || 0,
                )}ms
              </span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-on-surface-variant text-[18px]">memory</span>
            <span className="font-mono text-xs text-on-surface-variant">
              Inference: <span className="text-primary font-bold">{result.processing_ms}ms</span>
            </span>
          </div>
        </div>
        <div className="text-on-surface-variant text-[11px] italic">SentryPay Neural Guard v1.0.0</div>
      </footer>
    </main>
  )
}