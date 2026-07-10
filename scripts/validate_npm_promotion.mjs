#!/usr/bin/env node

function parseVersion(value) {
  const raw = String(value || "").trim();
  const match = raw.match(
    /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$/,
  );
  if (!match) {
    throw new Error("Invalid semantic version: " + (raw || "<empty>"));
  }
  return {
    raw,
    core: match.slice(1, 4).map(Number),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

function compareIdentifiers(left, right) {
  const leftNumeric = /^\d+$/.test(left);
  const rightNumeric = /^\d+$/.test(right);
  if (leftNumeric && rightNumeric) return Number(left) - Number(right);
  if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
  return left.localeCompare(right);
}

export function compareVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  for (let index = 0; index < 3; index += 1) {
    if (a.core[index] !== b.core[index]) return a.core[index] - b.core[index];
  }
  if (a.prerelease.length === 0 || b.prerelease.length === 0) {
    if (a.prerelease.length === b.prerelease.length) return 0;
    return a.prerelease.length === 0 ? 1 : -1;
  }
  for (let index = 0; index < Math.max(a.prerelease.length, b.prerelease.length); index += 1) {
    if (a.prerelease[index] === undefined) return -1;
    if (b.prerelease[index] === undefined) return 1;
    const compared = compareIdentifiers(a.prerelease[index], b.prerelease[index]);
    if (compared !== 0) return compared;
  }
  return 0;
}

export function validatePromotion({ target, beta, latest, resolved, integrity }) {
  const parsedTarget = parseVersion(target);
  if (parsedTarget.prerelease.length === 0) {
    throw new Error("Promotion target must be an already-published prerelease.");
  }
  if (target !== beta) {
    throw new Error("Promotion target " + target + " is not the current beta " + beta + ".");
  }
  if (target !== resolved) {
    throw new Error("Registry resolved " + resolved + ", expected " + target + ".");
  }
  const ordering = compareVersions(target, latest);
  if (ordering < 0) {
    throw new Error("Refusing to move latest backward from " + latest + " to " + target + ".");
  }
  if (!/^sha(?:1|256|384|512)-[A-Za-z0-9+/=]+$/.test(String(integrity || ""))) {
    throw new Error("Registry metadata is missing a valid dist.integrity value.");
  }
  return { target, previous_latest: latest, integrity, already_latest: ordering === 0 };
}

if (import.meta.url === "file://" + process.argv[1]) {
  try {
    const result = validatePromotion({
      target: process.argv[2],
      beta: process.argv[3],
      latest: process.argv[4],
      resolved: process.argv[5],
      integrity: process.argv[6],
    });
    console.log(JSON.stringify({ ok: true, ...result }));
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
