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
  PanelRight,
  XCircle,
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
const AUTO_MODEL = "__auto__";
const DEFAULT_LLM_MODEL = AUTO_MODEL;
const LEGACY_DEFAULT_LLM_MODEL = "llama3.1:8b-instruct-q4_K_M";
const LLM_MODEL_PRESETS = [
  "phi3:mini",
  "llama3.1:8b-instruct-q4_K_M",
  "llama3.1:70b-instruct-q4_K_M",
  "phi4:14b",
  "qwen2.5:14b",
  "mistral-small3.1",
];

function renderAssistantContent(content) {
  if (!content) {
    return <span className="text-muted-foreground">Generating response...</span>;
  }

  const normalized = content.replace(
    /\s+(Summary|Key points|Sources|Follow-up):/g,
    "\n$1:",
  );
  const lines = normalized.split(/\r?\n/);
  const blocks = [];
  let bullets = [];

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={"bullets-" + blocks.length} className="list-disc pl-5 space-y-1">
        {bullets.map((bullet, index) => <li key={index}>{bullet}</li>)}
      </ul>,
    );
    bullets = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) {
      flushBullets();
      return;
    }
    const heading = line.match(/^(Summary|Key points|Sources|Follow-up):\s*(.*)$/i);
    if (heading) {
      flushBullets();
      blocks.push(
        <div key={"heading-" + index} className="pt-2 first:pt-0">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-primary">
            {heading[1]}
          </div>
          {heading[2] && <p className="mt-1">{heading[2]}</p>}
        </div>,
      );
      return;
    }
    if (/^[-*]\s+/.test(line)) {
      bullets.push(line.replace(/^[-*]\s+/, ""));
      return;
    }
    flushBullets();
    blocks.push(<p key={"paragraph-" + index}>{line}</p>);
  });
  flushBullets();
  return <div className="space-y-2">{blocks}</div>;
}

