# Web Bot Auth deployment

This directory is the Lancelot Labs deployment of the [cross-shop key directory](../skills/product-search/cross-shop/key-directory/): `private.pem` (the Ed25519 identity key, never committed or bundled) and a `wrangler.toml` routed to `lancelotlabs.org` whose `main` points at the Worker source in the cross-shop checkout. The Worker derives the published public JWK from the `DIRECTORY_PRIVATE_KEY_PEM` secret, so the directory is fully determined by that secret.

Setup, deploy, and key-rotation procedure live in the key-directory README. Deploy and verify from here:

```sh
cd /Users/akelly/.agents/web-bot-auth
npx wrangler deploy
node ../skills/product-search/cross-shop/key-directory/verify-directory.mjs https://lancelotlabs.org/.well-known/http-message-signatures-directory
```
