import React, { useState } from "react";
import { createSession, stopSession, SessionInfo } from "../services/api";

interface SessionPanelProps {
  onSessionCreated: (session: SessionInfo) => void;
  currentSession: SessionInfo | null;
}

/**
 * Session management panel.
 *
 * Allows users to:
 * - Login with a user ID to create/resume a session
 * - View their session details and mount points
 * - Stop their session (persists session storage)
 *
 * Each user gets their own isolated session with:
 * - Private /mnt/workspace (session storage)
 * - Shared /mnt/datasets (EFS)
 * - Shared /mnt/tools (S3 Files)
 */
export default function SessionPanel({
  onSessionCreated,
  currentSession,
}: SessionPanelProps) {
  const [userId, setUserId] = useState("");
  const [sessionName, setSessionName] = useState("default");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async () => {
    if (!userId.trim()) return;
    setIsLoading(true);
    setError("");
    try {
      const session = await createSession(userId.trim(), sessionName);
      onSessionCreated(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session");
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    if (!currentSession) return;
    setIsLoading(true);
    try {
      await stopSession(currentSession.session_id);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop session");
    } finally {
      setIsLoading(false);
    }
  };

  if (!currentSession) {
    return (
      <div style={styles.loginContainer}>
        <div style={styles.loginCard}>
          <h2 style={styles.loginTitle}>🚀 AgentCore Runtime</h2>
          <p style={styles.loginSubtitle}>
            Hybrid Filesystem Demo — Multi-User Shell Access
          </p>

          <div style={styles.storagePreview}>
            <div style={styles.storageItem}>
              <span style={{ color: "#a6e3a1" }}>📁 /mnt/workspace</span>
              <span style={styles.storageDesc}>
                Session Storage — Private per user
              </span>
            </div>
            <div style={styles.storageItem}>
              <span style={{ color: "#89b4fa" }}>📊 /mnt/datasets</span>
              <span style={styles.storageDesc}>
                EFS — Shared across all users
              </span>
            </div>
            <div style={styles.storageItem}>
              <span style={{ color: "#f9e2af" }}>🔧 /mnt/tools</span>
              <span style={styles.storageDesc}>
                S3 Files — Shared tools (synced with S3)
              </span>
            </div>
          </div>

          <div style={styles.form}>
            <label style={styles.label}>User ID</label>
            <input
              type="text"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              placeholder="e.g., alice, bob, charlie"
              style={styles.input}
              autoFocus
            />
            <div style={styles.examples}>
              {["alice", "bob", "charlie"].map((name) => (
                <button
                  key={name}
                  onClick={() => setUserId(name)}
                  style={styles.exampleBtn}
                >
                  {name}
                </button>
              ))}
            </div>

            <label style={styles.label}>Session Name</label>
            <input
              type="text"
              value={sessionName}
              onChange={(e) => setSessionName(e.target.value)}
              placeholder="default"
              style={styles.input}
            />
            <div style={styles.examples}>
              {["default", "dev", "experiment"].map((name) => (
                <button
                  key={name}
                  onClick={() => setSessionName(name)}
                  style={styles.exampleBtn}
                >
                  {name}
                </button>
              ))}
            </div>

            <button
              onClick={handleLogin}
              disabled={isLoading || !userId.trim()}
              style={styles.loginBtn}
            >
              {isLoading ? "Connecting..." : "Connect to Runtime"}
            </button>
          </div>

          {error && <div style={styles.error}>{error}</div>}

          <p style={styles.hint}>
            Try logging in as different users (e.g., "alice" and "bob") in
            separate tabs to see isolated session storage but shared EFS/S3.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.sessionInfo}>
      <div style={styles.sessionHeader}>
        <span style={styles.userBadge}>👤 {currentSession.user_id}</span>
        <span style={styles.statusBadge}>● {currentSession.status}</span>
      </div>
      <div style={styles.sessionDetails}>
        <div style={styles.detailRow}>
          <span style={styles.detailLabel}>Session:</span>
          <code style={styles.detailValue}>
            {currentSession.session_id.slice(0, 24)}...
          </code>
        </div>
        <div style={styles.detailRow}>
          <span style={styles.detailLabel}>Name:</span>
          <span style={styles.detailValue}>{currentSession.session_name}</span>
        </div>
      </div>
      <button onClick={handleStop} style={styles.stopBtn} disabled={isLoading}>
        ⏹ Stop Session
      </button>
      {error && <div style={styles.error}>{error}</div>}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  loginContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    background: "#11111b",
  },
  loginCard: {
    background: "#1e1e2e",
    borderRadius: 12,
    padding: 32,
    width: 420,
    border: "1px solid #313244",
  },
  loginTitle: {
    color: "#cdd6f4",
    margin: "0 0 4px 0",
    fontSize: 22,
  },
  loginSubtitle: {
    color: "#6c7086",
    margin: "0 0 20px 0",
    fontSize: 13,
  },
  storagePreview: {
    background: "#181825",
    borderRadius: 8,
    padding: 12,
    marginBottom: 20,
  },
  storageItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "4px 0",
    fontFamily: "monospace",
    fontSize: 12,
  },
  storageDesc: {
    color: "#6c7086",
    fontSize: 11,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  label: {
    color: "#a6adc8",
    fontSize: 12,
    fontWeight: 500,
  },
  input: {
    background: "#313244",
    border: "1px solid #45475a",
    borderRadius: 6,
    padding: "8px 12px",
    color: "#cdd6f4",
    fontSize: 14,
    outline: "none",
  },
  loginBtn: {
    background: "#89b4fa",
    border: "none",
    borderRadius: 6,
    padding: "10px 16px",
    color: "#1e1e2e",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
    marginTop: 8,
  },
  examples: {
    display: "flex",
    gap: 6,
    marginTop: 2,
  },
  exampleBtn: {
    background: "#313244",
    border: "1px solid #45475a",
    borderRadius: 4,
    padding: "3px 8px",
    color: "#89b4fa",
    fontSize: 11,
    cursor: "pointer",
  },
  error: {
    color: "#f38ba8",
    fontSize: 12,
    marginTop: 8,
    padding: 8,
    background: "#f38ba811",
    borderRadius: 4,
  },
  hint: {
    color: "#6c7086",
    fontSize: 11,
    marginTop: 16,
    textAlign: "center",
    lineHeight: 1.4,
  },
  sessionInfo: {
    padding: 12,
    background: "#181825",
    borderBottom: "1px solid #313244",
  },
  sessionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  userBadge: {
    color: "#cdd6f4",
    fontWeight: 600,
    fontSize: 14,
  },
  statusBadge: {
    color: "#a6e3a1",
    fontSize: 12,
  },
  sessionDetails: {
    marginBottom: 8,
  },
  detailRow: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    marginBottom: 2,
  },
  detailLabel: {
    color: "#6c7086",
    fontSize: 11,
    minWidth: 60,
  },
  detailValue: {
    color: "#a6adc8",
    fontSize: 11,
  },
  stopBtn: {
    background: "#45475a",
    border: "none",
    borderRadius: 4,
    padding: "4px 10px",
    color: "#f38ba8",
    fontSize: 11,
    cursor: "pointer",
  },
};
