interface Props {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}

/** First, last, and the pages around the current one: 1 … 4 5 6 … 20 */
export function pageWindow(page: number, pageCount: number): (number | "gap")[] {
  const pages = new Set([1, pageCount, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pageCount));
  const sorted = [...pages].sort((a, b) => a - b);
  return sorted.flatMap((p, i) => (i > 0 && p - sorted[i - 1] > 1 ? ["gap" as const, p] : [p]));
}

export function Pagination({ page, pageCount, onChange }: Props) {
  if (pageCount <= 1) return null;
  return (
    <nav className="pagination" aria-label="Result pages">
      <button type="button" className="button button--secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        Previous<span className="visually-hidden"> page</span>
      </button>
      <ol className="pagination__pages">
        {pageWindow(page, pageCount).map((p, i) =>
          p === "gap" ? (
            <li key={`gap-${i}`} aria-hidden="true" className="pagination__gap">
              …
            </li>
          ) : (
            <li key={p}>
              <button
                type="button"
                className="pagination__page"
                aria-current={p === page ? "page" : undefined}
                onClick={() => p !== page && onChange(p)}
              >
                <span className="visually-hidden">Page </span>
                {p}
              </button>
            </li>
          ),
        )}
      </ol>
      <button
        type="button"
        className="button button--secondary"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        Next<span className="visually-hidden"> page</span>
      </button>
    </nav>
  );
}
