import PRODUCTION_DIRECTORY from "./http-message-signatures-directory.json" with {
  type: "json",
};

const DIRECTORY_PATH = "/.well-known/http-message-signatures-directory";
const EXPECTED_KEY_ID = "PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So";
const SIGNATURE_LABEL = "sig1";
const SIGNATURE_TTL_SECONDS = 10;
const textEncoder = new TextEncoder();

function base64(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

async function importSigningKey(privateKeyPem, directory, expectedKeyId) {
  const match = privateKeyPem.match(
    /^-----BEGIN PRIVATE KEY-----\r?\n([\s\S]+)\r?\n-----END PRIVATE KEY-----\r?\n?$/,
  );
  if (!match) {
    throw new Error("PRIVATE_KEY_PEM must contain one PKCS#8 private key");
  }

  const publicJwk = directory.keys[0];
  const thumbprint = base64(
    await crypto.subtle.digest(
      "SHA-256",
      textEncoder.encode(
        JSON.stringify({ crv: publicJwk.crv, kty: publicJwk.kty, x: publicJwk.x }),
      ),
    ),
  )
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
  if (thumbprint !== publicJwk.kid) {
    throw new Error("Published directory kid is not its RFC 7638 thumbprint");
  }
  if (thumbprint !== expectedKeyId) {
    throw new Error("Published directory key thumbprint does not match configured KEY_ID");
  }

  const privateKey = await crypto.subtle.importKey(
    "pkcs8",
    Uint8Array.from(atob(match[1].replaceAll(/\s/g, "")), (byte) =>
      byte.charCodeAt(0),
    ),
    "Ed25519",
    false,
    ["sign"],
  );
  const publicKey = await crypto.subtle.importKey(
    "jwk",
    {
      kty: publicJwk.kty,
      crv: publicJwk.crv,
      x: publicJwk.x,
    },
    "Ed25519",
    false,
    ["verify"],
  );
  const challenge = textEncoder.encode(expectedKeyId);
  const signature = await crypto.subtle.sign("Ed25519", privateKey, challenge);

  if (!(await crypto.subtle.verify("Ed25519", publicKey, signature, challenge))) {
    throw new Error("PRIVATE_KEY_PEM does not match the published directory key");
  }
  return privateKey;
}

async function createSignedDirectoryResponse(
  request,
  privateKey,
  directory,
  created,
  nonce,
) {
  if (nonce.byteLength !== 64) {
    throw new Error("Directory signature nonce must be exactly 64 bytes");
  }

  const authority = new URL(request.url).host;
  const keyId = directory.keys[0].kid;
  const signatureParameters =
    `("@authority";req);alg="ed25519";keyid="${keyId}"` +
    `;nonce="${base64(nonce)}";tag="http-message-signatures-directory"` +
    `;created=${created};expires=${created + SIGNATURE_TTL_SECONDS}`;
  const signatureBase =
    `"@authority";req: ${authority}\n` +
    `"@signature-params": ${signatureParameters}`;
  const signature = await crypto.subtle.sign(
    "Ed25519",
    privateKey,
    textEncoder.encode(signatureBase),
  );

  return new Response(JSON.stringify(directory), {
    headers: {
      "Content-Type": "application/http-message-signatures-directory+json",
      "Cache-Control": "no-store",
      "Signature-Input": `${SIGNATURE_LABEL}=${signatureParameters}`,
      Signature: `${SIGNATURE_LABEL}=:${base64(signature)}:`,
    },
  });
}

export function createDirectoryWorker(directory, expectedKeyId) {
  return {
    async fetch(request, env) {
      if (new URL(request.url).pathname !== DIRECTORY_PATH) {
        return new Response("Not found", { status: 404 });
      }
      if (typeof env.PRIVATE_KEY_PEM !== "string") {
        throw new Error("PRIVATE_KEY_PEM secret is required");
      }

      return createSignedDirectoryResponse(
        request,
        await importSigningKey(env.PRIVATE_KEY_PEM, directory, expectedKeyId),
        directory,
        Math.floor(Date.now() / 1000),
        crypto.getRandomValues(new Uint8Array(64)),
      );
    },
  };
}

export default createDirectoryWorker(PRODUCTION_DIRECTORY, EXPECTED_KEY_ID);
