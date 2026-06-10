import { useEffect, useState, useRef } from "react";
import {
  Send,
  Menu,
  X,
  FileText,
  Loader2,
  Trash2,
  Download,
  Bot,
  User,
  Moon,
  Sun,
  Plus,
} from "lucide-react";
import { Button } from "@/src/components/ui/button";
import { Input } from "@/src/components/ui/input";
import { Card, CardContent } from "@/src/components/ui/card";
import { Textarea } from "@/src/components/ui/textarea";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api"
).replace(/\/$/, "");
const CHAT_SESSION_KEY = "insightedge_chat_session_id";
const THEME_KEY = "insightedge_theme";
const SYSTEM_PROMPT_KEY = "insightedge_system_prompt";
const WORKSPACE_KEY = "insightedge_workspace_id";
const LLM_MODEL_KEY = "insightedge_llm_model";
const API_TOKEN_KEY = "insightedge_api_token";
const MAX_CONVERSATION_MESSAGES = 80;
const DEFAULT_LLM_MODEL = "llama3.1:8b-instruct-q4_K_M";
const LLM_MODEL_PRESETS = [
  "llama3.1:8b-instruct-q4_K_M",
  "phi3:mini",
  "llama3.1:70b-instruct-q4_K_M",
  "phi4:14b",
  "qwen2.5:14b",
  "mistral-small3.1",
];

function getOrCreateSessionId() {
  const existing = localStorage.getItem(CHAT_SESSION_KEY);
  if (existing) {
    return existing;
  }
  const created = crypto.randomUUID();
  localStorage.setItem(CHAT_SESSION_KEY, created);
  return created;
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

function postFormDataWithProgress(url, formData, timeoutMs, onProgress, headers = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.timeout = timeoutMs;
    for (const [key, value] of Object.entries(headers)) {
      if (value) xhr.setRequestHeader(key, value);
    }

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== "function") return;
      const percent = Math.min(
        100,
        Math.round((event.loaded / event.total) * 100),
      );
      onProgress(percent);
    };

    xhr.onload = () => {
      const body = xhr.responseText || "";
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(body ? JSON.parse(body) : {});
        } catch {
          resolve({});
        }
        return;
      }
      reject(new Error(body || `Upload failed with status ${xhr.status}`));
    };

    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.ontimeout = () => reject(new Error("Upload timed out"));
    xhr.send(formData);
  });
}

