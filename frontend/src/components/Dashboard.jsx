// src/components/Dashboard.jsx
// Redesigned two-column manual check layout.
// Left:  payment analysis form
// Right: "waiting for analysis" placeholder with abstract graphic + status pills

import { useState } from 'react'

export default function Dashboard({ form, onChange, onSubmit, loading }) {
  return (
    <main className="flex-1 w-full max-w-[1440px] mx-auto px-10 pt-24 pb-10 grid grid-cols-1 lg:grid-cols-12 gap-6">

      {/* ── LEFT COLUMN — Form ─────────────────────────────────────── */}
      <div className="lg:col-span-5 flex flex-col gap-6">

        {/* Form card */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 mb-2">
            Payment Analysis
          </h1>
          <p className="text-sm text-slate-500 mb-8">
            Input communication details for AI-driven risk assessment.
          </p>

          <div className="flex flex-col gap-4">

            {/* Paste Email or Message */}
            <Field label="Paste Email or Message">
              <textarea
                value={form.emailText}
                onChange={(e) => onChange('emailText', e.target.value)}
                rows={6}
                placeholder="Paste the email content or payment instructions here for automated threat detection..."
                className="w-full bg-[#f8f9ff] border border-slate-200 rounded-lg p-4 text-sm focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-all resize-none outline-none"
              />
            </Field>

            {/* Amount + Payment Type */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Amount">
                <div className="relative flex items-center">
                  <span className="absolute left-0 top-0 bottom-0 px-3 bg-slate-50 border border-r-0 border-slate-200 rounded-l-lg flex items-center justify-center text-slate-500 font-mono text-sm">
                    $
                  </span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={form.amount}
                    onChange={(e) => onChange('amount', e.target.value)}
                    placeholder="0.00"
                    className="w-full pl-12 bg-[#f8f9ff] border border-slate-200 rounded-lg p-3 font-mono text-sm focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-all outline-none"
                  />
                </div>
              </Field>

              <Field label="Payment Type">
                <div className="relative">
                  <select
                    value={form.paymentType}
                    onChange={(e) => onChange('paymentType', e.target.value)}
                    className="w-full bg-[#f8f9ff] border border-slate-200 rounded-lg p-3 text-sm appearance-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-all outline-none cursor-pointer"
                  >
                    <option>Wire Transfer</option>
                    <option>ACH</option>
                    <option>Real-Time Payment</option>
                    <option>Zelle</option>
                    <option>Check</option>
                    <option>Crypto</option>
                  </select>
                  <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none text-slate-500">
                    <span className="material-symbols-outlined">expand_more</span>
                  </div>
                </div>
              </Field>
            </div>

            {/* Recipient Name */}
            <Field label="Recipient Name">
              <input
                type="text"
                value={form.recipientName}
                onChange={(e) => onChange('recipientName', e.target.value)}
                placeholder="Legal Entity or Individual Name"
                className="w-full bg-[#f8f9ff] border border-slate-200 rounded-lg p-3 text-sm focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-all outline-none"
              />
            </Field>

            {/* Account Number */}
            <Field label="Account Number / IBAN">
              <input
                type="text"
                value={form.accountNumber}
                onChange={(e) => onChange('accountNumber', e.target.value)}
                placeholder="Enter full account details"
                className="w-full bg-[#f8f9ff] border border-slate-200 rounded-lg p-3 font-mono text-sm focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-all outline-none"
              />
            </Field>

            {/* Submit button */}
            <button
              onClick={onSubmit}
              disabled={loading}
              className="mt-4 w-full bg-[#515f74] text-white text-xs font-semibold uppercase tracking-widest py-4 rounded-lg flex justify-center items-center gap-2 hover:bg-[#3a485c] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-[20px]">progress_activity</span>
                  Analysing...
                </>
              ) : (
                <>
                  <ShieldFilledIcon />
                  Check Payment
                </>
              )}
            </button>
          </div>
        </div>

        {/* Privacy Protocol Notice */}
        <div className="bg-[#eff4ff] border border-[#dce9ff] rounded-xl p-4 flex gap-4 items-start">
          <span className="material-symbols-outlined text-[#515f74] mt-0.5">info</span>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-900 mb-1">
              Privacy Protocol Active
            </h4>
            <p className="text-[13px] text-slate-500 leading-snug">
              Sensitive data is redacted locally before being processed by the SentryPay neural engine.
            </p>
          </div>
        </div>
      </div>

      {/* ── RIGHT COLUMN — Waiting / Result Placeholder ────────────── */}
      <div className="lg:col-span-7">
        <WaitingPlaceholder loading={loading} />
      </div>
    </main>
  )
}


