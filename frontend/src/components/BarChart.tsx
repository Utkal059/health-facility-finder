import { useId, useState } from "react";
import { formatNumber } from "../lib/format";

export interface BarRow {
  label: string;
  value: number;
}

interface Props {
  title: string;
  description?: string;
  rows: BarRow[];
  /** What the values count, in the plural: "facilities", "beds". */
  unit: string;
}

/**
 * A horizontal bar chart in plain HTML and CSS. One series, so no legend: the
 * title names it. Every bar can be hovered or focused for its exact value and
 * share, and the same numbers are one click away as a table.
 */
export function BarChart({ title, description, rows, unit }: Props) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const headingId = useId();
  const max = Math.max(1, ...rows.map((row) => row.value));
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const share = (value: number) => (total ? `${((value / total) * 100).toFixed(1)}%` : "–");

  return (
    <figure className="chart" aria-labelledby={headingId}>
      <div className="chart__header">
        <div>
          <h2 id={headingId} className="chart__title">
            {title}
          </h2>
          {description && <p className="chart__description">{description}</p>}
        </div>
        <button
          type="button"
          className="button button--ghost"
          aria-pressed={view === "table"}
          onClick={() => setView(view === "chart" ? "table" : "chart")}
        >
          {view === "chart" ? "Show as table" : "Show as chart"}
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="muted">No data yet.</p>
      ) : view === "chart" ? (
        <ul className="bars">
          {rows.map((row) => {
            const summary = `${row.label}: ${formatNumber(row.value)} ${unit} (${share(row.value)})`;
            return (
              <li key={row.label} className="bars__row" tabIndex={0} aria-label={summary}>
                <span className="bars__label" aria-hidden="true">
                  {row.label}
                </span>
                <span className="bars__track" aria-hidden="true">
                  <span
                    className="bars__bar"
                    style={{ width: row.value ? `max(2px, ${(row.value / max) * 100}%)` : 0 }}
                  />
                  <span className="bars__value">{formatNumber(row.value)}</span>
                </span>
                <span className="bars__tooltip" aria-hidden="true">
                  {summary}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="visually-hidden">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col" className="num">
                  {unit[0].toUpperCase() + unit.slice(1)}
                </th>
                <th scope="col" className="num">
                  Share
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="num">{formatNumber(row.value)}</td>
                  <td className="num">{share(row.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}
