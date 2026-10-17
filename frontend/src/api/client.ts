/**
 * Single HTTP entry point. Every backend call in the app goes through
 * apiFetch so the base URL, API key, timeout, and error taxonomy live in
 * exactly one place.
 *
 * AbortController is skipped in test mode: jsdom's fetch rejects signals
 * created by Node's AbortController as "not an instance of AbortSignal",
 * which breaks every MSW-intercepted request. Test requests are fast and
 * are intercepted before hitting the network, so no timeout is needed there.
 */

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

const API_KEY: string =
  (import.meta.env.VITE_API_KEY as string | undefined) ?? "";

const DEFAULT_TIMEOUT_MS = 45_000;

import type { TenantContext } from "./types";

export const PRESET_TENANTS: TenantContext[] = [
  {
    tenantId: "tenant_acme",
    tenantName: "Acme Bank",
    userId: "alice_analyst",
    userName: "Alice Morgan",
    userRole: "analyst",
  },
  {
    tenantId: "tenant_fintech",
    tenantName: "FinTech Global",
    userId: "bob_analyst",
    userName: "Bob Vance",
    userRole: "analyst",
  },
  {
    tenantId: "global",
    tenantName: "Global Compliance (Admin)",
    userId: "system_admin",
    userName: "Sultan",
    userRole: "admin",
  },
];

const TENANT_STORAGE_KEY = "citerator_tenant_context";

export function getTenantContext(): TenantContext {
  if (typeof window === "undefined" || !window.localStorage) {
    return PRESET_TENANTS[0];
  }
  try {
    const raw = window.localStorage.getItem(TENANT_STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // fallback
  }
  return PRESET_TENANTS[0];
}

export function setTenantContext(ctx: TenantContext): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.setItem(TENANT_STORAGE_KEY, JSON.stringify(ctx));
    window.dispatchEvent(new CustomEvent("citerator_tenant_changed", { detail: ctx }));
  } catch {
    // ignore
  }
}

const IS_TEST_MODE: boolean =
  typeof import.meta !== "undefined" &&
  ((import.meta.env as { MODE?: string } | undefined)?.MODE === "test" ||
    Boolean((import.meta.env as { VITEST?: unknown } | undefined)?.VITEST));

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

export interface ApiResult<T> {
  data: T;
  traceId: string | null;
}

interface FetchOptions extends Omit<RequestInit, "signal"> {
  timeoutMs?: number;
}

function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (detail && typeof detail === "object" && "msg" in detail) {
    const msg = (detail as { msg?: string }).msg;
    if (msg) return msg;
  }
  return fallback;
}

export async function apiFetch<T>(
  path: string,
  init: FetchOptions = {}
): Promise<ApiResult<T>> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers: initHeaders, ...rest } = init;

  const controller = IS_TEST_MODE ? null : new AbortController();
  const timer = controller
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;

  const headers = new Headers(initHeaders);
  if (API_KEY && !headers.has("X-API-Key")) {
    headers.set("X-API-Key", API_KEY);
  }
  const tenantCtx = getTenantContext();
  if (tenantCtx?.tenantId && !headers.has("X-Tenant-Id")) {
    headers.set("X-Tenant-Id", tenantCtx.tenantId);
  }
  if (tenantCtx?.userId && !headers.has("X-User-Id")) {
    headers.set("X-User-Id", tenantCtx.userId);
  }
  if (tenantCtx?.userRole && !headers.has("X-User-Role")) {
    headers.set("X-User-Role", tenantCtx.userRole);
  }
  const isFormData =
    typeof FormData !== "undefined" && rest.body instanceof FormData;
  if (rest.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const requestInit: RequestInit = { ...rest, headers };
  if (controller) {
    requestInit.signal = controller.signal;
  }

  try {
    const response = await fetch(`${BASE_URL}${path}`, requestInit);

    const traceId =
      response.headers.get("X-Trace-Id") ?? response.headers.get("x-trace-id");

    if (response.status === 204) {
      return { data: undefined as unknown as T, traceId };
    }

    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }

    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body
          ? (body as { detail: unknown }).detail
          : body;
      throw new ApiError(
        response.status,
        detail,
        describeDetail(detail, `Request failed with status ${response.status}`)
      );
    }

    return { data: body as T, traceId };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as Error).name === "AbortError") {
      throw new ApiError(0, null, "Request timed out. The server may be busy.");
    }
    throw new ApiError(
      0,
      null,
      (err as Error).message || "Unable to reach the API."
    );
  } finally {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
  }
}

export const apiConfig = { baseUrl: BASE_URL };