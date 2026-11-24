import { useCallback, useEffect, useState, type DependencyList } from "react";
import { ApiError } from "./api";

export type Loadable<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "success"; data: T };

/**
 * Run `load` whenever `deps` change and track its state. Pass `null` to do
 * nothing (for example, no districts to load until a state is picked).
 * A newer request aborts the older one, so a slow response can never
 * overwrite a fresh one.
 */
export function useApi<T>(
  load: ((signal: AbortSignal) => Promise<T>) | null,
  deps: DependencyList,
): Loadable<T> & { retry: () => void } {
  const [state, setState] = useState<Loadable<T>>(load ? { status: "loading" } : { status: "idle" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!load) {
      setState({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    load(controller.signal).then(
      (data) => setState({ status: "success", data }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          error:
            error instanceof ApiError
              ? error
              : new ApiError(0, "unexpected", "Something went wrong. Please try again."),
        });
      },
    );
    return () => controller.abort();
    // `load` is a fresh closure on every render; `deps` says when it really changed.
  }, [...deps, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
