import type {
  FacilityDetail,
  MasterItem,
  Masters,
  MasterType,
  Place,
  SearchResponse,
  Stats,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

/** Every failure the UI shows goes through this, so error states can be specific. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal, params?: URLSearchParams): Promise<T> {
  const query = params?.toString();
  const url = `${BASE_URL}${path}${query ? `?${query}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, "network_error", "We couldn't reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    // The API always answers errors as {"error": {"code", "message"}}; a proxy might not.
    let code = "http_error";
    let message = `The server answered with an error (${response.status}).`;
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      // not JSON: keep the generic message
    }
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export function searchFacilities(params: URLSearchParams, signal?: AbortSignal) {
  return getJson<SearchResponse>("/api/facilities", signal, params);
}

export function getFacility(facilityId: string, signal?: AbortSignal) {
  return getJson<FacilityDetail>(`/api/facilities/${encodeURIComponent(facilityId)}`, signal);
}

export async function getStates(signal?: AbortSignal) {
  return (await getJson<{ states: Place[] }>("/api/masters/states", signal)).states;
}

export async function getDistricts(stateCode: string, signal?: AbortSignal) {
  const path = `/api/masters/states/${encodeURIComponent(stateCode)}/districts`;
  return (await getJson<{ districts: Place[] }>(path, signal)).districts;
}

const MASTER_TYPES: MasterType[] = ["ownership", "facility-types", "systems-of-medicine", "specialities"];

export async function getMasters(signal?: AbortSignal): Promise<Masters> {
  const lists = await Promise.all(
    MASTER_TYPES.map((type) => getJson<{ items: MasterItem[] }>(`/api/masters/${type}`, signal)),
  );
  return Object.fromEntries(MASTER_TYPES.map((type, i) => [type, lists[i].items])) as Masters;
}

export function getStats(signal?: AbortSignal) {
  return getJson<Stats>("/api/stats", signal);
}
