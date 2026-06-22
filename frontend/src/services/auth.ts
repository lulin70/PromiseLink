// Auth token & credential storage (pure, no API dependencies)
//
// Security note:
// - Token is stored in localStorage (short-lived, 15min expiry).
// - PoC secret is stored in sessionStorage to limit exposure window.
//   Closing the tab clears the secret; user must re-enter on next session.

const TOKEN_KEY = 'promiselink_token'
const USER_ID_KEY = 'promiselink_user_id'
const SECRET_KEY = 'promiselink_poc_secret'  // sessionStorage only
const DEFAULT_USER_ID = 'poc-user'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getUserId(): string {
  return localStorage.getItem(USER_ID_KEY) || DEFAULT_USER_ID
}

export function setUserId(userId: string): void {
  localStorage.setItem(USER_ID_KEY, userId)
}

export function removeUserId(): void {
  localStorage.removeItem(USER_ID_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}

export function logout(): void {
  removeToken()
  removeUserId()
  removeSavedSecret()
}

// Store PoC secret in sessionStorage (cleared when tab closes) for auto re-login.
// Storing in localStorage would expose the long-lived secret to XSS attacks.
export function saveLoginCredentials(secret: string): void {
  sessionStorage.setItem(SECRET_KEY, secret)
}

export function getSavedSecret(): string | null {
  return sessionStorage.getItem(SECRET_KEY)
}

export function removeSavedSecret(): void {
  sessionStorage.removeItem(SECRET_KEY)
}

// Direct login via fetch (used by api.ts for 401 retry — avoids circular dependency)
export async function directLogin(secret: string, userId: string): Promise<string | null> {
  try {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ poc_secret: secret, user_id: userId }),
    })
    if (!res.ok) return null
    const data = await res.json()
    if (data.access_token) {
      setToken(data.access_token)
      if (data.user_id) setUserId(data.user_id)
    }
    return data.access_token || null
  } catch {
    return null
  }
}
