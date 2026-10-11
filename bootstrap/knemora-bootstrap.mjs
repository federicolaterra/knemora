#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  chmodSync,
  closeSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { get } from "node:https";
import { homedir, platform, arch } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repository = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = join(repository, "infrastructure", "runtime-manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const minimumNodeMajor = 24;
const homeFormatVersion = 1;
const homeSchemaVersion = 1;
const diagnosticCommands = new Set(["doctor", "status", "logs", "backups"]);

function fail(message) {
  process.stderr.write(`Knemora: ${message}\n`);
  process.exit(2);
}

function commandName(arguments_) {
  return arguments_.find((item) => !item.startsWith("-")) ?? "start";
}

function checkNodeAndNpm() {
  const major = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (!Number.isInteger(major) || major < minimumNodeMajor) {
    fail(
      `Node.js ${minimumNodeMajor}+ is required; found ${process.version}. ` +
        "Install a supported Node.js release from https://nodejs.org/.",
    );
  }
  const npm = spawnSync("npm", ["--version"], { encoding: "utf8" });
  if (npm.status !== 0) {
    fail("npm is required with Node.js. Reinstall Node.js from https://nodejs.org/.");
  }
}

function configuredHome() {
  const value = process.env.KNEMORA_HOME || join(homedir(), ".knemora");
  if (value.includes("\0")) fail("KNEMORA_HOME contains an invalid null byte.");
  return resolve(value);
}

function assertContained(root, candidate) {
  const rel = relative(root, candidate);
  if (rel === "" || (!rel.startsWith(`..${sep}`) && rel !== ".." && !isAbsolute(rel))) return;
  fail(`Managed path escapes KNEMORA_HOME: ${candidate}`);
}

function readHomePreflight(home) {
  if (!existsSync(home)) return { status: "empty" };
  if (!lstatSync(home).isDirectory()) fail(`KNEMORA_HOME is not a directory: ${home}`);
  const descriptor = join(home, "config", "home.json");
  if (existsSync(descriptor)) {
    if (!lstatSync(descriptor).isFile() || lstatSync(descriptor).isSymbolicLink()) {
      fail(`Application-home descriptor is not a regular file: ${descriptor}`);
    }
    let value;
    try {
      value = JSON.parse(readFileSync(descriptor, "utf8"));
    } catch (error) {
      fail(`Application-home descriptor is unreadable: ${descriptor}: ${error.message}`);
    }
    if (value.formatVersion !== homeFormatVersion) {
      fail(
        `Application-home descriptor format ${String(value.formatVersion)} is unsupported; ` +
          `this build supports ${homeFormatVersion}. Run a newer Knemora build or restore a ` +
          "compatible backup.",
      );
    }
    if (!Number.isInteger(value.homeSchemaVersion) || value.homeSchemaVersion < 1) {
      fail(`Application-home descriptor has an invalid homeSchemaVersion: ${descriptor}`);
    }
    if (value.homeSchemaVersion > homeSchemaVersion) {
      fail(
        `Application home schema ${value.homeSchemaVersion} is newer than supported schema ` +
          `${homeSchemaVersion}. No files were changed.`,
      );
    }
    return { status: value.homeSchemaVersion === homeSchemaVersion ? "ready" : "migration-needed" };
  }

  const entries = readdirSync(home).filter((name) => name !== ".DS_Store");
  if (entries.length === 0) return { status: "empty" };
  const known = new Set([
    "bin",
    "cache",
    "config",
    "data",
    "datasets",
    "demo",
    "logs",
    "models",
    "python",
    "runtime",
    "sources",
    "wiki",
  ]);
  const unknown = entries.filter((name) => !known.has(name));
  if (unknown.length > 0) {
    fail(
      `Nonempty KNEMORA_HOME has no compatibility descriptor and contains unknown entries: ` +
        `${unknown.join(", ")}. Run ./knemora doctor and recover or relocate this directory.`,
    );
  }
  return { status: "legacy" };
}

function targetFor(component, backend) {
  const target = manifest[component].targets.find(
    (item) =>
      item.platform === platform() &&
      item.architecture === arch() &&
      item.backend === backend,
  );
  if (!target || target.status !== "supported") {
    fail(
      `${platform()} ${arch()} ${backend} is not supported yet. ` +
        "Milestone 08.5 supports macOS Apple Silicon with Metal only.",
    );
  }
  return target;
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function download(url, destination, expectedSize, redirects = 0) {
  if (redirects > 5) fail(`Too many redirects while downloading ${basename(destination)}.`);
  const allowedHosts = new Set([
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "releases.astral.sh",
  ]);
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" || !allowedHosts.has(parsed.hostname)) {
    fail(`Refusing unapproved download location: ${parsed.origin}`);
  }
  return new Promise((resolveDownload, rejectDownload) => {
    const request = get(parsed, { headers: { "User-Agent": "Knemora/0.1.0-alpha" } }, (response) => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode ?? 0)) {
        const location = response.headers.location;
        response.resume();
        if (!location) return rejectDownload(new Error("redirect omitted Location header"));
        return download(new URL(location, parsed).href, destination, expectedSize, redirects + 1)
          .then(resolveDownload, rejectDownload);
      }
      if (response.statusCode !== 200) {
        response.resume();
        return rejectDownload(new Error(`HTTP ${response.statusCode}`));
      }
      const declared = Number(response.headers["content-length"]);
      if (Number.isFinite(declared) && declared !== expectedSize) {
        response.resume();
        return rejectDownload(
          new Error(`archive size is ${declared}, expected ${expectedSize}`),
        );
      }
      const handle = openSync(destination, "w", 0o600);
      let received = 0;
      response.on("data", (chunk) => {
        received += chunk.length;
        if (received > expectedSize) response.destroy(new Error("archive exceeds expected size"));
        else writeFileSync(handle, chunk);
      });
      response.on("end", () => {
        closeSync(handle);
        if (received !== expectedSize) {
          rejectDownload(new Error(`archive is ${received} bytes, expected ${expectedSize}`));
        } else {
          process.stdout.write(`Downloaded ${basename(destination)} (${received} bytes).\n`);
          resolveDownload();
        }
      });
      response.on("error", (error) => {
        try { closeSync(handle); } catch {}
        rejectDownload(error);
      });
    });
    request.setTimeout(30_000, () => request.destroy(new Error("download timed out")));
    request.on("error", rejectDownload);
  });
}

