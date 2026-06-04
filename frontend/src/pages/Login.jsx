// src/pages/Login.jsx
// Login page with "Sign in with Google" + "View Demo Account" for judges.

import { useState } from 'react'

// SentryPay shield
const Logo = ({ size = 48 }) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: size, height: size }}>
    <path d="M12 2L4 5V11C4 16.19 7.41 21.05 12 22.5C16.59 21.05 20 16.19 20 11V5L12 2Z" fill="#0F172A"/>
    <path d="M9 12L11 14L15 10" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const GoogleIcon = () => (
  <svg height="20" viewBox="0 0 18 18" width="20">
    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
    <path d="M9 18c2.43 0 4.467-.806 5.956-2.184L12.048 13.558c-.806.54-1.836.859-3.048.859-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
    <path d="M3.964 10.706c-.18-.54-.282-1.117-.282-1.706 0-.589.102-1.166.282-1.706V4.962H.957C.347 6.177 0 7.549 0 9s.347 2.823.957 4.038l3.007-2.332z" fill="#FBBC05"/>
    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.443 2.048.957 4.962l3.007 2.332C4.672 5.164 6.656 3.58 9 3.58z" fill="#EA4335"/>
  </svg>
)

const FEATURES = [
  { icon: 'mail',                    title: 'Reads your Gmail securely',
    desc:  'Encrypted connection for metadata scanning only.' },
  { icon: 'analytics',               title: '90-day behavioural baseline',
    desc:  'Historical analysis of your payments to detect anomalies.' },
  { icon: 'notification_important',  title: 'Auto-flags suspicious requests',
    desc:  'Real-time alerts for high-risk activity and phishing.' },
  { icon: 'description',             title: 'Auto-generated compliance reports',
    desc:  'SAR documentation ready when needed for institutions.' },
]


export default function Login({ onSignIn, onSignInAsDemo }) {
  const [loadingGoogle, setLoadingGoogle] = useState(false)
  const [loadingDemo,   setLoadingDemo]   = useState(false)

  async function handleGoogle() {
    setLoadingGoogle(true)
    try { await onSignIn() }
    finally { setTimeout(() => setLoadingGoogle(false), 5000) }
  }

  async function handleDemo() {
    setLoadingDemo(true)
    try { await onSignInAsDemo() }
    finally { setTimeout(() => setLoadingDemo(false), 5000) }
  }

  return (
    <div className="flex flex-col min-h-screen bg-[#f8f9ff] text-[#0b1c30]">

      <main
        className="flex-grow flex items-center justify-center px-5 py-8"
        style={{
          background: 'radial-gradient(circle at top left, #f8f9ff 0%, #e5eeff 100%)',
        }}
      >
        <div className="max-w-[480px] w-full flex flex-col items-center">

          {/* Brand */}
          <div className="flex flex-col items-center mb-8 fade-in-up">
            <div className="h-12 w-12 mb-4 flex items-center justify-center">
              <Logo size={48} />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">SentryPay</h1>
            <p className="text-[13px] text-[#45464d] mt-1">
              AI-powered payment fraud detection
            </p>
          </div>

          {/* Card */}
          <div
            className="w-full rounded-xl p-8 fade-in-card"
            style={{
              background:           'rgba(255, 255, 255, 0.8)',
              backdropFilter:       'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              boxShadow:            '0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.05)',
              border:               '1px solid rgba(255, 255, 255, 0.3)',
            }}
          >
            <div className="mb-6">
              <h2 className="text-xl font-semibold mb-2">Welcome back</h2>
              <p className="text-sm text-[#45464d] leading-relaxed">
                Connect your Gmail to start monitoring suspicious payment requests in real time.
              </p>
            </div>

            {/* Sign in with Google */}
            <button
              onClick={handleGoogle}
              disabled={loadingGoogle || loadingDemo}
              className="w-full flex items-center justify-center gap-4 py-4 border border-[#c6c6cd] rounded-xl bg-white hover:bg-[#eff4ff] hover:border-[#0F172A] transition-colors duration-200 disabled:opacity-60 disabled:cursor-not-allowed mb-4"
            >
              {loadingGoogle ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-[20px]">progress_activity</span>
                  <span className="text-[15px] font-medium text-[#0b1c30]">Redirecting...</span>
                </>
              ) : (
                <>
                  <GoogleIcon />
                  <span className="text-[15px] font-medium text-[#0b1c30]">Sign in with Google</span>
                </>
              )}
            </button>

            {/* OR divider */}
            <div className="relative flex items-center justify-center my-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[#c6c6cd]" />
              </div>
              <span className="relative px-3 bg-white text-[10px] font-semibold tracking-wider text-[#45464d]">
                OR
              </span>
            </div>

            {/* View Demo Account */}
            <button
              onClick={handleDemo}
              disabled={loadingGoogle || loadingDemo}
              className="w-full flex items-center justify-center gap-3 py-4 bg-[#0F172A] text-white rounded-xl hover:bg-[#1e293b] transition-colors duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loadingDemo ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-[20px]">progress_activity</span>
                  <span className="text-[15px] font-medium">Loading demo...</span>
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[20px]">play_circle</span>
                  <span className="text-[15px] font-medium">View Demo Account</span>
                </>
              )}
            </button>
            <p className="text-[11px] text-[#45464d] text-center mt-2 italic">
              Skip OAuth — explore SentryPay with pre-loaded fraud cases
            </p>

            {/* WHAT YOU GET divider */}
            <div className="relative flex items-center justify-center my-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[#c6c6cd]" />
              </div>
              <span className="relative px-4 bg-white text-[11px] font-semibold tracking-wider text-[#45464d]">
                WHAT YOU GET
              </span>
            </div>

            {/* Features */}
            <ul className="space-y-3">
              {FEATURES.map(({ icon, title, desc }) => (
                <li key={title} className="flex items-start gap-4 p-3 rounded-lg transition-colors hover:bg-[#dce9ff]/50">
                  <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[#dae2fd] flex items-center justify-center">
                    <span className="material-symbols-outlined text-[#0F172A]" style={{ fontSize: '20px' }}>{icon}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-[#0b1c30]">{title}</p>
                    <p className="text-[13px] text-[#45464d] leading-snug">{desc}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <p className="mt-6 text-center text-[12px] text-[#45464d] max-w-[400px] leading-relaxed">
            By signing in you agree that SentryPay can read your Gmail for fraud analysis.
            Your data is never shared with third parties.
          </p>
        </div>
      </main>

      <footer className="py-6 border-t border-[#c6c6cd] bg-[#f8f9ff] flex justify-center items-center gap-8">
        <div className="flex items-center gap-1 text-[#45464d]">
          <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>lock</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider">END-TO-END ENCRYPTED</span>
        </div>
        <div className="h-4 w-px bg-[#c6c6cd]" />
        <div className="flex items-center gap-1 text-[#45464d]">
          <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>verified_user</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider">SOC 2 COMPLIANT</span>
        </div>
      </footer>

      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .fade-in-up   { animation: fadeInUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
        .fade-in-card { animation: fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) both; animation-delay: 0.1s; }
      `}</style>
    </div>
  )
}