import { useEffect, useRef, useState } from "react";
import { getHealth } from "@/api/health";
import type { HealthResponse } from "@/api/types";

export type HealthStatus = "checking" | "healthy" | "unreachable";

const POLL_INTERVAL_MS = 30_000;

export function useHealthStatus() {
  const [status, setStatus] = useState<HealthStatus>("checking");
  const [data, setData] = useState<HealthResponse | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    async function check() {
      try {
        const result = await getHealth();
        if (!mounted.current) return;
        setData(result);
        setStatus(result.status === "ok" ? "healthy" : "unreachable");
      } catch {
        if (!mounted.current) return;
        setData(null);
        setStatus("unreachable");
      }
    }

    void check();
    const timer = window.setInterval(check, POLL_INTERVAL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, []);

  return { status, data };
}