import React from "react";

interface StorageInfoProps {
  sessionId: string;
  userId: string;
}

/**
 * Storage information panel showing the hybrid filesystem layout.
 *
 * Explains what each user can see:
 * - Session Storage: Only their own files
 * - EFS: Same files as all other users
 * - S3 Files: Same files as all other users (also accessible via S3 APIs)
 */
export default function StorageInfo({ sessionId, userId }: StorageInfoProps) {
  const mounts = [
    {
      path: "/mnt/workspace",
      type: "Session Storage",
      icon: "📁",
      color: "#a6e3a1",
      scope: "Private (this session only)",
      description:
        "Isolated per-session workspace. Only you can see these files. " +
        "Persists across stop/resume.",
      examples: [
        "Project source code",
        "Installed packages (node_modules, venv)",
        "Build artifacts",
        "Git repositories",
      ],
    },
    {
      path: "/mnt/datasets",
      type: "Amazon EFS",
      icon: "📊",
      color: "#89b4fa",
      scope: "Shared (all sessions see same data)",
      description:
        "Shared EFS mount with full POSIX semantics. All users and sessions " +
        "read/write the same files concurrently. Permanent storage.",
      examples: [
        "Training datasets",
        "Reference data",
        "Shared analysis results",
        "Multi-agent collaboration files",
      ],
    },
    {
      path: "/mnt/tools",
      type: "Amazon S3 Files",
      icon: "🔧",
      color: "#f9e2af",
      scope: "Shared (synced with S3 bucket)",
      description:
        "S3 Files mount with bidirectional sync to a backing S3 bucket. " +
        "All sessions see the same tools. Also accessible via S3 APIs.",
      examples: [
        "Shared CLI tools and scripts",
        "Configuration templates",
        "Utility libraries",
        "Pre-built binaries",
      ],
    },
  ];

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>💾 Hybrid Storage Layout</span>
        <span style={styles.subtitle}>
          User: {userId} | Session: {sessionId.slice(0, 16)}...
        </span>
      </div>

      <div style={styles.diagram}>
        <pre style={styles.diagramText}>
{`┌─────────────────────────────────────────────────┐
│         AgentCore Runtime MicroVM                │
│         (Session: ${sessionId.slice(0, 20)}...)  │
├─────────────────────────────────────────────────┤
│  /mnt/workspace  ← Session Storage [PRIVATE]    │
│  /mnt/datasets   ← EFS             [SHARED]     │
│  /mnt/tools      ← S3 Files        [SHARED]     │
└─────────────────────────────────────────────────┘`}
        </pre>
      </div>

      <div style={styles.mountList}>
        {mounts.map((mount) => (
          <div
            key={mount.path}
            style={{ ...styles.mountCard, borderLeftColor: mount.color }}
          >
            <div style={styles.mountHeader}>
              <span style={{ ...styles.mountPath, color: mount.color }}>
                {mount.icon} {mount.path}
              </span>
              <span style={styles.mountType}>{mount.type}</span>
            </div>
            <div style={styles.mountScope}>{mount.scope}</div>
            <p style={styles.mountDesc}>{mount.description}</p>
            <div style={styles.examples}>
              {mount.examples.map((ex) => (
                <span key={ex} style={styles.exampleTag}>
                  {ex}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={styles.multiUserNote}>
        <strong>Multi-User Behavior:</strong>
        <ul style={styles.noteList}>
          <li>
            User A writes to <code>/mnt/workspace/app.py</code> → Only User A
            sees it
          </li>
          <li>
            User A writes to <code>/mnt/datasets/data.csv</code> → User B also
            sees it immediately
          </li>
          <li>
            User A writes to <code>/mnt/tools/script.sh</code> → User B sees it
            + it syncs to S3 bucket
          </li>
        </ul>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    height: "100%",
    overflow: "auto",
    background: "#1e1e2e",
    borderRadius: 8,
    border: "1px solid #313244",
  },
  header: {
    padding: "12px 16px",
    borderBottom: "1px solid #313244",
    background: "#181825",
  },
  title: {
    color: "#cdd6f4",
    fontWeight: 600,
    fontSize: 14,
    display: "block",
  },
  subtitle: {
    color: "#6c7086",
    fontSize: 11,
    fontFamily: "monospace",
  },
  diagram: {
    padding: "12px 16px",
    borderBottom: "1px solid #313244",
    background: "#11111b",
  },
  diagramText: {
    color: "#89b4fa",
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    margin: 0,
    lineHeight: 1.4,
  },
  mountList: {
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  mountCard: {
    background: "#181825",
    borderRadius: 8,
    padding: 12,
    borderLeft: "3px solid",
  },
  mountHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  mountPath: {
    fontFamily: "monospace",
    fontSize: 13,
    fontWeight: 600,
  },
  mountType: {
    color: "#6c7086",
    fontSize: 11,
    background: "#313244",
    padding: "2px 6px",
    borderRadius: 4,
  },
  mountScope: {
    color: "#a6adc8",
    fontSize: 12,
    fontWeight: 500,
    marginBottom: 4,
  },
  mountDesc: {
    color: "#6c7086",
    fontSize: 11,
    lineHeight: 1.4,
    margin: "4px 0 8px 0",
  },
  examples: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
  },
  exampleTag: {
    background: "#313244",
    color: "#a6adc8",
    fontSize: 10,
    padding: "2px 6px",
    borderRadius: 4,
  },
  multiUserNote: {
    margin: 16,
    padding: 12,
    background: "#181825",
    borderRadius: 8,
    border: "1px solid #45475a",
    color: "#cdd6f4",
    fontSize: 12,
  },
  noteList: {
    margin: "8px 0 0 0",
    paddingLeft: 20,
    color: "#a6adc8",
    fontSize: 11,
    lineHeight: 1.8,
  },
};
