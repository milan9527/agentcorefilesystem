/**
 * API client for the AgentCore Runtime Filesystem Demo backend.
 */

const API_BASE = "https://v11opo7s17.execute-api.us-east-1.amazonaws.com/api";

export interface CommandResult {
  stdout: string;
  stderr: string;
  exit_code: number | null;
  status: string | null;
}

export interface SessionInfo {
  session_id: string;
  user_id: string;
  session_name: string;
  status: string;
  mounts: Record<string, MountInfo>;
}

export interface MountInfo {
  path: string;
  type: string;
  scope: string;
  description?: string;
}

export interface FileListResult {
  path: string;
  output: string;
  exit_code: number;
}

/**
 * Create or resume a session for a user.
 */
export async function createSession(
  userId: string,
  sessionName: string = "default"
): Promise<SessionInfo> {
  const res = await fetch(`${API_BASE}/sessions/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, session_name: sessionName }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Stop a session (persists session storage).
 */
export async function stopSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await res.text());
}

/**
 * List active sessions.
 */
export async function listSessions(): Promise<{ sessions: SessionInfo[] }> {
  const res = await fetch(`${API_BASE}/sessions/active`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Execute a shell command in the user's AgentCore Runtime session.
 */
export async function executeCommand(
  sessionId: string,
  command: string,
  timeout: number = 60
): Promise<CommandResult> {
  const res = await fetch(`${API_BASE}/shell/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, command, timeout }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * List files at a path in the session's filesystem.
 */
export async function listFiles(
  sessionId: string,
  path: string
): Promise<FileListResult> {
  const res = await fetch(`${API_BASE}/files/list`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, path }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Read a file from the session's filesystem.
 */
export async function readFile(
  sessionId: string,
  filePath: string
): Promise<{ file_path: string; content: string; exit_code: number }> {
  const res = await fetch(`${API_BASE}/files/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, file_path: filePath }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Get storage info for all mounted filesystems.
 */
export async function getStorageInfo(
  sessionId: string
): Promise<{ mounts: Record<string, MountInfo>; raw_output: string }> {
  const res = await fetch(`${API_BASE}/files/storage-info`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, path: "/mnt" }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
