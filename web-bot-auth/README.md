# Web Bot Auth key directory

This Cloudflare Worker publishes the public Ed25519 key used by the Lancelot Labs Web Bot Auth identity. A successful directory response signs the request authority and its own body with the corresponding private key.

The private key is the `DIRECTORY_PRIVATE_KEY_PEM` secret on the `web-bot-auth` Worker. It is never part of the Worker source, Wrangler configuration, directory JSON, tests, or deployment bundle. The Worker verifies both the public JWK thumbprint and the signature against the published key before responding. A missing or mismatched secret fails the request instead of serving an unsigned directory.

The response follows [Cloudflare's key-directory enrollment profile](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/#2-host-a-key-directory):

- `Signature-Input` covers the original request's `@authority` using `;req`.
- `created`, `expires`, `keyid`, `alg="ed25519"`, and `tag="http-message-signatures-directory"` describe the signature.
- `Content-Digest` is also covered, following the active [HTTP Message Signatures Directory draft](https://datatracker.ietf.org/doc/draft-meunier-webbotauth-httpsig-directory/).
- `Cache-Control` keeps a response fresh for 60 seconds while its signature remains valid for 300 seconds. `must-revalidate` prevents a stale cached response from being treated as fresh.

`Signature-Agent` belongs on Web Bot Auth requests sent to storefronts. The directory response itself carries `Signature-Input` and `Signature`; it does not point back to itself with another `Signature-Agent` header.

## Test

The tests generate an ephemeral Ed25519 key and independently verify the Worker response with Node's cryptographic implementation and only the returned public JWKS. They never read the deployed private key.

```sh
cd /Users/akelly/.agents/web-bot-auth
node --test worker.test.mjs
```

## Provision and deploy

Run these commands from the merged checkout. `private.pem` is the ignored local PKCS#8 key; shell redirection passes it directly to Wrangler without printing it.

```sh
cd /Users/akelly/.agents/web-bot-auth
npx wrangler secret put DIRECTORY_PRIVATE_KEY_PEM < private.pem
npx wrangler deploy
node verify-directory.mjs
```

`wrangler secret put` creates and immediately deploys a Worker version. For the first signed-directory deployment, run it before `wrangler deploy`: the unsigned Worker ignores the new binding, and Wrangler can then satisfy `[secrets].required` when deploying the signer. This is not a key-rotation procedure; changing the secret alone while signer code is live will fail its public-key match.

The final command fetches the live HTTPS directory, verifies its content digest, JWK thumbprint, signature lifetime, cache lifetime, and Ed25519 response signature, then prints only non-secret validation metadata.

Cloudflare verified-bot enrollment requires a valid signed directory and is performed after the live verifier succeeds. Shopify documents its signed Web Bot Auth rate tier as independent of Cloudflare enrollment. Directory validation neither proves nor changes Shopify's tier assignment.
