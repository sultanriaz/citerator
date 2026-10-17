import { useEffect, useState } from "react";
import { Copy, RefreshCw } from "lucide-react";
import { getApiSettings, regenerateApiKey } from "@/api/settings";
import type { ApiSettings } from "@/api/types";
import { Toast } from "@/components/shared/Toast";

export function ApiTab() {
  const [settings, setSettings] = useState<ApiSettings | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    getApiSettings().then(setSettings).catch((e) =>
      setToast({ tone: "error", message: e.message })
    );
  }, []);

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setToast({ tone: "success", message: `${label} copied` });
  }

  async function regenerate() {
    if (!confirm("Regenerate the API key? The current key will stop working immediately.")) return;
    try {
      const r = await regenerateApiKey();
      setNewKey(r.api_key);
      setToast({ tone: "success", message: "New key generated — copy it now" });
      const fresh = await getApiSettings();
      setSettings(fresh);
    } catch (e) {
      setToast({ tone: "error", message: e instanceof Error ? e.message : "Regenerate failed" });
    }
  }

  if (!settings) return <p className="text-xs text-secondary">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border bg-surface p-6">
        <h2 className="text-lg font-semibold text-primary">Workspace API</h2>
        <p className="mt-1 text-xs text-secondary">
          {newKey ? "Copy the new key now — it will not be shown again." : "Demo credentials only. No live API is connected."}
        </p>

        <div className="mt-5">
          <div className="mb-1.5 text-xs font-medium text-primary">API key</div>
          <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2">
            <span className="flex-1 truncate font-mono text-xs text-primary">
              {newKey ?? settings.api_key_masked}
            </span>
            <button
              type="button"
              onClick={() => copy(newKey ?? settings.api_key_masked, "API key")}
              aria-label="Copy API key"
              className="rounded p-1 text-secondary hover:bg-surface hover:text-primary"
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        </div>

        <button
          type="button"
          onClick={regenerate}
          className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-secondary hover:bg-surface-elevated hover:text-primary"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Regenerate key
        </button>

        <p className="mt-3 text-2xs text-secondary">
          Rate limit: {settings.rate_limit.requests_per_minute} requests/minute ·{" "}
          {settings.rate_limit.window_seconds}s window
        </p>
      </div>

      <div className="space-y-3">
        {settings.endpoints.map((e) => (
          <div
            key={`${e.method}-${e.path}`}
            className="rounded-lg border border-border bg-surface p-4"
          >
            <div className="flex items-center gap-2">
              <span className="rounded border border-border px-1.5 py-0.5 font-mono text-2xs uppercase text-accent">
                {e.method}
              </span>
              <span className="font-mono text-xs text-primary">{e.path}</span>
              <button
                type="button"
                onClick={() => copy(e.example, "Example")}
                aria-label={`Copy ${e.path} example`}
                className="ml-auto rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary"
              >
                <Copy className="h-3 w-3" aria-hidden />
              </button>
            </div>
            <p className="mt-2 text-2xs text-secondary">{e.description}</p>
            <pre className="mt-2 truncate rounded bg-bg px-3 py-2 font-mono text-2xs text-secondary">
              {e.example}
            </pre>
          </div>
        ))}
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 w-80">
          <Toast tone={toast.tone} message={toast.message} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}