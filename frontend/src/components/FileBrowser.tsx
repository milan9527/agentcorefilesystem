import React, { useState } from "react";
import { listFiles, readFile, FileListResult } from "../services/api";

interface FileBrowserProps {
  sessionId: string;
}

/**
 * File browser component for navigating the AgentCore Runtime filesystem.
 *
 * Shows all three mount points:
 * - /mnt/workspace (Session Storage - private per session)
 * - /mnt/datasets (EFS - shared)
 * - /mnt/tools (S3 Files - shared)
 */
export default function FileBrowser({ sessionId }: FileBrowserProps) {
  const [currentPath, setCurrentPath] = useState("/mnt");
  const [listing, setListing] = useState<string>("");
  const [fileContent, setFileContent] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const browse = async (path: string) => {
    setIsLoading(true);
    setError("");
    setFileContent("");
    setSelectedFile("");
    try {
      const result: FileListResult = await listFiles(sessionId, path);
      setListing(result.output);
      setCurrentPath(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to list files");
    } finally {
      setIsLoading(false);
    }
  };

  const handleViewFile = async (filePath: string) => {
    setIsLoading(true);
    setError("");
    try {
      const result = await readFile(sessionId, filePath);
      setFileContent(result.content);
      setSelectedFile(filePath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read file");
    } finally {
      setIsLoading(false);
    }
  };

  const mountPoints = [
    {
      path: "/mnt/workspace",
      label: "📁 Workspace",
      type: "Session Storage",
      scope: "Private",
      color: "#a6e3a1",
    },
    {
      path: "/mnt/datasets",
      label: "📊 Datasets",
      type: "EFS",
      scope: "Shared",
      color: "#89b4fa",
    },
    {
      path: "/mnt/tools",
      label: "🔧 Tools",
      type: "S3 Files",
      scope: "Shared",
      color: "#f9e2af",
    },
  ];

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerTitle}>📂 File Browser</span>
        <span style={styles.pathDisplay}>{currentPath}</span>
      </div>

      {/* Mount point shortcuts */}
      <div style={styles.mounts}>
        {mountPoints.map((mp) => (
          <button
            key={mp.path}
            onClick={() => browse(mp.path)}
            style={{
              ...styles.mountBtn,
              borderColor: mp.color,
              color: mp.color,
              background:
                currentPath === mp.path ? `${mp.color}22` : "transparent",
            }}
          >
            <span>{mp.label}</span>
            <span style={styles.mountMeta}>
              {mp.type} • {mp.scope}
            </span>
          </button>
        ))}
      </div>

      {/* Navigation */}
      <div style={styles.nav}>
        <button
          onClick={() => {
            const parent = currentPath.split("/").slice(0, -1).join("/") || "/mnt";
            browse(parent);
          }}
          style={styles.navBtn}
          disabled={currentPath === "/mnt"}
        >
          ⬆️ Up
        </button>
        <button onClick={() => browse(currentPath)} style={styles.navBtn}>
          🔄 Refresh
        </button>
        <input
          type="text"
          placeholder="File path to view (e.g., /mnt/workspace/test.txt)"
          style={styles.fileInput}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              const target = e.currentTarget.value.trim();
              if (target) handleViewFile(target);
            }
          }}
        />
      </div>

      {/* File listing */}
      <div style={styles.content}>
        {isLoading && <div style={styles.loading}>Loading...</div>}
        {error && <div style={styles.error}>{error}</div>}
        {listing && !isLoading && (
          <pre style={styles.listing}>{listing}</pre>
        )}
      </div>

      {/* File content viewer */}
      {selectedFile && (
        <div style={styles.fileViewer}>
          <div style={styles.fileViewerHeader}>
            <span>📄 {selectedFile}</span>
            <button
              onClick={() => {
                setSelectedFile("");
                setFileContent("");
              }}
              style={styles.closeBtn}
            >
              ✕
            </button>
          </div>
          <pre style={styles.fileContent}>{fileContent}</pre>
        </div>
      )}
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
  pathDisplay: {
    color: "#89b4fa",
    fontSize: 12,
    fontFamily: "monospace",
  },
  mounts: {
    display: "flex",
    gap: 8,
    padding: "8px 12px",
    borderBottom: "1px solid #313244",
  },
  mountBtn: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    padding: "6px 10px",
    border: "1px solid",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 500,
    flex: 1,
  },
  mountMeta: {
    fontSize: 10,
    opacity: 0.7,
    marginTop: 2,
  },
  nav: {
    display: "flex",
    gap: 4,
    padding: "4px 12px",
    borderBottom: "1px solid #313244",
  },
  navBtn: {
    background: "#313244",
    border: "none",
    borderRadius: 4,
    color: "#cdd6f4",
    fontSize: 11,
    padding: "4px 8px",
    cursor: "pointer",
  },
  fileInput: {
    flex: 1,
    background: "#313244",
    border: "1px solid #45475a",
    borderRadius: 4,
    color: "#cdd6f4",
    fontSize: 11,
    padding: "4px 8px",
    fontFamily: "monospace",
    outline: "none",
    marginLeft: 8,
  },
  content: {
    flex: 1,
    overflow: "auto",
    padding: 12,
  },
  loading: {
    color: "#f9e2af",
    fontStyle: "italic",
  },
  error: {
    color: "#f38ba8",
    padding: 8,
    background: "#f38ba811",
    borderRadius: 4,
  },
  listing: {
    color: "#cdd6f4",
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 12,
    lineHeight: 1.4,
    margin: 0,
    whiteSpace: "pre-wrap",
  },
  fileViewer: {
    borderTop: "1px solid #313244",
    maxHeight: "40%",
    overflow: "auto",
  },
  fileViewerHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "6px 12px",
    background: "#181825",
    color: "#cdd6f4",
    fontSize: 12,
    position: "sticky",
    top: 0,
  },
  closeBtn: {
    background: "none",
    border: "none",
    color: "#f38ba8",
    cursor: "pointer",
    fontSize: 14,
  },
  fileContent: {
    color: "#cdd6f4",
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 12,
    lineHeight: 1.4,
    margin: 0,
    padding: 12,
    whiteSpace: "pre-wrap",
  },
};
