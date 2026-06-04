// src/pages/EmailDashboard.jsx
// Redesigned with cleaner card-based layout, coloured accent borders on hover,
// gradient header background for expanded BLOCK cards, and refined typography.

import { useState, useEffect } from 'react'
import {
  listEmailVerdicts,
  getGmailStatus,
  startGmailScan,
  getGmailScanProgress,
  confirmBlock,
  markSafe,
  confirmAllow,
} from '../api/sentrypay.js'
import { getStoredJwt } from '../hooks/useAuth.js'

// ── Verdict styling map ──────────────────────────────────────
const VERDICT_THEME = {
  BLOCK: {
    pillBg:     'bg-red-50',
    pillText:   'text-red-700',
    pillBorder: 'border-red-200',
    dot:        'bg-red-500',
    label:      'Blocked',
    accent:     'bg-red-500',
    border:     'border-red-200',
    hoverBorder:'hover:border-red-300',
    typology:   'text-red-600',
    gradient:   'from-red-50 to-transparent',
  },
  FRICTION: {
    pillBg:     'bg-amber-50',
    pillText:   'text-amber-700',
    pillBorder: 'border-amber-200',
    dot:        'bg-amber-500',
    label:      'Review',
    accent:     'bg-amber-500',
    border:     'border-slate-200',
    hoverBorder:'hover:border-amber-300',
    typology:   'text-amber-600',
    gradient:   'from-amber-50 to-transparent',
  },
  ALLOW: {
    pillBg:     'bg-green-50',
    pillText:   'text-green-700',
    pillBorder: 'border-green-200',
    dot:        'bg-green-500',
    label:      'Safe',
    accent:     'bg-green-500',
    border:     'border-slate-200',
    hoverBorder:'hover:border-green-300',
    typology:   'text-green-600',
    gradient:   'from-green-50 to-transparent',
  },
}

function getTheme(verdict) {
  return VERDICT_THEME[verdict] || VERDICT_THEME.FRICTION
}

function formatTimeAgo(iso) {
  if (!iso) return ''
  const d  = new Date(iso)
  const ms = Date.now() - d.getTime()
  const m  = Math.floor(ms / 60000)
  if (m < 1)   return 'just now'
  if (m < 60)  return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24)  return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── SAR download ────────────────────────────────────────────
async function downloadSar(decisionId) {
  if (!decisionId) {
    alert('No SAR available for this verdict yet.')
    return
  }
  try {
    const jwt = getStoredJwt()
    const res = await fetch(`/sar/${decisionId}`, {
      headers: {
        'X-API-Key':     'sentry-pay-dev-key-2026',
        'Authorization': jwt ? `Bearer ${jwt}` : '',
      },
    })
    if (!res.ok) {
      alert(`SAR download failed (${res.status}).`)
      return
    }
    const blob = await res.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `SAR_${decisionId.slice(0, 8).toUpperCase()}.pdf`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    alert(`Could not download SAR: ${err.message}`)
  }
}

