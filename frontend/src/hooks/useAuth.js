// src/hooks/useAuth.js
// Manages auth state. Supports both OAuth sign-in and Demo Mode sign-in.

import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'sentrypay_jwt'

// ── Helpers ──────────────────────────────────────────────────
function decodeJwt(token) {
  try {
    const payload = token.split('.')[1]
    const json    = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json)
  } catch {
    return null
  }
}

function isExpired(payload) {
  if (!payload?.exp) return true
  return Date.now() / 1000 > payload.exp
}

// Read JWT from URL hash and save it
function consumeJwtFromHash() {
  const hash = window.location.hash
  if (!hash.includes('jwt=')) return null

  const params  = new URLSearchParams(hash.slice(1))
  const jwt     = params.get('jwt')
  const newUser = params.get('new_user') === 'true'

  if (jwt) {
    localStorage.setItem(STORAGE_KEY, jwt)
    window.history.replaceState(null, '', window.location.pathname)
    return { jwt, newUser }
  }
  return null
}

// ── Hook ────────────────────────────────────────────────────
export default function useAuth() {
  const [jwt,       setJwt      ] = useState(null)
  const [user,      setUser     ] = useState(null)
  const [isNewUser, setIsNewUser] = useState(false)
  const [loading,   setLoading  ] = useState(true)

  useEffect(() => {
    const fromHash = consumeJwtFromHash()
    let token      = fromHash?.jwt || localStorage.getItem(STORAGE_KEY)

    if (!token) {
      setLoading(false)
      return
    }

    const payload = decodeJwt(token)
    if (!payload || isExpired(payload)) {
      localStorage.removeItem(STORAGE_KEY)
      setLoading(false)
      return
    }

    setJwt(token)
    setUser({
      user_id: payload.sub,
      email:   payload.email,
      name:    payload.name,
      isDemo:  payload.demo === true,
    })
    if (fromHash?.newUser) setIsNewUser(true)
    setLoading(false)
  }, [])

  // ── Sign in via Google OAuth (existing) ──────────────────
  const signIn = useCallback(async () => {
    try {
      const res  = await fetch('/auth/google')
      const data = await res.json()
      window.location.href = data.authorization_url
    } catch (err) {
      console.error('Sign in failed:', err)
      alert('Sign in failed. Check the backend is running.')
    }
  }, [])

  // ── Sign in as demo user (no OAuth) ──────────────────────
  const signInAsDemo = useCallback(async () => {
    try {
      const res = await fetch('/auth/demo', { method: 'POST' })
      if (!res.ok) {
        const error = await res.json()
        throw new Error(error.detail || `Demo sign-in failed (${res.status})`)
      }
      const data = await res.json()
      if (!data.jwt) throw new Error('No JWT returned from /auth/demo')

      localStorage.setItem(STORAGE_KEY, data.jwt)
      window.location.reload() // triggers auth check on next mount
    } catch (err) {
      console.error('Demo sign-in failed:', err)
      alert(`Demo sign-in failed: ${err.message}`)
    }
  }, [])

  // ── Sign out ─────────────────────────────────────────────
  const signOut = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setJwt(null)
    setUser(null)
    setIsNewUser(false)
    window.location.reload()
  }, [])

  return {
    jwt,
    user,
    isAuthenticated: !!user,
    isNewUser,
    loading,
    signIn,
    signInAsDemo,
    signOut,
  }
}

export function getStoredJwt() {
  return localStorage.getItem(STORAGE_KEY)
}