// ═════════════════════════════════════════════════════════════════
// FIELD wrapper — consistent label + input layout
// ═════════════════════════════════════════════════════════════════
function Field({ label, children }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </label>
      {children}
    </div>
  )
}


// ═════════════════════════════════════════════════════════════════
// WAITING PLACEHOLDER — abstract graphic + status pills
// ═════════════════════════════════════════════════════════════════
function WaitingPlaceholder({ loading }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 flex flex-col items-center justify-center min-h-[600px] shadow-sm relative overflow-hidden">

      {/* Background dot pattern */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#0b1c30 1px, transparent 1px)',
          backgroundSize:  '24px 24px',
        }}
      />

      <div className="relative z-10 flex flex-col items-center text-center max-w-md w-full">

        {/* Abstract graphic — circular halo around a card with chart */}
        <div className="w-48 h-48 rounded-full bg-[#dce9ff] flex items-center justify-center mb-8 shadow-[inset_0_0_40px_rgba(255,255,255,0.5)]">
          <div className="w-32 h-32 bg-white rounded-xl shadow-[0_8px_30px_rgba(11,28,48,0.06)] flex flex-col items-center justify-center p-4 border border-[#e5eeff]">
            <div className="w-full flex justify-between gap-2 mb-4">
              <div className="h-6 flex-1 bg-[#eff4ff] rounded-md" />
              <div className="h-6 flex-1 bg-[#eff4ff] rounded-md" />
              <div className="h-6 flex-1 bg-[#eff4ff] rounded-md" />
            </div>
            <span className={`material-symbols-outlined text-[#515f74] text-5xl opacity-40 mb-2 ${loading ? 'animate-pulse' : ''}`}>
              analytics
            </span>
            <div className="w-2/3 h-2 bg-[#eff4ff] rounded-full mt-2" />
          </div>
        </div>

        <h2 className="text-2xl font-semibold text-slate-900 mb-2 tracking-tight">
          {loading ? 'Analysing payment...' : 'Waiting for payment analysis...'}
        </h2>
        <p className="text-sm text-slate-500 mb-8">
          {loading
            ? 'SentryPay is querying 3 Elastic intelligence sources and running Gemini reasoning.'
            : 'Submit details or load a demo to see the AI agent in action.'
          }
        </p>

        {/* Status pills */}
        <div className="flex flex-wrap justify-center gap-3 w-full">
          <StatusPill label="Sentiment Analysis" />
          <StatusPill label="Pattern Matching" />
          <StatusPill label="Risk Scoring" />
        </div>
      </div>

      {/* Decorative bottom lines */}
      <div className="absolute bottom-6 left-6 right-6 flex justify-between opacity-20 pointer-events-none">
        <div className="w-16 h-px bg-slate-300" />
        <div className="w-16 h-px bg-slate-300" />
      </div>
    </div>
  )
}


function StatusPill({ label }) {
  return (
    <div className="flex items-center gap-1 text-slate-500 bg-[#f8f9ff] border border-slate-200 px-3 py-1.5 rounded-full text-[10px] font-semibold uppercase tracking-widest">
      <span className="material-symbols-outlined text-[14px]">check_circle</span>
      {label}
    </div>
  )
}


// ═════════════════════════════════════════════════════════════════
// Filled shield icon (for the Check Payment button)
// ═════════════════════════════════════════════════════════════════
function ShieldFilledIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-5 h-5">
      <path
        d="M12 2L4 5V11C4 16.19 7.41 21.05 12 22.5C16.59 21.05 20 16.19 20 11V5L12 2Z"
        fill="currentColor"
      />
      <path
        d="M9 12L11 14L15 10"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}