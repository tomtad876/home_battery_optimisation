import { useState } from 'react'
import { supabase } from '@/lib/supabaseClient'

export default function AuthForm({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSignup = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const { data, error } = await supabase.auth.signUp({ email, password })
    if (error) setError(error.message)
    else onLogin && onLogin(data)
    setLoading(false)
  }

  const handleLogin = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) setError(error.message)
    else onLogin && onLogin(data)
    setLoading(false)
  }

  const field =
    'w-full px-3 py-2 bg-surface-2 border border-hairline rounded-md text-ink placeholder:text-ink-faint focus:border-signal focus:outline-none'

  return (
    <div>
      <h3 className="text-lg font-semibold mb-3">Sign in / Sign up</h3>
      {error && <p className="text-danger-ink mb-2">{error}</p>}
      <form className="space-y-3">
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={field}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={field}
        />
        <div className="flex space-x-2">
          <button
            onClick={handleLogin}
            className="bg-signal text-canvas font-medium px-4 py-2 rounded-md hover:brightness-95 disabled:opacity-50"
            disabled={loading}
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
          <button
            onClick={handleSignup}
            className="bg-surface-2 border border-hairline text-ink px-4 py-2 rounded-md hover:border-ink-faint disabled:opacity-50"
            disabled={loading}
          >
            {loading ? 'Signing up...' : 'Sign up'}
          </button>
        </div>
      </form>
    </div>
  )
}
