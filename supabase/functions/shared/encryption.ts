/**
 * Fernet encryption/decryption for Deno Edge Functions.
 * Uses Web Crypto API only (no Node.js modules).
 *
 * Fernet token = base64( version(1) + timestamp(8) + IV(16) + ciphertext + HMAC(32) )
 * AES-128-CBC + HMAC-SHA256
 */

function base64ToBytes(b64: string): Uint8Array {
  // Fernet tokens use URL-safe base64 (- and _). atob() only handles
  // standard base64 (+ and /), so convert before decoding.
  const std = b64.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(std);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  // Fernet uses URL-safe base64 (- and _) — btoa() produces standard (+ and /)
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_");
}

async function importAesKey(raw: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, { name: "AES-CBC" }, false, ["encrypt", "decrypt"]);
}

async function importHmacKey(raw: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

function deriveKeyMaterial(key: Uint8Array): { signingKey: Uint8Array; encryptionKey: Uint8Array } {
  return { signingKey: key.slice(0, 16), encryptionKey: key.slice(16) };
}

function concat(...arrays: Uint8Array[]): Uint8Array {
  const total = arrays.reduce((sum, a) => sum + a.length, 0);
  const result = new Uint8Array(total);
  let offset = 0;
  for (const arr of arrays) {
    result.set(arr, offset);
    offset += arr.length;
  }
  return result;
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function fernetDecrypt(token: string, keyBase64: string): Promise<string> {
  const key = base64ToBytes(keyBase64);
  const { signingKey, encryptionKey } = deriveKeyMaterial(key);
  const tokenBytes = base64ToBytes(token);

  if (tokenBytes.length < 73) throw new Error("Invalid Fernet token: too short");
  if (tokenBytes[0] !== 0x80) throw new Error(`Unsupported Fernet version: ${tokenBytes[0]}`);

  const iv = tokenBytes.slice(9, 25);
  const ciphertext = tokenBytes.slice(25, tokenBytes.length - 32);
  const hmac = tokenBytes.slice(tokenBytes.length - 32);

  // Verify HMAC
  const hmacPayload = tokenBytes.slice(0, tokenBytes.length - 32);
  const hmacKey = await importHmacKey(signingKey);
  const expectedHmac = new Uint8Array(await crypto.subtle.sign("HMAC", hmacKey, hmacPayload));
  if (!timingSafeEqual(hmac, expectedHmac)) throw new Error("Invalid Fernet token: HMAC failed");

  // Decrypt
  const aesKey = await importAesKey(encryptionKey);
  const plainBuf = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, aesKey, ciphertext);
  return new TextDecoder().decode(plainBuf);
}

export async function fernetEncrypt(plaintext: string, keyBase64: string): Promise<string> {
  const key = base64ToBytes(keyBase64);
  const { signingKey, encryptionKey } = deriveKeyMaterial(key);

  const version = new Uint8Array([0x80]);
  const timestamp = new Uint8Array(8);
  let ts = Math.floor(Date.now() / 1000);
  for (let i = 7; i >= 0; i--) { timestamp[i] = ts & 0xff; ts >>>= 8; }
  const iv = crypto.getRandomValues(new Uint8Array(16));

  const aesKey = await importAesKey(encryptionKey);
  const cipherBuf = await crypto.subtle.encrypt({ name: "AES-CBC", iv }, aesKey, new TextEncoder().encode(plaintext));
  const ciphertext = new Uint8Array(cipherBuf);

  // HMAC over version + timestamp + iv + ciphertext
  const hmacPayload = concat(version, timestamp, iv, ciphertext);
  const hmacKey = await importHmacKey(signingKey);
  const hmac = new Uint8Array(await crypto.subtle.sign("HMAC", hmacKey, hmacPayload));

  return bytesToBase64(concat(version, timestamp, iv, ciphertext, hmac));
}

export async function decryptProviderConfig(raw: any, keyBase64: string): Promise<Record<string, string>> {
  if (!raw || typeof raw !== "object") return {};
  if ("encrypted" in raw && typeof raw.encrypted === "string") {
    const json = await fernetDecrypt(raw.encrypted, keyBase64);
    return JSON.parse(json);
  }
  return raw;
}
