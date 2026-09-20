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

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const DEFAULT_TIMEOUT_MS = 30000
export const DEFAULT_RETRIES = 2
const RETRY_BACKOFF_MS = 2000

// Gateway errors a sleeping/failed platform instance returns while it boots.
const RETRYABLE_STATUS = new Set([502, 503, 504])

const RETRYABLE_KINDS = new Set(['timeout', 'network'])

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'http', payload = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind // 'http' | 'network' | 'timeout'
    this.payload = payload
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
  if (err instanceof ApiError) {
    if (err.kind === 'timeout') {
      return 'The server did not respond in time — it may still be waking up. Try again in a moment.'
    }
    if (err.kind === 'network') {
      return 'Could not reach the server. Check your connection and try again.'
    }
    return err.message || fallback
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
      if (!retryable || attempt >= maxAttempts || !alive) throw err
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
    if (signal?.aborted) throw new ApiError('Request cancelled.', { kind: 'network' })
    if (err?.name === 'AbortError') {
      throw new ApiError('Request timed out.', { kind: 'timeout' })
    }
    throw new ApiError('Network error.', { kind: 'network' })
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
    })
  }
  return payload
}
