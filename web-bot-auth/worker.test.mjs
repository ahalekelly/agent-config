import assert from "node:assert/strict";
import { createHash, generateKeyPairSync } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createWorker } from "./worker.js";
import { verifyDirectoryResponse } from "./verify-directory.mjs";

const TARGET = "https://lancelotlabs.org/.well-known/http-message-signatures-directory";
const NOW = 1_800_000_000;

function fixture() {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const jwk = publicKey.export({ format: "jwk" });
  const canonical = JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x });
  const kid = createHash("sha256").update(canonical).digest("base64url");
  return {
    directory: { keys: [{ ...jwk, kid, use: "sig", nbf: 0 }] },
    privateKeyPem: privateKey.export({ format: "pem", type: "pkcs8" }),
  };
}

async function responseFrom(worker, privateKeyPem) {
  const originalNow = Date.now;
  Date.now = () => NOW * 1_000;
  try {
    return await worker.fetch(new Request(TARGET), {
      DIRECTORY_PRIVATE_KEY_PEM: privateKeyPem,
    });
  } finally {
    Date.now = originalNow;
  }
}

test("signs a directory response that an independent verifier accepts", async () => {
  const { directory, privateKeyPem } = fixture();
  const response = await responseFrom(createWorker(directory), privateKeyPem);
  const result = await verifyDirectoryResponse(response, NOW);

  assert.equal(result.keyId, directory.keys[0].kid);
  assert.equal(result.created, NOW);
  assert.equal(result.expires, NOW + 300);
  assert.equal(result.maxAge, 60);
});

test("covers the directory body with Content-Digest", async () => {
  const { directory, privateKeyPem } = fixture();
  const response = await responseFrom(createWorker(directory), privateKeyPem);
  const headers = new Headers(response.headers);
  const body = `${await response.text()} `;

  await assert.rejects(
    verifyDirectoryResponse(new Response(body, { headers }), NOW),
    /Content-Digest does not match/,
  );
});

test("rejects a signature lifetime outside the production profile", async () => {
  const { directory, privateKeyPem } = fixture();
  const response = await responseFrom(createWorker(directory), privateKeyPem);
  const headers = new Headers(response.headers);
  headers.set(
    "signature-input",
    headers.get("signature-input").replace(`expires=${NOW + 300}`, `expires=${NOW + 301}`),
  );

  await assert.rejects(
    verifyDirectoryResponse(new Response(await response.arrayBuffer(), { headers }), NOW),
    /signature lifetime must be exactly 300 seconds/,
  );
});

test("rejects a cache lifetime outside the production profile", async () => {
  const { directory, privateKeyPem } = fixture();
  const response = await responseFrom(createWorker(directory), privateKeyPem);
  const headers = new Headers(response.headers);
  headers.set("cache-control", headers.get("cache-control").replace("max-age=60", "max-age=61"));

  await assert.rejects(
    verifyDirectoryResponse(new Response(await response.arrayBuffer(), { headers }), NOW),
    /cache max-age must be exactly 60 seconds/,
  );
});

test("fails instead of signing with a secret for another key", async () => {
  const { directory } = fixture();
  const { privateKeyPem } = fixture();

  await assert.rejects(
    responseFrom(createWorker(directory), privateKeyPem),
    /Worker secret does not match configured key ID/,
  );
});

test("fails when the Worker secret is absent", async () => {
  const { directory } = fixture();

  await assert.rejects(
    createWorker(directory).fetch(new Request(TARGET), {}),
    /DIRECTORY_PRIVATE_KEY_PEM Worker secret is required/,
  );
});

test("keeps non-directory and non-GET responses unsigned", async () => {
  const { directory } = fixture();
  const worker = createWorker(directory);
  const responses = await Promise.all([
    worker.fetch(new Request("https://lancelotlabs.org/not-the-directory"), {}),
    worker.fetch(new Request(TARGET, { method: "POST" }), {}),
  ]);

  for (const response of responses) {
    assert.equal(response.status, 404);
    assert.equal(response.headers.has("signature"), false);
    assert.equal(response.headers.has("signature-input"), false);
    assert.equal((await response.text()).includes("keys"), false);
  }
});

test("rejects a second published key until it has its own secret", () => {
  const { directory } = fixture();
  assert.throws(
    () => createWorker({ keys: [...directory.keys, directory.keys[0]] }),
    /exactly one published key and signing secret/,
  );
});

test("the committed directory contains no private key material", async () => {
  const directory = JSON.parse(
    await readFile(new URL("./http-message-signatures-directory.json", import.meta.url), "utf8"),
  );
  assert.equal(directory.keys.length, 1);
  assert.equal("d" in directory.keys[0], false);
  assert.equal(
    createHash("sha256")
      .update(
        JSON.stringify({
          crv: directory.keys[0].crv,
          kty: directory.keys[0].kty,
          x: directory.keys[0].x,
        }),
      )
      .digest("base64url"),
    directory.keys[0].kid,
  );
});

test("Wrangler requires the private-key secret without storing its value", async () => {
  const config = await readFile(new URL("./wrangler.toml", import.meta.url), "utf8");
  assert.match(config, /\[secrets\]\nrequired = \["DIRECTORY_PRIVATE_KEY_PEM"\]/);
  assert.doesNotMatch(config, /DIRECTORY_PRIVATE_KEY_PEM\s*=/);
});
