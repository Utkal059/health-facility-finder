import { describe, expect, it } from "vitest";
import {
  EMPTY_SEARCH,
  activeFilterCount,
  hasCriteria,
  readSearch,
  validateSearch,
  writeSearch,
  type SearchState,
} from "./searchParams";

const search = (patch: Partial<SearchState>): SearchState => ({ ...EMPTY_SEARCH, ...patch });

describe("reading the URL", () => {
  it("gives the empty search for an empty URL", () => {
    expect(readSearch(new URLSearchParams())).toEqual(EMPTY_SEARCH);
  });

  it("works out the 'search by' choice from the parameter that is present", () => {
    const state = readSearch(new URLSearchParams("state=3&systemOfMedicine=Ayurveda"));
    expect(state.searchBy).toBe("systemOfMedicine");
    expect(state.query).toBe("Ayurveda");
  });

  it("ignores values it does not understand instead of failing", () => {
    const state = readSearch(new URLSearchParams("icu=maybe&sort=price&page=-2&pageSize=500"));
    expect(state).toMatchObject({ icu: "", sort: "", page: 1, pageSize: 10 });
  });

  it("drops a district that has no state", () => {
    expect(readSearch(new URLSearchParams("district=27")).district).toBe("");
  });
});

describe("writing the URL", () => {
  it("round-trips a full search", () => {
    const full = search({
      state: "3", district: "27", searchBy: "name", query: "civil", ownership: "G",
      icu: "yes", speciality: "Cardiology", sort: "beds", page: 3, pageSize: 20,
    });
    expect(readSearch(writeSearch(full))).toEqual(full);
  });

  it("leaves out defaults and blanks, and trims what it keeps", () => {
    const params = writeSearch(search({ state: "3", query: "  apollo  ", page: 1 }));
    expect(params.toString()).toBe("state=3&name=apollo");
  });

  it("uses the API's parameter name for the chosen 'search by'", () => {
    const params = writeSearch(search({ searchBy: "facilityId", query: "IN0310000334" }));
    expect(params.toString()).toBe("facilityId=IN0310000334");
  });
});

describe("validation", () => {
  it("refuses an empty search, like the API does", () => {
    expect(hasCriteria(search({ sort: "beds", page: 2 }))).toBe(false);
    expect(validateSearch(EMPTY_SEARCH)).toMatch(/choose a state/i);
  });

  it("checks the facility ID format before calling the API", () => {
    expect(validateSearch(search({ searchBy: "facilityId", query: "IN123" }))).toMatch(/10 digits/);
    expect(validateSearch(search({ searchBy: "facilityId", query: "in0310000334" }))).toBeNull();
  });

  it("asks for at least two letters of a name", () => {
    expect(validateSearch(search({ query: "a" }))).toMatch(/2 letters/);
    expect(validateSearch(search({ query: "ab" }))).toBeNull();
  });

  it("counts the filters inside the 'All filters' panel", () => {
    expect(activeFilterCount(search({ state: "3", icu: "no", speciality: "ENT" }))).toBe(2);
  });
});
