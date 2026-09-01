"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type SubmitEvent,
} from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Skill = { id: string; label: string };

type MatchResponse = {
  occupations: string[];
  shortlist: { label: string; shared_skills: number }[];
  skills_used: number;
  unknown_skill_ids: string[];
  skills_not_required: string[];
  min_skills: number;
  seconds: number;
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill[]>([]);
  const [highlight, setHighlight] = useState(0);
  const [open, setOpen] = useState(false);

  const [data, setData] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const term = query.trim();
    // Return without touching state: stale suggestions stay in memory but
    // `showList` hides them, and setState inside an effect is a lint error
    // under React 19.
    if (term === "") return;

    // Debounced, and aborted on the next keystroke so slow responses can't
    // land out of order and overwrite newer suggestions.
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `${API}/skills?q=${encodeURIComponent(term)}&limit=8`,
          { signal: controller.signal },
        );
        if (!res.ok) return;
        const found: Skill[] = await res.json();
        const taken = new Set(selected.map((s) => s.id));
        setSuggestions(found.filter((s) => !taken.has(s.id)));
        setHighlight(0);
        setOpen(true);
      } catch {
        // aborted or offline; keep the previous suggestions
      }
    }, 150);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, selected]);

  function add(skill: Skill) {
    setSelected((prev) => [...prev, skill]);
    setQuery("");
    setSuggestions([]);
    setOpen(false);
    inputRef.current?.focus();
  }

  function remove(id: string) {
    setSelected((prev) => prev.filter((s) => s.id !== id));
  }

  // Derived rather than stored, so clearing the box always hides the list.
  const showList = open && query.trim() !== "" && suggestions.length > 0;

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && query === "" && selected.length > 0) {
      remove(selected[selected.length - 1].id);
      return;
    }
    if (!showList) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((h) => Math.min(h + 1, suggestions.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (event.key === "Enter") {
      // Otherwise Enter would submit the form instead of picking a skill.
      event.preventDefault();
      add(suggestions[highlight]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected.length === 0) return;

    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await fetch(`${API}/match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_ids: selected.map((s) => s.id) }),
      });
      const body = await res.json();
      if (!res.ok) {
        // FastAPI sends a string for HTTPException, an array for validation
        const detail = body?.detail;
        throw new Error(
          typeof detail === "string" ? detail : `Request failed (${res.status})`,
        );
      }
      setData(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  // The reasoner returns labels only; shared-skill counts come from the
  // shortlist it considered, so look them up by label.
  const sharedSkills = new Map(
    data?.shortlist.map((s) => [s.label, s.shared_skills]) ?? [],
  );

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
      <h1 className="text-2xl font-semibold">Find matching professions</h1>
      <p className="mt-2 text-sm text-black/60 dark:text-white/60">
        Start typing a skill and pick it from the list. Occupations are derived
        by an OWL reasoner, so expect a few seconds.
      </p>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
        <div className="relative">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-black/15 px-3 py-2 focus-within:border-black/40 dark:border-white/20 dark:focus-within:border-white/50">
            {selected.map((skill) => (
              <span
                key={skill.id}
                className="flex items-center gap-1.5 rounded-md bg-black/5 py-1 pl-2.5 pr-1.5 text-sm dark:bg-white/10"
              >
                {skill.label}
                <button
                  type="button"
                  onClick={() => remove(skill.id)}
                  aria-label={`Remove ${skill.label}`}
                  className="rounded px-1 text-black/40 hover:text-black dark:text-white/40 dark:hover:text-white"
                >
                  ×
                </button>
              </span>
            ))}

            <input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-expanded={showList}
              aria-controls="skill-suggestions"
              aria-autocomplete="list"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              onBlur={() => setOpen(false)}
              placeholder={selected.length === 0 ? "e.g. psychological interventions" : ""}
              className="min-w-40 flex-1 bg-transparent px-1 py-1 text-sm outline-none"
            />
          </div>

          {showList && (
            <ul
              id="skill-suggestions"
              role="listbox"
              className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-black/10 bg-background shadow-lg dark:border-white/15"
            >
              {suggestions.map((skill, i) => (
                <li key={skill.id} role="option" aria-selected={i === highlight}>
                  <button
                    type="button"
                    // mousedown fires before blur, which would close the list
                    // and cancel the click.
                    onMouseDown={(e) => {
                      e.preventDefault();
                      add(skill);
                    }}
                    onMouseEnter={() => setHighlight(i)}
                    className={`block w-full px-3 py-2 text-left text-sm ${
                      i === highlight ? "bg-black/5 dark:bg-white/10" : ""
                    }`}
                  >
                    {skill.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <button
            type="submit"
            disabled={loading || selected.length === 0}
            className="rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background disabled:opacity-40"
          >
            {loading ? "Reasoning…" : "Match"}
          </button>
        </div>
      </form>

      {error && (
        <p className="mt-6 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {data && (
        <section className="mt-10">
          <p className="text-sm text-black/50 dark:text-white/50">
            {data.skills_used} skill{data.skills_used === 1 ? "" : "s"} used ·
            threshold {data.min_skills} · reasoned in {data.seconds}s
            {data.skills_not_required.length > 0 && (
              <> · {data.skills_not_required.length} not required by any shortlisted occupation</>
            )}
          </p>

          {data.occupations.length === 0 ? (
            <p className="mt-6 text-sm text-black/60 dark:text-white/60">
              No occupation met the threshold. Try adding more skills — the
              reasoner needs at least {data.min_skills} of an occupation&apos;s
              essential skills before it will classify you into it.
            </p>
          ) : (
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.occupations.map((label) => (
                <article
                  key={label}
                  className="rounded-xl border border-black/10 p-5 dark:border-white/15"
                >
                  <h2 className="font-medium">{label}</h2>
                  {sharedSkills.has(label) && (
                    <p className="mt-2 text-xs text-black/50 dark:text-white/50">
                      shares {sharedSkills.get(label)} essential skill
                      {sharedSkills.get(label) === 1 ? "" : "s"}
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
