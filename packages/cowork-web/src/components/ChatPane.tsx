import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../hooks/useChat";
import { ToolCallCard } from "./ToolCallCard";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (text: string) => void;
}

export function ChatPane({ messages, sending, onSend }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    onSend(input);
    setInput("");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-gray-400 text-center mt-20">
            Send a message to get started.
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i}>
            {/* User message */}
            {msg.role === "user" && (
              <div className="flex justify-end">
                <div className="bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2 max-w-[80%] whitespace-pre-wrap">
                  {msg.text}
                </div>
              </div>
            )}
            {/* Assistant message */}
            {msg.role === "assistant" && (
              <div className="flex justify-start">
                <div className="max-w-[85%] space-y-2">
                  {msg.thought && (
                    <details className="text-xs text-gray-500 dark:text-gray-400 border-l-2 border-gray-300 dark:border-gray-600 pl-3">
                      <summary className="cursor-pointer select-none italic">
                        thinking…
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
                    <div className="bg-gray-100 dark:bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2 prose prose-sm dark:prose-invert max-w-none">
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
            <div className="bg-gray-100 dark:bg-gray-800 rounded-2xl px-4 py-2 text-gray-400 animate-pulse">
              ...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-gray-200 dark:border-gray-700 p-3 flex gap-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={sending}
          className="flex-1 px-4 py-2 rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          autoFocus
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </form>
    </div>
  );
}
