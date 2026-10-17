import { useEffect } from "react";
import { X } from "lucide-react";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  width?: string;
}

export function Drawer({ open, onClose, title, children, width = "w-full md:w-[540px]" }: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-label={title}
        className={`relative h-full ${width} overflow-y-auto border-l border-border bg-surface`}
      >
        <header className="sticky top-0 flex items-center border-b border-border bg-surface px-4 py-3">
          <h2 className="truncate text-sm font-medium text-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="ml-auto rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}