import { useEffect, useState, useRef } from "react";
import {
  Send,
  Plus,
  FileText,
  Loader2,
  Trash2,
  Paperclip,
  Bot,
  User,
  Moon,
  Sun,
} from "lucide-react";
import { Button } from "@/src/components/ui/button";
import { Input } from "@/src/components/ui/input";
import { Card, CardContent } from "@/src/components/ui/card";
import { Textarea } from "@/src/components/ui/textarea";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api"
).replace(/\/$/, "");
const CHAT_SESSION_KEY = "insightedge_chat_session_id";

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

export default function App() {
  const [files, setFiles] = useState([]);
  const [question, setQuestion] = useState("");
  const [conversation, setConversation] = useState([]);
  const [status, setStatus] = useState("Ready");
  const [isIngesting, setIsIngesting] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [sessionId] = useState(() => getOrCreateSessionId());
  const [theme, setTheme] = useState("light");
  const scrollRef = useRef(null);

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
  }, [theme]);

  function toggleTheme() {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  }

  useEffect(() => {
    async function loadSessionHistory() {
      try {
        const res = await fetchWithTimeout(
          `${API_BASE}/chat/session/${sessionId}`,
          { method: "GET" },
          15000,
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setConversation(data.history || []);
      } catch {
        setConversation([]);
      }
    }
    loadSessionHistory();
  }, [sessionId]);

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

    setIsIngesting(true);
    setStatus("Uploading files...");

    try {
      const createJobRes = await fetchWithTimeout(
        `${API_BASE}/ingest/files`,
        { method: "POST", body: formData },
        30000,
      );
      if (!createJobRes.ok) throw new Error(await createJobRes.text());

      const job = await createJobRes.json();
      setStatus("Processing files...");

      // Poll specifically for this job_id
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetchWithTimeout(
            `${API_BASE}/ingest/jobs/${job.job_id}`,
            { method: "GET" },
            5000,
          );

          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === "completed") {
              clearInterval(pollInterval);
              setIsIngesting(false);
              setStatus("Ingestion complete!");
              setFiles([]);
            } else if (statusData.status === "failed") {
              clearInterval(pollInterval);
              setIsIngesting(false);
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
    }
  }

  async function handleAsk(e) {
    if (e) e.preventDefault();
    if (!question.trim()) return;

    const currentQ = question;
    setQuestion("");
    setIsAsking(true);
    setStatus("Thinking...");

    // Optimistic update
    setConversation((prev) => [...prev, { role: "user", content: currentQ }]);

    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: currentQ,
            session_id: sessionId,
          }),
        },
        60000,
      );

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      setConversation((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer,
          citations: data.citations,
        },
      ]);
      setStatus("Ready");
    } catch (err) {
      console.error(err);
      setStatus("Error asking question.");
      setConversation((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, I encountered an error answering that.",
        },
      ]);
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

  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-80 border-r bg-muted/20 p-4 flex flex-col gap-4 hidden md:flex">
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
                  </div>
                )}
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
          <h2 className="font-medium">New Conversation</h2>
          <div className="md:hidden">
            <Button
              variant="ghost"
              size="icon"
              onClick={() =>
                setTheme((t) => (t === "light" ? "dark" : "light"))
              }
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
                        <div key={i} className="truncate">
                          • {cit.source || cit}
                        </div>
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
              className="min-h-[50px] max-h-[200px] pr-12 resize-none py-3 shadow-sm border-input focus-visible:ring-1"
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
