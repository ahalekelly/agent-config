import { isToolCallEventType, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const blockReason = "Blocked: do not delete files with rm. Use the trash command instead, e.g. `trash path/to/file`.";

function shellTokens(command: string): string[] {
  const matches = command.match(/'[^']*'|"(?:\\.|[^"])*"|[^\s;&|()`]+|[;&|()`]/g);
  return matches ?? [];
}

function unquote(token: string): string {
  if ((token.startsWith("'") && token.endsWith("'")) || (token.startsWith('"') && token.endsWith('"'))) {
    return token.slice(1, -1);
  }
  return token;
}

function isRmToken(token: string): boolean {
  return unquote(token).split("/").at(-1) === "rm";
}

function containsRm(command: string): boolean {
  let commandStart = true;
  let previous = "";
  const wrappers = new Set(["command", "sudo", "env", "time", "xargs", "-exec", "-execdir", "-c"]);
  const separators = new Set([";", "&", "&&", "|", "||", "(", ")", "`"]);

  for (const token of shellTokens(command)) {
    const base = unquote(token).split("/").at(-1) ?? "";
    if (separators.has(token)) commandStart = true;
    else if (isRmToken(token) && (commandStart || wrappers.has(previous))) return true;
    else if (previous === "-c" && /^\s*(\/[^\s;&|()`]+\/)?rm\b/.test(unquote(token))) return true;
    else if (commandStart && token.includes("=") && !token.startsWith("=")) commandStart = true;
    else commandStart = wrappers.has(base);
    previous = base;
  }

  return false;
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", (event) => {
    if (!isToolCallEventType("bash", event)) return undefined;
    if (!containsRm(event.input.command)) return undefined;
    return { block: true, reason: blockReason };
  });
}
