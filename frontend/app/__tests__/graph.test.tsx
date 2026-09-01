import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "../page";
import { skillsFixture } from "./fixtures";
import { installFetch, jsonResponse, addSkillViaSearch } from "./test-utils";

const graphFixture = {
  occupations: ["Data scientist"],
  shortlist: [
    {
      id: "o1",
      label: "Data scientist",
      shared_skills: 2,
      inferred: true,
      matched_skills: ["s1", "s2"],
    },
    {
      id: "o2",
      label: "Data entry clerk",
      shared_skills: 1,
      inferred: false,
      // "sX" is not among `skills` below -- it must not produce an edge.
      matched_skills: ["s1", "sX"],
    },
  ],
  skills: [
    { id: "s1", label: "Python" },
    { id: "s2", label: "SQL" },
  ],
  skills_used: 2,
  unknown_skill_ids: [],
  skills_not_required: [],
  min_skills: 1,
  seconds: 1.2,
};

function setup() {
  render(<Home />);
  const input = screen.getByRole("combobox");
  return { input };
}

async function submitGraphFixture() {
  installFetch({
    "/skills": () => jsonResponse(skillsFixture),
    "/match": () => jsonResponse(graphFixture),
  });
  const { input } = setup();
  await addSkillViaSearch(input, "python", "Python programming");

  vi.useRealTimers();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Match" }));
  await screen.findByText("Data scientist");
  return { user };
}

describe("Graph View switch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('is an accessible role="switch", off by default', async () => {
    await submitGraphFixture();

    const toggle = screen.getByRole("switch", { name: "Graph View:" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("replaces the result cards with the SVG graph when switched on", async () => {
    const { user } = await submitGraphFixture();

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);

    await user.click(screen.getByRole("switch", { name: "Graph View:" }));

    expect(screen.getByRole("switch", { name: "Graph View:" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByRole("heading", { level: 2 })).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  it("renders inferred occupations distinctly from non-inferred ones, with edges only for known skill ids", async () => {
    const { user } = await submitGraphFixture();
    await user.click(screen.getByRole("switch", { name: "Graph View:" }));

    const svg = screen.getByRole("img");
    const titles = Array.from(svg.querySelectorAll("title")).map((t) => t.textContent);
    expect(titles).toContain("Data scientist (inferred)");
    expect(titles).toContain("Data entry clerk (considered, below threshold)");

    // The inferred occupation's text is bold (font-weight 600); the
    // non-inferred one is not -- a visible distinction beyond the tooltip.
    const inferredText = Array.from(svg.querySelectorAll("text")).find(
      (t) => t.textContent === "Data scientist",
    );
    const nonInferredText = Array.from(svg.querySelectorAll("text")).find(
      (t) => t.textContent === "Data entry clerk",
    );
    expect(inferredText).toHaveAttribute("font-weight", "600");
    expect(nonInferredText).toHaveAttribute("font-weight", "400");

    // 2 edges from the inferred occupation (s1, s2) + 1 from the
    // non-inferred one (s1 only -- "sX" has no matching skill node).
    expect(svg.querySelectorAll("path")).toHaveLength(3);
  });
});
