import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { MobileNav } from "./MobileNav";
import { ShieldCheck } from "lucide-react";

export function AppShell() {
  return (
    <div className="flex h-screen w-screen bg-bg text-primary">
      <Sidebar />
      <MobileNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
        <footer className="flex items-center gap-2 border-t border-border bg-bg px-6 py-2 text-2xs text-secondary">
          <ShieldCheck className="h-3.5 w-3.5 text-accent" aria-hidden />
          <span>Decision-support tool, not legal advice. Verify citations before acting.</span>
          <span className="ml-auto font-mono text-muted">Fictional demo data &middot; v0.8.2</span>
        </footer>
      </div>
    </div>
  );
}