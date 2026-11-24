import type { ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { EmptyState, ErrorState, Loading } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { getFacility } from "../lib/api";
import { formatDate, formatNumber, mapUrl } from "../lib/format";
import type { FacilityDetail } from "../lib/types";
import { useApi } from "../lib/useApi";
import { useDocumentTitle } from "../lib/useDocumentTitle";

const FACILITY_ID = /^IN\d{10}$/i;

export default function FacilityPage() {
  const { facilityId = "" } = useParams();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  const valid = FACILITY_ID.test(facilityId);

  const facility = useApi(valid ? (signal) => getFacility(facilityId, signal) : null, [facilityId]);
  useDocumentTitle(facility.status === "success" ? facility.data.facilityName : "Facility");

  const back = (
    <p className="back-link">
      <Link to={from ? `/${from}` : "/"}>← {from ? "Back to results" : "New search"}</Link>
    </p>
  );

  if (!valid || (facility.status === "error" && facility.error.status === 404)) {
    return (
      <>
        {back}
        <h1>Facility not found</h1>
        <EmptyState title={`There is no facility with the ID "${facilityId}".`}>
          <p>
            {valid
              ? "It may not have been collected yet, or NHPR may have removed it."
              : "A facility ID is IN followed by 10 digits, for example IN0310000334."}
          </p>
        </EmptyState>
      </>
    );
  }

  return (
    <>
      {back}
      {facility.status === "loading" && <Loading label="Loading facility…" />}
      {facility.status === "error" && <ErrorState error={facility.error} onRetry={facility.retry} />}
      {facility.status === "success" && <Details facility={facility.data} />}
    </>
  );
}

function Details({ facility }: { facility: FacilityDetail }) {
  const coordinates =
    facility.latitude && facility.longitude ? `${facility.latitude}, ${facility.longitude}` : null;

  return (
    <article className="details">
      <header className="details__header">
        <h1>{facility.facilityName}</h1>
        <div className="details__meta">
          <StatusBadge status={facility.facilityStatus} />
          <span className="mono">{facility.facilityId}</span>
        </div>
      </header>

      <div className="details__grid">
        <Section title="Overview">
          <Row label="Ownership" value={facility.ownership} />
          <Row label="Facility type" value={facility.facilityType} />
          <Row label="System of medicine" value={facility.systemsOfMedicine.join(", ") || null} />
          <Row label="Type of service" value={facility.typeOfService} />
          <Row label="ABDM-enabled software" value={facility.abdmSoftware} />
        </Section>

        <Section title="Beds and ICU">
          <Row label="Total beds" value={count(facility.totalBeds)} />
          <Row label="ICU services" value={facility.hasIcuBeds} />
          <Row label="ICU beds" value={count(facility.icuBeds)} />
          <Row label="Ventilators" value={count(facility.ventilators)} />
        </Section>

        <Section title="Location">
          <Row label="Address" value={facility.address} />
          <Row label="Village / town" value={facility.villageCityTownName} />
          <Row label="Sub-district" value={facility.subDistrictName} />
          <Row label="District" value={facility.districtName} />
          <Row label="State" value={facility.stateName} />
          <Row label="Pincode" value={facility.pincode} />
          <Row label="Coordinates" value={coordinates} />
          <Row
            label="Map"
            value={
              <a href={mapUrl(facility)} target="_blank" rel="noopener noreferrer">
                Open in Google Maps<span className="visually-hidden"> (opens in a new tab)</span>
              </a>
            }
          />
        </Section>

        <Section title="Contact">
          <Row label="Phone" value={facility.phone && <a href={`tel:${facility.phone}`}>{facility.phone}</a>} />
          <Row
            label="Website"
            value={
              facility.website && (
                <a href={facility.website} target="_blank" rel="noopener noreferrer nofollow">
                  {facility.website.replace(/^https?:\/\//, "")}
                  <span className="visually-hidden"> (opens in a new tab)</span>
                </a>
              )
            }
          />
        </Section>

        <section className="panel details__wide" aria-labelledby="specialities-heading">
          <h2 id="specialities-heading">Specialities</h2>
          {facility.specialities.length ? (
            <ul className="tags">
              {facility.specialities.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">NHPR lists no specialities for this facility.</p>
          )}
        </section>
      </div>

      <p className="details__source">
        From the public NHPR facility search. First seen {formatDate(facility.firstSeenAt)}, last
        updated {formatDate(facility.lastSeenAt)}.
      </p>
    </article>
  );
}

function count(value: number | null) {
  return value === null ? null : formatNumber(value);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `section-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section className="panel" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <dl className="rows">{children}</dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rows__row">
      <dt>{label}</dt>
      <dd>{value ?? <span className="muted">Not published</span>}</dd>
    </div>
  );
}
