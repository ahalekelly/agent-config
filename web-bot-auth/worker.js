// Web Bot Auth key directory — serves the public key for signed-agent verification.
const DIRECTORY = {
  "keys": [
    {
      "kty": "OKP",
      "crv": "Ed25519",
      "x": "7iNTWpE-E4r2zc6mYb096LTviEObmmB9BtNo2zmi1LA",
      "kid": "PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So",
      "use": "sig",
      "nbf": 0
    }
  ]
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== "/.well-known/http-message-signatures-directory") {
      return new Response("Not found", { status: 404 });
    }
    return new Response(JSON.stringify(DIRECTORY), {
      headers: {
        "Content-Type": "application/http-message-signatures-directory+json",
        "Cache-Control": "max-age=86400",
      },
    });
  },
};