// ═════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═════════════════════════════════════════════════════════════
export default function EmailDashboard({ user }) {
  const [emails,    setEmails  ] = useState([])
  const [loading,   setLoading ] = useState(true)
  const [status,    setStatus  ] = useState(null)
  const [filter,    setFilter  ] = useState('ALL')
  const [selected,  setSelected] = useState(null)
  const [scanning,  setScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState(null)

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 30_000)
    return () => clearInterval(interval)
  }, [filter])

  async function refresh() {
    try {
      const verdict = filter === 'ALL' ? null : filter
      const [es, s] = await Promise.all([
        listEmailVerdicts({ limit: 50, verdict }),
        getGmailStatus(),
      ])
      setEmails(es)
      setStatus(s)
    } catch (err) {
      console.error('Dashboard load failed:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleRebuildBaseline() {
    if (scanning) return
    setScanning(true)
    setScanProgress({ status: 'starting', message: 'Starting Gmail scan...' })

    try {
      await startGmailScan()
      const interval = setInterval(async () => {
        try {
          const progress = await getGmailScanProgress()
          setScanProgress(progress)
          if (progress.status === 'complete' || progress.status === 'error') {
            clearInterval(interval)
            setTimeout(() => {
              setScanning(false)
              setScanProgress(null)
              refresh()
            }, 2500)
          }
        } catch (err) {
          console.error('Progress poll failed:', err)
        }
      }, 2000)
    } catch (err) {
      setScanning(false)
      setScanProgress({ status: 'error', error: err.message })
    }
  }

  function handleFeedbackSuccess() {
    refresh()
    setSelected(null)
  }

  const counts = emails.reduce((acc, e) => {
    acc[e.agent_verdict] = (acc[e.agent_verdict] || 0) + 1
    return acc
  }, {})

  return (
    <main className="max-w-[1440px] mx-auto px-10 pt-24 pb-10">

      {/* Page header */}
      <div className="mb-6 flex justify-between items-start gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-[32px] font-semibold tracking-tight text-slate-900 leading-10">
              Email Monitoring
            </h1>
            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide bg-green-50 text-green-700 border border-green-200">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 mr-1.5 animate-pulse" />
              Live
            </span>
          </div>
          <p className="text-sm text-slate-500 flex items-center gap-3">
            {status?.email || user?.email}
            <span className="w-1 h-1 rounded-full bg-slate-300" />
            Auto-refreshes every 30 seconds
          </p>
        </div>

        <button
          onClick={handleRebuildBaseline}
          disabled={scanning}
          className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 px-4 py-2 rounded-lg flex items-center gap-2 text-xs font-semibold uppercase tracking-wider transition-all shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {scanning ? (
            <>
              <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
              Scanning...
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-[18px]">refresh</span>
              Rebuild Baseline
            </>
          )}
        </button>
      </div>

      {/* Scan progress banner */}
      {scanning && scanProgress && (
        <div className="mb-6 bg-sky-50 border border-sky-200 rounded-xl p-4 flex items-center gap-3">
          <span className="material-symbols-outlined text-sky-600 animate-spin text-[24px]">progress_activity</span>
          <div className="flex-1">
            <p className="text-sm font-bold text-sky-900">{scanProgress.message || 'Processing...'}</p>
            <div className="mt-1 flex gap-4 text-xs text-sky-700">
              <span>Found: {scanProgress.emails_found || 0}</span>
              <span>Processed: {scanProgress.emails_processed || 0}</span>
              <span>Transactions: {scanProgress.transactions || 0}</span>
            </div>
          </div>
          {scanProgress.status === 'complete' && (
            <span className="material-symbols-outlined text-green-600 text-[24px]">check_circle</span>
          )}
        </div>
      )}

      {/* Filter chips */}
      <div className="flex gap-3 mb-8 border-b border-slate-200 pb-6 overflow-x-auto">
        <FilterChip
          label="All" count={emails.length} dotColour={null}
          active={filter === 'ALL'}
          onClick={() => setFilter('ALL')}
        />
        <FilterChip
          label="Blocked" count={counts.BLOCK || 0} dotColour="bg-red-500"
          active={filter === 'BLOCK'}
          onClick={() => setFilter('BLOCK')}
        />
        <FilterChip
          label="Review" count={counts.FRICTION || 0} dotColour="bg-amber-500"
          active={filter === 'FRICTION'}
          onClick={() => setFilter('FRICTION')}
        />
        <FilterChip
          label="Safe" count={counts.ALLOW || 0} dotColour="bg-green-500"
          active={filter === 'ALLOW'}
          onClick={() => setFilter('ALLOW')}
        />
      </div>

      {/* Email list */}
      {loading && emails.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <span className="material-symbols-outlined text-4xl animate-spin">progress_activity</span>
          <p className="mt-2 text-sm">Loading your monitored emails...</p>
        </div>
      ) : emails.length === 0 ? (
        <EmptyState onRebuild={handleRebuildBaseline} />
      ) : (
        <div className="flex flex-col gap-4">
          {emails.map(email => (
            <EmailCard
              key={email.verdict_id}
              email={email}
              isExpanded={selected === email.verdict_id}
              onClick={() => setSelected(selected === email.verdict_id ? null : email.verdict_id)}
              onFeedback={handleFeedbackSuccess}
            />
          ))}
        </div>
      )}
    </main>
  )
}

