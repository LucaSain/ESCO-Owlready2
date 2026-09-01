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

type ShortlistEntry = {
  label: string;
  shared_skills: number;
  // Everything below arrived with the graph view. They are optional because
  // a backend older than this bundle omits them, and a cached page against a
  // rolling API is a normal transient state -- not a reason to crash.
  id?: string;
  /** true when the reasoner classified the candidate into it, as opposed to
   *  merely considering it. */
  inferred?: boolean;
  /** ids of the candidate's skills this occupation requires -- the edges. */
  matched_skills?: string[];
};

type MatchResponse = {
  occupations: string[];
  shortlist: ShortlistEntry[];
  /** the candidate's skills that reached the reasoner, with labels.
   *  Absent from responses predating the graph view. */
  skills?: Skill[];
  skills_used: number;
  unknown_skill_ids: string[];
  skills_not_required: string[];
  min_skills: number;
  seconds: number;
};

function Spinner() {
  return (
    <svg
      className="size-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/** Placeholder cards, so the answer has a visible destination while the
 *  reasoner runs. Shown only on the first request, when there is nothing
 *  older to keep on screen. */
function ResultsSkeleton() {
  return (
    <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-xl border border-black/10 p-5 dark:border-white/15">
          <div className="h-4 w-2/3 animate-pulse rounded bg-black/10 dark:bg-white/15" />
          <div className="mt-3 h-3 w-1/3 animate-pulse rounded bg-black/5 dark:bg-white/10" />
        </div>
      ))}
    </div>
  );
}

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm">
      <span className="text-black/60 dark:text-white/60">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked ? "bg-foreground" : "bg-black/20 dark:bg-white/25"
        }`}
      >
        <span
          className={`absolute top-0.5 size-4 rounded-full bg-background transition-[left] ${
            checked ? "left-[1.125rem]" : "left-0.5"
          }`}
        />
      </button>
    </label>
  );
}

const GRAPH = {
  width: 920,
  row: 30,
  pad: 16,
  leftLabel: 300, // skill labels end here
  leftDot: 312,
  rightDot: 608,
  rightLabel: 620, // occupation labels start here
};

/** Truncate for SVG, which has no text-overflow. The full string goes in a
 *  <title> so hovering still shows it. */
function clip(text: string, max = 44) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Bipartite skills -> occupations graph. Deliberately hand-rolled SVG: a
 *  typical result is ~26 nodes and ~37 edges, which a fixed two-column
 *  layout renders more legibly than a force simulation, and costs no
 *  dependency at all. */
function SkillGraph({ data }: { data: MatchResponse }) {
  const skills = data.skills ?? [];
  // Inferred first, then by overlap: the ones the reasoner actually
  // classified into belong at the top where they are read first.
  const occupations = [...data.shortlist].sort(
    (a, b) =>
      Number(b.inferred) - Number(a.inferred) || b.shared_skills - a.shared_skills,
  );

  // A response with no `skills` came from a backend that predates the graph
  // data. Say so plainly rather than rendering an empty box or throwing --
  // "can't access property length" tells the user nothing actionable.
  if (data.skills === undefined) {
    return (
      <p className="mt-6 text-sm text-black/60 dark:text-white/60">
        This API build doesn&apos;t return graph data yet. The list view still
        works.
      </p>
    );
  }

  if (skills.length === 0 || occupations.length === 0) return null;

  const rows = Math.max(skills.length, occupations.length);
  const height = rows * GRAPH.row + GRAPH.pad * 2;
  const span = height - GRAPH.pad * 2;
  const y = (i: number, count: number) => GRAPH.pad + (span / count) * (i + 0.5);

  const skillY = new Map(skills.map((s, i) => [s.id, y(i, skills.length)]));

  return (
    <div className="mt-6 overflow-x-auto">
      <svg
        viewBox={`0 0 ${GRAPH.width} ${height}`}
        width={GRAPH.width}
        className="max-w-full"
        role="img"
        aria-label={`${skills.length} skills connected to ${occupations.length} occupations`}
      >
        {/* edges first, so nodes and labels draw over them */}
        {occupations.map((occ, oi) => {
          const oy = y(oi, occupations.length);
          return (occ.matched_skills ?? []).map((sid) => {
            const sy = skillY.get(sid);
            if (sy === undefined) return null;
            const mid = (GRAPH.leftDot + GRAPH.rightDot) / 2;
            return (
              <path
                key={`${occ.id ?? occ.label}-${sid}`}
                d={`M ${GRAPH.leftDot} ${sy} C ${mid} ${sy}, ${mid} ${oy}, ${GRAPH.rightDot} ${oy}`}
                fill="none"
                stroke="currentColor"
                strokeWidth={occ.inferred ? 1.5 : 1}
                className={
                  occ.inferred
                    ? "text-black/40 dark:text-white/45"
                    : "text-black/12 dark:text-white/15"
                }
              />
            );
          });
        })}

        {skills.map((s, i) => (
          <g key={s.id} className="text-black/70 dark:text-white/70">
            <title>{s.label}</title>
            <text
              x={GRAPH.leftLabel}
              y={y(i, skills.length)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize="12"
              fill="currentColor"
            >
              {clip(s.label)}
            </text>
            <circle cx={GRAPH.leftDot} cy={y(i, skills.length)} r="3.5" fill="currentColor" />
          </g>
        ))}

        {occupations.map((occ, i) => (
          <g
            key={occ.id ?? occ.label}
            className={
              occ.inferred
                ? "text-black dark:text-white"
                : "text-black/35 dark:text-white/40"
            }
          >
            <title>
              {occ.label}
              {occ.inferred ? " (inferred)" : " (considered, below threshold)"}
            </title>
            <circle cx={GRAPH.rightDot} cy={y(i, occupations.length)} r="3.5" fill="currentColor" />
            <text
              x={GRAPH.rightLabel}
              y={y(i, occupations.length)}
              dominantBaseline="middle"
              fontSize="12"
              fontWeight={occ.inferred ? 600 : 400}
              fill="currentColor"
            >
              {clip(occ.label, 36)}
            </text>
          </g>
        ))}
      </svg>

      <p className="mt-3 text-xs text-black/50 dark:text-white/50">
        Bold occupations are the reasoner&apos;s conclusions. Faint ones were
        considered but did not meet the threshold.
      </p>
    </div>
  );
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill[]>([]);
  const [highlight, setHighlight] = useState(0);
  const [open, setOpen] = useState(false);

  const [data, setData] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [graphView, setGraphView] = useState(false);
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

  // Reasoning genuinely takes seconds, so show the clock rather than a
  // spinner that could mean anything. Cleared by the effect's teardown when
  // `loading` flips back.
  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 100);
    return () => clearInterval(id);
  }, [loading]);

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
    setElapsed(0);
    setError(null);
    // Deliberately NOT clearing `data`: blanking the page while a
    // multi-second request runs reads as "it broke". The old results stay,
    // dimmed, until the new ones land.
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
            {loading ? (
              <span className="flex items-center gap-2">
                <Spinner />
                Reasoning… {elapsed.toFixed(1)}s
              </span>
            ) : (
              "Match"
            )}
          </button>
        </div>
      </form>

      {/* Screen readers get the same signal the button shows visually. */}
      <p className="sr-only" role="status" aria-live="polite">
        {loading ? `Reasoning, ${elapsed.toFixed(0)} seconds elapsed` : ""}
      </p>

      {loading && !data && <ResultsSkeleton />}

      {error && (
        <p className="mt-6 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {data && (
        <section
          className={`mt-10 transition-opacity ${loading ? "opacity-40" : "opacity-100"}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-black/50 dark:text-white/50">
              {data.skills_used} skill{data.skills_used === 1 ? "" : "s"} used ·
              reasoned in {data.seconds}s
              {data.skills_not_required.length > 0 && (
                <> · {data.skills_not_required.length} not required by any shortlisted occupation</>
              )}
            </p>

            <Switch
              checked={graphView}
              onChange={setGraphView}
              label="Graph View:"
            />
          </div>

          {graphView ? (
            <SkillGraph data={data} />
          ) : data.occupations.length === 0 ? (
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
