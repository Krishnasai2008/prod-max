export const STATE = {
  now: "2026-11-09T10:00:00",
  running: {
    task_id: 3,
    start: "2026-11-09T09:15:00",
    elapsed_s: 2700,
  },
  tasks: [
    {
      id: 3,
      title: "OS lab 3",
      course: "os",
      kind: "lab",
      est_min: 240,
      due: "2026-11-12",
      energy: "deep",
      first_step: "open the handout",
      logged_min: 45,
      running: true,
      note: "stuck on fork",
      p_late: 0.4,
      start_by: "2026-11-10",
      behind: false,
      links: [
        { id: 1, target: "/home/u/os/lab3.pdf", short: "~/os/lab3.pdf", kind: "file" },
        { id: 2, target: "https://example.com/lab3", short: "https://example.com/lab3", kind: "url" },
      ],
    },
    {
      id: 4,
      title: "DBMS chapter 4",
      course: "db",
      kind: "task",
      est_min: 60,
      due: "2026-11-13",
      energy: "shallow",
      first_step: "skim the summary",
      logged_min: 0,
      running: false,
      note: null,
      p_late: 0.6,
      start_by: "2026-11-08",
      behind: true,
      links: [],
    },
  ],
  today: {
    cap_min: 240,
    worked_min: 45,
    peak: "09-12",
    plan: [
      { task_id: 3, minutes: 195 },
      { task_id: 4, minutes: 45 },
    ],
    unrated: false,
    peak_hint: null,
  },
  crunch: 0.31,
  reviews_due: 7,
  new_per_day: 10,
  courses: ["db", "os"],
  kinds: ["lab", "task"],
  llm: true,
  spots: 2,
  exam: { open: null },
  lh: { found: true, cards_ready: 12, unsorted: 1, plugin: "ok" },
  tutor: { topic_id: 3, topic: "paging", course: "os" },
};

export const SPOT = {
  left: 2,
  spot: { id: 1, topic: "paging", course: "os", title: "notes.md › TLB", lines: ["a", "b <i>", "c", "d"] },
};

export const NEXT = {
  left: 7,
  held: 2,
  item: {
    id: 5,
    topic: "paging",
    course: "os",
    title: "notes.md › TLB",
    question: "What is a **TLB**?",
    kind: "markdown",
  },
};

export const STUDY = {
  topics: [
    {
      id: 1,
      course: "os",
      name: "paging",
      exam: "2026-12-01",
      weight: 2,
      mastery: 0.45,
      items: 12,
      due: 3,
      prereqs: [],
      facets: {
        memory: { value: 0.81, strength: 1, n: 9 },
        understanding: { value: 0.67, strength: 1, n: 6 },
        application: { value: 0.5, strength: 0.4, n: 2 },
        covered: 9,
        total: 15,
      },
    },
    {
      id: 2,
      course: "os",
      name: "virtual memory",
      exam: "2026-12-10",
      weight: 1,
      mastery: 0.2,
      items: 4,
      due: 1,
      prereqs: [1],
      facets: {
        memory: { value: 0.3, strength: 0.8, n: 4 },
        understanding: { value: 0.1, strength: 0.2, n: 1 },
        application: null,
        covered: 4,
        total: 8,
      },
    },
    {
      id: 3,
      course: "db",
      name: "indexes",
      exam: "2026-11-20",
      weight: 1.5,
      mastery: 0.8,
      items: 6,
      due: 0,
      prereqs: [],
      facets: { memory: { value: 0.8, strength: 1, n: 6 }, understanding: null, application: null, covered: 0, total: 0 },
    },
  ],
  next: { topic_id: 1, unblocks_id: 2 },
  ranking: [
    { topic_id: 1, mastery: 0.45, score: 0.05 },
    { topic_id: 3, mastery: 0.8, score: 0.02 },
  ],
  calibration: {
    n: 40,
    brier: 0.182,
    gap: 0.12,
    bins: [
      { lo: 60, hi: 80, n: 10, said: 0.7, recalled: 0.6 },
      { lo: 80, hi: 100, n: 5, said: 0.9, recalled: 0.75 },
    ],
    sources: [{ source: "review", n: 40, brier: 0.182, gap: 0.12 }],
  },
  readiness: [{ course: "os", value: 0.62, exam: "2026-11-20", topics: 2 }],
  misses: [{ when: "2026-11-08T21:10:00", topic_id: 1, confidence: 0.9, source: "review", label: "notes.md#TLB" }],
  queue: { due: 7, held: 2 },
};

export const OUTLINE = {
  path: "/home/u/os.md",
  kind: "markdown",
  whole_file_exists: false,
  sections: [
    {
      locator: "Paging",
      title: "Paging",
      level: 1,
      lines: 2,
      leaf: false,
      pdf: false,
      picked: false,
      exists: false,
    },
    {
      locator: "TLB",
      title: "TLB",
      level: 2,
      lines: 3,
      leaf: true,
      pdf: false,
      picked: true,
      exists: false,
    },
    {
      locator: "Example",
      title: "Example",
      level: 2,
      lines: 6,
      leaf: true,
      pdf: false,
      picked: true,
      exists: false,
    },
    {
      locator: "L20-25",
      title: "Example",
      level: 2,
      lines: 4,
      leaf: true,
      pdf: false,
      picked: true,
      exists: false,
    },
    {
      locator: "Virtual memory",
      title: "Virtual memory",
      level: 2,
      lines: 5,
      leaf: true,
      pdf: false,
      picked: true,
      exists: true,
    },
  ],
};

