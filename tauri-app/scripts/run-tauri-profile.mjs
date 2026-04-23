import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const tauriAppDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(tauriAppDir, "..");

function sanitizeProfile(value) {
  const cleaned = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");

  return cleaned || "default";
}

const profile = sanitizeProfile(
  process.env.VITE_INTERVIEW_COACH_PROFILE || process.env.INTERVIEW_COACH_PROFILE || "default"
);
const runtimeRoot = path.join(repoRoot, ".runtime", "profiles", profile);
const cargoTargetDir = process.env.CARGO_TARGET_DIR || path.join(runtimeRoot, "tauri-target");

fs.mkdirSync(cargoTargetDir, { recursive: true });

const env = {
  ...process.env,
  CARGO_TARGET_DIR: cargoTargetDir,
  INTERVIEW_COACH_PROFILE: profile,
  VITE_INTERVIEW_COACH_PROFILE: profile,
};

const args = process.argv.slice(2);
const tauriArgs = args.length > 0 ? args : ["dev"];
const command = process.platform === "win32" ? "npx.cmd" : "npx";

const child = spawn(command, ["tauri", ...tauriArgs], {
  cwd: tauriAppDir,
  env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