function run(command, arguments_, options = {}) {
  const result = spawnSync(command, arguments_, {
    cwd: options.cwd ?? repository,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    timeout: options.timeout ?? 600_000,
  });
  if (result.error) fail(`${options.step ?? command} could not start: ${result.error.message}`);
  if (result.status !== 0) {
    const detail = options.capture ? (result.stderr || result.stdout || "").trim() : "";
    fail(`${options.step ?? command} failed with status ${result.status}.${detail ? ` ${detail}` : ""}`);
  }
  return result;
}

function validateTarListing(archive) {
  const listing = run("/usr/bin/tar", ["-tzf", archive], {
    capture: true,
    step: "Archive validation",
    timeout: 30_000,
  }).stdout.split("\n").filter(Boolean);
  if (listing.length === 0 || listing.length > 100) fail("uv archive has an invalid entry count.");
  for (const name of listing) {
    if (name.startsWith("/") || name.includes("\\") || name.split("/").includes("..")) {
      fail(`uv archive contains an unsafe path: ${name}`);
    }
  }
  const verbose = run("/usr/bin/tar", ["-tvzf", archive], {
    capture: true,
    step: "Archive link validation",
    timeout: 30_000,
  }).stdout.split("\n").filter(Boolean);
  if (verbose.some((line) => ["l", "h"].includes(line[0]))) {
    fail("uv archive contains a link entry; extraction was refused.");
  }
}

function findNamedFile(root, name) {
  const queue = [root];
  let visited = 0;
  while (queue.length > 0) {
    const directory = queue.shift();
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      visited += 1;
      if (visited > 100) fail("uv archive expanded to too many entries.");
      const candidate = join(directory, entry.name);
      if (entry.isSymbolicLink()) fail(`uv archive extracted a symbolic link: ${candidate}`);
      if (entry.isDirectory()) queue.push(candidate);
      else if (entry.isFile() && entry.name === name) return candidate;
    }
  }
  return null;
}

