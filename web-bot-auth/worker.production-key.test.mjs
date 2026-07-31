import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import worker from "./worker.mjs";

const enabled =
  process.env.WEB_BOT_AUTH_PRODUCTION_KEY_TEST === "1" && !process.env.CI;

test(
  "production private key matches the published directory key",
  { skip: !enabled },
  async () => {
    const privateKeyPath = process.env.WEB_BOT_AUTH_PRODUCTION_KEY_PATH;
    if (typeof privateKeyPath !== "string" || privateKeyPath.length === 0) {
      throw new Error(
        "WEB_BOT_AUTH_PRODUCTION_KEY_PATH is required when the production-key test is enabled",
      );
    }
    const privateKeyPem = await readFile(privateKeyPath, "utf8");
    const response = await worker.fetch(
      new Request(
        "https://lancelotlabs.org/.well-known/http-message-signatures-directory",
      ),
      { PRIVATE_KEY_PEM: privateKeyPem },
    );
    const directory = await response.json();

    assert.equal(response.status, 200);
    assert.equal(directory.keys.some((key) => "d" in key), false);
  },
);
