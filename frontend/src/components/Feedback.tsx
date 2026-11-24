import type { ReactNode } from "react";
import type { ApiError } from "../lib/api";

export function Loading({ label }: { label: string }) {
  return (
    <div className="feedback" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="feedback feedback--empty">
      <p className="feedback__title">{title}</p>
      {children}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const title =
    error.status === 429
      ? "Too many searches in a short time"
      : error.status === 0
        ? "Can't reach the server"
        : "Something went wrong";
  return (
    <div className="feedback feedback--error" role="alert">
      <p className="feedback__title">{title}</p>
      <p>{error.message}</p>
      {onRetry && (
        <button type="button" className="button button--secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
