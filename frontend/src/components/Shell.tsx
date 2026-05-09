import React, { useState, useRef, useEffect } from "react";
import { executeCommand, CommandResult } from "../services/api";

interface ShellProps {
  sessionId: string;
  userId: string;
}

interface HistoryEntry {
  command: string;
  result: CommandResult;
  timestamp: Date;
}

/**
 * Interactive shell component that executes commands in the user's
 * AgentCore Runtime session via InvokeAgentRuntimeCommand.
 *
 * Each command runs in the same microVM container with access to:
 * - /mnt/workspace (session storage - private)
 * - /mnt/datasets (EFS - shared)
 * - /mnt/tools (S3 Files - shared)
 */
export default function Shell({ sessionId, userId }: ShellProps) {
  const [command, setCommand] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    outputRef.current?.scrollTo(0, outputRef.current.scrollHeight);
  }, [history]);

  const handleExecute = async () => {
    if (!command.trim() || isExecuting) return;

    const cmd = command.trim();
    setCommand("");
    setCommandHistory((prev) => [...prev, cmd]);
    setHistoryIndex(-1);
    setIsExecuting(true);

    try {
      const result = await executeCommand(sessionId, cmd);
      setHistory((prev) => [
        ...prev,
        { command: cmd, result, timestamp: new Date() },
      ]);
    } catch (err) {
      setHistory((prev) => [
        ...prev,
        {
          command: cmd,
          result: {
            stdout: "",
            stderr: err instanceof Error ? err.message : "Unknown error",
            exit_code: -1,
            status: "ERROR",
          },
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsExecuting(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleExecute();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (commandHistory.length > 0) {
        const newIndex =
          historyIndex === -1
            ? commandHistory.length - 1
            : Math.max(0, historyIndex - 1);
        setHistoryIndex(newIndex);
        setCommand(commandHistory[newIndex]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex >= 0) {
        const newIndex = historyIndex + 1;
        if (newIndex >= commandHistory.length) {
          setHistoryIndex(-1);
          setCommand("");
        } else {
          setHistoryIndex(newIndex);
          setCommand(commandHistory[newIndex]);
        }
      }
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerTitle}>
          🖥️ Shell — {userId}@agentcore-runtime
        </span>
        <span style={styles.sessionBadge}>Session: {sessionId.slice(0, 20)}...</span>
      </div>

      <div ref={outputRef} style={styles.output}>
        <div style={styles.welcomeMsg}>
          AgentCore Runtime Shell — Hybrid Filesystem Mode
          <br />
          ├── /mnt/workspace (Session Storage - YOUR private files)
          <br />
          ├── /mnt/datasets  (EFS - shared datasets, all users)
          <br />
          └── /mnt/tools     (S3 Files - shared tools, all users)
          <br />
          <br />
          Type commands to execute in your AgentCore Runtime session.
          <br />
          Each command runs via InvokeAgentRuntimeCommand API.
          <br />
        </div>

        {history.map((entry, i) => (
          <div key={i} style={styles.entry}>
            <div style={styles.prompt}>
              <span style={styles.promptUser}>{userId}@runtime</span>
              <span style={styles.promptSep}>:</span>
              <span style={styles.promptPath}>~</span>
              <span style={styles.promptDollar}>$ </span>
              <span style={styles.promptCmd}>{entry.command}</span>
            </div>
            {entry.result.stdout && (
              <pre style={styles.stdout}>{entry.result.stdout}</pre>
            )}
            {entry.result.stderr && (
              <pre style={styles.stderr}>{entry.result.stderr}</pre>
            )}
            <div style={styles.exitCode}>
              [{entry.result.status === "COMPLETED" ? "✓" : "✗"} exit:{" "}
              {entry.result.exit_code}]
            </div>
          </div>
        ))}

        {isExecuting && (
          <div style={styles.executing}>⏳ Executing...</div>
        )}
      </div>

      <div style={styles.inputRow}>
        <span style={styles.inputPrompt}>{userId}@runtime:~$ </span>
        <input
          ref={inputRef}
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter command (e.g., ls /mnt/workspace)"
          disabled={isExecuting}
          style={styles.input}
          autoFocus
        />
      </div>

      <div style={styles.quickCommands}>
        <span style={styles.quickLabel}>Quick:</span>
        {[
          "ls /mnt/workspace",
          "ls /mnt/datasets",
          "ls /mnt/tools",
          "df -h /mnt/workspace /mnt/datasets /mnt/tools",
          "echo 'hello' > /mnt/workspace/test.txt",
          "cat /mnt/workspace/test.txt",
        ].map((cmd) => (
          <button
            key={cmd}
            onClick={() => {
              setCommand(cmd);
              inputRef.current?.focus();
            }}
            style={styles.quickBtn}
          >
            {cmd.length > 30 ? cmd.slice(0, 30) + "..." : cmd}
          </button>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    background: "#1e1e2e",
    borderRadius: 8,
    overflow: "hidden",
    border: "1px solid #313244",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "8px 12px",
    background: "#181825",
    borderBottom: "1px solid #313244",
  },
  headerTitle: {
    color: "#cdd6f4",
    fontWeight: 600,
    fontSize: 13,
  },
  sessionBadge: {
    color: "#6c7086",
    fontSize: 11,
    fontFamily: "monospace",
  },
  output: {
    flex: 1,
    overflow: "auto",
    padding: 12,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    fontSize: 13,
    lineHeight: 1.5,
  },
  welcomeMsg: {
    color: "#6c7086",
    marginBottom: 12,
    fontStyle: "italic",
  },
  entry: {
    marginBottom: 8,
  },
  prompt: {
    color: "#cdd6f4",
  },
  promptUser: {
    color: "#a6e3a1",
    fontWeight: 600,
  },
  promptSep: {
    color: "#cdd6f4",
  },
  promptPath: {
    color: "#89b4fa",
    fontWeight: 600,
  },
  promptDollar: {
    color: "#cdd6f4",
  },
  promptCmd: {
    color: "#f5e0dc",
  },
  stdout: {
    color: "#cdd6f4",
    margin: "2px 0",
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
  },
  stderr: {
    color: "#f38ba8",
    margin: "2px 0",
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
  },
  exitCode: {
    color: "#6c7086",
    fontSize: 11,
  },
  executing: {
    color: "#f9e2af",
    animation: "pulse 1s infinite",
  },
  inputRow: {
    display: "flex",
    alignItems: "center",
    padding: "8px 12px",
    background: "#11111b",
    borderTop: "1px solid #313244",
  },
  inputPrompt: {
    color: "#a6e3a1",
    fontFamily: "monospace",
    fontSize: 13,
    whiteSpace: "nowrap",
  },
  input: {
    flex: 1,
    background: "transparent",
    border: "none",
    outline: "none",
    color: "#cdd6f4",
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    fontSize: 13,
    marginLeft: 4,
  },
  quickCommands: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    padding: "6px 12px",
    background: "#181825",
    borderTop: "1px solid #313244",
    alignItems: "center",
  },
  quickLabel: {
    color: "#6c7086",
    fontSize: 11,
    marginRight: 4,
  },
  quickBtn: {
    background: "#313244",
    border: "none",
    borderRadius: 4,
    color: "#89b4fa",
    fontSize: 11,
    padding: "2px 6px",
    cursor: "pointer",
    fontFamily: "monospace",
  },
};
