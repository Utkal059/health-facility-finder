import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { getDistricts, getMasters, getStates } from "../lib/api";
import { formatNumber } from "../lib/format";
import {
  EMPTY_SEARCH,
  SEARCH_BY_OPTIONS,
  activeFilterCount,
  validateSearch,
  writeSearch,
  type IcuOption,
  type SearchBy,
  type SearchState,
} from "../lib/searchParams";
import type { MasterItem, Place } from "../lib/types";
import { useApi } from "../lib/useApi";

interface Props {
  current: SearchState;
  onSearch: (search: SearchState) => void;
  onReset: () => void;
}

const QUERY_PLACEHOLDERS: Partial<Record<SearchBy, string>> = {
  name: "e.g. Civil Hospital",
  facilityId: "e.g. IN0310000334",
};

export function SearchForm({ current, onSearch, onReset }: Props) {
  const [draft, setDraft] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(() => activeFilterCount(current) > 0);
  const queryRef = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const ids = useId();

  // Follow the URL when it changes underneath us (back/forward, a shared link).
  const currentKey = writeSearch(current).toString();
  useEffect(() => {
    setDraft(current);
    setError(null);
    // `current` is a new object on every render; `currentKey` says when it really changed.
  }, [currentKey]);

  const states = useApi((signal) => getStates(signal), []);
  const districts = useApi(
    draft.state ? (signal) => getDistricts(draft.state, signal) : null,
    [draft.state],
  );
  const masters = useApi((signal) => getMasters(signal), []);

  const update = (patch: Partial<SearchState>) => {
    setDraft((previous) => ({ ...previous, ...patch }));
    setError(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = validateSearch(draft);
    if (problem) {
      setError(problem);
      queryRef.current?.focus();
      return;
    }
    onSearch({ ...draft, page: 1 });
  };

  const reset = () => {
    setDraft(EMPTY_SEARCH);
    setError(null);
    onReset();
  };

  const masterList = masters.status === "success" ? masters.data : null;
  const filterCount = activeFilterCount(draft);
  const queryLabel = SEARCH_BY_OPTIONS.find((o) => o.value === draft.searchBy)?.label ?? "Search";
  const errorId = `${ids}-error`;

  return (
    <form className="search-form" onSubmit={submit} noValidate aria-label="Search facilities">
      <div className="search-form__row">
        <Field id={`${ids}-state`} label="State">
          <select
            id={`${ids}-state`}
            value={draft.state}
            onChange={(e) => update({ state: e.target.value, district: "" })}
          >
            <option value="">{states.status === "loading" ? "Loading states…" : "All states"}</option>
            {states.status === "success" && placeOptions(states.data)}
          </select>
          {states.status === "error" && (
            <LoadProblem what="states" onRetry={states.retry} />
          )}
        </Field>

        <Field id={`${ids}-district`} label="District">
          <select
            id={`${ids}-district`}
            value={draft.district}
            disabled={!draft.state}
            onChange={(e) => update({ district: e.target.value })}
            aria-describedby={!draft.state ? `${ids}-district-hint` : undefined}
          >
            <option value="">
              {!draft.state ? "Choose a state first" : districts.status === "loading" ? "Loading districts…" : "All districts"}
            </option>
            {districts.status === "success" && placeOptions(districts.data)}
          </select>
          {!draft.state && (
            <span id={`${ids}-district-hint`} className="visually-hidden">
              Choose a state to see its districts.
            </span>
          )}
          {districts.status === "error" && <LoadProblem what="districts" onRetry={districts.retry} />}
        </Field>

        <Field id={`${ids}-by`} label="Search by">
          <select
            id={`${ids}-by`}
            value={draft.searchBy}
            onChange={(e) => update({ searchBy: e.target.value as SearchBy, query: "" })}
          >
            {SEARCH_BY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field id={`${ids}-query`} label={queryLabel} wide>
          {draft.searchBy === "facilityType" || draft.searchBy === "systemOfMedicine" ? (
            <select
              id={`${ids}-query`}
              ref={queryRef}
              value={draft.query}
              onChange={(e) => update({ query: e.target.value })}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
            >
              <option value="">{masterList ? "Any" : "Loading…"}</option>
              {masterList &&
                masterOptions(
                  masterList[draft.searchBy === "facilityType" ? "facility-types" : "systems-of-medicine"],
                  draft.query,
                )}
            </select>
          ) : (
            <input
              id={`${ids}-query`}
              ref={queryRef}
              type="search"
              value={draft.query}
              placeholder={QUERY_PLACEHOLDERS[draft.searchBy]}
              autoComplete="off"
              spellCheck={false}
              autoCapitalize={draft.searchBy === "facilityId" ? "characters" : "off"}
              maxLength={100}
              onChange={(e) => update({ query: e.target.value })}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
            />
          )}
        </Field>

        <div className="search-form__submit">
          <button type="submit" className="button button--primary">
            Search
          </button>
        </div>
      </div>

      {error && (
        <p id={errorId} className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="search-form__toolbar">
        <button
          type="button"
          className="button button--ghost"
          aria-expanded={filtersOpen}
          aria-controls={`${ids}-filters`}
          onClick={() => setFiltersOpen((open) => !open)}
        >
          <span aria-hidden="true">{filtersOpen ? "▾" : "▸"}</span> All filters
          {filterCount > 0 && <span className="count-pill">{filterCount}<span className="visually-hidden"> active</span></span>}
        </button>
        <button type="button" className="button button--ghost" onClick={reset}>
          Reset filters
        </button>
      </div>

      <div id={`${ids}-filters`} className="filters" hidden={!filtersOpen}>
        <Field id={`${ids}-ownership`} label="Ownership">
          <select id={`${ids}-ownership`} value={draft.ownership} onChange={(e) => update({ ownership: e.target.value })}>
            <option value="">Any</option>
            {masterList && masterOptions(masterList.ownership, draft.ownership)}
          </select>
        </Field>

        <fieldset className="field field--radios">
          <legend>ICU services</legend>
          {(["", "yes", "no"] as IcuOption[]).map((value) => (
            <label key={value || "any"} className="radio">
              <input
                type="radio"
                name={`${ids}-icu`}
                value={value}
                checked={draft.icu === value}
                onChange={() => update({ icu: value })}
              />
              {value === "" ? "Any" : value === "yes" ? "Yes" : "No"}
            </label>
          ))}
        </fieldset>

        <Field id={`${ids}-speciality`} label="Speciality">
          <select id={`${ids}-speciality`} value={draft.speciality} onChange={(e) => update({ speciality: e.target.value })}>
            <option value="">Any</option>
            {masterList && masterOptions(masterList.specialities, draft.speciality)}
          </select>
        </Field>
        {masters.status === "error" && <LoadProblem what="filter options" onRetry={masters.retry} />}
      </div>
    </form>
  );
}

function Field({ id, label, wide, children }: { id: string; label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={`field${wide ? " field--wide" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

function LoadProblem({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <span className="field__problem">
      Couldn't load {what}.{" "}
      <button type="button" className="link-button" onClick={onRetry}>
        Retry
      </button>
    </span>
  );
}

function placeOptions(places: Place[]) {
  return places.map((place) => (
    <option key={place.code} value={place.code}>
      {place.name} ({formatNumber(place.facilityCount)})
    </option>
  ));
}

/** Only offer values that would find something, plus whatever is already chosen. */
function masterOptions(items: MasterItem[], selected: string) {
  return items
    .filter((item) => item.facilityCount > 0 || (item.code ?? item.name) === selected)
    .map((item) => {
      const value = item.code ?? item.name;
      return (
        <option key={value} value={value}>
          {item.name}
        </option>
      );
    });
}
