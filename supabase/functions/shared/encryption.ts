/**
 * Fernet encryption/decryption for Deno Edge Functions.
 * Used to decrypt per-user API keys stored in batteries.provider_config.
 *
 * Fernet format: base64(token)
 * Token = version (1 byte) + timestamp (8 bytes) + IV (16 bytes) + ciphertext + HMAC (32 bytes)
 * Uses AES-128-CBC + HMAC-SHA256
 */

import { createHmac, createCipheriv, createDecipheriv, timingSafeEqual } from "https://deno.land/std@0.208.0/node/crypto.ts";

function base64ToBytes(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

function deriveKeyMaterial(key: Uint8Array): { signingKey: Uint8Array; encryptionKey: Uint8Array } {
  // Fernet key must be 32 bytes: first 16 = signing key, last 16 = encryption key
  const signingKey = key.slice(0, 16);
  const encryptionKey = key.slice(16);
  return { signingKey, encryptionKey };
}

export function fernetDecrypt(token: string, keyBase64: string): string {
  const key = base64ToBytes(keyBase64);
  const { signingKey, encryptionKey } = deriveKeyMaterial(key);

  const tokenBytes = base64ToBytes(token);

  // Minimum Fernet token size: 1+8+16+16+32 = 73 bytes
  if (tokenBytes.length < 73) {
    throw new Error("Invalid Fernet token: too short");
  }

  const version = tokenBytes[0];
  if (version !== 0x80) {
    throw new Error(`Unsupported Fernet version: ${version}`);
  }

  const timestamp = tokenBytes.slice(1, 9);
  const iv = tokenBytes.slice(9, 25);
  const ciphertext = tokenBytes.slice(25, tokenBytes.length - 32);
  const hmac = tokenBytes.slice(tokenBytes.length - 32);

  // Verify HMAC
  const hmacPayload = new Uint8Array(1 + 8 + 16 + ciphertext.length);
  hmacPayload.set(tokenBytes.slice(0, 25 + ciphertext.length));
  const expectedHmac = createHmac("sha256", signingKey).update(hmacPayload).digest();

  if (!timingSafeEqual(hmac, expectedHmac)) {
    throw new Error("Invalid Fernet token: HMAC verification failed");
  }

  // Decrypt with AES-128-CBC
  const decipher = createDecipheriv("aes-128-cbc", encryptionKey, iv);
  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);

  return decrypted.toString("utf-8");
}

export function fernetEncrypt(plaintext: string, keyBase64: string): string {
  const key = base64ToBytes(keyBase64);
  const { signingKey, encryptionKey } = deriveKeyMaterial(key);

  // Version byte
  const version = new Uint8Array([0x80]);

  // Timestamp (8 bytes, big-endian)
  const timestamp = new Uint8Array(8);
  const ts = Math.floor(Date.now() / 1000);
  for (let i = 7; i >= 0; i--) {
    timestamp[i] = ts & 0xff;
    ts >>>= 8;
  }

  // Random IV (16 bytes)
  const iv = crypto.getRandomValues(new Uint8Array(16));

  // Encrypt with AES-128-CBC
  const cipher = createCipheriv("aes-128-cbc", encryptionKey, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf-8"), cipher.final()]);

  // HMAC over version + timestamp + iv + ciphertext
  const hmacPayload = new Uint8Array(version.length + timestamp.length + iv.length + ciphertext.length);
  hmacPayload.set(version, 0);
  hmacPayload.set(timestamp, version.length);
  hmacPayload.set(iv, version.length + timestamp.length);
  hmacPayload.set(ciphertext, version.length + timestamp.length + iv.length);
  const hmac = createHmac("sha256", signingKey).update(hmacPayload).digest();

  // Combine: version + timestamp + iv + ciphertext + hmac
  const token = new Uint8Array(version.length + timestamp.length + iv.length + ciphertext.length + hmac.length);
  token.set(version, 0);
  token.set(timestamp, version.length);
  token.set(iv, version.length + timestamp.length);
  token.set(ciphertext, version.length + timestamp.length + iv.length);
  token.set(hmac, version.length + timestamp.length + iv.length + ciphertext.length);

  return bytesToBase64(token);
}

/**
 * Decrypt a provider_config object that may be encrypted.
 * If stored as {"encrypted": "gAAAAA..."}, decrypt and return the inner dict.
 * If stored as plain dict, return as-is (legacy).
 */
export function decryptProviderConfig(raw: any, keyBase64: string): Record<string, string> {
  if (!raw || typeof raw !== "object") return {};
  if ("encrypted" in raw && typeof raw.encrypted === "string") {
    const json = fernetDecrypt(raw.encrypted, keyBase64);
    return JSON.parse(json);
  }
  // Legacy unencrypted
  return raw;
}
