import { createClient } from '@supabase/supabase-js'

let _client = null

function getClient() {
  if (_client) return _client
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  if (!url || !key) return null
  _client = createClient(url, key)
  return _client
}

// Export a proxy that lazily initializes the real client on first property access.
// This avoids the "supabaseUrl is required" error during SSR/build,
// and returns null methods gracefully when env vars are missing.
export const supabase = new Proxy(
  {},
  {
    get(_, prop) {
      const client = getClient()
      if (!client) {
        // Return no-op functions so supabase.auth.getSession() etc. don't crash
        if (prop === 'auth') {
          return new Proxy(
            {},
            {
              get(__, authProp) {
                if (authProp === 'getSession')
                  return () => Promise.resolve({ data: { session: null }, error: null })
                if (authProp === 'onAuthStateChange')
                  return () => ({ data: { subscription: { unsubscribe: () => {} } } })
                if (authProp === 'signOut') return () => Promise.resolve({ error: null })
                if (authProp === 'signUp')
                  return () => Promise.resolve({ data: {}, error: { message: 'Supabase not configured' } })
                if (authProp === 'signInWithPassword')
                  return () => Promise.resolve({ data: {}, error: { message: 'Supabase not configured' } })
                return () => {}
              },
            }
          )
        }
        return undefined
      }
      return client[prop]
    },
  }
)
