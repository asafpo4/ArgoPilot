import "server-only";

export class ServiceError extends Error {
  constructor(
    public readonly kind: "unreachable" | "bad-status" | "bad-body",
    public readonly status?: number,
  ) {
    super(kind);
  }
}

/** Server-side fetch with a hard timeout and no caching. Never exposes the URL in its errors. */
export async function getJson<T>(url: string, timeoutMs: number): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw new ServiceError("unreachable");
  }
  if (!res.ok) throw new ServiceError("bad-status", res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ServiceError("bad-body");
  }
}
