#!/usr/bin/env node
/**
 * hooks/subway-bash-read.cjs
 *
 * PreToolUse hook for Claude Code (Bash) and Antigravity (run_command).
 * Intercepts naked file reads (`cat`, `head`, `tail`, `less`, `more`) on files
 * exceeding $SUBWAY_MIN_LINES (default: 350) and redirects to `subway read`.
 *
 * Piped commands (`cat file | grep`) and redirections (`cat file > out`) pass through.
 * Uses `../lib/resolve-command.cjs` for robust quote-aware command resolution.
 * Fails open if no GEMINI_API_KEY is configured or if subway CLI is absent.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { execSync } = require("child_process");
const { resolveCommand } = require("../lib/resolve-command.cjs");

function hasGeminiKey(projectDir) {
  if (process.env.GEMINI_API_KEY && process.env.GEMINI_API_KEY.trim()) {
    return true;
  }

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

  const claudeSettings = path.join(os.homedir(), ".claude", "settings.json");
  try {
    if (fs.existsSync(claudeSettings)) {
      const parsed = JSON.parse(fs.readFileSync(claudeSettings, "utf8"));
      if (parsed?.env?.GEMINI_API_KEY?.trim()) {
        return true;
      }
    }
  } catch {}

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
  const repoBin = path.resolve(__dirname, "..", "bin", "subway");
  if (fs.existsSync(repoBin)) {
    return repoBin;
  }

  if (projectDir) {
    const localScript = path.join(projectDir, "scripts", "subway");
    if (fs.existsSync(localScript)) {
      return "scripts/subway";
    }
  }

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

const READ_COMMANDS = new Set(["cat", "head", "tail", "less", "more"]);
const FLAG_WITH_VALUE = new Set(["-n", "-c", "-s", "--lines", "--bytes"]);

function parseCount(value) {
  const match = /^([+-]?)(\d+)$/.exec(value || "");
  if (!match) {
    return null;
  }

  const count = Number(match[2]);
  if (!Number.isSafeInteger(count)) {
    return null;
  }

  return { sign: match[1], count };
}

function requestedOutput(command, args, fileLines) {
  let unit = "lines";
  let parsedCount = { sign: "", count: 10 };
  let optionsEnded = false;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (arg === "--") {
      optionsEnded = true;
      continue;
    }
    if (optionsEnded) {
      continue;
    }

    if (
      arg === "-f" ||
      arg === "-F" ||
      arg === "--follow" ||
      arg.startsWith("--follow=") ||
      arg === "-z" ||
      arg === "--zero-terminated"
    ) {
      return null;
    }

    let value = null;
    if (["-n", "--lines", "-c", "--bytes"].includes(arg)) {
      if (i + 1 >= args.length) {
        return null;
      }
      unit = arg === "-c" || arg === "--bytes" ? "bytes" : "lines";
      value = args[++i];
    } else if (arg.startsWith("--lines=")) {
      unit = "lines";
      value = arg.slice("--lines=".length);
    } else if (arg.startsWith("--bytes=")) {
      unit = "bytes";
      value = arg.slice("--bytes=".length);
    } else if (/^-n.+/.test(arg)) {
      unit = "lines";
      value = arg.slice(2);
    } else if (/^-c.+/.test(arg)) {
      unit = "bytes";
      value = arg.slice(2);
    } else if (/^-\d+$/.test(arg)) {
      unit = "lines";
      value = arg.slice(1);
    } else if (command === "tail" && /^\+\d+$/.test(arg)) {
      unit = "lines";
      value = arg;
    } else {
      continue;
    }

    parsedCount = parseCount(value);
    if (!parsedCount) {
      return null;
    }
  }

  // A byte bound of N can emit at most N newline-delimited lines. Treating N
  // as the line bound is conservative without reading or decoding the file a
  // second time. Relative byte positions can emit the rest of the file, so
  // keep treating those as potentially unbounded.
  if (unit === "bytes") {
    if (
      (command === "head" && parsedCount.sign === "-") ||
      (command === "tail" && parsedCount.sign === "+")
    ) {
      return null;
    }
    return parsedCount.count;
  }

  if (command === "head") {
    if (parsedCount.sign === "-") {
      return Math.max(fileLines - parsedCount.count, 0);
    }
    return Math.min(parsedCount.count, fileLines);
  }

  if (parsedCount.sign === "+") {
    return Math.max(fileLines - parsedCount.count + 1, 0);
  }
  return Math.min(parsedCount.count, fileLines);
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
  const cmd = (toolInput.command || toolInput.CommandLine || "").trim();

  if (!cmd) {
    process.exit(0);
  }

  // Allow piped commands and redirections
  if (/[|>]/.test(cmd)) {
    process.exit(0);
  }

  // Fail-open: if no Gemini key is configured, allow normal execution
  if (!hasGeminiKey(projectDir)) {
    process.exit(0);
  }

  const subwayCmd = resolveSubwayCmd(projectDir);
  if (!subwayCmd) {
    process.exit(0);
  }

  let minLines = parseInt(
    process.env.SUBWAY_MIN_LINES || process.env.SHUNT_MIN_LINES || "350",
    10
  );
  if (isNaN(minLines) || minLines < 1) {
    minLines = 350;
  }

  const { segments } = resolveCommand(cmd);

  for (const segment of segments) {
    if (!READ_COMMANDS.has(segment.command)) {
      continue;
    }

    const args = segment.args || [];
    for (let i = 0; i < args.length; i++) {
      const arg = args[i];
      if (FLAG_WITH_VALUE.has(arg)) {
        i++; // skip flag value
        continue;
      }
      if (arg.startsWith("-")) {
        continue;
      }

      const resolvedPath = path.isAbsolute(arg)
        ? arg
        : path.resolve(projectDir, arg);

      if (fs.existsSync(resolvedPath) && fs.statSync(resolvedPath).isFile()) {
        const lines = countLines(resolvedPath);
        const outputLines =
          segment.command === "head" || segment.command === "tail"
            ? requestedOutput(segment.command, args, lines)
            : null;
        if (lines > minLines && (outputLines === null || outputLines > minLines)) {
          const relativePath = path.relative(projectDir, resolvedPath);
          const reason =
            `File is ${lines} lines (threshold: ${minLines}). ` +
            `Route this read through the Subway instead of ${segment.command}: ` +
            `${subwayCmd} read --question "<what you want to know>" --paths "${relativePath}".`;

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
      }
    }
  }

  process.exit(0);
}

main().catch(() => process.exit(0));
