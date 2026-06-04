// src/components/HistoryDrawer.jsx
// Refined right-side history drawer matching the new design.
// Shows last 10 decisions from BigQuery with clean status badges.

import { useState, useEffect } from 'react'
import { getDecisions } from '../api/sentrypay.js'

// SentryPay shield logo
const ShieldLogo = ({ size = 20 }) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: size, height: size }}>
    <path d="M12 2L4 5V11C4 16.19 7.41 21.05 12 22.5C16.59 21.05 20 16.19 20 11V5L12 2Z" fill="currentColor"/>
    <path d="M9 12L11 14L15 10" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)


// Map verdict → visual style
function verdictBadge(verdict) {
  switch (verdict) {
    case 'BLOCK':
      return { label: 'Blocked', bg: 'bg-red-100',    text: 'text-red-800',    darkBg: 'bg-red-500/20',    darkText: 'text-red-300' }
    case 'FRICTION':
      return { label: 'Flagged', bg: 'bg-amber-100',  text: 'text-amber-800',  darkBg: 'bg-amber-500/20',  darkText: 'text-amber-300' }
    case 'ALLOW':
    default:
      return { label: 'Allowed', bg: 'bg-green-100',  text: 'text-green-800',  darkBg: 'bg-green-500/20',  darkText: 'text-green-300' }
  }
}


function formatTimeAgo(iso) {
  if (!iso) return ''
  const d  = new Date(iso)
  const ms = Date.now() - d.getTime()
  const m  = Math.floor(ms / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}


function formatMoney(n) {
  return `$${parseFloat(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}


export default function HistoryDrawer({ open, onClose }) {
  const [decisions, setDecisions] = useState([])
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState(null)
  const [selected,  setSelected]  = useState(null)

  // Fetch when drawer opens
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    getDecisions(10)
      .then(data => { if (!cancelled) setDecisions(data || []) })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open])

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className={`fixed inset-0 bg-slate-900/30 z-[60] transition-opacity duration-300 ${
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Drawer */}
      <aside
        className={`fixed top-0 right-0 h-full w-full max-w-[420px] bg-[#d3e4fe] z-[70] shadow-2xl flex flex-col transform transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <header className="flex items-center justify-between p-6 border-b border-slate-300/40 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#131b2e] text-[#7c839b] rounded-lg flex items-center justify-center">
              <ShieldLogo size={20} />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-slate-900">History</h2>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Last 10 decisions
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center text-slate-700 hover:bg-slate-300/40 rounded-full transition-colors"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </header>

        {/* List Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-1">

          {loading && decisions.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <span className="material-symbols-outlined text-3xl animate-spin">progress_activity</span>
              <p className="mt-2 text-sm">Loading history...</p>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
              {error}
            </div>
          )}

          {!loading && decisions.length === 0 && !error && (
            <div className="text-center py-12 text-slate-500">
              <span className="material-symbols-outlined text-5xl text-slate-400">inbox</span>
              <p className="mt-2 text-sm">No decisions yet.</p>
              <p className="text-xs text-slate-400 mt-1">Analyse a payment to see it here.</p>
            </div>
          )}

          {decisions.map(decision => {
            const isSelected = selected === decision.decision_id
            const badge      = verdictBadge(decision.verdict)
            return (
              <DecisionItem
                key={decision.decision_id}
                decision={decision}
                badge={badge}
                isSelected={isSelected}
                onClick={() => setSelected(isSelected ? null : decision.decision_id)}
              />
            )
          })}
        </div>

        {/* Footer */}
        <footer className="p-4 border-t border-slate-300/40 shrink-0">
          <a
            href="mailto:support@sentrypay.ai"
            className="flex items-center gap-2 text-slate-600 hover:text-slate-900 transition-colors text-sm font-medium w-full p-2 rounded-lg hover:bg-slate-300/30"
          >
            <span className="material-symbols-outlined text-[20px]">help</span>
            Support
          </a>
        </footer>
      </aside>
    </>
  )
}


// ═════════════════════════════════════════════════════════════
// Decision item — toggles between light and dark "selected" state
// ═════════════════════════════════════════════════════════════
function DecisionItem({ decision, badge, isSelected, onClick }) {
  if (isSelected) {
    return (
      <div
        onClick={onClick}
        className="bg-[#131b2e] p-4 rounded-xl cursor-pointer hover:opacity-90 transition-opacity relative"
      >
        <div className="flex justify-between items-start mb-2 gap-3">
          <h3 className="text-lg font-semibold text-[#7c839b] truncate">
            {decision.recipient_name || 'Unknown recipient'}
          </h3>
          <span className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wider rounded ${badge.darkBg} ${badge.darkText} whitespace-nowrap`}>
            {badge.label}
          </span>
        </div>
        <p className="text-[13px] text-[#7c839b]/70 mb-1">
          {formatTimeAgo(decision.decision_date)}
        </p>
        <p className="font-mono text-sm text-[#7c839b]">
          {formatMoney(decision.amount)}
        </p>
      </div>
    )
  }

  return (
    <div
      onClick={onClick}
      className="bg-[#d3e4fe] hover:bg-[#dce9ff] p-4 rounded-xl cursor-pointer transition-colors"
    >
      <div className="flex justify-between items-start mb-2 gap-3">
        <h3 className="text-base font-semibold text-slate-900 truncate">
          {decision.recipient_name || 'Unknown recipient'}
        </h3>
        <span className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wider rounded ${badge.bg} ${badge.text} whitespace-nowrap`}>
          {badge.label}
        </span>
      </div>
      <p className="text-[13px] text-slate-500 mb-1">
        {formatTimeAgo(decision.decision_date)}
      </p>
      <p className="font-mono text-sm text-slate-900">
        {formatMoney(decision.amount)}
      </p>
    </div>
  )
}