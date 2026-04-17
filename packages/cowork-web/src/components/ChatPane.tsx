import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../hooks/useChat";
import { ToolCallCard } from "./ToolCallCard";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, Square } from "lucide-react";

interface Props {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (text: string) => void;
}

export function ChatPane({ messages, sending, onSend }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim() || sending) return;
    onSend(input);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="text-[var(--dls-text-secondary)] text-sm">
              Send a message to get started.
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i}>
            {/* User message */}
            {msg.role === "user" && (
              <div className="flex justify-end">
                <div className="bg-[var(--dls-accent)] text-white rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[80%] whitespace-pre-wrap text-[14px]">
                  {msg.text}
                </div>
              </div>
            )}
            {/* Assistant message */}
            {msg.role === "assistant" && (
              <div className="flex justify-start">
                <div className="max-w-[85%] space-y-2">
                  {msg.thought && (
                    <details className="text-xs text-[var(--dls-text-secondary)] border-l-2 border-[var(--dls-border)] pl-3">
                      <summary className="cursor-pointer select-none italic">
                        thinking...
                      </summary>
                      <div className="mt-1 whitespace-pre-wrap opacity-80">
                        {msg.thought}
                      </div>
                    </details>
                  )}
                  {msg.toolCalls.map((tc) => (
                    <ToolCallCard
                      key={tc.id}
                      entry={tc}
                      onApprove={(s) => onSend(`Approved: ${s}`)}
                      onDeny={(s) => onSend(`Denied: ${s}`)}
                    />
                  ))}
                  {msg.text && (
                    <div className="bg-[var(--dls-surface)] rounded-2xl rounded-bl-sm px-4 py-2.5 prose prose-sm max-w-none shadow-[var(--dls-card-shadow)] text-[var(--dls-text-primary)]">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.text}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-[var(--dls-surface)] rounded-2xl px-4 py-2.5 text-[var(--dls-text-secondary)]">
              <div className="flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--dls-text-secondary)] animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--dls-text-secondary)] animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--dls-text-secondary)] animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="border-t border-[var(--dls-border)] p-3 md:p-4">
        <div className="relative flex items-end gap-2 rounded-2xl border border-[var(--dls-border)] bg-[var(--dls-app-bg)] px-4 py-3 shadow-sm focus-within:ring-2 focus-within:ring-[rgba(var(--dls-accent-rgb),0.2)] focus-within:border-[rgba(var(--dls-accent-rgb),0.4)]">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Shift+Enter for newline)"
            disabled={sending}
            rows={1}
            className="flex-1 resize-none bg-transparent text-[14px] text-[var(--dls-text-primary)] placeholder:text-[var(--dls-text-secondary)] focus:outline-none disabled:opacity-50 max-h-[200px]"
            autoFocus
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={sending || !input.trim()}
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
              input.trim() && !sending
                ? "bg-[var(--dls-accent)] text-white hover:bg-[var(--dls-accent-hover)] shadow-sm"
                : "bg-[var(--dls-hover)] text-[var(--dls-text-secondary)] cursor-not-allowed"
            }`}
            title="Send message"
          >
            {sending ? <Square size={14} /> : <ArrowUp size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
