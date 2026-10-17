import { cn } from "@/lib/cn";

export interface CitationChipProps {
  index: number;
  onClick: () => void;
  active?: boolean;
}

export function CitationChip({ index, onClick, active }: CitationChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Open source ${index}`}
      className={cn(
        "mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded border px-1 align-super font-mono text-2xs transition-colors",
        active
          ? "border-accent bg-accent-soft text-accent"
          : "border-border-strong bg-surface text-secondary hover:border-accent hover:text-accent"
      )}
    >
      [{index}]
    </button>
  );
}