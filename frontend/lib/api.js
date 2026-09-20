// Shared HTTP helper for the optimiser UI.
//
// Why this exists (see CODE_REVIEW.md §2 and §7):
//
// - The backend sleeps when idle. The first request after that can take 30–60s
//   to come back. A bare `fetch()` with no deadline left the whole UI stuck on
//   "Loading..." with no way to tell "cold" from "dead".
// - A network blip should not read as a crash, and a 422 should not read as
//   "[object Object]".
// - FastAPI reports validation errors as `detail: [{loc, msg, type}]`. Rendering
//   that array as a React child crashes the page (it did, on /settings).
//
// So: one place that sets a deadline, retries only what is safe to retry,
// reports what actually happened, and always hands the UI a string it can render.
//
// "What actually happened" is worth spelling out, because three very different
// problems all look like "the app is broken" from the outside (2026-09-20):
//   - the backend is asleep      → timeout, then a retry, then an honest message
//   - nothing is listening       → network error; a /health probe proves it
//   - CORS blocked the response  → also a network error in JS, but the probe
//     succeeds, which is how we can say "the API is up; your origin isn't allowed"
//   - the build has no API URL   → no request is made at all

const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL || ''

const LOCAL_HOSTNAME_RE = /^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)$/

function isLocalHostname(hostname) {
  return !!hostname && LOCAL_HOSTNAME_RE.test(hostname)
}

function hostnameOf(url) {
  if (!url) return null
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

function pageHostname() {
  return typeof window !== 'undefined' ? window.location.hostname : null
}

/**
 * Work out which backend to talk to.
 *
 * - NEXT_PUBLIC_API_URL set → use it.
 * - unset + local dev (localhost/127.0.0.1) → the usual uvicorn port.
 * - unset + deployed build → `''`, meaning "misconfigured", so apiFetch can say
 *   so instead of firing requests at localhost and reporting a connection
 *   error. Deliberately *not* falling back to the prod API: a preview
 *   deployment that quietly talks to production can push schedules to a real
 *   inverter.
 */
export function resolveApiUrl(
  rawUrl = RAW_API_URL,
  hostname = typeof window !== 'undefined' ? window.location.hostname : null
) {
  if (rawUrl) return rawUrl.replace(/\/+$/, '')
  if (!hostname || isLocalHostname(hostname)) return 'http://localhost:8000'
  return ''
}

export const API_URL = resolveApiUrl()

export const DEFAULT_TIMEOUT_MS = 30000
export const DEFAULT_RETRIES = 2
const RETRY_BACKOFF_MS = 2000

// Gateway errors a sleeping/failed platform instance returns while it boots.
const RETRYABLE_STATUS = new Set([502, 503, 504])

const RETRYABLE_KINDS = new Set(['timeout', 'network'])

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'http', payload = null, url = null, timeoutMs = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind // 'http' | 'network' | 'timeout' | 'config'
    this.payload = payload
    this.url = url
    this.timeoutMs = timeoutMs
    this.reachability = null // 'blocked' | 'unreachable' | null (set after a failure)
  }
}

