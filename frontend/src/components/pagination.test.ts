import { describe, expect, it } from "vitest";
import { pageWindow } from "./Pagination";

describe("page window", () => {
  it("shows every page when there are only a few", () => {
    expect(pageWindow(2, 3)).toEqual([1, 2, 3]);
  });

  it("collapses the long runs into gaps", () => {
    expect(pageWindow(10, 20)).toEqual([1, "gap", 9, 10, 11, "gap", 20]);
  });

  it("has no gap where pages are adjacent", () => {
    expect(pageWindow(1, 20)).toEqual([1, 2, "gap", 20]);
    expect(pageWindow(3, 20)).toEqual([1, 2, 3, 4, "gap", 20]);
  });
});
