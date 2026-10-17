import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { getModelsSettings, updateModelsSettings } from "@/api/settings";
import type { ModelsSettings } from "@/api/types";
import { Toast } from "@/components/shared/Toast";

const PROVIDERS = ["gemini", "openai", "anthropic", "fake"] as const;
const PROVIDER_MODELS: Record<string, string[]> = {
  gemini: ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
  openai: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
  anthropic: ["claude-3-haiku-20240307", "claude-3-5-sonnet-latest"],
  fake: ["fake"],
};

export function ModelsTab() {
  const [settings, setSettings] = useState<ModelsSettings | null>(null);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    getModelsSettings().then(setSettings).catch((e) =>
      setToast({ tone: "error", message: e.message })
    );
  }, []);

  async function update(patch: { llm_provider?: string; llm_model?: string; rerank_model?: string }) {
    try {
      const saved = await updateModelsSettings(patch);
      setSettings(saved);
      setToast({ tone: "success", message: "Saved" });
    } catch (e) {
      setToast({ tone: "error", message: e instanceof Error ? e.message : "Save failed" });
      const fresh = await getModelsSettings();
      setSettings(fresh);
    }
  }

  if (!settings) return <p className="text-xs text-secondary">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border bg-surface p-6">
        <h2 className="text-lg font-semibold text-primary">Models &amp; privacy</h2>
        <p className="mt-1 text-xs text-secondary">
          Choose the right balance of cost, quality, and data residency.
        </p>

        <div className="mt-6 space-y-5">
          <label className="block">
            <div className="mb-1.5 text-xs font-medium text-primary">Embedding model</div>
            <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-secondary opacity-70">
              <span className="flex-1">{settings.embedding_model.value} · Local</span>
              <span className="rounded border border-border px-1.5 py-0.5 text-2xs text-muted">
                {settings.embedding_model.reason}
              </span>
            </div>
          </label>

          <label className="block">
            <div className="mb-1.5 text-xs font-medium text-primary">Answer provider</div>
            <select
              value={settings.llm_provider}
              onChange={(e) => {
                const provider = e.target.value;
                const firstModel = PROVIDER_MODELS[provider]?.[0];
                update({ llm_provider: provider, llm_model: firstModel });
              }}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
            >
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <div className="mb-1.5 text-xs font-medium text-primary">Answer model</div>
            <select
              value={settings.llm_model}
              onChange={(e) => update({ llm_model: e.target.value })}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
            >
              {(PROVIDER_MODELS[settings.llm_provider] ?? [settings.llm_model]).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <div className="mb-1.5 text-xs font-medium text-primary">Rerank model</div>
            <input
              type="text"
              defaultValue={settings.rerank_model}
              onBlur={(e) => e.target.value !== settings.rerank_model && update({ rerank_model: e.target.value })}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
            />
          </label>
        </div>

        <div className="mt-6 rounded-lg border border-accent/20 bg-accent-soft/40 p-4">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
            <div>
              <div className="text-xs font-medium text-primary">
                {settings.cost_privacy_note}
              </div>
              <p className="mt-1 text-2xs text-secondary">
                Local embeddings keep document vectors private. Local models have no per-token API fee but
                require infrastructure. API models may send query context to an external provider.
              </p>
            </div>
          </div>
        </div>
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 w-80">
          <Toast tone={toast.tone} message={toast.message} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}