import { SendHorizontal } from "lucide-react";
import { useState } from "react";

export interface QueryInputProps {
  onSubmit: (question: string) => void;
  disabled?: boolean;
  initialValue?: string;
}

export function QueryInput({ onSubmit, disabled, initialValue = "" }: QueryInputProps) {
  const [value, setValue] = useState(initialValue);

  function handleSubmit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-3 focus-within:border-accent transition-colors">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        disabled={disabled}
        rows={3}
        placeholder="Ask a compliance question..."
        aria-label="Compliance question"
        className="w-full resize-none bg-transparent text-sm text-primary placeholder:text-muted focus:outline-none"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-2xs text-muted">
          Cmd/Ctrl + Enter to send
        </span>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          aria-label="Send question"
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground transition-opacity disabled:opacity-40"
        >
          <SendHorizontal className="h-3.5 w-3.5" aria-hidden />
          Send
        </button>
      </div>
    </div>
  );
}