// ═════════════════════════════════════════════════════════════
// FILTER CHIP
// ═════════════════════════════════════════════════════════════
function FilterChip({ label, count, dotColour, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-4 py-1.5 text-sm flex items-center gap-2 border transition-all shadow-sm whitespace-nowrap ${
        active
          ? 'bg-sky-50 text-sky-700 border-sky-200'
          : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border-slate-200'
      }`}
    >
      {dotColour && <span className={`w-2 h-2 rounded-full ${dotColour}`} />}
      {label}
      <span className={`px-1.5 py-0.5 rounded-md text-[11px] font-mono ${
        active ? 'bg-sky-100' : 'bg-slate-100'
      }`}>{count}</span>
    </button>
  )
}

// ═════════════════════════════════════════════════════════════
// EMAIL CARD — expanded or collapsed
// ═════════════════════════════════════════════════════════════
function EmailCard({ email, isExpanded, onClick, onFeedback }) {
  const theme     = getTheme(email.agent_verdict)
  const isBlocked = email.agent_verdict === 'BLOCK'
  const hasSar    = isBlocked && (email.sar_generated || email.decision_id)
  const confPct   = Math.round((email.agent_confidence || 0) * 100)

  if (isExpanded) {
    return (
      <article className={`bg-white border ${theme.border} rounded-xl overflow-hidden shadow-md transition-all`}>
        {/* Header */}
        <button
          onClick={onClick}
          className={`w-full p-6 flex justify-between items-start border-b ${theme.border} bg-gradient-to-r ${theme.gradient} text-left`}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-3 flex-wrap">
              <VerdictPill verdict={email.agent_verdict} confidence={email.agent_confidence} />
              <span className="text-sm text-slate-500">{formatTimeAgo(email.timestamp)}</span>
              {hasSar && <SarBadge />}
              {email.human_verdict && <ReviewedBadge />}
            </div>
            <h2 className="text-xl font-semibold text-slate-900 mb-1 leading-tight">
              {email.email_subject || '(no subject)'}
            </h2>
            <p className="text-sm text-slate-500 truncate">
              From: {email.sender} · {email.recipient_name || 'Unknown'}
            </p>
          </div>
          <div className="text-right flex flex-col items-end ml-4">
            <span className="text-2xl font-mono tracking-tight text-slate-900">
              ${parseFloat(email.amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
            {email.typology_matched && (
              <span className={`text-xs font-semibold uppercase mt-1 ${theme.typology}`}>
                {email.typology_matched}
              </span>
            )}
            <span className="material-symbols-outlined text-slate-400 mt-2">expand_less</span>
          </div>
        </button>

        {/* Body */}
        <div className="p-6 bg-slate-50/50">
          <div className="grid grid-cols-4 gap-4 mb-6">
            <DetailField label="Recipient" value={email.recipient_name || '—'} />
            <DetailField label="Account"   value={email.account_number ? '****' + email.account_number.slice(-4) : '—'} mono />
            <DetailField
              label="Sender Domain"
              value={email.sender_domain || '—'}
              mono
              highlight={isBlocked}
            />
            <ConfidenceBar confidence={confPct} accentColour={theme.accent} />
          </div>

          {hasSar && (
            <button
              onClick={() => downloadSar(email.decision_id)}
              className="w-full py-3 border border-red-200 bg-red-50 hover:bg-red-100 text-red-700 rounded-lg flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-wider transition-all"
            >
              <span className="material-symbols-outlined text-[18px]">picture_as_pdf</span>
              Download SAR Report (PDF)
            </button>
          )}

          {!email.human_verdict && (
            <FeedbackSection email={email} onFeedback={onFeedback} hasSar={hasSar} />
          )}

          {email.human_verdict && (
            <div className="mt-6 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2 text-xs">
              <span className="material-symbols-outlined text-green-600 text-[18px]">verified</span>
              <span className="text-green-800 font-semibold">
                You marked this as: {String(email.human_verdict).replace(/_/g, ' ')}
              </span>
            </div>
          )}
        </div>
      </article>
    )
  }

  // ── Collapsed view ──────────────────────────────────────
  return (
    <article
      className={`bg-white border ${theme.border} ${theme.hoverBorder} rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-all cursor-pointer group`}
      onClick={onClick}
    >
      <div className="p-6 flex justify-between items-center group-hover:bg-slate-50 transition-colors relative overflow-hidden">
        <div className={`absolute left-0 top-0 bottom-0 w-1 ${theme.accent} opacity-0 group-hover:opacity-100 transition-opacity`} />
        <div className="flex-1 min-w-0 pr-6 pl-2">
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <VerdictPill verdict={email.agent_verdict} confidence={email.agent_confidence} />
            <span className="text-sm text-slate-500">{formatTimeAgo(email.timestamp)}</span>
            {hasSar && <SarBadge />}
            {email.human_verdict && <ReviewedBadge />}
          </div>
          <h3 className="text-base font-semibold text-slate-900 mb-1 truncate">
            {email.email_subject || '(no subject)'}
          </h3>
          <p className="text-sm text-slate-500 truncate">
            From: {email.sender} · {email.recipient_name || 'Unknown'}
          </p>
        </div>
        <div className="text-right flex flex-col items-end border-l border-slate-200 pl-6 whitespace-nowrap">
          <span className="text-lg font-mono tracking-tight text-slate-900 mb-1">
            ${parseFloat(email.amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </span>
          {email.typology_matched && (
            <span className={`text-[11px] font-semibold uppercase mb-2 ${theme.typology}`}>
              {email.typology_matched}
            </span>
          )}
          <span className="material-symbols-outlined text-slate-400 group-hover:text-sky-600 transition-colors">expand_more</span>
        </div>
      </div>
    </article>
  )
}

// ═════════════════════════════════════════════════════════════
// SUB-COMPONENTS
// ═════════════════════════════════════════════════════════════
function VerdictPill({ verdict, confidence }) {
  const theme = getTheme(verdict)
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide ${theme.pillBg} ${theme.pillText} border ${theme.pillBorder}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${theme.dot} mr-1.5`} />
      {theme.label} {confidence ? `· ${Math.round(confidence * 100)}%` : ''}
    </span>
  )
}

