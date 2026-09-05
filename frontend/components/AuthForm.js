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

  return (
    <div>
      <h3 className="text-lg font-semibold mb-3">Sign in / Sign up</h3>
      {error && <p className="text-red-600 mb-2">{error}</p>}
      <form className="space-y-3">
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-3 py-2 border rounded"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 border rounded"
        />
        <div className="flex space-x-2">
          <button onClick={handleLogin} className="bg-blue-600 text-white px-3 py-2 rounded" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
          <button onClick={handleSignup} className="bg-green-600 text-white px-3 py-2 rounded" disabled={loading}>
            {loading ? 'Signing up...' : 'Sign up'}
          </button>
        </div>
      </form>
    </div>
  )
}
