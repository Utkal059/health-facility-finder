import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { mapUrl } from "../lib/format";
import type { FacilitySummary } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

export function FacilityCard({ facility }: { facility: FacilitySummary }) {
  const location = useLocation();
  const headingId = `facility-${facility.facilityId}`;

  return (
    <article className="card" aria-labelledby={headingId}>
      <header className="card__header">
        <h3 id={headingId} className="card__title">
          {/* Remember the search so the details page can link back to it. */}
          <Link to={`/facility/${facility.facilityId}`} state={{ from: location.search }}>
            {facility.facilityName}
          </Link>
        </h3>
        <StatusBadge status={facility.facilityStatus} />
      </header>

      <dl className="card__facts">
        <Fact label="Facility ID" value={<span className="mono">{facility.facilityId}</span>} />
        <Fact label="Ownership" value={facility.ownership} />
        <Fact label="Type" value={facility.facilityType} />
        <Fact label="ICU services" value={facility.hasIcuBeds} />
        <Fact label="ABDM software" value={facility.abdmSoftware} />
        {facility.totalBeds !== null && <Fact label="Beds" value={facility.totalBeds} />}
      </dl>

      <p className="card__address">
        {[facility.address, facility.districtName, facility.stateName].filter(Boolean).join(", ")}
        {facility.pincode && <> &ndash; {facility.pincode}</>}
      </p>

      <p className="card__links">
        <a href={mapUrl(facility)} target="_blank" rel="noopener noreferrer">
          View on map<span className="visually-hidden"> for {facility.facilityName} (opens in a new tab)</span>
        </a>
      </p>
    </article>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{value ?? <span className="muted">Not published</span>}</dd>
    </div>
  );
}
