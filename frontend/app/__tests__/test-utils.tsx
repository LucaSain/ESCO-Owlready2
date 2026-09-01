import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

/** Minimal stand-in for the bits of `Response` the app actually reads. */
export function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }) {
  return {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    json: async () => body,
  } as Response;
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/**
 * Stubs `global.fetch` with a router keyed by substring match against the
 * request URL (e.g. "/skills" or "/match"). Every call must match a
 * registered handler -- an unmatched URL throws, so a test can never
 * accidentally reach a real network.
 */
export function installFetch(handlers: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(handlers).find((k) => url.includes(k));
    if (!key) {
      throw new Error(`No fetch handler registered for ${url}`);
    }
    return handlers[key](url, init);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Advances the 150ms suggestion debounce (and flushes the resulting
 *  promise chain) inside `act`, so React state updates from the resolved
 *  fetch are applied before assertions run. Requires fake timers. */
export async function flushDebounce(ms = 150) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/**
 * Sets the combobox's value and lets the 150ms debounce elapse.
 *
 * Deliberately uses `fireEvent` rather than `@testing-library/user-event`:
 * in this toolchain (vitest 4 + jsdom 30 + user-event 14), any
 * `userEvent` interaction issued while `vi.useFakeTimers()` is active
 * deadlocks forever (confirmed with a minimal repro -- a bare
 * `userEvent.setup().click()` on a plain button never resolves once fake
 * timers are installed, with or without `advanceTimers` configured).
 * `fireEvent` dispatches synchronously and is unaffected, so it is what
 * drives every interaction that must happen while the debounce clock is
 * being controlled by hand. Requires fake timers.
 */
export async function typeAndSettle(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  await flushDebounce();
}

/**
 * Types a search query, waits for the debounce, then selects the
 * suggestion matching `label`. Temporarily switches to real timers so
 * `userEvent` can safely drive the click (see `typeAndSettle` above for
 * why that switch is necessary) -- `userEvent.click` is used here rather
 * than `fireEvent.click` because the suggestion button only listens for
 * `mousedown` (to beat the input's blur), and `userEvent.click` fires
 * that as part of its realistic event sequence. Restores fake timers
 * before returning, so a caller can search again immediately after.
 */
export async function addSkillViaSearch(input: HTMLElement, query: string, label: string) {
  await typeAndSettle(input, query);
  vi.useRealTimers();
  const user = userEvent.setup();
  await user.click(await screen.findByText(label));
  vi.useFakeTimers();
}
