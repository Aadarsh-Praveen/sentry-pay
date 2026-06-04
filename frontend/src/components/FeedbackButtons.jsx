// src/components/FeedbackButtons.jsx
// ─────────────────────────────────────────────────────────────
// Lets the user confirm or correct a verdict — drives continuous learning.

import { useState } from 'react'
import { confirmBlock, markSafe, confirmAllow } from '../api/sentrypay.js'

export default function FeedbackButtons({ email, onFeedback }) {
  const [busy,    setBusy   ] = useState(false)
  const [message, setMessage] = useState(null)

  if (email.human_verdict) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-3 flex items-center gap-2 text-xs">
        <span className="material-symbols-outlined text-green-600 text-[18px]">verified</span>
        <span className="text-green-800 font-semibold">
          You marked this as: {email.human_verdict.replace(/_/g, ' ')}
        </span>
      </div>
    )
  }

  async function handleConfirm() {
    setBusy(true)
    try {
      let result
      if (email.agent_verdict === 'BLOCK') {
        result = await confirmBlock(email.verdict_id)
      } else if (email.agent_verdict === 'ALLOW') {
        result = await confirmAllow(email.verdict_id)
      } else {
        // FRICTION → user verifying it's actually fraud → treat as confirm_block
        result = await confirmBlock(email.verdict_id)
      }
      setMessage({ type: 'success', text: getSuccessMsg(email.agent_verdict, result) })
      setTimeout(() => onFeedback(), 1500)
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to record feedback' })
    } finally {
      setBusy(false)
    }
  }

  async function handleCorrect() {
    setBusy(true)
    try {
      const result = await markSafe(email.verdict_id, 'Marked as safe by user')
      setMessage({
        type: 'success',
        text: `Added to your safe vendors. We'll allow ${email.recipient_name} payments automatically.`,
      })
      setTimeout(() => onFeedback(), 2000)
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to record feedback' })
    } finally {
      setBusy(false)
    }
  }

  function getSuccessMsg(verdict, result) {
    if (verdict === 'BLOCK') {
      return `Confirmed fraud. Account flagged across SentryPay's community blocklist.`
    }
    return `Confirmed safe. Vendor added to your trusted list.`
  }

  // ── Render ────────────────────────────────────────────────
  if (message) {
    return (
      <div className={`rounded-lg p-3 flex items-start gap-2 text-xs ${
        message.type === 'success' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
      }`}>
        <span className={`material-symbols-outlined text-[18px] ${
          message.type === 'success' ? 'text-green-600' : 'text-red-600'
        }`}>
          {message.type === 'success' ? 'check_circle' : 'error'}
        </span>
        <span className={message.type === 'success' ? 'text-green-800' : 'text-red-800'}>
          {message.text}
        </span>
      </div>
    )
  }

  return (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">
        Was this verdict correct?
      </p>
      <div className="flex gap-2">
        <button
          onClick={handleConfirm}
          disabled={busy}
          className="flex-1 flex items-center justify-center gap-1 bg-primary text-on-primary px-3 py-2 rounded-lg text-xs font-bold hover:opacity-90 active:scale-95 transition-all disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[16px]">check_circle</span>
          {email.agent_verdict === 'BLOCK'    ? 'Yes, confirmed fraud'
          : email.agent_verdict === 'ALLOW'  ? 'Yes, this is safe'
          : 'Yes, suspicious'}
        </button>
        <button
          onClick={handleCorrect}
          disabled={busy}
          className="flex-1 flex items-center justify-center gap-1 bg-surface-container border border-outline-variant text-on-surface px-3 py-2 rounded-lg text-xs font-bold hover:bg-surface-variant active:scale-95 transition-all disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[16px]">cancel</span>
          {email.agent_verdict === 'BLOCK' ? 'No, this is safe' : 'No, this looks risky'}
        </button>
      </div>
      <p className="text-[10px] text-on-surface-variant mt-2 italic">
        Your feedback trains SentryPay's fraud models for everyone.
      </p>
    </div>
  )
}