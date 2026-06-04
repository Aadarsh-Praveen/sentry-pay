// src/components/Header.jsx
// Refined navigation header with proper SentryPay shield logo + cleaner styling.

import { useState } from 'react'
import { DEMO_SCENARIOS } from '../constants/demoScenarios.js'

// SentryPay shield logo (matches favicon + Login page)
const Logo = ({ size = 32 }) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: size, height: size }}>
    <path d="M12 2L4 5V11C4 16.19 7.41 21.05 12 22.5C16.59 21.05 20 16.19 20 11V5L12 2Z" fill="#0F172A"/>
    <path d="M9 12L11 14L15 10" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

export default function Header({ user, view, onLoadDemo, onOpenHistory, onSwitchView, onSignOut }) {
  const [demoOpen, setDemoOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)

  function handleDemo(scenario) {
    setDemoOpen(false)
    onLoadDemo(scenario)
  }

  const isInbox    = view === 'emails'
  const isManual   = view === 'dashboard' || view === 'loading' || view === 'result'

  return (
    <header className="bg-white border-b border-slate-200 fixed top-0 w-full z-50 h-16">
      <div className="flex justify-between items-center w-full px-10 h-16 max-w-[1440px] mx-auto">

        {/* Left: brand */}
        <div className="flex items-center gap-2">
          <Logo size={32} />
          <span className="text-2xl font-bold tracking-tight text-slate-900">SentryPay</span>
        </div>

        {/* Center: nav links */}
        <nav className="hidden md:flex items-center gap-8 h-full">
          <button
            onClick={() => onSwitchView && onSwitchView('emails')}
            className={`h-full flex items-center px-2 gap-1.5 transition-colors ${
              isInbox
                ? 'text-slate-900 font-bold border-b-2 border-slate-900'
                : 'text-slate-500 hover:text-slate-900'
            }`}
          >
            <span className="material-symbols-outlined text-xl">inbox</span>
            <span className="text-xs font-semibold tracking-wider uppercase">Inbox</span>
          </button>
          <button
            onClick={() => onSwitchView && onSwitchView('dashboard')}
            className={`h-full flex items-center px-2 gap-1.5 transition-colors ${
              isManual
                ? 'text-slate-900 font-bold border-b-2 border-slate-900'
                : 'text-slate-500 hover:text-slate-900'
            }`}
          >
            <span className="material-symbols-outlined text-xl">fact_check</span>
            <span className="text-xs font-semibold tracking-wider uppercase">Manual Check</span>
          </button>
        </nav>

        {/* Right: actions */}
        <div className="flex items-center gap-3">

          {/* Load Demo dropdown */}
          <div className="relative">
            <button
              onClick={() => setDemoOpen(v => !v)}
              className="bg-slate-900 text-white text-xs font-semibold uppercase tracking-wider px-4 py-2 rounded-full flex items-center gap-1 hover:opacity-90 transition-opacity"
            >
              Load Demo
              <span className="material-symbols-outlined text-sm">keyboard_arrow_down</span>
            </button>
            {demoOpen && (
              <div className="absolute right-0 top-12 w-56 bg-white border border-slate-200 rounded-xl shadow-xl z-50 overflow-hidden">
                {DEMO_SCENARIOS.map(s => (
                  <button
                    key={s.id}
                    onClick={() => handleDemo(s)}
                    className="w-full text-left px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-0"
                  >
                    <div className="text-xs font-bold text-slate-900">{s.badge}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{s.label}</div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* History */}
          <button
            onClick={onOpenHistory}
            className="text-slate-500 hover:text-slate-900 transition-colors p-2"
            title="History"
          >
            <span className="material-symbols-outlined">history</span>
          </button>

          {/* User menu */}
          {user && (
            <div className="relative">
              <button
                onClick={() => setUserOpen(v => !v)}
                className="flex items-center gap-2 cursor-pointer"
              >
                <div className="w-8 h-8 rounded-full bg-slate-900 flex items-center justify-center text-white text-xs font-bold uppercase">
                  {user.name?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase() || 'U'}
                </div>
                <span className="text-xs font-semibold text-slate-900 hidden md:block">
                  {user.name?.split(' ')[0] || 'User'}
                </span>
              </button>
              {userOpen && (
                <div className="absolute right-0 top-12 w-60 bg-white border border-slate-200 rounded-xl shadow-xl z-50 overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100">
                    <p className="text-sm font-bold text-slate-900 truncate">{user.name}</p>
                    <p className="text-xs text-slate-500 truncate">{user.email}</p>
                  </div>
                  <button
                    onClick={() => { setUserOpen(false); onSignOut() }}
                    className="w-full text-left px-4 py-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                  >
                    <span className="material-symbols-outlined text-[18px]">logout</span>
                    Sign Out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {(demoOpen || userOpen) && (
        <div className="fixed inset-0 z-40" onClick={() => { setDemoOpen(false); setUserOpen(false) }} />
      )}
    </header>
  )
}