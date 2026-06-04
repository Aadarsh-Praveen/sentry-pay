// src/api/sentrypay.js
// API client with JWT auth + X-API-Key fallback for payment endpoints.

import axios from 'axios'
import { getStoredJwt } from '../hooks/useAuth.js'

const API_KEY = import.meta.env.VITE_API_KEY || 'sentry-pay-dev-key-2026'

const client = axios.create({
  baseURL: '',
  timeout: 120_000,
})

// Inject JWT (if signed in) + X-API-Key into every request
client.interceptors.request.use(config => {
  const jwt = getStoredJwt()
  if (jwt) {
    config.headers['Authorization'] = `Bearer ${jwt}`
  }
  config.headers['X-API-Key']    = API_KEY
  config.headers['Content-Type'] = 'application/json'
  return config
})

// ── PAYMENT ANALYSIS (existing) ──
export async function analysePayment(params) {
  const res = await client.post('/analyse', {
    email_text:     params.emailText,
    amount:         parseFloat(params.amount),
    recipient_name: params.recipientName,
    account_number: params.accountNumber,
    payment_type:   params.paymentType,
    user_id:        params.userId || 'demo_user_001',
  })
  return res.data
}

export async function getDecisions(limit = 10) {
  const res = await client.get(`/decisions?limit=${limit}`)
  return res.data
}

export function getSarUrl(decisionId) {
  return `/sar/${decisionId}`
}

export async function healthCheck() {
  const res = await client.get('/health')
  return res.data
}

// ── GMAIL (new) ──
export async function getGmailStatus() {
  const res = await client.get('/gmail/status')
  return res.data
}

export async function startGmailScan() {
  const res = await client.post('/gmail/scan')
  return res.data
}

export async function getGmailScanProgress() {
  const res = await client.get('/gmail/scan/progress')
  return res.data
}

export async function listEmailVerdicts(opts = {}) {
  const params = new URLSearchParams()
  if (opts.limit)   params.set('limit',   opts.limit)
  if (opts.verdict) params.set('verdict', opts.verdict)
  const res = await client.get(`/gmail/emails?${params.toString()}`)
  return res.data
}

// ── FEEDBACK (new) ──
export async function confirmBlock(verdictId, note) {
  const res = await client.post('/feedback/confirm-block', {
    verdict_id: verdictId,
    note,
  })
  return res.data
}

export async function markSafe(verdictId, note) {
  const res = await client.post('/feedback/mark-safe', {
    verdict_id: verdictId,
    note,
  })
  return res.data
}

export async function confirmAllow(verdictId) {
  const res = await client.post('/feedback/confirm-allow', {
    verdict_id: verdictId,
  })
  return res.data
}

export async function getLearningStats() {
  const res = await client.get('/learning/stats')
  return res.data
}

export async function getMe() {
  const res = await client.get('/auth/me')
  return res.data
}