export const EXCERPT = {
  kind: "markdown",
  text: "**Answer.** A cache of page-table entries.",
  question: "What is a **TLB**?",
  image: null,
  path: "~/notes/os.md",
  locator: "TLB",
  error: null,
  intervals: {
    1: "2026-11-09T10:10:00",
    2: "2026-11-10T10:00:00",
    3: "2026-11-12T10:00:00",
    4: "2026-11-20T10:00:00",
  },
};

export const EXAM = {
  courses: ["os"],
  topics: [{ id: 1, course: "os", name: "paging" }],
  papers: [{ id: 2, course: "os", title: "2025 midsem", questions: 9, minutes: 90 }],
  bank: [{ topic_id: 1, topic: "paging", course: "os", n: 14, by_trust: { source: 14 } }],
  mocks: [
    { id: 3, title: "os mock 2026-11-09", course: "os", questions: 10, minutes: 30, status: "marked", pct: 0.62, predicted: 0.55 },
    { id: 4, title: "os mock 2026-11-08", course: "os", questions: 5, minutes: 10, status: "marked", pct: 0.62, predicted: null },
  ],
  open: null,
};

const ITEMS = [
  { pos: 1, question_id: 11, marks: 2, topic: "paging", prompt: "How many faults?", kind: "number", page: false,
    answer: null, confidence: null, dont_know: false, trust: "source" },
  { pos: 2, question_id: 12, marks: 2, topic: "paging", prompt: "Pick the policy", kind: "choice", page: false,
    options: ["FIFO", "LRU", "OPT"], answer: null, confidence: null, dont_know: false, trust: "checked" },
  { pos: 3, question_id: 13, marks: 5, topic: "paging", prompt: "Explain the TLB", kind: "open", page: false,
    answer: null, confidence: null, dont_know: false, trust: "source" },
];

export const MOCK_RUNNING = { id: 1, title: "os mock 2026-11-09", course: "os", minutes: 30, status: "running",
  left_s: 1290, items: ITEMS, result: null };

const FINISHED = [
  { ...ITEMS[0], answer: "12", confidence: 0.8, key: "12", score: 1, readable: true, auto: true },
  { ...ITEMS[1], answer: "1", confidence: 0.6, key: "B: LRU", score: 0, readable: true, auto: true },
  { ...ITEMS[2], answer: "a cache", confidence: 0.7, key: "**Answer.** A cache of page-table entries.", score: null, readable: true, auto: false },
];

export const MOCK_TO_MARK = { ...MOCK_RUNNING, status: "to mark", left_s: 400, items: FINISHED };

export const MOCK_MARKED = { ...MOCK_RUNNING, status: "marked", left_s: 400,
  items: FINISHED.map((i) => ({ ...i, score: i.score ?? 0.6 })),
  result: { got: 31, total: 50, pct: 0.62, predicted: 0.55, over_min: 4, said: 0.7, unread: [2], missed: [2, 5, 9],
    by_topic: [{ topic_id: 1, topic: "paging", got: 12, total: 20 }, { topic_id: 2, topic: "scheduling", got: 19, total: 30 }] } };

export const PRACTICE = {
  generators: [
    { id: "paging", title: "Page replacement", variants: ["count", "final", "fewest"] },
    { id: "cpu", title: "CPU scheduling", variants: ["avg_wait", "order", "which"] },
    { id: "disk", title: "Disk scheduling", variants: ["movement", "order"] },
  ],
  topics: [
    { id: 3, name: "paging", course: "os", gens: ["paging"], attempts: 6, right: 4 },
    { id: 4, name: "scheduling", course: "os", gens: [], attempts: 0, right: 0 },
  ],
  errors: ["bad.toml: <b>the template doesn't reproduce its original answer</b>"],
};

export const PROBLEM = {
  topic_id: 3, topic: "paging", course: "os", gen: "paging", seed: 1804289383, variant: "count",
  title: "Page replacement", kind: "number",
  text: "Frames: 3. Reference string: 7 0 1 2\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nHow many page faults occur under LRU?",
};

export const VERDICT = { correct: false, readable: false, key: "12", steps: "LRU walkthrough\n\nFaults: 12" };

export const LH = {
  found: true,
  sessions: [
    { chat_id: "chat_practice", title: "Paging problems", kind: "practice", topic_id: null, tagged: false,
      updated: "2026-11-09T13:20:00", minutes: 9, error: null },
    { chat_id: "chat_teach", title: "TLB and paging", kind: "teach", topic_id: 3, tagged: true,
      updated: "2026-11-09T12:30:00", minutes: 4, error: null },
  ],
  skipped: ["chat_v2: newer LearnHarness format (version 2)"],
};
