import DIRECTORY from "./http-message-signatures-directory.json" with { type: "json" };

const DIRECTORY_PATH = "/.well-known/http-message-signatures-directory";
const MEDIA_TYPE = "application/http-message-signatures-directory+json";
const CACHE_SECONDS = 60;
const SIGNATURE_SECONDS = 300;
const encoder = new TextEncoder();

function base64(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

function base64url(bytes) {
  return base64(bytes).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function pkcs8Bytes(pem) {
  if (typeof pem !== "string") {
    throw new Error("DIRECTORY_PRIVATE_KEY_PEM Worker secret is required");
  }

  const lines = pem.trim().split(/\r?\n/);
  if (
    lines[0] !== "-----BEGIN PRIVATE KEY-----" ||
    lines.at(-1) !== "-----END PRIVATE KEY-----"
  ) {
    throw new Error("DIRECTORY_PRIVATE_KEY_PEM must contain a PKCS#8 private key");
  }

  const encoded = lines.slice(1, -1).join("");
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) {
    throw new Error("DIRECTORY_PRIVATE_KEY_PEM contains invalid base64");
  }
  return Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
}

async function jwkThumbprint(jwk) {
  const canonical = JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x });
  return base64url(await crypto.subtle.digest("SHA-256", encoder.encode(canonical)));
}

async function signedResponse(request, body, publicKeyJwk, privateKeyPem) {
  if (
    publicKeyJwk.kty !== "OKP" ||
    publicKeyJwk.crv !== "Ed25519" ||
    typeof publicKeyJwk.x !== "string" ||
    typeof publicKeyJwk.kid !== "string" ||
    "d" in publicKeyJwk
  ) {
    throw new Error("Directory must contain one public Ed25519 JWK with a key ID");
  }
  if ((await jwkThumbprint(publicKeyJwk)) !== publicKeyJwk.kid) {
    throw new Error(`Published key does not match configured key ID ${publicKeyJwk.kid}`);
  }

  const privateKey = await crypto.subtle.importKey(
    "pkcs8",
    pkcs8Bytes(privateKeyPem),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
  const publicKey = await crypto.subtle.importKey(
    "jwk",
    publicKeyJwk,
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  const contentDigest = `sha-256=:${base64(
    await crypto.subtle.digest("SHA-256", encoder.encode(body)),
  )}:`;
  const created = Math.floor(Date.now() / 1_000);
  const parameters =
    `("@authority";req "content-digest");alg="ed25519"` +
    `;keyid="${publicKeyJwk.kid}";tag="http-message-signatures-directory"` +
    `;created=${created};expires=${created + SIGNATURE_SECONDS}`;
  const signatureBase =
    `"@authority";req: ${new URL(request.url).host}\n` +
    `"content-digest": ${contentDigest}\n` +
    `"@signature-params": ${parameters}`;
  const signature = await crypto.subtle.sign(
    "Ed25519",
    privateKey,
    encoder.encode(signatureBase),
  );
  if (!(await crypto.subtle.verify("Ed25519", publicKey, signature, encoder.encode(signatureBase)))) {
    throw new Error(`Worker secret does not match configured key ID ${publicKeyJwk.kid}`);
  }

  return new Response(body, {
    headers: {
      "Cache-Control": `public, max-age=${CACHE_SECONDS}, must-revalidate, no-transform`,
      "Content-Digest": contentDigest,
      "Content-Type": MEDIA_TYPE,
      Signature: `sig1=:${base64(signature)}:`,
      "Signature-Input": `sig1=${parameters}`,
    },
  });
}

export function createWorker(directory) {
  if (!Array.isArray(directory.keys) || directory.keys.length !== 1) {
    throw new Error("Directory Worker requires exactly one published key and signing secret");
  }
  const body = JSON.stringify(directory);
  const publicKey = directory.keys[0];

  return {
    async fetch(request, env) {
      const url = new URL(request.url);
      if (request.method !== "GET" || url.pathname !== DIRECTORY_PATH) {
        return new Response("Not found", { status: 404 });
      }
      return signedResponse(request, body, publicKey, env?.DIRECTORY_PRIVATE_KEY_PEM);
    },
  };
}

export default createWorker(DIRECTORY);
