#!/usr/bin/env node
/**
 * hooks/subway-file-size.cjs
 *
 * PreToolUse hook for Claude Code (Read) and Antigravity (view_file).
 * Intercepts full file reads on files exceeding $SUBWAY_MIN_LINES (default: 350)
 * and redirects the agent to `subway read` (Gemini Flash), keeping heavy
 * payloads out of the primary agent's context window.
 *
 * Targeted reads (offset/limit or StartLine/EndLine slices <= threshold) pass through.
 * Fails open if no GEMINI_API_KEY is configured or if subway CLI is absent.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { execSync } = require("child_process");

function hasGeminiKey(projectDir) {
  if (process.env.GEMINI_API_KEY && process.env.GEMINI_API_KEY.trim()) {
    return true;
  }

  // Check ~/.config/subway/api_key and ~/.config/pinpoint/gemini_api_key
  const configPaths = [
    path.join(os.homedir(), ".config", "subway", "api_key"),
    path.join(os.homedir(), ".config", "pinpoint", "gemini_api_key"),
  ];
  for (const cp of configPaths) {
    try {
      if (fs.existsSync(cp) && fs.readFileSync(cp, "utf8").trim()) {
        return true;
      }
    } catch {}
  }

  // Global Claude settings
  const claudeSettings = path.join(os.homedir(), ".claude", "settings.json");
  try {
    if (fs.existsSync(claudeSettings)) {
      const parsed = JSON.parse(fs.readFileSync(claudeSettings, "utf8"));
      if (parsed?.env?.GEMINI_API_KEY?.trim()) {
        return true;
      }
    }
  } catch {}

  // Local project .env.local or .env
  if (projectDir) {
    for (const envName of [".env.local", ".env"]) {
      const envPath = path.join(projectDir, envName);
      try {
        if (fs.existsSync(envPath)) {
          const content = fs.readFileSync(envPath, "utf8");
          if (/^\s*GEMINI_API_KEY\s*=\s*['"]?[^'"\n]+/m.test(content)) {
            return true;
          }
        }
      } catch {}
    }
  }

  return false;
}

function resolveSubwayCmd(projectDir) {
  // 1. Local bin in subway repo
  const repoBin = path.resolve(__dirname, "..", "bin", "subway");
  if (fs.existsSync(repoBin)) {
    return repoBin;
  }

  // 2. Project-local scripts/subway
  if (projectDir) {
    const localScript = path.join(projectDir, "scripts", "subway");
    if (fs.existsSync(localScript)) {
      return "scripts/subway";
    }
  }

  // 3. System PATH / ~/.local/bin
  const localBin = path.join(os.homedir(), ".local", "bin", "subway");
  if (fs.existsSync(localBin)) {
    return "subway";
  }

  try {
    execSync("which subway", { stdio: "ignore" });
    return "subway";
  } catch {
    return null;
  }
}

function countLines(filePath) {
  try {
    const buffer = fs.readFileSync(filePath);
    let count = 0;
    for (let i = 0; i < buffer.length; i++) {
      if (buffer[i] === 10) count++;
    }
    if (buffer.length > 0 && buffer[buffer.length - 1] !== 10) {
      count++;
    }
    return count;
  } catch {
    return 0;
  }
}

async function main() {
  let inputData = "";
  for await (const chunk of process.stdin) {
    inputData += chunk;
  }

  if (!inputData.trim()) {
    process.exit(0);
  }

  let input;
  try {
    input = JSON.parse(inputData);
  } catch {
    process.exit(0);
  }

  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const toolInput = input.tool_input || input.toolCall?.args || {};
  const rawPath = toolInput.file_path || toolInput.path || toolInput.AbsolutePath;

  let minLines = parseInt(
    process.env.SUBWAY_MIN_LINES || process.env.SHUNT_MIN_LINES || "350",
    10
  );
  if (isNaN(minLines) || minLines < 1) {
    minLines = 350;
  }

  // Allow targeted reads:
  // - offset or limit is specified
  // - or StartLine/EndLine slice is smaller than minLines
  if (toolInput.offset != null || toolInput.limit != null) {
    process.exit(0);
  }
  if (toolInput.StartLine != null && toolInput.EndLine != null) {
    const range = Math.abs(toolInput.EndLine - toolInput.StartLine);
    if (range <= minLines) {
      process.exit(0);
    }
  }

  if (!rawPath) {
    process.exit(0);
  }

  const resolvedPath = path.isAbsolute(rawPath)
    ? rawPath
    : path.resolve(projectDir, rawPath);

  if (!fs.existsSync(resolvedPath) || !fs.statSync(resolvedPath).isFile()) {
    process.exit(0);
  }

  // Fail-open: if no Gemini key is configured, allow normal read
  if (!hasGeminiKey(projectDir)) {
    process.exit(0);
  }

  // Fail-open: check if subway executable can be located
  const subwayCmd = resolveSubwayCmd(projectDir);
  if (!subwayCmd) {
    process.exit(0);
  }

  const lines = countLines(resolvedPath);
  if (lines <= minLines) {
    process.exit(0);
  }

  const relativePath = path.relative(projectDir, resolvedPath);
  const reason =
    `File is ${lines} lines (threshold: ${minLines}). ` +
    `Route this read through the Subway to save context tokens: ` +
    `${subwayCmd} read --question "<what you want to know>" --paths "${relativePath}". ` +
    `If you need exact content for editing, re-read with offset/limit (or StartLine/EndLine) for just the section you need.`;

  const output = {
    decision: "deny",
    reason,
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };

  process.stdout.write(JSON.stringify(output));
  process.exit(0);
}

main().catch(() => process.exit(0));
