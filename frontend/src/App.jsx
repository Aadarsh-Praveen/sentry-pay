// src/App.jsx
// Routes:
//   - Not signed in           → Login
//   - Signed in + new user    → Onboarding (Gmail scan)
//   - Signed in + onboarded   → EmailDashboard / Manual / Result

import { useState } from 'react'
import useAuth         from './hooks/useAuth.js'
import Header          from './components/Header.jsx'
import HistoryDrawer   from './components/HistoryDrawer.jsx'
import Dashboard       from './components/Dashboard.jsx'
import BlockResult     from './components/BlockResult.jsx'
import FrictionResult  from './components/FrictionResult.jsx'
import AllowResult     from './components/AllowResult.jsx'
import Login           from './pages/Login.jsx'
import Onboarding      from './pages/Onboarding.jsx'
import EmailDashboard  from './pages/EmailDashboard.jsx'
import { analysePayment } from './api/sentrypay.js'

const VIEWS = {
  DASHBOARD: 'dashboard',
  EMAILS:    'emails',
  LOADING:   'loading',
  RESULT:    'result',
}

const EMPTY_FORM = {
  emailText:     '',
  amount:        '',
  recipientName: '',
  accountNumber: '',
  paymentType:   'Wire Transfer',
  userId:        'demo_user_001',
}

export default function App() {
  const auth = useAuth()

  const [view,        setView       ] = useState(VIEWS.EMAILS)
  const [form,        setForm       ] = useState(EMPTY_FORM)
  const [result,      setResult     ] = useState(null)
  const [error,       setError      ] = useState(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [onboarded,   setOnboarded  ] = useState(false)

  function handleChange(field, value) {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  function handleLoadDemo(scenario) {
    setForm({
      emailText:     scenario.emailText,
      amount:        scenario.amount,
      recipientName: scenario.recipientName,
      accountNumber: scenario.accountNumber,
      paymentType:   scenario.paymentType,
      userId:        auth.user?.user_id || scenario.userId || 'demo_user_001',
    })
    setView(VIEWS.DASHBOARD)
    setResult(null)
    setError(null)
  }

  async function handleSubmit() {
    if (!form.emailText || !form.amount || !form.recipientName || !form.accountNumber) {
      setError('Please fill in all required fields.')
      return
    }
    setError(null)
    setView(VIEWS.LOADING)

    try {
      const data = await analysePayment({
        emailText:     form.emailText,
        amount:        parseFloat(form.amount),
        recipientName: form.recipientName,
        accountNumber: form.accountNumber,
        paymentType:   form.paymentType,
        userId:        auth.user?.user_id || form.userId,
      })
      setResult(data)
      setView(VIEWS.RESULT)
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
        'Analysis failed. Make sure the backend is running on port 8000.'
      )
      setView(VIEWS.DASHBOARD)
    }
  }

  function handleBack() {
    setView(VIEWS.EMAILS)
    setResult(null)
    setError(null)
  }

  function renderResult() {
    if (!result) return null
    const props = { result, form, onBack: handleBack }
    if (result.verdict === 'BLOCK')    return <BlockResult    {...props} />
    if (result.verdict === 'FRICTION') return <FrictionResult {...props} />
    return                                    <AllowResult    {...props} />
  }

  // Auth gates
  if (auth.loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9ff]">
        <span className="material-symbols-outlined text-4xl animate-spin text-slate-900">progress_activity</span>
      </div>
    )
  }

  if (!auth.isAuthenticated) {
    return <Login onSignIn={auth.signIn} onSignInAsDemo={auth.signInAsDemo} />
  }

  // Skip onboarding for demo users (they already have a baseline)
  if (auth.isNewUser && !onboarded && !auth.user?.isDemo) {
    return <Onboarding user={auth.user} onComplete={() => setOnboarded(true)} />
  }

  return (
    <div className="min-h-screen bg-[#f8f9ff]">
      <Header
        user          = {auth.user}
        view          = {view}
        onLoadDemo    = {handleLoadDemo}
        onOpenHistory = {() => setHistoryOpen(true)}
        onSwitchView  = {(v) => { setView(v); setResult(null); setError(null) }}
        onSignOut     = {auth.signOut}
      />

      {error && (
        <div className="fixed top-16 left-0 right-0 z-40 bg-[#ffdad6] border-b border-[#ba1a1a] px-10 py-3 flex items-center gap-3">
          <span className="material-symbols-outlined text-[#ba1a1a] text-[20px]">error</span>
          <span className="text-sm text-[#93000a] font-medium">{error}</span>
          <button
            onClick={() => setError(null)}
            className="ml-auto material-symbols-outlined text-[#ba1a1a] text-[20px]"
          >
            close
          </button>
        </div>
      )}

      {view === VIEWS.LOADING && (
        <main className="pt-24 min-h-screen flex items-center justify-center">
          <div className="text-center max-w-sm">
            <div className="w-24 h-24 mx-auto mb-8 relative flex items-center justify-center">
              <div className="absolute inset-0 rounded-full bg-[#dce9ff] analysis-pulse" />
              <div className="absolute inset-4 rounded-full bg-[#d3e4fe] analysis-pulse" style={{ animationDelay: '400ms' }} />
              <span className="material-symbols-outlined text-[40px] text-slate-900 relative z-10" style={{ fontVariationSettings: "'FILL' 1" }}>security</span>
            </div>
            <h2 className="text-2xl font-bold text-slate-900 mb-3">Analysing payment...</h2>
            <p className="text-sm text-slate-500 mb-6">
              SentryPay is querying 3 Elastic intelligence sources and running Gemini reasoning.
            </p>
          </div>
        </main>
      )}

      {view === VIEWS.EMAILS    && <EmailDashboard user={auth.user} />}
      {view === VIEWS.DASHBOARD && <Dashboard form={form} onChange={handleChange} onSubmit={handleSubmit} loading={false} />}
      {view === VIEWS.RESULT    && renderResult()}

      <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  )
}