function modelLabel(model) {
  return model === AUTO_MODEL ? "Auto (router)" : model;
}

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
  const [activeChatMetadata, setActiveChatMetadata] = useState(null);
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
    () => {
      const saved = localStorage.getItem(LLM_MODEL_KEY);
      return !saved || saved === LEGACY_DEFAULT_LLM_MODEL || saved === "phi3:mini"
        ? DEFAULT_LLM_MODEL
        : saved;
    },
  );
  const [llmModelOptions, setLlmModelOptions] = useState([
    AUTO_MODEL,
    ...LLM_MODEL_PRESETS,
  ]);
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
  const [evidencePanelOpen, setEvidencePanelOpen] = useState(false);
  const [evidenceTab, setEvidenceTab] = useState("evidence");
  const [selectedEvidence, setSelectedEvidence] = useState(null);
  const scrollRef = useRef(null);
  const ingestPollRef = useRef(null);

  function openEvidencePanel(citation, message) {
    setSelectedEvidence({
      citation,
      citations: message?.citations || [],
      metadata: message || activeChatMetadata || {},
    });
    setEvidenceTab("evidence");
    setEvidencePanelOpen(true);
  }

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
            [AUTO_MODEL, ...availableModels, data.llm_model, ...LLM_MODEL_PRESETS].filter(
              Boolean,
            ),
          ),
        );
        setLlmModelOptions(nextOptions);

        const savedModel = localStorage.getItem(LLM_MODEL_KEY);
        const currentModel = savedModel || llmModel;
        if (
          currentModel !== AUTO_MODEL &&
          availableModels.length &&
          !availableModels.includes(currentModel)
        ) {
          setLlmModel(
            availableModels.includes(data.llm_model)
              ? data.llm_model
              : availableModels[0],
          );
        }
      } catch {
        setLlmModelOptions([AUTO_MODEL, ...LLM_MODEL_PRESETS]);
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
          headers: authHeaders({
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          }),
          body: JSON.stringify({
            question: currentQ,
            session_id: sessionId,
            system_prompt: systemPrompt.trim() || undefined,
            workspace_id: workspaceId,
            llm_model: llmModel === AUTO_MODEL ? undefined : llmModel,
          }),
        },
        210000,
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

      const processSseEvent = (eventBlob) => {
        const dataLine = eventBlob
          .split(/\r?\n/)
          .find((line) => line.startsWith("data: "));
        if (!dataLine) return;

        let event;
        try {
          event = JSON.parse(dataLine.slice(6));
        } catch {
          return;
        }

        if (event.type === "token") {
          streamedAnswer += event.token || "";
          applyAssistantUpdate(streamedAnswer);
          } else if (event.type === "final") {
            streamedAnswer = event.answer || streamedAnswer;
            const metadata = {
              citations: event.citations || [],
              model: event.model,
              model_source: event.model_source,
              workspace_id: event.workspace_id,
              retrieval_mode: event.retrieval_mode,
              retrieved_chunks: event.retrieved_chunks,
              final_context_chunks: event.final_context_chunks,
              latency_ms: event.latency_ms,
              request_id: event.request_id,
              query_type: event.query_type,
              complexity_score: event.complexity_score,
              routing_rationale: event.routing_rationale,
              candidate_chunks: event.candidate_chunks,
              confidence: event.confidence,
              groundedness: event.groundedness,
              refusal: event.refusal,
              verification_reason: event.verification_reason,
            };
            setActiveChatMetadata(metadata);
            applyAssistantUpdate(streamedAnswer, metadata);
        } else if (event.type === "error") {
          throw new Error(event.message || "Streaming error");
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split(/\r?\n\r?\n/);
        buffer = events.pop() || "";

        for (const eventBlob of events) {
          processSseEvent(eventBlob);
        }
      }

      if (buffer.trim()) processSseEvent(buffer);

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
        className={`fixed top-0 left-0 z-50 h-full w-80 border-r bg-background p-3 flex flex-col gap-3 transition-transform duration-200 md:hidden ${
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

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain ie-scroll space-y-3 pr-1">
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
                    {modelLabel(model)}
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
                  <div className="ie-scroll space-y-1 max-h-40 overflow-y-auto">
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
      <aside className="w-72 shrink-0 min-h-0 border-r bg-muted/20 p-3 hidden md:flex flex-col gap-3">
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

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain ie-scroll pr-1">
          <div className="space-y-3">
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
                      {modelLabel(model)}
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
                    <div className="ie-scroll space-y-1 max-h-40 overflow-y-auto">
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
      <main className="flex-1 min-w-0 flex flex-col h-full relative transition-colors duration-300">
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
                Workspace: {workspaceId} | Model: {modelLabel(activeChatMetadata?.model || llmModel)}
                {activeChatMetadata?.retrieval_mode && (
                  <> | Retrieval: {activeChatMetadata.retrieval_mode}</>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setEvidencePanelOpen((value) => !value)}
              className="h-8 w-8"
              title="Open evidence and routing panel"
            >
              <PanelRight className="h-4 w-4" />
            </Button>
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
                    <CardContent className="p-4">
                      {msg.role === "assistant" ? (
                        renderAssistantContent(msg.content)
                      ) : (
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      )}
                    </CardContent>
                  </Card>
                  {(msg.citations?.length > 0 || msg.refusal || msg.retrieval_mode) && (
                    <div className="text-xs text-muted-foreground bg-muted/50 border rounded-md p-3 space-y-2">
                      <div className="font-semibold flex items-center gap-1">
                        <FileText className="h-3 w-3" /> Evidence and routing
                      </div>
                      {msg.refusal && (
                        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-800 dark:text-amber-200">
                          Evidence was insufficient, so this answer was withheld or qualified.
                        </div>
                      )}
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
                        {msg.query_type && <span>Type: {msg.query_type}</span>}
                        {msg.retrieval_mode && <span>Retrieval: {msg.retrieval_mode}</span>}
                        {msg.model && <span>Model: {msg.model}</span>}
                        {typeof msg.complexity_score === "number" && <span>Complexity: {msg.complexity_score.toFixed(2)}</span>}
                        {typeof msg.groundedness === "number" && <span>Groundedness: {msg.groundedness.toFixed(2)}</span>}
                        {msg.latency_ms !== undefined && <span>Latency: {msg.latency_ms} ms</span>}
                        {msg.request_id && <span>Request: {msg.request_id}</span>}
                      </div>
                      {msg.routing_rationale && (
                        <div className="text-[10px] text-muted-foreground">
                          Routing rationale: {msg.routing_rationale}
                        </div>
                      )}
                      {msg.citations?.map((cit, i) => (
                        <details key={i} className="rounded-md border bg-background/70 p-2">
                          <summary className="cursor-pointer list-none">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium truncate">
                                {cit.filename || cit.source || "Source " + (i + 1)}
                              </span>
                              {typeof cit.score === "number" && (
                                <span className="shrink-0 text-[10px]">
                                  score {cit.score.toFixed(3)}
                                </span>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
                              {cit.page_number && <span>Page {cit.page_number}</span>}
                              {cit.slide_number && <span>Slide {cit.slide_number}</span>}
                              {cit.section_title && <span>{cit.section_title}</span>}
                              {cit.retrieval_rank && <span>Rank {cit.retrieval_rank}</span>}
                              {cit.source_type && <span>{cit.source_type}</span>}
                              {cit.ocr_used && <span>OCR-derived</span>}
                              {cit.table_used && <span>Table</span>}
                            </div>
                          </summary>
                          <div className="mt-2 space-y-1 text-[11px] text-foreground/80">
                            {cit.snippet && <div>{cit.snippet}</div>}
                            {cit.document_id && <div>Document: {cit.document_id}</div>}
                            {cit.chunk_id && <div>Chunk: {cit.chunk_id}</div>}
                            {(cit.start_char !== undefined || cit.end_char !== undefined) && (
                              <div>Offsets: {cit.start_char ?? "?"} - {cit.end_char ?? "?"}</div>
                            )}
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-[11px]"
                              onClick={() => openEvidencePanel(cit, msg)}
                            >
                              <PanelRight className="mr-1 h-3 w-3" />
                              Open in evidence panel
                            </Button>
                          </div>
                        </details>
                      ))}
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

      {evidencePanelOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/20 xl:hidden"
          onClick={() => setEvidencePanelOpen(false)}
        />
      )}
      {evidencePanelOpen && (
        <aside className="fixed right-0 top-0 z-50 flex h-full w-[min(92vw,24rem)] min-h-0 flex-col border-l bg-background shadow-xl xl:static xl:z-auto xl:w-80 xl:shrink-0 xl:shadow-none">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <div className="text-sm font-semibold">Trust details</div>
              <div className="text-[11px] text-muted-foreground">Evidence and routing for the latest answer</div>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setEvidencePanelOpen(false)} title="Close trust details">
              <XCircle className="h-4 w-4" />
            </Button>
          </div>
          <div className="grid grid-cols-2 border-b p-1">
            <Button type="button" variant={evidenceTab === "evidence" ? "secondary" : "ghost"} size="sm" className="h-8 text-xs" onClick={() => setEvidenceTab("evidence")}>Evidence</Button>
            <Button type="button" variant={evidenceTab === "routing" ? "secondary" : "ghost"} size="sm" className="h-8 text-xs" onClick={() => setEvidenceTab("routing")}>Routing</Button>
          </div>
          <div className="ie-scroll min-h-0 flex-1 overflow-y-auto p-3">
            {evidenceTab === "evidence" ? (
              <div className="space-y-3">
                {(selectedEvidence?.citations || activeChatMetadata?.citations || []).length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">Sources will appear here after a document-grounded answer.</div>
                ) : (
                  <>
                    <div className="space-y-2">
                      {(selectedEvidence?.citations || activeChatMetadata?.citations || []).map((cit, i) => (
                        <button
                          key={cit.chunk_id || i}
                          type="button"
                          className="w-full rounded-md border bg-card p-3 text-left transition hover:bg-muted/60"
                          onClick={() => setSelectedEvidence((previous) => ({ citation: cit, citations: previous?.citations || activeChatMetadata?.citations || [], metadata: previous?.metadata || activeChatMetadata || {} }))}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="truncate text-xs font-medium">{cit.filename || cit.source || "Source " + (i + 1)}</span>
                            <span className="shrink-0 text-[10px] text-muted-foreground">{cit.score == null ? "n/a" : cit.score.toFixed(3)}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                            {cit.page_number != null && <span>Page {cit.page_number}</span>}
                            {cit.slide_number != null && <span>Slide {cit.slide_number}</span>}
                            {cit.section_title && <span>{cit.section_title}</span>}
                            {cit.ocr_used && <span>OCR</span>}
                            {cit.table_used && <span>Table</span>}
                          </div>
                        </button>
                      ))}
                    </div>
                    {selectedEvidence?.citation && (
                      <div className="rounded-md border bg-muted/30 p-3 text-[11px]">
                        <div className="mb-2 text-xs font-semibold">Selected source</div>
                        <p className="whitespace-pre-wrap leading-relaxed">{selectedEvidence.citation.snippet || "No snippet was returned."}</p>
                        <dl className="mt-3 space-y-1 text-muted-foreground">
                          {selectedEvidence.citation.document_id && <div><dt className="inline font-medium">Document: </dt><dd className="inline break-all">{selectedEvidence.citation.document_id}</dd></div>}
                          {selectedEvidence.citation.chunk_id && <div><dt className="inline font-medium">Chunk: </dt><dd className="inline break-all">{selectedEvidence.citation.chunk_id}</dd></div>}
                          {selectedEvidence.citation.source_type && <div><dt className="inline font-medium">Type: </dt><dd className="inline">{selectedEvidence.citation.source_type}</dd></div>}
                          {(selectedEvidence.citation.start_char != null || selectedEvidence.citation.end_char != null) && <div><dt className="inline font-medium">Offsets: </dt><dd className="inline">{selectedEvidence.citation.start_char ?? "?"} - {selectedEvidence.citation.end_char ?? "?"}</dd></div>}
                        </dl>
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div className="space-y-3 text-xs">
                {(() => {
                  const metadata = selectedEvidence?.metadata || activeChatMetadata || {};
                  const rows = [
                    ["Model", modelLabel(metadata.model || llmModel)],
                    ["Model route", metadata.model_source],
                    ["Query type", metadata.query_type],
                    ["Complexity", typeof metadata.complexity_score === "number" ? metadata.complexity_score.toFixed(2) : null],
                    ["Retrieval", metadata.retrieval_mode],
                    ["Candidates", metadata.candidate_chunks],
                    ["Retrieved", metadata.retrieved_chunks],
                    ["Final context", metadata.final_context_chunks],
                    ["Groundedness", typeof metadata.groundedness === "number" ? metadata.groundedness.toFixed(2) : null],
                    ["Confidence", typeof metadata.confidence === "number" ? metadata.confidence.toFixed(2) : null],
                    ["Latency", metadata.latency_ms != null ? String(metadata.latency_ms) + " ms" : null],
                    ["Request ID", metadata.request_id],
                  ];
                  return (
                    <>
                      <div className="rounded-md border bg-muted/30 p-3">
                        <dl className="space-y-2">
                          {rows.filter(([, value]) => value != null && value !== "").map(([label, value]) => <div key={label} className="flex items-start justify-between gap-3"><dt className="text-muted-foreground">{label}</dt><dd className="max-w-[62%] break-words text-right font-medium">{String(value)}</dd></div>)}
                        </dl>
                      </div>
                      {metadata.refusal && <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-amber-800 dark:text-amber-200">This answer was refused or qualified because the evidence was weak.</div>}
                      {metadata.routing_rationale && <div className="rounded-md border p-3 text-muted-foreground"><div className="mb-1 font-medium text-foreground">Why this route</div>{metadata.routing_rationale}</div>}
                      {metadata.verification_reason && <div className="rounded-md border p-3 text-muted-foreground"><div className="mb-1 font-medium text-foreground">Verification</div>{metadata.verification_reason}</div>}
                    </>
                  );
                })()}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
