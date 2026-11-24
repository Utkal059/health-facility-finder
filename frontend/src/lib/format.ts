import type { FacilitySummary } from "./types";

// Indian digit grouping: 1,23,456.
const numberFormat = new Intl.NumberFormat("en-IN");
const dateFormat = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

export function formatNumber(value: number): string {
  return numberFormat.format(value);
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`;
}

/** A Google Maps link: exact coordinates when NHPR has them, otherwise the address. */
export function mapUrl(facility: FacilitySummary): string {
  const query =
    facility.latitude && facility.longitude
      ? `${facility.latitude},${facility.longitude}`
      : [facility.facilityName, facility.address, facility.districtName, facility.stateName, facility.pincode]
          .filter(Boolean)
          .join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}
