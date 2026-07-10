import assert from "node:assert/strict";
import test from "node:test";

import { compareVersions, validatePromotion } from "./validate_npm_promotion.mjs";

const integrity = "sha512-YWdlbnRsYXllci13YWxsZXQ=";

test("validates promotion of the current beta without rebuilding", () => {
  assert.deepEqual(
    validatePromotion({
      target: "0.1.74-beta.2",
      beta: "0.1.74-beta.2",
      latest: "0.1.73",
      resolved: "0.1.74-beta.2",
      integrity,
    }),
    {
      target: "0.1.74-beta.2",
      previous_latest: "0.1.73",
      integrity,
      already_latest: false,
    },
  );
});

test("implements prerelease ordering and rejects unsafe promotions", () => {
  assert.ok(compareVersions("0.1.74-beta.2", "0.1.74-beta.1") > 0);
  assert.ok(compareVersions("0.1.74", "0.1.74-beta.2") > 0);
  assert.throws(
    () =>
      validatePromotion({
        target: "0.1.72-beta.1",
        beta: "0.1.72-beta.1",
        latest: "0.1.73",
        resolved: "0.1.72-beta.1",
        integrity,
      }),
    /backward/,
  );
  assert.throws(
    () =>
      validatePromotion({
        target: "0.1.74-beta.1",
        beta: "0.1.74-beta.2",
        latest: "0.1.73",
        resolved: "0.1.74-beta.1",
        integrity,
      }),
    /current beta/,
  );
  assert.equal(
    validatePromotion({
      target: "0.1.74-beta.2",
      beta: "0.1.74-beta.2",
      latest: "0.1.74-beta.2",
      resolved: "0.1.74-beta.2",
      integrity,
    }).already_latest,
    true,
  );
});
