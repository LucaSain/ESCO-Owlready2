import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import Home from "../page";
import { skillsFixture } from "./fixtures";
import { installFetch, jsonResponse, typeAndSettle, flushDebounce } from "./test-utils";

function setup() {
  render(<Home />);
  const input = screen.getByRole("combobox");
  return { input };
}

describe("skills autocomplete", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not fetch before the debounce elapses, then fetches once", async () => {
    const fetchMock = installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();

    fireEvent.change(input, { target: { value: "python" } });
    expect(fetchMock).not.toHaveBeenCalled();

    await flushDebounce();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl] = fetchMock.mock.calls[0];
    expect(String(calledUrl)).toContain("/skills?q=python");
  });

  it("resets the debounce on every keystroke, firing only once text settles", async () => {
    const fetchMock = installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();

    fireEvent.change(input, { target: { value: "p" } });
    await flushDebounce(100); // still under 150ms
    fireEvent.change(input, { target: { value: "py" } });
    await flushDebounce(100); // resets again, still under 150ms since "p"
    expect(fetchMock).not.toHaveBeenCalled();

    await flushDebounce(150);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/skills?q=py");
  });

  it("renders suggestions returned by the debounced request", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();

    await typeAndSettle(input, "python");

    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("Python programming")).toBeInTheDocument();
    expect(screen.getByText("Data analysis")).toBeInTheDocument();
    expect(screen.getByText("Statistical methods")).toBeInTheDocument();
  });

  it("adds a chip and clears the input when a suggestion is clicked", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");

    // The suggestion button only listens for mousedown (so it can
    // preventDefault and beat the input's blur).
    fireEvent.mouseDown(screen.getByText("Python programming"));

    expect(
      screen.getByRole("button", { name: "Remove Python programming" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("adds a chip when Enter is pressed on the highlighted suggestion", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");

    fireEvent.keyDown(input, { key: "Enter" });

    expect(
      screen.getByRole("button", { name: "Remove Python programming" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("filters already-selected skills out of subsequent suggestions", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");
    fireEvent.mouseDown(screen.getByText("Python programming"));

    await typeAndSettle(input, "data");

    const list = screen.getByRole("listbox");
    expect(within(list).queryByText("Python programming")).not.toBeInTheDocument();
    expect(within(list).getByText("Data analysis")).toBeInTheDocument();
    expect(within(list).getByText("Statistical methods")).toBeInTheDocument();
  });
});

describe("keyboard navigation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("moves the highlight with ArrowDown/ArrowUp, clamped at the ends", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");

    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    let options = screen.getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveAttribute("aria-selected", "false");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    options = screen.getAllByRole("option");
    expect(options[2]).toHaveAttribute("aria-selected", "true");

    // Clamped at the last item.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    options = screen.getAllByRole("option");
    expect(options[2]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    options = screen.getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });

  it("closes the suggestion list on Escape", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Escape" });

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("removes the last chip on Backspace when the input is empty", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();

    await typeAndSettle(input, "python");
    fireEvent.mouseDown(screen.getByText("Python programming"));
    await typeAndSettle(input, "data");
    fireEvent.mouseDown(screen.getByText("Data analysis"));

    expect(screen.getAllByRole("button", { name: /^Remove /i })).toHaveLength(2);
    expect(input).toHaveValue("");

    fireEvent.keyDown(input, { key: "Backspace" });

    const remaining = screen.getAllByRole("button", { name: /^Remove /i });
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toHaveAccessibleName("Remove Python programming");

    fireEvent.keyDown(input, { key: "Backspace" });
    expect(screen.queryAllByRole("button", { name: /^Remove /i })).toHaveLength(0);
  });

  it("does not touch chips when Backspace is pressed with text in the input", async () => {
    installFetch({ "/skills": () => jsonResponse(skillsFixture) });
    const { input } = setup();
    await typeAndSettle(input, "python");
    fireEvent.mouseDown(screen.getByText("Python programming"));

    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.keyDown(input, { key: "Backspace" });

    expect(
      screen.getByRole("button", { name: "Remove Python programming" }),
    ).toBeInTheDocument();
    // Backspace with text present is not intercepted -- the input's own
    // native editing behaviour would handle it outside of this test's
    // synthetic `change` events, so the value here is untouched by our
    // handler (it only special-cases the empty-input case).
    expect(input).toHaveValue("a");
  });
});