async function ensureUv(home) {
  const target = targetFor("uv", "host");
  const version = manifest.uv.version;
  const install = join(home, "bin", "uv", version, `${platform()}-${arch()}`);
  const executable = join(install, target.executable);
  assertContained(home, executable);
  if (existsSync(executable)) {
    const check = spawnSync(executable, ["--version"], { encoding: "utf8", timeout: 10_000 });
    if (check.status === 0 && check.stdout.includes(`uv ${version}`)) return executable;
  }

  mkdirSync(join(home, "cache", "downloads"), { recursive: true, mode: 0o700 });
  mkdirSync(dirname(install), { recursive: true, mode: 0o700 });
  const archive = join(home, "cache", "downloads", target.archive.name);
  const partial = `${archive}.partial`;
  rmSync(partial, { force: true });
  if (
    !existsSync(archive) ||
    statSync(archive).size !== target.archive.size ||
    sha256(archive) !== target.archive.sha256
  ) {
    rmSync(archive, { force: true });
    try {
      await download(target.archive.url, partial, target.archive.size);
    } catch (error) {
      rmSync(partial, { force: true });
      fail(`uv download failed: ${error.message}. Existing installations were not changed.`);
    }
    if (sha256(partial) !== target.archive.sha256) {
      rmSync(partial, { force: true });
      fail("uv archive checksum did not match the pinned upstream checksum.");
    }
    renameSync(partial, archive);
  }
  validateTarListing(archive);
  const staging = mkdtempSync(join(dirname(install), ".uv-install-"));
  try {
    run("/usr/bin/tar", ["-xzf", archive, "-C", staging], {
      step: "uv archive extraction",
      timeout: 30_000,
    });
    const extracted = findNamedFile(staging, target.executable);
    if (!extracted) fail("uv archive did not contain the expected executable.");
    const prepared = `${install}.prepared-${process.pid}`;
    rmSync(prepared, { recursive: true, force: true });
    mkdirSync(prepared, { recursive: true, mode: 0o700 });
    copyFileSync(extracted, join(prepared, target.executable));
    chmodSync(join(prepared, target.executable), 0o755);
    run(join(prepared, target.executable), ["--version"], {
      capture: true,
      step: "uv capability validation",
      timeout: 10_000,
    });
    rmSync(install, { recursive: true, force: true });
    renameSync(prepared, install);
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  return executable;
}

function managedEnvironment(home, uv) {
  return {
    ...process.env,
    KNEMORA_HOME: home,
    KNEMORA_MANAGED_UV: uv,
    UV_CACHE_DIR: join(home, "cache", "uv"),
    UV_PYTHON_INSTALL_DIR: join(home, "python"),
    UV_TOOL_DIR: join(home, "cache", "uv-tools"),
    UV_TOOL_BIN_DIR: join(home, "bin", "uv-tools"),
    UV_MANAGED_PYTHON: "1",
  };
}

function bootstrapFingerprint() {
  const digest = createHash("sha256");
  for (const path of [
    manifestPath,
    join(repository, "apps", "api", "pyproject.toml"),
    join(repository, "apps", "api", "uv.lock"),
  ]) digest.update(readFileSync(path));
  digest.update(repository);
  return digest.digest("hex");
}

function venvIsManaged(home, fingerprint) {
  const statePath = join(home, "runtime", "bootstrap.json");
  const python = join(repository, "apps", "api", ".venv", "bin", "python");
  try {
    const state = JSON.parse(readFileSync(statePath, "utf8"));
    const realPython = realpathSync(python);
    const managedRoot = realpathSync(join(home, "python"));
    const version = spawnSync(python, ["--version"], { encoding: "utf8", timeout: 10_000 });
    return (
      state.formatVersion === 1 &&
      state.fingerprint === fingerprint &&
      state.pythonVersion === manifest.python.version &&
      (realPython === managedRoot || realPython.startsWith(`${managedRoot}${sep}`)) &&
      version.status === 0 &&
      `${version.stdout}${version.stderr}`.includes(`Python ${manifest.python.version}`)
    );
  } catch {
    return false;
  }
}

function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.tmp-${process.pid}`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporary, path);
}

function preparePython(home, uv) {
  const fingerprint = bootstrapFingerprint();
  if (venvIsManaged(home, fingerprint)) return;
  const env = managedEnvironment(home, uv);
  mkdirSync(env.UV_CACHE_DIR, { recursive: true, mode: 0o700 });
  mkdirSync(env.UV_PYTHON_INSTALL_DIR, { recursive: true, mode: 0o700 });
  run(
    uv,
    [
      "python",
      "install",
      manifest.python.version,
      "--managed-python",
      "--no-bin",
      "--install-dir",
      env.UV_PYTHON_INSTALL_DIR,
    ],
    { env, step: `Managed CPython ${manifest.python.version} installation` },
  );
  const api = join(repository, "apps", "api");
  const venv = join(api, ".venv");
  const legacy = `${venv}.legacy-${process.pid}`;
  if (existsSync(venv)) renameSync(venv, legacy);
  try {
    run(
      uv,
      [
        "sync",
        "--frozen",
        "--dev",
        "--python",
        manifest.python.version,
        "--managed-python",
      ],
      { cwd: api, env, step: "Locked Python dependency installation" },
    );
    atomicJson(join(home, "runtime", "bootstrap.json"), {
      formatVersion: 1,
      fingerprint,
      pythonVersion: manifest.python.version,
      repository,
    });
    rmSync(legacy, { recursive: true, force: true });
  } catch (error) {
    rmSync(venv, { recursive: true, force: true });
    if (existsSync(legacy)) renameSync(legacy, venv);
    throw error;
  }
}

function recordBootstrapRuntime(home, uv) {
  const path = join(home, "config", "runtime.json");
  let metadata = { formatVersion: 1, components: {} };
  if (existsSync(path)) {
    try {
      metadata = JSON.parse(readFileSync(path, "utf8"));
    } catch (error) {
      fail(`Runtime metadata is unreadable: ${path}: ${error.message}`);
    }
    if (metadata.formatVersion !== 1 || typeof metadata.components !== "object") {
      fail(`Runtime metadata format is unsupported: ${path}`);
    }
  }
  const target = targetFor("uv", "host");
  const uvIdentity = `uv-${manifest.uv.version}-${platform()}-${arch()}`;
  const pythonIdentity = `cpython-${manifest.python.version}-${platform()}-${arch()}`;
  if (
    metadata.components.uv?.activeInstallationId === uvIdentity &&
    metadata.components.python?.activeInstallationId === pythonIdentity
  ) {
    return;
  }
  const installedAt = new Date().toISOString();
  metadata.components.uv = {
    activeInstallationId: uvIdentity,
    component: "uv",
    version: manifest.uv.version,
    upstreamRelease: manifest.uv.source,
    platform: platform(),
    architecture: arch(),
    backend: "host",
    archive: target.archive.name,
    archiveSize: target.archive.size,
    expectedSha256: target.archive.sha256,
    verifiedSha256: target.archive.sha256,
    executableRelativePath: relative(home, uv),
    verifiedAt: installedAt,
  };
  metadata.components.python = {
    activeInstallationId: pythonIdentity,
    component: "cpython",
    version: manifest.python.version,
    upstreamRelease: "Astral uv managed CPython distributions",
    platform: platform(),
    architecture: arch(),
    backend: "managed-python",
    rootRelativePath: "python",
    verification: "version pinned; artifact identity and checksum verified by pinned uv",
    verifiedAt: installedAt,
  };
  atomicJson(path, metadata);
}

function delegate(home, uv) {
  const python = join(repository, "apps", "api", ".venv", "bin", "python");
  const env = managedEnvironment(home, uv);
  env.KNEMORA_REPOSITORY_ROOT = repository;
  env.PYTHONPATH = [join(repository, "apps", "api"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(":");
  const result = spawnSync(python, ["-m", "knemora_bootstrap", ...process.argv.slice(2)], {
    cwd: repository,
    env,
    stdio: "inherit",
  });
  if (result.error) fail(`managed Python handoff failed: ${result.error.message}`);
  process.exit(result.status ?? 2);
}

checkNodeAndNpm();
const home = configuredHome();
const preflight = readHomePreflight(home);
const requestedCommand = commandName(process.argv.slice(2));
const fingerprint = bootstrapFingerprint();
if (
  preflight.status === "migration-needed" &&
  requestedCommand !== "setup" &&
  !diagnosticCommands.has(requestedCommand)
) {
  fail("Application-home migration is required. Run ./knemora setup before this command.");
}
if (diagnosticCommands.has(requestedCommand) && !venvIsManaged(home, fingerprint)) {
  process.stdout.write(
    `home compatibility: ${preflight.status}; managed diagnostics require ./knemora setup\n`,
  );
  process.exit(preflight.status === "ready" ? 1 : 2);
}
mkdirSync(home, { recursive: true, mode: 0o700 });
const uv = await ensureUv(home);
preparePython(home, uv);
recordBootstrapRuntime(home, uv);
delegate(home, uv);