export default function App() {
  const [files, setFiles] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [workspaces, setWorkspaces] = useState(["default"]);
  const [workspaceId, setWorkspaceId] = useState(
    () => localStorage.getItem(WORKSPACE_KEY) || "default",
  );
  const [question, setQuestion] = useState("");
  const [conversation, setConversation] = useState([]);
  const [status, setStatus] = useState("Ready");
  const [isIngesting, setIsIngesting] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [sessionId] = useState(() => getOrCreateSessionId());
  const [theme, setTheme] = useState(
    () => localStorage.getItem(THEME_KEY) || "light",
  );
  const [systemPrompt, setSystemPrompt] = useState(
    () => localStorage.getItem(SYSTEM_PROMPT_KEY) || "",
  );
  const [llmModel, setLlmModel] = useState(
    () => localStorage.getItem(LLM_MODEL_KEY) || DEFAULT_LLM_MODEL,
  );
  const [llmModelOptions, setLlmModelOptions] = useState(LLM_MODEL_PRESETS);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [apiToken, setApiToken] = useState(
    () => import.meta.env.VITE_API_KEY || localStorage.getItem(API_TOKEN_KEY) || "",
  );
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [showWorkspaceCreate, setShowWorkspaceCreate] = useState(false);
  const [workspaceAction, setWorkspaceAction] = useState("");
  const [workspaceToDelete, setWorkspaceToDelete] = useState("");
  const [docToDelete, setDocToDelete] = useState("");
  const [confirmClearKb, setConfirmClearKb] = useState(false);
  const scrollRef = useRef(null);
  const ingestPollRef = useRef(null);

  function authHeaders(extra = {}) {
    const token = apiToken.trim();
    return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
  }

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(SYSTEM_PROMPT_KEY, systemPrompt);
  }, [systemPrompt]);

  useEffect(() => {
    localStorage.setItem(LLM_MODEL_KEY, llmModel);
  }, [llmModel]);

  useEffect(() => {
    localStorage.setItem(WORKSPACE_KEY, workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    if (import.meta.env.VITE_API_KEY) return;
    if (apiToken.trim()) {
      localStorage.setItem(API_TOKEN_KEY, apiToken.trim());
    } else {
      localStorage.removeItem(API_TOKEN_KEY);
    }
  }, [apiToken]);

  useEffect(() => {
    return () => {
      if (ingestPollRef.current) clearInterval(ingestPollRef.current);
    };
  }, []);

  useEffect(() => {
    async function loadHealth() {
      try {
        const healthBase = API_BASE.replace(/\/api$/, "");
        const res = await fetchWithTimeout(
          `${healthBase}/api/health`,
          { method: "GET", headers: authHeaders() },
          15000,
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        const availableModels = Array.isArray(data.available_llm_models)
          ? data.available_llm_models.filter(Boolean)
          : [];
        const nextOptions = Array.from(
          new Set(
            [...availableModels, data.llm_model, ...LLM_MODEL_PRESETS].filter(
              Boolean,
            ),
          ),
        );
        setLlmModelOptions(nextOptions);

        const savedModel = localStorage.getItem(LLM_MODEL_KEY);
        const currentModel = savedModel || llmModel;
        if (availableModels.length && !availableModels.includes(currentModel)) {
          setLlmModel(
            availableModels.includes(data.llm_model)
              ? data.llm_model
              : availableModels[0],
          );
        }
      } catch {
        setLlmModelOptions(LLM_MODEL_PRESETS);
      }
    }
    loadHealth();
  }, [apiToken]);

  function toggleTheme() {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  }

  useEffect(() => {
    async function loadSessionHistory() {
      try {
        const res = await fetchWithTimeout(
          `${API_BASE}/chat/session/${sessionId}?workspace_id=${encodeURIComponent(workspaceId)}`,
          { method: "GET", headers: authHeaders() },
          15000,
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setConversation((data.history || []).slice(-MAX_CONVERSATION_MESSAGES));
      } catch {
        setConversation([]);
      }
    }
    loadSessionHistory();
  }, [sessionId, workspaceId, apiToken]);

  async function refreshWorkspaces() {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/ingest/workspaces`,
        { method: "GET", headers: authHeaders() },
        15000,
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const next = (data.workspaces || [])
        .map((item) => item.workspace_id)
        .filter(Boolean);
      const unique = Array.from(new Set(["default", ...next]));
      setWorkspaces(unique);
      if (!unique.includes(workspaceId)) {
        setWorkspaceId("default");
      }
    } catch {
      setWorkspaces((prev) => Array.from(new Set(["default", ...prev])));
    }
  }

  async function refreshDocuments() {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/ingest/documents?workspace_id=${encodeURIComponent(workspaceId)}`,
        { method: "GET", headers: authHeaders() },
        15000,
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDocuments(data.documents || []);
    } catch {
      setDocuments([]);
    }
  }

  useEffect(() => {
    refreshWorkspaces();
  }, []);

  useEffect(() => {
    refreshDocuments();
  }, [workspaceId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversation, isAsking]);

  async function ingestFiles() {
    if (!files.length) {
      setStatus("Select at least one file.");
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    formData.append("workspace_id", workspaceId);

    setIsIngesting(true);
    setUploadProgress(0);
    setStatus("Uploading files...");

    try {
      const job = await postFormDataWithProgress(
        `${API_BASE}/ingest/files`,
        formData,
        30000,
        (percent) => {
          setUploadProgress(percent);
          setStatus(`Uploading files... ${percent}%`);
        },
        authHeaders(),
      );

      setStatus("Processing files...");
      setUploadProgress(100);

      // Poll specifically for this job_id
      if (ingestPollRef.current) clearInterval(ingestPollRef.current);
      ingestPollRef.current = setInterval(async () => {
        try {
          const statusRes = await fetchWithTimeout(
            `${API_BASE}/ingest/jobs/${job.job_id}`,
            { method: "GET", headers: authHeaders() },
            5000,
          );

          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === "completed") {
              clearInterval(ingestPollRef.current);
              ingestPollRef.current = null;
              setIsIngesting(false);
              setUploadProgress(0);
              setStatus("Ingestion complete!");
              setFiles([]);
              refreshWorkspaces();
              refreshDocuments();
            } else if (statusData.status === "failed") {
              clearInterval(ingestPollRef.current);
              ingestPollRef.current = null;
              setIsIngesting(false);
              setUploadProgress(0);
              setStatus(
                "Ingestion failed: " + (statusData.error || "Unknown error"),
              );
            } else {
              setStatus(`Processing: ${statusData.status}...`);
            }
          }
        } catch (err) {
          console.error(err);
        }
      }, 1000);
    } catch (e) {
      console.error(e);
      setStatus("Error starting ingest: " + e.message);
      setIsIngesting(false);
      setUploadProgress(0);
    }
  }

  async function handleAsk(e) {
    if (e) e.preventDefault();
    if (!question.trim()) return;

    const currentQ = question;
    setQuestion("");
    setIsAsking(true);
    setStatus("Thinking...");

    // Optimistic update with a placeholder assistant message for token streaming
    setConversation((prev) =>
      [
        ...prev,
        { role: "user", content: currentQ },
        { role: "assistant", content: "", citations: [] },
      ].slice(-MAX_CONVERSATION_MESSAGES),
    );

    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/chat/stream`,
        {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            question: currentQ,
            session_id: sessionId,
            system_prompt: systemPrompt.trim() || undefined,
            workspace_id: workspaceId,
            llm_model: llmModel,
          }),
        },
        60000,
      );

      if (!res.ok) throw new Error(await res.text());
      if (!res.body) throw new Error("Streaming response body is unavailable");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamedAnswer = "";

      const applyAssistantUpdate = (answerText, metadata = undefined) => {
        setConversation((prev) => {
          if (prev.length === 0) return prev;
          const next = [...prev];
          const lastIndex = next.length - 1;
          if (next[lastIndex]?.role === "assistant") {
            next[lastIndex] = {
              ...next[lastIndex],
              content: answerText,
              ...(metadata ? metadata : {}),
            };
          }
          return next.slice(-MAX_CONVERSATION_MESSAGES);
        });
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const eventBlob of events) {
          const dataLine = eventBlob
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;

          let event;
          try {
            event = JSON.parse(dataLine.slice(6));
          } catch {
            continue;
          }

          if (event.type === "token") {
            streamedAnswer += event.token || "";
            applyAssistantUpdate(streamedAnswer);
          } else if (event.type === "final") {
            streamedAnswer = event.answer || streamedAnswer;
            applyAssistantUpdate(streamedAnswer, {
              citations: event.citations || [],
              model: event.model,
              workspace_id: event.workspace_id,
              retrieval_mode: event.retrieval_mode,
              retrieved_chunks: event.retrieved_chunks,
              final_context_chunks: event.final_context_chunks,
              latency_ms: event.latency_ms,
              request_id: event.request_id,
            });
          } else if (event.type === "error") {
            throw new Error(event.message || "Streaming error");
          }
        }
      }

      setStatus("Ready");
    } catch (err) {
      console.error(err);
      setStatus("Error asking question.");
      setConversation((prev) =>
        [
          ...prev.slice(0, -1),
          {
            role: "assistant",
            content: "Sorry, I encountered an error answering that.",
          },
        ].slice(-MAX_CONVERSATION_MESSAGES),
      );
    } finally {
      setIsAsking(false);
    }
  }

  function handleFileChange(e) {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setStatus("Ready to upload");
    }
  }

  async function clearKnowledgeBase() {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/ingest/documents?workspace_id=${encodeURIComponent(workspaceId)}`,
        { method: "DELETE", headers: authHeaders() },
        30000,
      );
      if (!res.ok) throw new Error(await res.text());
      setStatus("Knowledge base cleared.");
      setDocuments([]);
      setConfirmClearKb(false);
    } catch (e) {
      setStatus("Failed to clear knowledge base: " + e.message);
    }
  }

  async function deleteDocument(docId) {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/ingest/documents/${encodeURIComponent(docId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
        { method: "DELETE", headers: authHeaders() },
        30000,
      );
      if (!res.ok) throw new Error(await res.text());
      setStatus("Document deleted.");
      setDocToDelete("");
      refreshDocuments();
    } catch (e) {
      setStatus("Failed to delete document: " + e.message);
    }
  }

  function downloadConversation(format) {
    if (!conversation.length) {
      setStatus("No conversation to export.");
      return;
    }

    const timestamp = new Date().toISOString();
    const baseName = `insightedge-chat-${workspaceId}-${sessionId.slice(0, 8)}`;
    let fileName = `${baseName}.md`;
    let mimeType = "text/markdown;charset=utf-8";
    let content = "";

    if (format === "json") {
      fileName = `${baseName}.json`;
      mimeType = "application/json;charset=utf-8";
      content = JSON.stringify(
        {
          exported_at: timestamp,
          workspace_id: workspaceId,
          session_id: sessionId,
          conversation,
        },
        null,
        2,
      );
    } else {
      const lines = [
        "# InsightEdge Conversation",
        "",
        `- Exported: ${timestamp}`,
        `- Workspace: ${workspaceId}`,
        `- Session: ${sessionId}`,
        "",
      ];
      for (const turn of conversation) {
        const speaker = turn.role === "user" ? "User" : "Assistant";
        lines.push(`## ${speaker}`);
        lines.push("");
        lines.push(turn.content || "");
        lines.push("");
        if (turn.role === "assistant" && Array.isArray(turn.citations) && turn.citations.length) {
          lines.push("### Sources");
          for (const [index, citation] of turn.citations.entries()) {
            const source = citation.filename || citation.source || `Source ${index + 1}`;
            const score = typeof citation.score === "number" ? `, score ${citation.score.toFixed(3)}` : "";
            const page = citation.page_number ? `, page ${citation.page_number}` : "";
            lines.push(`- [${index + 1}] ${source}${page}${score}`);
            if (citation.snippet) lines.push(`  - Snippet: ${citation.snippet}`);
          }
          lines.push("");
        }
      }
      content = lines.join("\n");
    }

    const blob = new Blob([content], { type: mimeType });
    const blobUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(blobUrl);
    setStatus(`Conversation exported as ${format.toUpperCase()}.`);
  }

  function normalizeWorkspaceName(raw) {
    const normalized = raw
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48);
    return normalized;
  }

  function createWorkspace() {
    const normalized = normalizeWorkspaceName(workspaceDraft);
    if (!normalized) {
      setStatus("Invalid workspace name.");
      return;
    }
    setWorkspaces((prev) => Array.from(new Set([...prev, normalized])));
    setWorkspaceId(normalized);
    setWorkspaceDraft("");
    setShowWorkspaceCreate(false);
    setStatus(`Switched to workspace "${normalized}".`);
  }

  async function deleteWorkspace() {
    if (!workspaceToDelete || workspaceToDelete === "default") return;
    setWorkspaceAction("delete");
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/ingest/workspaces/${encodeURIComponent(workspaceToDelete)}`,
        { method: "DELETE", headers: authHeaders() },
        30000,
      );
      if (!res.ok) throw new Error(await res.text());
      setWorkspaces((prev) => prev.filter((workspace) => workspace !== workspaceToDelete));
      if (workspaceId === workspaceToDelete) {
        setWorkspaceId("default");
        setConversation([]);
        setDocuments([]);
      }
      setStatus(`Workspace "${workspaceToDelete}" deleted.`);
      setWorkspaceToDelete("");
      refreshWorkspaces();
    } catch (e) {
      setStatus("Failed to delete workspace: " + e.message);
    } finally {
      setWorkspaceAction("");
    }
  }

  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden font-sans">
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed top-0 left-0 z-50 h-full w-80 border-r bg-background p-4 flex flex-col gap-4 transition-transform duration-200 md:hidden ${
          mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-2 font-bold text-xl text-primary">
            <Bot className="h-6 w-6" />
            <span>InsightEdge</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setMobileSidebarOpen(false)}
            className="h-8 w-8"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-auto space-y-4">
          <Card>
            <CardContent className="p-4 space-y-2">
              <div className="text-sm font-medium">Workspace</div>
              <div className="flex gap-2">
                <select
                  value={workspaceId}
                  onChange={(e) => setWorkspaceId(e.target.value)}
                  className="flex-1 rounded-md border bg-background px-2 py-2 text-xs"
                >
                  {workspaces.map((workspace) => (
                    <option key={workspace} value={workspace}>
                      {workspace}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 px-2 text-xs"
                  onClick={() => setShowWorkspaceCreate((value) => !value)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  New
                </Button>
              </div>
              {showWorkspaceCreate && (
                <div className="space-y-2 rounded-md border bg-muted/40 p-2">
                  <Input
                    value={workspaceDraft}
                    onChange={(e) => setWorkspaceDraft(e.target.value)}
                    placeholder="workspace-name"
                    className="h-8 text-xs"
                  />
                  <div className="flex gap-2">
                    <Button size="sm" className="h-7 px-2 text-xs" onClick={createWorkspace}>
                      Create
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs"
                      onClick={() => {
                        setShowWorkspaceCreate(false);
                        setWorkspaceDraft("");
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
              <div className="flex items-center justify-between rounded-md bg-primary/10 px-2 py-1.5 text-xs">
                <span className="truncate">Active: {workspaceId}</span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs text-destructive"
                  onClick={() => setWorkspaceToDelete(workspaceId)}
                  disabled={workspaceId === "default" || workspaceAction === "delete"}
                >
                  Delete
                </Button>
              </div>
              {workspaceToDelete && (
                <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs space-y-2">
                  <div>Delete workspace "{workspaceToDelete}" and its local state?</div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-7 px-2 text-xs"
                      onClick={deleteWorkspace}
                      disabled={workspaceAction === "delete"}
                    >
                      {workspaceAction === "delete" ? "Deleting..." : "Delete"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs"
                      onClick={() => setWorkspaceToDelete("")}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 space-y-2">
              <div className="text-sm font-medium">LLM Model</div>
              <select
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                className="w-full rounded-md border bg-background px-2 py-2 text-xs"
              >
                {llmModelOptions.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
              <div className="text-[10px] text-muted-foreground">
                Installed Ollama models appear first.
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 space-y-4">
              <div className="text-sm font-medium">Knowledge Base</div>
              <Input
                type="file"
                multiple
                onChange={handleFileChange}
                className="text-xs file:mr-2 file:py-1 file:px-2 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:bg-primary/90"
              />
              <div className="text-[10px] text-muted-foreground">
                File-only local ingestion. Nothing is fetched from the web.
              </div>
              {files.length > 0 && (
                <div className="space-y-2">
                  {files.map((f, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 text-xs text-muted-foreground bg-muted p-2 rounded-md"
                    >
                      <FileText className="h-3 w-3" />
                      <span className="truncate flex-1">{f.name}</span>
                    </div>
                  ))}
                  <Button
                    size="sm"
                    className="w-full"
                    onClick={ingestFiles}
                    disabled={isIngesting}
                  >
                    {isIngesting ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      "Upload & Process"
                    )}
                  </Button>
                  {isIngesting && (
                    <div className="space-y-1">
                      <div className="h-1.5 w-full rounded bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-muted-foreground text-right">
                        Upload {uploadProgress}%
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    Ingested documents
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    onClick={() => setConfirmClearKb(true)}
                    disabled={documents.length === 0}
                  >
                    <Trash2 className="h-3 w-3 mr-1" />
                    Clear
                  </Button>
                </div>
                {documents.length === 0 ? (
                  <div className="text-xs text-muted-foreground">
                    No documents ingested yet.
                  </div>
                ) : (
                  <div className="space-y-1 max-h-40 overflow-auto">
                    {documents.map((doc) => (
                      <div
                        key={doc.doc_id}
                        className="text-xs text-muted-foreground bg-muted p-2 rounded-md"
                        title={`${doc.source} (${doc.chunks} chunks)`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="truncate flex-1">
                            {doc.source} ({doc.chunks})
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0 text-destructive"
                            onClick={() => setDocToDelete(doc.doc_id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                        {docToDelete === doc.doc_id && (
                          <div className="mt-2 flex items-center gap-2 text-[10px]">
                            <span className="flex-1">Delete this document?</span>
                            <Button size="sm" variant="destructive" className="h-6 px-2 text-[10px]" onClick={() => deleteDocument(doc.doc_id)}>
                              Delete
                            </Button>
                            <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px]" onClick={() => setDocToDelete("")}>
                              Cancel
                            </Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {confirmClearKb && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs space-y-2">
                    <div>Clear every document in "{workspaceId}"?</div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="destructive" className="h-7 px-2 text-xs" onClick={clearKnowledgeBase}>
                        Clear
                      </Button>
                      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setConfirmClearKb(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 space-y-2">
              <div className="text-sm font-medium">Local API Token</div>
              <Input
                type="password"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                placeholder="Optional bearer token"
                className="text-xs"
                disabled={Boolean(import.meta.env.VITE_API_KEY)}
              />
              <div className="text-[10px] text-muted-foreground">
                Used only for your local backend when API key protection is enabled.
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">System Prompt</div>
                {systemPrompt && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    onClick={() => setSystemPrompt("")}
                  >
                    Reset
                  </Button>
                )}
              </div>
              <Textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Optional per-session system instructions..."
                className="min-h-24 text-xs"
              />
            </CardContent>
          </Card>

          <div className="px-2">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Status
            </div>
            <div className="flex items-center gap-2 text-sm">
              <div
                className={`h-2 w-2 rounded-full ${status === "Ready" || status === "Ingestion complete!" ? "bg-green-500" : "bg-yellow-500 animate-pulse"}`}
              ></div>
              <span>{status}</span>
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                onClick={() => downloadConversation("md")}
              >
                <Download className="h-3 w-3 mr-1" />
                Markdown
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                onClick={() => downloadConversation("json")}
              >
                <Download className="h-3 w-3 mr-1" />
                JSON
              </Button>
            </div>
          </div>
        </div>
      </aside>

      {/* Sidebar */}
      <aside className="w-80 border-r bg-muted/20 p-4 hidden md:flex flex-col gap-4">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-2 font-bold text-xl text-primary">
            <Bot className="h-6 w-6" />
            <span>InsightEdge</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            className="h-8 w-8"
          >
            {theme === "light" ? (
              <Moon className="h-4 w-4" />
            ) : (
              <Sun className="h-4 w-4" />
            )}
          </Button>
        </div>

        <div className="flex-1 overflow-auto">
          <div className="space-y-4">
            <Card>
              <CardContent className="p-4 space-y-2">
                <div className="text-sm font-medium">Workspace</div>
                <div className="flex gap-2">
                  <select
                    value={workspaceId}
                    onChange={(e) => setWorkspaceId(e.target.value)}
                    className="flex-1 rounded-md border bg-background px-2 py-2 text-xs"
                  >
                    {workspaces.map((workspace) => (
                      <option key={workspace} value={workspace}>
                        {workspace}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 px-2 text-xs"
                    onClick={() => setShowWorkspaceCreate((value) => !value)}
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    New
                  </Button>
                </div>
                {showWorkspaceCreate && (
                  <div className="space-y-2 rounded-md border bg-muted/40 p-2">
                    <Input
                      value={workspaceDraft}
                      onChange={(e) => setWorkspaceDraft(e.target.value)}
                      placeholder="workspace-name"
                      className="h-8 text-xs"
                    />
                    <div className="flex gap-2">
                      <Button size="sm" className="h-7 px-2 text-xs" onClick={createWorkspace}>
                        Create
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => {
                          setShowWorkspaceCreate(false);
                          setWorkspaceDraft("");
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
                <div className="flex items-center justify-between rounded-md bg-primary/10 px-2 py-1.5 text-xs">
                  <span className="truncate">Active: {workspaceId}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs text-destructive"
                    onClick={() => setWorkspaceToDelete(workspaceId)}
                    disabled={workspaceId === "default" || workspaceAction === "delete"}
                  >
                    Delete
                  </Button>
                </div>
                {workspaceToDelete && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs space-y-2">
                    <div>Delete workspace "{workspaceToDelete}" and its local state?</div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-7 px-2 text-xs"
                        onClick={deleteWorkspace}
                        disabled={workspaceAction === "delete"}
                      >
                        {workspaceAction === "delete" ? "Deleting..." : "Delete"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => setWorkspaceToDelete("")}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 space-y-2">
                <div className="text-sm font-medium">LLM Model</div>
                <select
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  className="w-full rounded-md border bg-background px-2 py-2 text-xs"
                >
                  {llmModelOptions.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
                <div className="text-[10px] text-muted-foreground">
                  Installed Ollama models appear first.
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 space-y-4">
                <div className="text-sm font-medium">Knowledge Base</div>
                <div className="flex items-center gap-2">
                  <Input
                    type="file"
                    multiple
                    onChange={handleFileChange}
                    className="text-xs file:mr-2 file:py-1 file:px-2 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:bg-primary/90"
                  />
                </div>
                <div className="text-[10px] text-muted-foreground">
                  File-only local ingestion. Nothing is fetched from the web.
                </div>
                {files.length > 0 && (
                  <div className="space-y-2">
                    {files.map((f, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-muted-foreground bg-muted p-2 rounded-md"
                      >
                        <FileText className="h-3 w-3" />
                        <span className="truncate flex-1">{f.name}</span>
                      </div>
                    ))}
                    <Button
                      size="sm"
                      className="w-full"
                      onClick={ingestFiles}
                      disabled={isIngesting}
                    >
                      {isIngesting ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      ) : (
                        "Upload & Process"
                      )}
                    </Button>
                    {isIngesting && (
                      <div className="space-y-1">
                        <div className="h-1.5 w-full rounded bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary transition-all"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                        <div className="text-[10px] text-muted-foreground text-right">
                          Upload {uploadProgress}%
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      Ingested documents
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 px-2 text-xs"
                      onClick={() => setConfirmClearKb(true)}
                      disabled={documents.length === 0}
                    >
                      <Trash2 className="h-3 w-3 mr-1" />
                      Clear
                    </Button>
                  </div>
                  {documents.length === 0 ? (
                    <div className="text-xs text-muted-foreground">
                      No documents ingested yet.
                    </div>
                  ) : (
                    <div className="space-y-1 max-h-40 overflow-auto">
                      {documents.map((doc) => (
                        <div
                          key={doc.doc_id}
                          className="text-xs text-muted-foreground bg-muted p-2 rounded-md"
                          title={`${doc.source} (${doc.chunks} chunks)`}
                        >
                          <div className="flex items-center gap-2">
                            <span className="truncate flex-1">
                              {doc.source} ({doc.chunks})
                            </span>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 w-6 p-0 text-destructive"
                              onClick={() => setDocToDelete(doc.doc_id)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                          {docToDelete === doc.doc_id && (
                            <div className="mt-2 flex items-center gap-2 text-[10px]">
                              <span className="flex-1">Delete this document?</span>
                              <Button size="sm" variant="destructive" className="h-6 px-2 text-[10px]" onClick={() => deleteDocument(doc.doc_id)}>
                                Delete
                              </Button>
                              <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px]" onClick={() => setDocToDelete("")}>
                                Cancel
                              </Button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {confirmClearKb && (
                    <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs space-y-2">
                      <div>Clear every document in "{workspaceId}"?</div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="destructive" className="h-7 px-2 text-xs" onClick={clearKnowledgeBase}>
                          Clear
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setConfirmClearKb(false)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 space-y-2">
                <div className="text-sm font-medium">Local API Token</div>
                <Input
                  type="password"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  placeholder="Optional bearer token"
                  className="text-xs"
                  disabled={Boolean(import.meta.env.VITE_API_KEY)}
                />
                <div className="text-[10px] text-muted-foreground">
                  Used only for your local backend when API key protection is enabled.
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">System Prompt</div>
                  {systemPrompt && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs"
                      onClick={() => setSystemPrompt("")}
                    >
                      Reset
                    </Button>
                  )}
                </div>
                <Textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Optional per-session system instructions..."
                  className="min-h-24 text-xs"
                />
              </CardContent>
            </Card>

            <div className="px-2">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                Status
              </div>
              <div className="flex items-center gap-2 text-sm">
                <div
                  className={`h-2 w-2 rounded-full ${status === "Ready" || status === "Ingestion complete!" ? "bg-green-500" : "bg-yellow-500 animate-pulse"}`}
                ></div>
                <span>{status}</span>
              </div>
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-xs"
                  onClick={() => downloadConversation("md")}
                >
                  <Download className="h-3 w-3 mr-1" />
                  Markdown
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-xs"
                  onClick={() => downloadConversation("json")}
                >
                  <Download className="h-3 w-3 mr-1" />
                  JSON
                </Button>
              </div>
            </div>
          </div>
        </div>

        <div className="text-xs text-center text-muted-foreground p-2 border-t">
          Session: {sessionId.slice(0, 8)}...
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="flex-1 flex flex-col h-full relative transition-colors duration-300">
        <header className="h-14 border-b flex items-center justify-between px-6 bg-background/50 backdrop-blur sticky top-0 z-10">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileSidebarOpen(true)}
              className="h-8 w-8 md:hidden"
            >
              <Menu className="h-4 w-4" />
            </Button>
            <div>
              <h2 className="font-medium leading-tight">InsightEdge Chat</h2>
              <div className="text-[11px] text-muted-foreground">
                Workspace: {workspaceId} | Model: {llmModel}
              </div>
            </div>
          </div>
          <div className="md:hidden">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              className="h-8 w-8"
            >
              {theme === "light" ? (
                <Moon className="h-4 w-4" />
              ) : (
                <Sun className="h-4 w-4" />
              )}
            </Button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {conversation.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground space-y-4 opacity-50">
              <Bot className="h-12 w-12" />
              <p>Start asking questions about your documents.</p>
            </div>
          ) : (
            conversation.map((msg, idx) => (
              <div
                key={idx}
                className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
              >
                <div
                  className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${msg.role === "user" ? "bg-primary text-primary-foreground border border-primary" : "bg-muted border border-border"}`}
                >
                  {msg.role === "user" ? (
                    <User className="h-5 w-5" />
                  ) : (
                    <Bot className="h-5 w-5" />
                  )}
                </div>
                <div className={`space-y-2 max-w-[80%]`}>
                  <Card
                    className={`text-sm leading-relaxed shadow-sm border-0 ${
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground rounded-tr-none"
                        : "bg-card text-card-foreground border border-border/50 rounded-tl-none"
                    }`}
                  >
                    <CardContent className="p-4">{msg.content}</CardContent>
                  </Card>
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="text-xs text-muted-foreground bg-muted/50 border rounded-md p-3 space-y-1">
                      <div className="font-semibold mb-1 flex items-center gap-1">
                        <FileText className="h-3 w-3" /> Sources
                      </div>
                      {msg.citations.map((cit, i) => (
                        <div key={i} className="rounded-md border bg-background/70 p-2 space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium truncate">
                              {cit.filename || cit.source || cit}
                            </span>
                            {typeof cit.score === "number" && (
                              <span className="shrink-0 text-[10px]">
                                score {cit.score.toFixed(3)}
                              </span>
                            )}
                          </div>
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
                            {cit.page_number && <span>Page {cit.page_number}</span>}
                            {cit.section_title && <span>{cit.section_title}</span>}
                            {cit.retrieval_rank && <span>Rank {cit.retrieval_rank}</span>}
                            {cit.source_type && <span>{cit.source_type}</span>}
                            {cit.ocr_used && <span>OCR-derived</span>}
                          </div>
                          {cit.snippet && (
                            <div className="text-[11px] text-foreground/80 line-clamp-3">
                              {cit.snippet}
                            </div>
                          )}
                        </div>
                      ))}
                      {(msg.request_id || msg.retrieval_mode || msg.final_context_chunks !== undefined) && (
                        <div className="pt-1 text-[10px] text-muted-foreground">
                          {msg.retrieval_mode && <span>Retrieval: {msg.retrieval_mode}. </span>}
                          {msg.final_context_chunks !== undefined && (
                            <span>Context chunks: {msg.final_context_chunks}. </span>
                          )}
                          {msg.latency_ms !== undefined && <span>Latency: {msg.latency_ms} ms. </span>}
                          {msg.request_id && <span>Request: {msg.request_id}</span>}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {isAsking && (
            <div className="flex gap-4">
              <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0 border border-border">
                <Bot className="h-5 w-5" />
              </div>
              <div className="bg-card border p-4 rounded-lg rounded-tl-none shadow-sm">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            </div>
          )}
          <div ref={scrollRef} />
        </div>

        {/* Input Area */}
        <div className="p-4 border-t bg-background">
          <div className="max-w-4xl mx-auto relative flex gap-2">
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleAsk();
                }
              }}
              placeholder="Message InsightEdge..."
              className="min-h-12.5 max-h-50 pr-12 resize-none py-3 shadow-sm border-input focus-visible:ring-1"
            />
            <Button
              size="icon"
              className="absolute right-2 bottom-2 h-8 w-8 shadow-sm"
              onClick={handleAsk}
              disabled={!question.trim() || isAsking}
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
          <div className="text-center text-[10px] text-muted-foreground mt-2">
            InsightEdge can make mistakes. Verify important information.
          </div>
        </div>
      </main>
    </div>
  );
}
