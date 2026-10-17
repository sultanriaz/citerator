import { useEffect, useState } from "react";
import { useTheme } from "@/hooks/useTheme";

type Density = "comfortable" | "compact";
const DENSITY_KEY = "citerator.density";

export function AppearanceTab() {
  const { theme, setTheme } = useTheme();
  const [density, setDensity] = useState<Density>(() =>
    (localStorage.getItem(DENSITY_KEY) as Density) || "comfortable"
  );

  useEffect(() => {
    localStorage.setItem(DENSITY_KEY, density);
  }, [density]);

  return (
    <div className="rounded-xl border border-border bg-surface p-6">
      <h2 className="text-lg font-semibold text-primary">Your workspace, your way.</h2>

      <div className="mt-6 space-y-5 max-w-lg">
        <label className="block">
          <div className="mb-1.5 text-xs font-medium text-primary">Theme</div>
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value as "light" | "dark")}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>

        <label className="block">
          <div className="mb-1.5 text-xs font-medium text-primary">Density</div>
          <select
            value={density}
            onChange={(e) => setDensity(e.target.value as Density)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none"
          >
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </select>
        </label>

        <p className="text-2xs text-secondary">
          Comfortable spacing gives complex evidence room to breathe. Compact mode fits more
          table rows on screen.
        </p>
      </div>
    </div>
  );
}