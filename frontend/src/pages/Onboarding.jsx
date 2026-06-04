// src/pages/Onboarding.jsx
// ─────────────────────────────────────────────────────────────
// First-time user flow: kick off Gmail history scan + show progress.

import { useState, useEffect } from 'react'
import { startGmailScan, getGmailScanProgress } from '../api/sentrypay.js'

const STEPS = [
  { key: 'scanning',           label: 'Scanning your Gmail', icon: 'mail' },
  { key: 'extracting',         label: 'Reading payment details', icon: 'psychology' },
  { key: 'indexing',           label: 'Building transaction history', icon: 'inventory_2' },
  { key: 'computing_baseline', label: 'Computing your patterns', icon: 'monitoring' },
  { key: 'complete',           label: 'Baseline ready', icon: 'check_circle' },
]

export default function Onboarding({ user, onComplete }) {
  const [progress, setProgress] = useState(null)
  const [error,    setError   ] = useState(null)

  // Kick off the scan on mount
  useEffect(() => {
    let cancelled = false
    async function start() {
      try {
        await startGmailScan()
        // Begin polling immediately
        if (!cancelled) pollProgress()
      } catch (err) {
        setError(err?.response?.data?.detail || 'Failed to start Gmail scan')
      }
    }
    start()
    return () => { cancelled = true }
  }, [])

  // Poll progress every 2 seconds
  function pollProgress() {
    const interval = setInterval(async () => {
      try {
        const data = await getGmailScanProgress()
        setProgress(data)
        if (data.status === 'complete' || data.status === 'error') {
          clearInterval(interval)
          if (data.status === 'complete') {
            // small pause so user sees the "complete" state
            setTimeout(() => onComplete(), 1500)
          } else {
            setError(data.error || 'Build failed')
          }
        }
      } catch (err) {
        console.error('Progress poll failed:', err)
      }
    }, 2000)
  }

  const currentStepIndex = STEPS.findIndex(s => s.key === progress?.status)
  const progressPercent  = progress
    ? Math.max(10, Math.min(100, ((currentStepIndex + 1) / STEPS.length) * 100))
    : 5

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-6">
      <div className="max-w-lg w-full">

        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-fixed rounded-2xl mb-4">
            <span className="material-symbols-outlined text-primary text-[32px]">shield_with_heart</span>
          </div>
          <h1 className="text-3xl font-bold text-primary mb-2">
            Welcome, {user?.name?.split(' ')[0] || 'there'}
          </h1>
          <p className="text-on-surface-variant">
            We're scanning your Gmail to learn your payment patterns. This usually takes 1-2 minutes.
          </p>
        </div>

        {/* Progress card */}
        <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-8 shadow-xl">

          {/* Progress bar */}
          <div className="mb-6">
            <div className="flex justify-between text-xs font-bold tracking-wider text-on-surface-variant uppercase mb-2">
              <span>{progress?.message || 'Starting...'}</span>
              <span>{Math.round(progressPercent)}%</span>
            </div>
            <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-700"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Step list */}
          <div className="space-y-3">
            {STEPS.map((step, i) => {
              const isActive   = step.key === progress?.status
              const isComplete = currentStepIndex > i || progress?.status === 'complete'
              return (
                <div
                  key={step.key}
                  className={`flex items-center gap-3 p-3 rounded-lg transition-all ${
                    isActive
                      ? 'bg-primary-fixed border border-primary'
                      : isComplete
                        ? 'opacity-100'
                        : 'opacity-40'
                  }`}
                >
                  <span className={`material-symbols-outlined text-[20px] ${
                    isActive ? 'text-primary animate-pulse'
                    : isComplete ? 'text-green-600'
                    : 'text-outline'
                  }`}>
                    {isComplete && !isActive ? 'check_circle' : step.icon}
                  </span>
                  <span className={`text-sm ${isActive ? 'font-bold text-primary' : 'text-on-surface'}`}>
                    {step.label}
                  </span>
                  {isActive && (
                    <span className="material-symbols-outlined text-primary text-[18px] ml-auto animate-spin">
                      progress_activity
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* Stats */}
          {progress && (
            <div className="mt-6 pt-6 border-t border-outline-variant grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="font-mono text-2xl font-bold text-primary">{progress.emails_found || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">Emails Found</div>
              </div>
              <div>
                <div className="font-mono text-2xl font-bold text-primary">{progress.emails_processed || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">Processed</div>
              </div>
              <div>
                <div className="font-mono text-2xl font-bold text-primary">{progress.transactions || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">Payments Found</div>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="mt-6 p-4 bg-error-container rounded-lg flex items-start gap-2">
              <span className="material-symbols-outlined text-error text-[20px]">error</span>
              <div className="flex-1">
                <p className="text-sm text-on-error-container font-semibold">Scan failed</p>
                <p className="text-xs text-on-error-container mt-1">{error}</p>
                <button
                  onClick={() => onComplete()}
                  className="mt-3 text-xs underline text-on-error-container hover:no-underline"
                >
                  Skip and continue
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Skip option */}
        {!error && progress?.status !== 'complete' && (
          <div className="text-center mt-4">
            <button
              onClick={() => onComplete()}
              className="text-xs text-on-surface-variant hover:text-primary underline"
            >
              Skip and continue in the background
            </button>
          </div>
        )}
      </div>
    </div>
  )
}