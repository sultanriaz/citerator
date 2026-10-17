import type { LucideIcon } from "lucide-react";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-muted" aria-hidden />
      <h3 className="mt-3 text-sm font-medium text-primary">{title}</h3>
      {description && (
        <p className="mt-1 max-w-md text-xs text-secondary">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}