/** Origin of a URL, for error copy. Falls back to the raw string. */
function originOf(url) {
  if (!url) return null
  try {
    return new URL(url).origin
  } catch {
    return url
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function formatLocation(loc) {
  if (!Array.isArray(loc)) return ''
  return loc
    .filter((part) => typeof part === 'string' && !['body', 'query', 'path', 'header'].includes(part))
    .join('.')
}

/**
 * Turn any error body into a single human-readable string.
 * Handles FastAPI's `detail` as a string, as a 422 array of {loc, msg}, and the
 * odd shape where the detail itself is nested.
 */
export function extractDetail(payload, fallback = 'Something went wrong.') {
  if (payload == null) return fallback

  if (typeof payload === 'string') return payload.trim() || fallback

  if (Array.isArray(payload)) {
    const messages = payload.map((item) => extractDetail(item, '')).filter(Boolean)
    return messages.length ? messages.join('; ') : fallback
  }

  if (typeof payload === 'object') {
    // FastAPI 422 entries look like { type, loc: ['body', 'field'], msg: '...' }.
    // Check these first so the offending field name survives.
    if (typeof payload.msg === 'string') {
      const where = formatLocation(payload.loc)
      return where ? `${where}: ${payload.msg}` : payload.msg
    }
    const detail = payload.detail ?? payload.error ?? payload.message
    if (typeof detail === 'string') return detail.trim() || fallback
    if (detail != null) {
      const nested = extractDetail(detail, '')
      if (nested) return nested
    }
  }

  return fallback
}

/** User-facing copy for a failure. `null` means "no failure". */
export function friendlyError(err, fallback = 'Something went wrong.') {
  if (err == null) return null
  if (!(err instanceof ApiError)) return err.message || fallback

  if (err.kind === 'config') {
    return `${err.message} Nothing was requested — set NEXT_PUBLIC_API_URL for this environment (Vercel → Settings → Environment Variables) and redeploy.`
  }

  const where = originOf(err.url)
  const pageHost = pageHostname()

  // The server answered, but the browser refused the response. In practice this
  // is CORS: the page's origin is not in the backend's allowed list. Vercel
  // previews have their own hostname per branch, so this is the usual reason a
  // preview deployment "cannot reach" a perfectly healthy API.
  if (err.reachability === 'blocked') {
    return `The API at ${where} is up, but the browser blocked the response — that is CORS: ${
      pageHost ? `this page's origin (${pageHost})` : 'this page'
    } is not in the backend's allowed origins. Add it to FRONTEND_ORIGINS (preview deployments need their own host allowed).`
  }

  // A deployed page pointed at an API on localhost is a config mistake, not a
  // connection problem: the request is going to the *viewer's* machine. (It is
  // legitimate when deliberately testing a preview against a local backend —
  // then the fix is to start that backend.)
  const aimedAtViewersMachine =
    isLocalHostname(hostnameOf(err.url)) && pageHost && !isLocalHostname(pageHost)

  if (aimedAtViewersMachine) {
    return `Could not reach the API at ${where}. This page is served from ${pageHost}, so it is asking your own machine for a backend${
      ' — either start that backend, or set NEXT_PUBLIC_API_URL for this environment (Vercel → Settings → Environment Variables).'
    }`
  }

  if (err.kind === 'timeout') {
    const budget = err.timeoutMs ? ` within ${Math.round(err.timeoutMs / 1000)}s` : ''
    return `No answer from the API${where ? ` at ${where}` : ''}${budget}. It may still be waking up — try again in a moment.`
  }
  if (err.kind === 'network') {
    return `Could not reach the API${where ? ` at ${where}` : ''} — nothing answered.${
      where && isLocalHostname(hostnameOf(err.url))
        ? ' The local backend looks like it is not running (see RUN_LOCALLY.md).'
        : ' Check your connection.'
    }`
  }
  return err.message || fallback
}

/** Did the request fail in a way that suggests a sleeping/slow backend? */
export function looksLikeColdStart(err) {
  return (
    err instanceof ApiError &&
    (RETRYABLE_KINDS.has(err.kind) || RETRYABLE_STATUS.has(err.status))
  )
}

/**
 * Read a response body as JSON without ever throwing on HTML/empty bodies.
 * A cold-start 502 or a proxy error page returns HTML, which used to surface as
 * `SyntaxError: Unexpected token '<'`.
 */
export async function readJson(response) {
  try {
    const text = await response.text()
    if (!text) return null
    return JSON.parse(text)
  } catch {
    return null
  }
}

/**
 * Did the server answer at all? A `no-cors` request bypasses CORS enforcement
 * (opaque response), so:
 *   resolves  → the server is reachable; the browser blocked the *real* request
 *   rejects   → nothing is there (refused / DNS / offline)
 * Only ever used after a failure, and only against /health (no auth, no side
 * effects), to tell the two apart in the message the user sees.
 */
async function probeReachability(url, timeoutMs = 8000) {
  const origin = originOf(url)
  if (!origin) return false
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    await fetch(`${origin}/health`, { mode: 'no-cors', cache: 'no-store', signal: controller.signal })
    return true
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/**
 * fetch() with a deadline, bounded retries and a guaranteed renderable error.
 *
 * @param {string} path           Path ("/sites/me") or absolute URL.
 * @param {object} [options]
 * @param {string} [options.method='GET']
 * @param {object} [options.headers]
 * @param {any}    [options.body]            JSON-serialised if not undefined/null.
 * @param {string} [options.accessToken]     Adds the Authorization header.
 * @param {number} [options.timeoutMs]       Per-attempt deadline (default 30s).
 * @param {number} [options.retries]         Extra attempts after the first.
 * @param {boolean}[options.retryUnsafe=true] Allow retrying non-GET methods.
 *   Set false for calls that are not safe to repeat (e.g. a live inverter push).
 * @param {AbortSignal} [options.signal]
 * @param {Function} [options.onRetry]       Called as ({ attempt, error }) before each retry.
 * @returns {Promise<any>} Parsed JSON body (null for an empty body).
 * @throws {ApiError}
 */
export async function apiFetch(path, options = {}) {
  const {
    method = 'GET',
    headers = {},
    body,
    accessToken,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retries = DEFAULT_RETRIES,
    retryUnsafe = true,
    signal,
    onRetry,
  } = options

  const url = /^https?:\/\//i.test(path) ? path : `${API_URL}${path}`
  if (!API_URL && !/^https?:\/\//i.test(path)) {
    throw new ApiError(
      'This build has no API URL configured (NEXT_PUBLIC_API_URL is missing for this environment).',
      { kind: 'config' }
    )
  }
  const requestHeaders = { ...headers }
  if (body !== undefined && body !== null && requestHeaders['Content-Type'] === undefined) {
    requestHeaders['Content-Type'] = 'application/json'
  }
  if (accessToken) requestHeaders.Authorization = `Bearer ${accessToken}`

  const methodIsSafe = ['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())
  const maxAttempts = 1 + Math.max(0, methodIsSafe || retryUnsafe ? retries : 0)

  let lastError
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await attemptFetch(url, {
        method,
        headers: requestHeaders,
        body,
        timeoutMs,
        signal,
      })
    } catch (err) {
      lastError = err
      const retryable =
        err instanceof ApiError &&
        (RETRYABLE_KINDS.has(err.kind) || RETRYABLE_STATUS.has(err.status))
      const alive = !signal?.aborted
      if (!retryable || attempt >= maxAttempts || !alive) {
        // Last chance to explain *why* it failed: CORS block or nothing there.
        if (err instanceof ApiError && err.kind === 'network') {
          err.reachability = (await probeReachability(err.url)) ? 'blocked' : 'unreachable'
        }
        throw err
      }
      if (onRetry) onRetry({ attempt, error: err })
      await sleep(RETRY_BACKOFF_MS * attempt)
    }
  }
  throw lastError
}

async function attemptFetch(url, { method, headers, body, timeoutMs, signal }) {
  const controller = new AbortController()
  const abortFromOutside = () => controller.abort()
  if (signal) signal.addEventListener('abort', abortFromOutside)
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined || body === null ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    })
  } catch (err) {
    if (signal?.aborted) throw new ApiError('Request cancelled.', { kind: 'network', url })
    if (err?.name === 'AbortError') {
      throw new ApiError('Request timed out.', { kind: 'timeout', url, timeoutMs })
    }
    throw new ApiError('Network error.', { kind: 'network', url })
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', abortFromOutside)
  }

  const payload = await readJson(response)
  if (!response.ok) {
    throw new ApiError(extractDetail(payload, `Request failed (HTTP ${response.status}).`), {
      status: response.status,
      kind: 'http',
      payload,
      url,
    })
  }
  return payload
}
