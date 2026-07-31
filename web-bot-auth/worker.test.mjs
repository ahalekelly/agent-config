import assert from "node:assert/strict";
import test from "node:test";

import { createDirectoryWorker } from "./worker.mjs";

const REQUEST = new Request(
  "https://lancelotlabs.org/.well-known/http-message-signatures-directory",
);
const textEncoder = new TextEncoder();

function base64url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

function privateKeyPem(pkcs8) {
  const encoded = Buffer.from(pkcs8).toString("base64");
  const lines = encoded.match(/.{1,64}/g).join("\n");
  return `-----BEGIN PRIVATE KEY-----\n${lines}\n-----END PRIVATE KEY-----\n`;
}

function signatureBytes(response) {
  const signature = response.headers.get("Signature");
  const match = signature.match(/^sig1=:([A-Za-z0-9+/]+={0,2}):$/);
  assert.ok(match, "Signature must be an RFC 8941 byte sequence labeled sig1");
  return Uint8Array.from(atob(match[1]), (byte) => byte.charCodeAt(0));
}

function signatureBase(response, request) {
  const signatureInput = response.headers.get("Signature-Input");
  assert.ok(signatureInput?.startsWith("sig1="));
  return textEncoder.encode(
    `"@authority";req: ${new URL(request.url).host}\n` +
      `"@signature-params": ${signatureInput.slice("sig1=".length)}`,
  );
}

const keyPair = await crypto.subtle.generateKey("Ed25519", true, [
  "sign",
  "verify",
]);
const exportedPublicJwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
const keyId = base64url(
  await crypto.subtle.digest(
    "SHA-256",
    textEncoder.encode(
      JSON.stringify({
        crv: exportedPublicJwk.crv,
        kty: exportedPublicJwk.kty,
        x: exportedPublicJwk.x,
      }),
    ),
  ),
);
const directory = {
  keys: [
    {
      kty: exportedPublicJwk.kty,
      crv: exportedPublicJwk.crv,
      x: exportedPublicJwk.x,
      kid: keyId,
      use: "sig",
      nbf: 0,
    },
  ],
};
const fixturePem = privateKeyPem(
  await crypto.subtle.exportKey("pkcs8", keyPair.privateKey),
);
const worker = createDirectoryWorker(directory, keyId);

async function signedFixture() {
  const response = await worker.fetch(REQUEST, { PRIVATE_KEY_PEM: fixturePem });
  return { response };
}

test("directory response has the required verifiable signature", async () => {
  const { response } = await signedFixture();
  const signatureInput = response.headers.get("Signature-Input");
  const timing = signatureInput.match(/;created=(\d+);expires=(\d+)$/);
  assert.ok(timing, "Signature-Input must contain created and expires");

  assert.equal(
    response.headers.get("Content-Type"),
    "application/http-message-signatures-directory+json",
  );
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.ok(
    signatureInput.startsWith(
      `sig1=("@authority";req);alg="ed25519";keyid="${keyId}";nonce="`,
    ),
  );
  assert.ok(signatureInput.includes(';tag="http-message-signatures-directory"'));
  assert.equal(Number(timing[2]) - Number(timing[1]), 10);
  assert.equal(
    await crypto.subtle.verify(
      "Ed25519",
      keyPair.publicKey,
      signatureBytes(response),
      signatureBase(response, REQUEST),
    ),
    true,
  );
});

test("directory response signature rejects signature-input tampering", async () => {
  const { response } = await signedFixture();
  response.headers.set(
    "Signature-Input",
    response.headers.get("Signature-Input").replace(/created=\d+/, "created=0"),
  );

  assert.equal(
    await crypto.subtle.verify(
      "Ed25519",
      keyPair.publicKey,
      signatureBytes(response),
      signatureBase(response, REQUEST),
    ),
    false,
  );
});

test("directory response signature rejects the wrong request authority", async () => {
  const { response } = await signedFixture();
  const wrongRequest = new Request(
    "https://mirror.example/.well-known/http-message-signatures-directory",
  );

  assert.equal(
    await crypto.subtle.verify(
      "Ed25519",
      keyPair.publicKey,
      signatureBytes(response),
      signatureBase(response, wrongRequest),
    ),
    false,
  );
});

test("worker response verifies with its published directory key", async () => {
  const { response } = await signedFixture();
  const responseDirectory = await response.json();
  const publicJwk = responseDirectory.keys[0];
  const publicKey = await crypto.subtle.importKey(
    "jwk",
    { kty: publicJwk.kty, crv: publicJwk.crv, x: publicJwk.x },
    "Ed25519",
    false,
    ["verify"],
  );

  assert.equal(
    responseDirectory.keys.some((key) => "d" in key),
    false,
    "directory must not expose private key data",
  );
  assert.equal(
    await crypto.subtle.verify(
      "Ed25519",
      publicKey,
      signatureBytes(response),
      signatureBase(response, REQUEST),
    ),
    true,
  );
});

test("worker rejects a missing private key secret", async () => {
  await assert.rejects(
    worker.fetch(REQUEST, {}),
    /PRIVATE_KEY_PEM secret is required/,
  );
});

test("worker rejects a private key that does not match the directory", async () => {
  const wrongKeyPair = await crypto.subtle.generateKey("Ed25519", true, [
    "sign",
    "verify",
  ]);
  const wrongPem = privateKeyPem(
    await crypto.subtle.exportKey("pkcs8", wrongKeyPair.privateKey),
  );

  await assert.rejects(
    worker.fetch(REQUEST, { PRIVATE_KEY_PEM: wrongPem }),
    /PRIVATE_KEY_PEM does not match the published directory key/,
  );
});
