/**
 * The search lives in the URL, so results can be bookmarked, shared and
 * reached with the back button. The URL uses the API's own parameter names,
 * which keeps the mapping trivial: the query string we show is the query
 * string we send.
 */

export type SearchBy = "name" | "facilityType" | "facilityId" | "systemOfMedicine";
export type SortOption = "" | "name" | "district" | "beds";
export type IcuOption = "" | "yes" | "no";

export interface SearchState {
  state: string;
  district: string;
  searchBy: SearchBy;
  query: string;
  ownership: string;
  icu: IcuOption;
  speciality: string;
  sort: SortOption;
  page: number;
  pageSize: number;
}

export const SEARCH_BY_OPTIONS: { value: SearchBy; label: string }[] = [
  { value: "name", label: "Facility name" },
  { value: "facilityType", label: "Facility type" },
  { value: "facilityId", label: "Facility ID" },
  { value: "systemOfMedicine", label: "System of medicine" },
];

export const DEFAULT_PAGE_SIZE = 10;
const MAX_PAGE_SIZE = 50;
const FACILITY_ID = /^IN\d{10}$/i;

export const EMPTY_SEARCH: SearchState = {
  state: "",
  district: "",
  searchBy: "name",
  query: "",
  ownership: "",
  icu: "",
  speciality: "",
  sort: "",
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
};

export function readSearch(params: URLSearchParams): SearchState {
  const text = (key: string) => params.get(key)?.trim() ?? "";
  const searchBy = SEARCH_BY_OPTIONS.find((option) => text(option.value))?.value ?? "name";
  const icu = text("icu");
  const sort = text("sort");

  return {
    state: text("state"),
    district: text("state") ? text("district") : "",
    searchBy,
    query: text(searchBy),
    ownership: text("ownership"),
    icu: icu === "yes" || icu === "no" ? icu : "",
    speciality: text("speciality"),
    sort: sort === "name" || sort === "district" || sort === "beds" ? sort : "",
    page: wholeNumber(text("page"), 1, Number.MAX_SAFE_INTEGER, 1),
    pageSize: wholeNumber(text("pageSize"), 1, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE),
  };
}

/** The query string for both the browser URL and the API call. Defaults are left out. */
export function writeSearch(search: SearchState): URLSearchParams {
  const params = new URLSearchParams();
  const put = (key: string, value: string) => {
    if (value.trim()) params.set(key, value.trim());
  };
  put("state", search.state);
  if (search.state) put("district", search.district);
  put(search.searchBy, search.query);
  put("ownership", search.ownership);
  put("icu", search.icu);
  put("speciality", search.speciality);
  put("sort", search.sort);
  if (search.page > 1) params.set("page", String(search.page));
  if (search.pageSize !== DEFAULT_PAGE_SIZE) params.set("pageSize", String(search.pageSize));
  return params;
}

/** Sorting and paging alone don't make a search; the API refuses those too. */
export function hasCriteria(search: SearchState): boolean {
  return [search.state, search.district, search.query, search.ownership, search.icu, search.speciality]
    .some((value) => value.trim() !== "");
}

export function activeFilterCount(search: SearchState): number {
  return [search.ownership, search.icu, search.speciality].filter(Boolean).length;
}

/** A message for the person searching, or null when the search can go ahead. */
export function validateSearch(search: SearchState): string | null {
  const query = search.query.trim();
  if (!hasCriteria(search)) {
    return "Choose a state, or enter something to search for.";
  }
  if (search.searchBy === "facilityId" && query && !FACILITY_ID.test(query)) {
    return "A facility ID is IN followed by 10 digits, for example IN0310000334.";
  }
  if (search.searchBy === "name" && query.length === 1) {
    return "Type at least 2 letters of the facility name.";
  }
  return null;
}

function wholeNumber(text: string, min: number, max: number, fallback: number): number {
  if (!/^\d+$/.test(text)) return fallback;
  const value = Number(text);
  return value >= min && value <= max ? value : fallback;
}