function SarBadge() {
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border border-slate-200 text-slate-700 bg-slate-50">
      <span className="material-symbols-outlined text-[14px] mr-1">description</span>
      SAR
    </span>
  )
}

function ReviewedBadge() {
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide bg-sky-50 text-sky-700 border border-sky-200">
      <span className="material-symbols-outlined text-[14px] mr-1">verified</span>
      Reviewed
    </span>
  )
}

function DetailField({ label, value, mono = false, highlight = false }) {
  return (
    <div>
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">{label}</span>
      {highlight ? (
        <span className={`text-sm ${mono ? 'font-mono' : ''} text-red-700 bg-red-50 px-2 py-0.5 rounded border border-red-200 inline-block`}>
          {value}
        </span>
      ) : (
        <span className={`text-sm text-slate-900 ${mono ? 'font-mono' : ''}`}>{value}</span>
      )}
    </div>
  )
}

function ConfidenceBar({ confidence, accentColour }) {
  return (
    <div>
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">Confidence</span>
      <div className="flex items-center gap-3">
        <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
          <div className={`h-full ${accentColour}`} style={{ width: `${confidence}%` }} />
        </div>
        <span className="text-sm font-mono font-bold text-slate-900">{confidence}%</span>
      </div>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════
// FEEDBACK SECTION
// ═════════════════════════════════════════════════════════════
function FeedbackSection({ email, onFeedback, hasSar }) {
  const [busy, setBusy] = useState(false)

  async function handleConfirm() {
    setBusy(true)
    try {
      if (email.agent_verdict === 'ALLOW') {
        await confirmAllow(email.verdict_id)
      } else {
        await confirmBlock(email.verdict_id)
      }
      onFeedback()
    } catch (err) {
      alert('Feedback failed: ' + err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    setBusy(true)
    try {
      await markSafe(email.verdict_id, 'Marked as safe by user')
      onFeedback()
    } catch (err) {
      alert('Feedback failed: ' + err.message)
    } finally {
      setBusy(false)
    }
  }

  const isBlock    = email.agent_verdict === 'BLOCK'
  const isFriction = email.agent_verdict === 'FRICTION'

  return (
    <div className={`border-t border-slate-200 pt-6 ${hasSar ? 'mt-6' : 'mt-0'}`}>
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-3">
        Was this verdict correct?
      </span>
      <div className="flex gap-3">
        <button
          onClick={handleConfirm}
          disabled={busy}
          className={`flex-1 text-white py-2.5 rounded-lg flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-wider transition-all shadow-sm disabled:opacity-60 ${
            isBlock ? 'bg-red-600 hover:bg-red-700' : 'bg-slate-900 hover:bg-slate-800'
          }`}
        >
          <span className="material-symbols-outlined text-[18px]">check_circle</span>
          {isBlock    ? 'Yes, confirmed fraud'
          : isFriction ? 'Yes, suspicious'
          : 'Yes, this is safe'}
        </button>
        <button
          onClick={handleReject}
          disabled={busy}
          className="flex-1 bg-white text-slate-700 py-2.5 rounded-lg flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-wider transition-all hover:bg-slate-50 border border-slate-200 shadow-sm disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-[18px]">cancel</span>
          {isBlock ? 'No, this is safe' : 'No, this looks risky'}
        </button>
      </div>
      <p className="text-[11px] text-slate-500 mt-3 italic">
        Your feedback trains SentryPay's fraud models for everyone.
      </p>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════
// EMPTY STATE
// ═════════════════════════════════════════════════════════════
function EmptyState({ onRebuild }) {
  return (
    <div className="text-center py-20 text-slate-500">
      <span className="material-symbols-outlined text-6xl text-slate-300">forward_to_inbox</span>
      <h3 className="text-xl font-semibold text-slate-900 mt-4 mb-2">No payment emails yet</h3>
      <p className="text-sm max-w-md mx-auto mb-6">
        SentryPay watches your Gmail every 5 minutes. To analyse existing emails right now, click below to scan your last 90 days of mail.
      </p>
      <button
        onClick={onRebuild}
        className="inline-flex items-center gap-2 px-6 py-3 bg-slate-900 text-white rounded-xl text-xs font-bold tracking-widest uppercase hover:bg-slate-800 active:scale-95 transition-all shadow-sm"
      >
        <span className="material-symbols-outlined text-[18px]">refresh</span>
        Scan My Gmail Now
      </button>
    </div>
  )
}