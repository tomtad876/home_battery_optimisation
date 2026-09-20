// Tests for the shared fetch helper (lib/api.js).
//
// Run with: npm run test:api   (no dependencies — uses node:test)
//
// These cover the failure modes the 2026-09-19 code review called out: a bare
// fetch() with no deadline, a network blip that looked like a crash, a FastAPI
// 422 rendered as "[object Object]", and an HTML error body surfacing as
// "SyntaxError: Unexpected token '<'".

import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { readFileSync } from 'node:fs'

// api.js is an ESM file that lives inside a CommonJS package (the Next.js app),
// so Node would treat a plain `import './api.js'` as CommonJS. Load it explicitly
// as ESM from source — it has no imports of its own, so this needs no bundler.
const source = readFileSync(new URL('./api.js', import.meta.url), 'utf8')
const { ApiError, apiFetch, extractDetail, friendlyError, readJson } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
)

// --- extractDetail: the shapes FastAPI actually returns ----------------------

test('string detail passes through', () => {
  assert.equal(
    extractDetail({ detail: 'NO_DATA: No forecast data available yet.' }),
    'NO_DATA: No forecast data available yet.'
  )
})

test('422 array becomes a readable string naming the field', () => {
  const body = {
    detail: [
      {
        type: 'float_parsing',
        loc: ['body', 'battery_capacity_kwh'],
        msg: 'Input should be a valid number, unable to parse string as a number',
        input: 'abc',
      },
    ],
  }
  const message = extractDetail(body)
  assert.equal(typeof message, 'string')
  assert.equal(
    message,
    'battery_capacity_kwh: Input should be a valid number, unable to parse string as a number'
  )
})

test('422 with several fields joins them', () => {
  assert.equal(
    extractDetail({
      detail: [
        { loc: ['body', 'min_soc_pct'], msg: 'Input should be a valid number' },
        { loc: ['body', 'max_soc_pct'], msg: 'Field required' },
      ],
    }),
    'min_soc_pct: Input should be a valid number; max_soc_pct: Field required'
  )
})

test('missing detail falls back instead of throwing', () => {
  assert.equal(extractDetail(null, 'Preview failed.'), 'Preview failed.')
  assert.equal(extractDetail({}, 'Push failed.'), 'Push failed.')
  assert.equal(extractDetail('   ', 'Push failed.'), 'Push failed.')
})

// --- readJson: cold-start HTML bodies must not explode ------------------------

test('HTML error body reads as null, not a SyntaxError', async () => {
  const response = new Response('<!DOCTYPE html><html>502 Bad Gateway</html>', { status: 502 })
  assert.equal(await readJson(response), null)
})

test('empty body reads as null', async () => {
  assert.equal(await readJson(new Response(null, { status: 204 })), null)
})

test('JSON body parses', async () => {
  const response = new Response(JSON.stringify({ ok: true }), { status: 200 })
  assert.deepEqual(await readJson(response), { ok: true })
})

// --- error copy ---------------------------------------------------------------

test('deadline and connection failures get honest copy', () => {
  assert.match(friendlyError(new ApiError('x', { kind: 'timeout' })), /waking up/)
  assert.match(friendlyError(new ApiError('x', { kind: 'network' })), /Could not reach the server/)
  assert.equal(friendlyError(new ApiError('NO_DATA: nope', { status: 400 })), 'NO_DATA: nope')
})

// --- apiFetch: deadline, retries, and what must NOT be retried ----------------

test('connection failure is retried, then surfaces as a network error', async () => {
  let retries = 0
  await assert.rejects(
    apiFetch('http://127.0.0.1:9/nope', { retries: 2, onRetry: () => { retries += 1 } }),
    (err) => err instanceof ApiError && err.kind === 'network'
  )
  assert.equal(retries, 2, 'should have retried twice (3 attempts)')
})

test('a live push is never retried — a timeout may mean it already landed', async () => {
  let retries = 0
  await assert.rejects(
    apiFetch('http://127.0.0.1:9/nope', {
      method: 'POST',
      body: {},
      retries: 2,
      retryUnsafe: false,
      onRetry: () => { retries += 1 },
    })
  )
  assert.equal(retries, 0)
})

test('an unresponsive server times out instead of hanging', async () => {
  const server = http.createServer(() => {})
  await new Promise((resolve) => server.listen(0, resolve))
  const { port } = server.address()
  const started = Date.now()
  try {
    await assert.rejects(
      apiFetch(`http://127.0.0.1:${port}/slow`, { timeoutMs: 300, retries: 1 }),
      (err) => err instanceof ApiError && err.kind === 'timeout'
    )
    // 0.3s deadline + 2s backoff + 0.3s deadline
    assert.ok(Date.now() - started < 6000, 'should give up quickly, not hang')
  } finally {
    server.close()
  }
})

test('a gateway error (cold start) is retried and reported readably', async () => {
  let hits = 0
  const server = http.createServer((req, res) => {
    hits += 1
    res.writeHead(502, { 'Content-Type': 'text/html' })
    res.end('<html>Bad Gateway</html>')
  })
  await new Promise((resolve) => server.listen(0, resolve))
  const { port } = server.address()
  try {
    await assert.rejects(
      apiFetch(`http://127.0.0.1:${port}/x`, { retries: 1, timeoutMs: 2000 }),
      (err) => err instanceof ApiError && err.status === 502 && /HTTP 502/.test(err.message)
    )
    assert.equal(hits, 2, '502 should be retried once')
  } finally {
    server.close()
  }
})

test('a 4xx is not retried', async () => {
  let hits = 0
  const server = http.createServer((req, res) => {
    hits += 1
    res.writeHead(400, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ detail: 'NO_DATA: nope' }))
  })
  await new Promise((resolve) => server.listen(0, resolve))
  const { port } = server.address()
  try {
    await assert.rejects(
      apiFetch(`http://127.0.0.1:${port}/optimise/mvp`, { method: 'POST', body: {}, retries: 2 }),
      (err) => err instanceof ApiError && err.status === 400 && err.message === 'NO_DATA: nope'
    )
    assert.equal(hits, 1, '4xx is a decision, not a blip — do not retry')
  } finally {
    server.close()
  }
})
