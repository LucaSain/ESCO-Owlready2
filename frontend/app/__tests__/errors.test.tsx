import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "../page";
import { skillsFixture } from "./fixtures";
import { installFetch, jsonResponse, addSkillViaSearch } from "./test-utils";

function setup() {
  render(<Home />);
  const input = screen.getByRole("combobox");
  return { input };
}

describe("error handling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the server's string `detail` message on a non-ok response", async () => {
    installFetch({
      "/skills": () => jsonResponse(skillsFixture),
      "/match": () =>
        jsonResponse({ detail: "At least one skill id is required" }, { ok: false, status: 422 }),
    });
    const { input } = setup();
    await addSkillViaSearch(input, "python", "Python programming");

    vi.useRealTimers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Match" }));

    expect(
      await screen.findByText("At least one skill id is required"),
    ).toBeInTheDocument();
  });

  it('never renders "[object Object]" for a validation-style array `detail`', async () => {
    installFetch({
      "/skills": () => jsonResponse(skillsFixture),
      "/match": () =>
        jsonResponse(
          {
            detail: [
              { loc: ["body", "skill_ids"], msg: "field required", type: "value_error.missing" },
            ],
          },
          { ok: false, status: 422 },
        ),
    });
    const { input } = setup();
    await addSkillViaSearch(input, "python", "Python programming");

    vi.useRealTimers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Match" }));

    expect(await screen.findByText("Request failed (422)")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("[object Object]");
  });
});
