import { useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { FacilityCard } from "../components/FacilityCard";
import { EmptyState, ErrorState, Loading } from "../components/Feedback";
import { Pagination } from "../components/Pagination";
import { SearchForm } from "../components/SearchForm";
import { searchFacilities } from "../lib/api";
import { plural } from "../lib/format";
import { hasCriteria, readSearch, writeSearch, type SearchState, type SortOption } from "../lib/searchParams";
import { useApi } from "../lib/useApi";
import { useDocumentTitle } from "../lib/useDocumentTitle";

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "name", label: "Name (A–Z)" },
  { value: "district", label: "District" },
  { value: "beds", label: "Most beds" },
];

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const current = useMemo(() => readSearch(params), [params]);
  const queryString = writeSearch(current).toString();
  const searching = hasCriteria(current);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const results = useApi(
    searching ? (signal) => searchFacilities(writeSearch(current), signal) : null,
    [queryString],
  );

  useDocumentTitle(searching ? "Search results" : null);

  const go = (next: SearchState) => setParams(writeSearch(next));

  const changePage = (page: number) => {
    go({ ...current, page });
    // Keyboard and screen-reader users land at the top of the new page of results.
    headingRef.current?.focus();
    headingRef.current?.scrollIntoView({ block: "start" });
  };

  return (
    <>
      <div className="intro">
        <h1>Find a health facility</h1>
        <p className="lede">
          Search hospitals, clinics and other facilities registered with India's National Health
          Facility Registry, by location, name, type or services.
        </p>
      </div>

      <SearchForm current={current} onSearch={go} onReset={() => setParams({})} />

      <section className="results" aria-labelledby="results-heading">
        {!searching ? (
          <EmptyState title="Start with a state">
            <p>Pick a state and district, or search by name, type, ID or system of medicine.</p>
          </EmptyState>
        ) : (
          <>
            <div className="results__header">
              <h2 id="results-heading" ref={headingRef} tabIndex={-1}>
                {results.status === "success"
                  ? plural(results.data.totalFacilities, "facility", "facilities") + " found"
                  : "Search results"}
              </h2>
              <div className="field field--inline">
                <label htmlFor="sort">Sort by</label>
                <select
                  id="sort"
                  value={current.sort}
                  onChange={(e) => go({ ...current, sort: e.target.value as SortOption, page: 1 })}
                >
                  {/* Without a sort, name searches come back best match first, the rest by name. */}
                  <option value="">
                    {current.searchBy === "name" && current.query ? "Best match" : "Default"}
                  </option>
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {results.status === "loading" && <Loading label="Searching facilities…" />}
            {results.status === "error" && <ErrorState error={results.error} onRetry={results.retry} />}
            {results.status === "success" &&
              (results.data.facilities.length === 0 ? (
                <EmptyState title="No facilities match this search">
                  <p>
                    {current.page > 1
                      ? "This page is past the last result."
                      : "Try fewer filters, a different district, or part of the name instead of all of it."}
                  </p>
                </EmptyState>
              ) : (
                <>
                  <p className="results__range" aria-live="polite">
                    Page {current.page} of {results.data.numberOfPages}
                  </p>
                  <ol className="results__list">
                    {results.data.facilities.map((facility) => (
                      <li key={facility.facilityId}>
                        <FacilityCard facility={facility} />
                      </li>
                    ))}
                  </ol>
                  <Pagination
                    page={current.page}
                    pageCount={results.data.numberOfPages}
                    onChange={changePage}
                  />
                </>
              ))}
          </>
        )}
      </section>
    </>
  );
}
