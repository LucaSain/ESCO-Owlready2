import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "../page";
import { skillsFixture, matchFixture } from "./fixtures";
import { installFetch, jsonResponse, addSkillViaSearch } from "./test-utils";

function setup() {
  render(<Home />);
  const input = screen.getByRole("combobox");
  return { input };
}

describe("submitting a match request", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("disables the Match button until at least one skill is picked", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();

    expect(screen.getByRole("button", { name: "Match" })).toBeDisabled();

    await addSkillViaSearch(input, "python", "Python programming");

    expect(screen.getByRole("button", { name: "Match" })).toBeEnabled();
  });

  it("POSTs the selected skill ids as { skill_ids } to /match", async () => {
    const fetchMock = installFetch({
      "/skills": () => jsonResponse(skillsFixture),
      "/match": () => jsonResponse(matchFixture),
    });
    const { input } = setup();
    await addSkillViaSearch(input, "python", "Python programming");
    await addSkillViaSearch(input, "data", "Data analysis");

    // addSkillViaSearch leaves fake timers installed; switch to real ones
    // before the next userEvent interaction (see test-utils for why).
    vi.useRealTimers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Match" }));

    expect(await screen.findByText("Data scientist")).toBeInTheDocument();

    const matchCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/match"));
    expect(matchCall).toBeDefined();
    const [, init] = matchCall as [unknown, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ skill_ids: ["s1", "s2"] });
  });

  it('shows "Reasoning…" on the Match button while the request is in flight', async () => {
    let resolveMatch!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveMatch = resolve;
    });
    installFetch({
      "/skills": () => jsonResponse(skillsFixture),
      "/match": () => pending,
    });
    const { input } = setup();
    await addSkillViaSearch(input, "python", "Python programming");

    vi.useRealTimers();
    const user = userEvent.setup();
    const matchButton = screen.getByRole("button", { name: "Match" });
    expect(matchButton).toHaveTextContent("Match");

    await user.click(matchButton);

    expect(await screen.findByText(/Reasoning…/)).toBeInTheDocument();
    expect(matchButton).toBeDisabled();

    resolveMatch(jsonResponse(matchFixture));

    expect(await screen.findByText("Data scientist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Match" })).toBeEnabled();
  });
});

describe("rendered results", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function submitAndWait() {
    installFetch({
      "/skills": () => jsonResponse(skillsFixture),
      "/match": () => jsonResponse(matchFixture),
    });
    const { input } = setup();
    await addSkillViaSearch(input, "python", "Python programming");

    vi.useRealTimers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Match" }));
    await screen.findByText("Data scientist");
  }

  it("renders exactly one card per entry in `occupations`", async () => {
    await submitAndWait();

    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings).toHaveLength(matchFixture.occupations.length);
    expect(headings.map((h) => h.textContent)).toEqual(matchFixture.occupations);
  });

  it('shows skills-used and reasoning time, and never says "threshold"', async () => {
    await submitAndWait();

    const summary = screen.getByText(/reasoned in/i);
    expect(summary.textContent).toContain("3 skills used");
    expect(summary.textContent).toContain("reasoned in 2.3s");
    expect(summary.textContent?.toLowerCase()).not.toContain("threshold");
  });
});
