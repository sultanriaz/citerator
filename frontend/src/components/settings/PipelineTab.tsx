import { useEffect, useState } from "react";
import { getPipelineSettings, updatePipelineSettings, previewThreshold } from "@/api/settings";
import type { PipelineSettings, ThresholdPreview } from "@/api/types";
import { Toast } from "@/components/shared/Toast";
import { ShieldCheck } from "lucide-react";

const STRATEGIES = ["structure", "semantic", "fixed"] as const;
const STRATEGY_LABEL: Record<string, string> = {
  structure: "Structure-aware",
  semantic: "Semantic",
  fixed: "Fixed-size",
};

export function PipelineTab() {
  const [settings, setSettings] = useState<PipelineSettings | null>(null);
  const [preview, setPreview] = useState<ThresholdPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    getPipelineSettings().then(setSettings).catch((e) =>
      setToast({ tone: "error", message: e.message })
    );
  }, []);

  async function update(patch: Partial<PipelineSettings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      const saved = await updatePipelineSettings(patch);
      setSettings(saved);
      setToast({ tone: "success", message: "Saved" });
    } catch (e) {
      setToast({ tone: "error", message: e instanceof Error ? e.message : "Save failed" });
      const fresh = await getPipelineSettings();
      setSettings(fresh);
    }
  }

  async function refreshPreview(threshold: number, floor: number) {
    setBusy(true);
    try {
      const p = await previewThreshold(threshold, floor);
      setPreview(p);
    } catch {
      // preview is best-effort
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return <p className="text-xs text-secondary">Loading...</p>;

  const total = preview?.total ?? 120;
  const confident = preview?.confident ?? Math.round(total * (settings.confidence_threshold));
  const escalated = total - confident;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
      <div className="space-y-6">
        <div className="rounded-xl border border-border bg-surface p-6">
          <h2 className="text-lg font-semibold text-primary">
            Evidence-first, by configuration.
          </h2>
          <p className="mt-1 text-xs text-secondary">
            Control how documents become grounded answers.
          </p>

          <div className="mt-6 space-y-5">
            <label className="block">
              <div className="mb-1.5 text-xs font-medium text-primary">Chunking strategy</div>
              <select
                value={settings.active_chunking_strategy}
                onChange={(e) => update({ active_chunking_strategy: e.target.value })}
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
              >
                {STRATEGIES.map((s) => (
                  <option key={s} value={s}>{STRATEGY_LABEL[s]}</option>
                ))}
              </select>
            </label>

            <div>
              <div className="mb-1.5 flex items-center text-xs">
                <span className="font-medium text-primary">Chunk size</span>
                <span className="ml-auto text-2xs text-muted">requires re-ingestion</span>
              </div>
              <input type="range" disabled value={384} readOnly className="w-full accent-accent opacity-50" />
              <div className="mt-1 flex justify-between text-2xs text-secondary">
                <span>384 tokens</span>
              </div>
            </div>

            <div>
              <div className="mb-1.5 flex items-center text-xs">
                <span className="font-medium text-primary">Chunk overlap</span>
                <span className="ml-auto text-2xs text-muted">requires re-ingestion</span>
              </div>
              <input type="range" disabled value={48} readOnly className="w-full accent-accent opacity-50" />
              <div className="mt-1 flex justify-between text-2xs text-secondary">
                <span>48 tokens</span>
              </div>
            </div>

            <div>
              <div className="mb-1.5 flex items-center text-xs">
                <span className="font-medium text-primary">Retrieval top-k</span>
                <span className="ml-auto font-mono text-2xs text-accent">{settings.top_k_retrieve} chunks</span>
              </div>
              <input
                type="range"
                min={5}
                max={50}
                step={1}
                value={settings.top_k_retrieve}
                onChange={(e) => setSettings({ ...settings, top_k_retrieve: Number(e.target.value) })}
                onMouseUp={() => update({ top_k_retrieve: settings.top_k_retrieve })}
                onTouchEnd={() => update({ top_k_retrieve: settings.top_k_retrieve })}
                className="w-full accent-accent"
              />
            </div>

            <div>
              <div className="mb-1.5 flex items-center text-xs">
                <span className="font-medium text-primary">Rerank top-k</span>
                <span className="ml-auto font-mono text-2xs text-accent">{settings.top_k_rerank} chunks</span>
              </div>
              <input
                type="range"
                min={1}
                max={20}
                step={1}
                value={settings.top_k_rerank}
                onChange={(e) => setSettings({ ...settings, top_k_rerank: Number(e.target.value) })}
                onMouseUp={() => update({ top_k_rerank: settings.top_k_rerank })}
                onTouchEnd={() => update({ top_k_rerank: settings.top_k_rerank })}
                className="w-full accent-accent"
              />
            </div>

            <div>
              <div className="mb-1.5 flex items-center text-xs">
                <span className="font-medium text-primary">Confidence threshold</span>
                <span className="ml-auto font-mono text-2xs text-accent">
                  {Math.round(settings.confidence_threshold * 100)} %
                </span>
              </div>
              <input
                type="range"
                min={0.05}
                max={0.95}
                step={0.01}
                value={settings.confidence_threshold}
                onChange={(e) => setSettings({ ...settings, confidence_threshold: Number(e.target.value) })}
                onMouseUp={() => {
                  update({ confidence_threshold: settings.confidence_threshold });
                  void refreshPreview(settings.confidence_threshold, settings.confidence_floor);
                }}
                className="w-full accent-accent"
              />
            </div>
          </div>

          <div className="mt-6 rounded-lg border border-accent/20 bg-accent-soft/40 p-4">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
              <div className="flex-1">
                <div className="text-xs font-medium text-primary">
                  Below {Math.round(settings.confidence_threshold * 100)}%, a human steps in.
                </div>
                <p className="mt-1 text-2xs text-secondary">
                  At this threshold, approximately <span className="text-accent font-medium">{confident}</span> benchmark
                  questions are answered and <span className="text-warning font-medium">{escalated}</span> are escalated.
                </p>
                <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-border">
                  <div
                    className="bg-accent"
                    style={{ width: `${(confident / total) * 100}%` }}
                  />
                  <div
                    className="bg-warning"
                    style={{ width: `${(escalated / total) * 100}%` }}
                  />
                </div>
                <div className="mt-2 text-2xs text-muted">
                  Illustrative preview · {total} evaluation questions
                  {busy && " · updating..."}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <aside className="rounded-xl border border-border bg-surface p-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-md border border-accent/30 bg-accent-soft">
          <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
        </div>
        <h3 className="mt-4 text-sm font-medium text-primary">
          A deliberate safety boundary.
        </h3>
        <p className="mt-3 text-2xs leading-relaxed text-secondary">
          Your pipeline never has to guess. When retrieval quality falls below your
          threshold, Citerator routes the question to a person.
        </p>
        <div className="mt-6 text-2xs font-medium uppercase tracking-wider text-muted">
          Precision over completion
        </div>
      </aside>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 w-80">
          <Toast tone={toast.tone} message={toast.message} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}