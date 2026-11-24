export function StatusBadge({ status }: { status: string }) {
  const approved = status.toLowerCase() === "approved";
  return (
    <span className={`badge ${approved ? "badge--approved" : "badge--other"}`}>
      {approved && (
        <svg aria-hidden="true" viewBox="0 0 16 16" width="12" height="12">
          <path d="M6.2 11.6 2.6 8l1.1-1.1 2.5 2.5 6.1-6.1L13.4 4.4z" fill="currentColor" />
        </svg>
      )}
      {status}
    </span>
  );
}
