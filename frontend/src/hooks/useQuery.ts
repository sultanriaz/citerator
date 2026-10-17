import { useCallback, useState } from "react";
import { ApiError } from "@/api/client";
import { postQuery } from "@/api/query";
import type { QueryRequest, QueryResponse } from "@/api/types";

export interface QueryTurn {
  id: string;
  question: string;
  request: QueryRequest;
  status: "pending" | "success" | "error";
  response?: QueryResponse;
  traceId?: string | null;
  error?: string;
}

export function useQuery() {
  const [turns, setTurns] = useState<QueryTurn[]>([]);
  const [inFlight, setInFlight] = useState(false);

  const submit = useCallback(async (request: QueryRequest) => {
    const id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    const turn: QueryTurn = {
      id,
      question: request.question,
      request,
      status: "pending",
    };
    setTurns((prev) => [...prev, turn]);
    setInFlight(true);

    try {
      const { data, traceId } = await postQuery(request);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id
            ? { ...t, status: "success", response: data, traceId }
            : t
        )
      );
      return { id, response: data, traceId };
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.";
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, status: "error", error: message } : t
        )
      );
      return { id, error: message };
    } finally {
      setInFlight(false);
    }
  }, []);

  const retry = useCallback(
    async (turnId: string) => {
      const target = turns.find((t) => t.id === turnId);
      if (!target) return;
      setTurns((prev) => prev.filter((t) => t.id !== turnId));
      await submit(target.request);
    },
    [turns, submit]
  );

  return { turns, inFlight, submit, retry };
}