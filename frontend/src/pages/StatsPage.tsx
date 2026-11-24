import { Link } from "react-router-dom";
import { BarChart, type BarRow } from "../components/BarChart";
import { ErrorState, Loading } from "../components/Feedback";
import { getStats } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { CountRow, Stats } from "../lib/types";
import { useApi } from "../lib/useApi";
import { useDocumentTitle } from "../lib/useDocumentTitle";

export default function StatsPage() {
  useDocumentTitle("Coverage");
  const stats = useApi((signal) => getStats(signal), []);

  return (
    <>
      <div className="intro">
        <h1>What the data covers</h1>
        <p className="lede">Everything here comes from the facilities collected from NHPR so far.</p>
      </div>
      {stats.status === "loading" && <Loading label="Loading figures…" />}
      {stats.status === "error" && <ErrorState error={stats.error} onRetry={stats.retry} />}
      {stats.status === "success" && <Figures stats={stats.data} />}
    </>
  );
}

function Figures({ stats }: { stats: Stats }) {
  const withIcuShare = stats.totalFacilities
    ? Math.round((stats.facilitiesWithIcu / stats.totalFacilities) * 100)
    : 0;

  return (
    <>
      <dl className="tiles">
        <Tile label="Facilities" value={formatNumber(stats.totalFacilities)} />
        <Tile label="States" value={formatNumber(stats.byState.length)} />
        <Tile label="Beds published" value={formatNumber(stats.totalBeds)} />
        <Tile
          label="Offer ICU services"
          value={formatNumber(stats.facilitiesWithIcu)}
          note={`${withIcuShare}% of facilities`}
        />
      </dl>

      <div className="charts">
        <BarChart
          title="Facilities by state"
          rows={toBars(stats.byState)}
          unit="facilities"
        />
        <BarChart
          title="Facilities by type"
          description="The eight most common types; the rest are grouped as Other."
          rows={topWithOther(toBars(stats.byFacilityType), 8)}
          unit="facilities"
        />
        <BarChart title="Facilities by ownership" rows={toBars(stats.byOwnership)} unit="facilities" />
      </div>

      <section className="panel" aria-labelledby="beds-heading">
        <h2 id="beds-heading">Bed capacity by district</h2>
        <p className="muted">
          Beds as published on NHPR. Many facilities publish none, so treat these as lower bounds.
        </p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">District</th>
                <th scope="col">State</th>
                <th scope="col" className="num">Facilities</th>
                <th scope="col" className="num">Beds</th>
                <th scope="col" className="num">ICU beds</th>
              </tr>
            </thead>
            <tbody>
              {stats.bedsByDistrict.slice(0, 15).map((row) => (
                <tr key={row.code}>
                  <th scope="row">
                    <Link to={`/?state=${row.stateCode}&district=${row.code}`}>
                      {row.name}
                    </Link>
                  </th>
                  <td>{row.stateName}</td>
                  <td className="num">{formatNumber(row.facilities)}</td>
                  <td className="num">{formatNumber(row.totalBeds)}</td>
                  <td className="num">{formatNumber(row.icuBeds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile">
      <dt>{label}</dt>
      <dd>
        <span className="tile__value">{value}</span>
        {note && <span className="tile__note">{note}</span>}
      </dd>
    </div>
  );
}

function toBars(rows: CountRow[]): BarRow[] {
  return rows.map((row) => ({ label: row.name, value: row.facilities }));
}

function topWithOther(rows: BarRow[], keep: number): BarRow[] {
  if (rows.length <= keep + 1) return rows;
  const rest = rows.slice(keep).reduce((sum, row) => sum + row.value, 0);
  return [...rows.slice(0, keep), { label: "Other", value: rest }];
}
