import { useState } from "react";
import { TopBar } from "@/components/layout/TopBar";
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { PipelineTab } from "@/components/settings/PipelineTab";
import { ApiTab } from "@/components/settings/ApiTab";
import { ModelsTab } from "@/components/settings/ModelsTab";
import { AppearanceTab } from "@/components/settings/AppearanceTab";

type Tab = "pipeline" | "api" | "models" | "appearance";

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("pipeline");

  return (
    <div className="flex h-full flex-col">
      <TopBar
        breadcrumbs={["Workspace", "Settings"]}
        rightSlot={
          <button
            type="button"
            disabled
            title="Changes save automatically"
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground opacity-90 cursor-default"
          >
            <Check className="h-3.5 w-3.5" aria-hidden />
            Save changes
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <header className="mb-5">
          <h1 className="text-2xl font-semibold tracking-tight text-primary">Settings</h1>
          <p className="mt-1 text-xs text-secondary">
            Configure a pipeline that matches your compliance standards.
          </p>
        </header>

        <nav className="mb-6 flex gap-6 border-b border-border text-xs">
          {(["pipeline", "api", "models", "appearance"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "-mb-px border-b-2 px-1 pb-3 font-medium transition-colors capitalize",
                tab === t
                  ? "border-accent text-accent"
                  : "border-transparent text-secondary hover:text-primary"
              )}
            >
              {t}
            </button>
          ))}
        </nav>

        {tab === "pipeline" && <PipelineTab />}
        {tab === "api" && <ApiTab />}
        {tab === "models" && <ModelsTab />}
        {tab === "appearance" && <AppearanceTab />}
      </div>
    </div>
  );
}