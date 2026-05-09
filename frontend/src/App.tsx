import React, { useState } from "react";
import SessionPanel from "./components/SessionPanel";
import Shell from "./components/Shell";
import FileBrowser from "./components/FileBrowser";
import StorageInfo from "./components/StorageInfo";
import { SessionInfo } from "./services/api";

type Tab = "shell" | "files" | "storage";

/**
 * Main application component for the AgentCore Runtime Filesystem Demo.
 *
 * Flow:
 * 1. User logs in with a user ID → creates/resumes an AgentCore Runtime session
 * 2. User gets access to shell, file browser, and storage info
 * 3. Each user's session has:
 *    - Private /mnt/workspace (session storage)
 *    - Shared /mnt/datasets (EFS)
 *    - Shared /mnt/tools (S3 Files)
 * 4. Multiple users can log in simultaneously (different tabs/browsers)
 *    and each sees their own workspace but shared EFS/S3 data
 */
export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("shell");

  if (!session) {
    return <SessionPanel onSessionCreated={setSession} currentSession={null} />;
  }

  return (
    <div style={styles.app}>
      {/* Top bar with session info */}
      <SessionPanel onSessionCreated={setSession} currentSession={session} />

      {/* Tab navigation */}
      <div style={styles.tabs}>
        {(
          [
            { id: "shell", label: "🖥️ Shell", desc: "Execute commands" },
            { id: "files", label: "📂 Files", desc: "Browse filesystem" },
            { id: "storage", label: "💾 Storage", desc: "Mount info" },
          ] as { id: Tab; label: string; desc: string }[]
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              ...styles.tab,
              ...(activeTab === tab.id ? styles.tabActive : {}),
            }}
          >
            <span style={styles.tabLabel}>{tab.label}</span>
            <span style={styles.tabDesc}>{tab.desc}</span>
          </button>
        ))}
      </div>

      {/* Main content area */}
      <div style={styles.content}>
        {activeTab === "shell" && (
          <Shell sessionId={session.session_id} userId={session.user_id} />
        )}
        {activeTab === "files" && (
          <FileBrowser sessionId={session.session_id} />
        )}
        {activeTab === "storage" && (
          <StorageInfo
            sessionId={session.session_id}
            userId={session.user_id}
          />
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  app: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    background: "#11111b",
    color: "#cdd6f4",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  tabs: {
    display: "flex",
    gap: 2,
    padding: "0 12px",
    background: "#181825",
    borderBottom: "1px solid #313244",
  },
  tab: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    padding: "8px 16px",
    background: "transparent",
    border: "none",
    borderBottom: "2px solid transparent",
    cursor: "pointer",
    color: "#6c7086",
    transition: "all 0.15s",
  },
  tabActive: {
    color: "#cdd6f4",
    borderBottomColor: "#89b4fa",
    background: "#1e1e2e",
  },
  tabLabel: {
    fontSize: 13,
    fontWeight: 500,
  },
  tabDesc: {
    fontSize: 10,
    opacity: 0.7,
  },
  content: {
    flex: 1,
    padding: 12,
    overflow: "hidden",
  },
};
