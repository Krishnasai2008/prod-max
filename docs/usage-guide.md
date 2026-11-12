# pm usage guide

This guide explains what each part of `pm` does, why it works the way it does, and how to fit it into
your week. `README.md` is the short reference (every command and flag in a table); this guide is the
long version. A full worked example is at the end ([A typical two days with pm](#a-typical-two-days-with-pm)).

## Contents

1. [The idea in one minute](#the-idea-in-one-minute)
2. [Setup](#setup)
3. [Input formats](#input-formats)
4. [Tasks and the timer](#tasks-and-the-timer)
5. [Estimate bias](#estimate-bias)
6. [Deadline risk](#deadline-risk)
7. [The daily plan](#the-daily-plan)
8. [The app](#the-app)
9. [Studying with spaced repetition](#studying-with-spaced-repetition)
10. [Testing yourself](#testing-yourself)
11. [Practice](#practice)
12. [Studying with LearnHarness](#studying-with-learnharness)
13. [Letting a model help](#letting-a-model-help)
14. [Bug tracking with `pm run`](#bug-tracking-with-pm-run)
15. [File search and the daemon](#file-search-and-the-daemon)
16. [Nudges](#nudges)
17. [The notes site](#the-notes-site)
18. [Settings](#settings)
19. [Backup and undo](#backup-and-undo)
20. [Trying things safely](#trying-things-safely)
21. [A typical two days with pm](#a-typical-two-days-with-pm)
22. [Troubleshooting](#troubleshooting)

---

## The idea in one minute

Most planners trust your estimates. `pm` doesn't: it watches how long things *actually* take, learns
your personal "fudge factor" per kind of work (labs, psets, exams…), and uses it everywhere:

- **`pm risk`** simulates thousands of possible futures to tell you the chance each deadline slips and
  the last safe day to start.
- **`pm today`** fills today's focus hours with the right work, in the same order the simulation assumes.
- **`pm review`** schedules flashcard-style reviews of your own notes so you remember them at exam time.
- **`pm run`** notices when a command keeps failing, and records the diff that finally fixed it.
- **`pm watch`** keeps your Downloads searchable and nudges you when it's time to start something.

Everything lives in one SQLite file on your machine (`~/.local/share/prod-max/pm.db`), created by the
first command you run. Back it up with `pm backup` (see [Backup and undo](#backup-and-undo)).

## Setup

```
uv tool install --editable .      # from the prod-max folder; puts `pm` on your PATH
pm --help                         # list of commands
pm add --help                     # flags for one command
```

Without installing, run `uv run pm <cmd>` from the project folder. The two `--install` commands
(`pm watch --install`, `pm ui --install`) need the installed `pm`.

`pm doctor` checks your setup at any time: the database, whether the daemon is running, the folders
it watches, the model command, and which optional programs are installed.

First-time settings worth making (see [Settings](#settings) for all of them):

```
pm set hours_per_day 5            # honest focused hours, not hours awake
pm set peak 09-12                 # when your brain works best
pm set watch ~/Downloads          # folders to index for `pm find`
```

Optional programs (each one unlocks a feature, nothing breaks without them):
`pdftotext` (PDF text), `pdfinfo` (PDF page counts), `pdftoppm` (PDF pages as pictures in the app,
and OCR of scans), `tesseract` (OCR of images and scanned PDFs), `notify-send` (desktop nudges),
`git` (fix diffs in `pm run`). `pm doctor` lists which ones you have.

## Input formats

These are the same in every command.

| What | Accepted | Examples |
|---|---|---|
| Duration | hours and/or minutes, always with the unit | `90m`, `4h`, `1h30m`, `2.5h` |
| Date | ISO date, `+N` days from today, `today`, `tomorrow`, or a weekday | `2026-11-20`, `+3`, `fri` |

A number without a unit (`--est 90`) is refused, because it could mean 90 minutes or 90 hours. A
weekday means the next one after today: on a Friday, `fri` is next week's Friday, and `today` is today.
| Hours range | `start-end`, whole hours from 0 to 24 | `09-12`, `08-22` |

## Tasks and the timer

A **task** is a piece of work with an estimate. Optionally it has a due date, a course, a kind and a
first step.

### Adding a task

```
pm add "OS lab 4: shell" --est 3h --due +4 --course os --kind lab --first "read the handout"
added #1
```

- `--est` (required): your honest guess. Don't pad it: `pm` corrects it for you, and padding hides
  the very bias it's trying to learn.
- `--due`: the deadline. Tasks without one are left out of `pm risk` and come after the tasks that
  have one in `pm today`.
- `--course`: free text such as `os` or `dbms`. Used for grouping, stats and tagging files.
- `--kind`: the bucket your estimate bias is learned in (`lab`, `pset`, `exam`, `essay`, ...; default
  `task`). Use a small, consistent set of kinds. If labs always run long but psets don't, `pm` can only
  see that when they have different kinds.
- `--shallow`: low-focus work (emails, forms, admin). Deep work is the default. `pm today` lists deep
  work in your peak hours and shallow work after it.
- `--first`: a tiny, concrete first step ("open the handout", "write the function signature"). It's
  shown when you start the task, which makes starting easier.

### Tracking time

```
pm start 1                          # starts the timer (stops any other running timer)
pm stop "parser done, next: pipes"  # stops it; the note is where you left off
```

- When you `start` again later, `pm` shows the first step **and** your last "where you left off"
  note, so you can get going without re-reading everything.
- Only one timer runs at a time. Starting a task stops the one that's running.
- Forgot to stop? `pm stop --as 45m` records 45 minutes instead of the real elapsed time. A session
  longer than 6h prints a warning to remind you.
- `pm stop` with nothing running exits with code 1 (handy in scripts).

### Links: open what you need when you start

```
pm link 1 ~/os/lab4/handout.pdf
linked #1: ~/os/lab4/handout.pdf
pm link 1 https://man7.org/linux/man-pages/man2/fork.2.html
pm link 1                           # numbered list
pm link 1 --rm 2                    # remove link 2
pm start 1
started #1 OS lab 4: shell
opened 2 links
```

- `pm start` opens every link on the task; `pm start 1 --no-open` only lists them.
- A file is checked when it's opened, not when you link it: a moved file prints `skipped: gone …`.
- Documents and images open in their app. For anything else (a script, an HTML page) `pm` opens the
  folder instead, so a link can never run code. Addresses must be `http://` or `https://`.

### Rating your energy

```
pm stop "parser done" --energy 4
stopped #1 after 50m
energy 4
```

`--energy` (1 drained … 5 sharp) says how alert you were. After a while `pm energy` shows your energy
by clock hour and, once there are at least 10 rated sessions and 5 hours of them, suggests the
3-hour stretch you're sharpest in as your `peak`:

```
pm energy
09-10  3.2  (2h40m)
10-11  4.1  (3h)
11-12  4.3  (2h10m)
...
suggested peak 10-13 (now 09-12): pm set peak 10-13
```

It never changes `peak` by itself. In the app, a card on Today asks for the rating after you stop
(for 30 minutes), and the suggestion shows up there with a **Use** button.

Worked without the timer? Log it afterwards. The time counts as ending now:

```
pm log 3 15m
logged 15m on #3
```

### Finishing

```
pm done 1
done #1: 4h30m logged, estimated 3h
```

**Finishing matters.** Only finished tasks teach `pm` your bias, because an unfinished task's
"actual time" isn't known yet. If you abandon a task, drop it (`pm drop`, below) so it doesn't
teach `pm` a false ratio.

Finished the wrong one? `pm ls --done` lists the last 20 finished or dropped tasks with their
numbers, and `pm reopen N` opens one again with its logged time. Plain `pm` with no command is the
same as `pm today`.

### Changing or dropping a task

Plans change. `pm edit` changes an open task and only touches the fields you name:

```
$ pm edit 2 --est 3h --due +9
edited #2

$ pm edit 2 --title "DBMS pset 2 (redo)"
edited #2

$ pm edit 2 --no-due --course ""
edited #2
```

- `--title`, `--est`, `--due`, `--course`, `--kind`, `--shallow` and `--first` mean the same as in
  `pm add`; `--deep` switches a shallow task back to deep work.
- `--no-due` removes the due date. `--course ""` and `--first ""` clear those fields.
- `pm edit 2` with nothing to change prints `error: nothing to change`.
- The estimate can change only while no time is logged. After that you get
  `error: the estimate is locked once time is logged; pm learns from it`. The estimate is what the
  bias model compares your actual time against, so changing it after the fact would teach `pm`
  something false; estimate the next task honestly instead.
- A finished or dropped task can't be edited.

Some work you decide not to do. `pm drop` closes a task without pretending you finished it:

```
$ pm drop 3
dropped #3
```

A dropped task:

- stops its timer if it was running;
- leaves `pm ls`, `pm today` and `pm risk`;
- isn't counted in your estimate bias or on-time history;
- keeps the time you already logged: it still counts as time worked.

### Seeing your tasks

```
pm ls
#1  OS lab 4: shell  [lab/os]  due 2026-11-13  est 3h  logged 0m
#2  DBMS pset 2  [pset/dbms]  due 2026-11-15  est 2h  logged 0m
#3  email TA about regrade  [task/-]  due -  est 20m  logged 0m
```

`▶` marks the running task.

## Estimate bias

```
pm bias
all  n=2  median x1.19
```

The **ratio** of a finished task is `actual ÷ estimate`. `x1.40` means things take 40% longer than you
think, and `x0.80` means you overestimate. `pm bias` shows the typical (median) ratio overall and per
kind.

How it's used:

- Before you have finished anything, `pm` assumes **x1.5**. That's a sensible pessimistic default for
  students.
- As tasks finish, your real ratios gradually outweigh that default. It's a blend, so one wild task
  can't swing everything. That's why two tasks at x1.5 and x0.75 give `x1.19` above, not their plain
  median.
- A kind gets its own bias once it has **3 finished tasks**. Until then it uses the overall one.
- `pm risk` and `pm today` multiply each task's *remaining* estimate by this bias. So if you estimated
  3h, logged 2h30m and your lab bias is x1.5, `pm` thinks about 2h are left, not 30 minutes.

Tip: the bias becomes useful after about 5–10 finished tasks of a kind. Keep estimating honestly.

## Deadline risk

```
pm risk
#1  OS lab 4: shell  due 2026-11-13  late 1%  start by 2026-11-11
#2  DBMS pset 2  due 2026-11-15  late 0%  start by 2026-11-12
crunch risk 1%  start the queue by 2026-11-11
```

What each part means:

- **late N%**: the chance this task misses its deadline if you work at `hours_per_day` from today.
- **start by**: the latest day you can start this task and still finish on time 95% of the time.
  `BEHIND` means that day has already passed.
- **crunch risk**: the chance that *at least one* deadline slips. This is the number to watch in
  busy weeks.
- **start the queue by**: the earliest of the start-by dates.

How it works: `pm` runs 10,000 simulated futures. In each one, every task's length is drawn from your
learned bias (so some runs are lucky and some unlucky), and tasks are worked **earliest deadline first**
at `hours_per_day`. The percentages are just the share of futures in which a task was late.

### Risk in the app

Open **Risk** (or press `5`). It shows the same crunch risk and start-by line as `pm risk`, then a
timeline with one row per task: a bar from the likely finish (the 50% mark) to the worst case (the
95% mark), a marker at the due date and a small triangle at the start-by date. The table under it
repeats the dates and adds the days-late column: when a task misses, about how many days late it
finishes.

Two sliders try a different week without saving anything. **hours a day** reruns the simulation at
another pace, and **lost days** pretends you lose that many days before you start. Say one task has
12 hours of bias-corrected work left, `hours_per_day` is 4 and it is due Friday: from Monday the
simulation finishes on Wednesday. Set **lost days** to 1 and the finish moves to Thursday; set it
to 3 and it moves to Saturday, a day late, so the bar crosses the due marker, the days-late column
says about a day, and the crunch risk climbs. **Reset** puts both sliders back. If you like the new
pace, **Use N h a day** saves it as `hours_per_day` (it asks first). The hours slider moves in half
hours; if your saved value is finer, such as `0.3`, it moves in tenths.

When to look: once a day, or whenever you add a big task. If crunch risk climbs above roughly 20%,
start earlier, raise `hours_per_day` (only if that's realistic), or cut scope.

## The daily plan

```
pm today
Deep work (peak 09-12):
  #1 OS lab 4: shell  ~4h30m  first step: read the handout
  #2 DBMS pset 2  ~30m
```

`pm today` fills today's `hours_per_day` with work, earliest deadline first, using bias-corrected
remaining time (the `~` numbers). Deep tasks are listed under your peak hours, then shallow ones.

It uses **the same order as `pm risk`**, so following `pm today` is exactly the plan the risk numbers
assume. If today is full, lower-priority tasks (like the shallow email above) don't appear. That's
on purpose: they aren't today's job.

## The app

The CLI is quick, but a day has a lot of small clicks in it. `pm ui` starts a local web app that is
a second front end over the same database. The CLI is unchanged, and you can mix the two freely.

```
$ pm ui
pm ui on http://127.0.0.1:8321
```

It opens the page in your browser (unless you pass `--no-open`), listens on `127.0.0.1:8321` (or
`--port N`, from 1024 to 65535), and runs until Ctrl-C. If it's already running on that port, it
prints `pm ui is already running: http://127.0.0.1:8321`, opens the page and exits 0. If another
program has the port, it says `error: port 8321 is in use; try pm ui --port 8322`.

### The screens

**Today** is what you keep open while you work:

- The running timer, with a ticking clock, the first step and your "where you left off" note. Write
  a pause note and press **Stop**, or press **Done**. The **Stop as…** fold-out records a shorter
  time for a timer you forgot; it opens itself after 6 hours.
- With nothing running, one button starts the first task in today's plan.
- The day meter: time worked today against `hours_per_day`.
- Today's plan, deep work (under your peak hours) first, then shallow. Each card has `~` minutes for
  today, the due date, a late-risk bar (green under 20%, orange under 50%, red), `BEHIND` or
  "start today", the first step, and Start / Log / Done.
- How many reviews are due.

**Tasks** is the list view:

- An add form with the same formats as `pm add` (`90m`, `1h30m`, `2026-11-20`, `+3`). Course and
  kind autocomplete from what you already use.
- Open tasks in deadline order: logged and estimated time, due date, late risk, start-by, and
  Start / Log / Done / Edit / Drop. Drop asks first. Once time is logged the estimate field is
  locked, for the [same reason as `pm edit`](#changing-or-dropping-a-task).
- The last 10 finished tasks with their actual/estimate ratio and whether they were on time or late.

**Review** is where you study:

- One due item at a time: the progress (`3 of 7`), the topic, the title (your prompt, or the file and
  its locator) and the question when the note has one. The answer is not on the page or in the
  first request.
- Set your confidence with the slider or `0`–`9`, then press **Show answer**. The excerpt appears,
  rendered: Markdown with maths and tables, or a PDF page as an image when `pdftoppm` is installed
  (its text otherwise). Maths comes from MathJax on a CDN, so the first time it needs the network;
  offline the TeX stays readable.
- Four grade buttons, each saying when that grade comes back (`Good · in 3d`), and **Suspend**.
  After the last item, it compares what you said with what you recalled:
  `reviewed 7 · recalled 5 · you said 80% on average, recalled 71%`, plus how many new items wait.

**Study** is the overview:

- **Study next** (the same pick as `pm study next`) with its mastery and what it unblocks, then the
  top 5 ranking.
- Topics by course, with a prerequisite graph when the course has links and a table with exam,
  weight, a mastery bar, items and due. Edit a topic's exam and weight here, or add one with its
  prerequisites.
- Under each topic's mastery bar, its three parts (a faint bar means thin evidence; a missing part
  says `no items yet`, `no checks yet` or `no practice yet`) and `covered 9 of 15 sections`; above
  the topics, a readiness line per course; a **Confident mistakes** card when you have any.
- The calibration chart with the same numbers in a table under it (and a table per source once you
  have answers from more than one), and the queue line
  (`7 due now · 2 new items wait for another day`).
- **Add items from a file**: give a path, tick sections, and choose or create a topic
  (see [Adding a whole file](#adding-a-whole-file)).

**Risk** is the same forecast as `pm risk` drawn as a timeline, with two what-if sliders
(see [Risk in the app](#risk-in-the-app)).

**Stats** draws the stats page's sections — streaks, the heatmap, time, estimates, deadlines, study
and bugs — locally, without pushing (see [The notes site](#the-notes-site)).

**Bugs** shows totals, bursts, tag filters and the 50 newest episodes, with each episode's runs and
fix diff (see [Bugs in the app](#bugs-in-the-app)).

**Files** is search with Open, Show in folder and Study this
(see [Files in the app](#files-in-the-app)).

**Settings** lists every setting with a Save button and the same checks as `pm set`
(see [Settings in the app](#settings-in-the-app)).

The header always shows the running timer with a Stop button, the crunch risk and reviews due, on
every screen.

The page refreshes after every click, when you switch back to its tab, and every minute, so a timer
you started with `pm start` in a terminal shows up there. It never wipes what you are typing.

**Exam** (`0`) builds and runs timed mock tests and holds the question bank; see
[Testing yourself](#testing-yourself). **Practice** (`p`) gives generated problems that the code
checks; see [Practice](#practice). **Spot** has no key: open it from the Study screen.

### Keys

Not while you are typing in a field:

| Key | Does |
|---|---|
| `1` | Today |
| `2` | Tasks |
| `3` | Review |
| `4` | Study |
| `5` | Risk |
| `6` | Stats |
| `7` | Bugs |
| `8` | Files |
| `9` | Settings |
| `0` | Exam |
| `p` | Practice |
| `/` | jump to Files and focus the search box |
| `n` | new task |
| `s` | start the first planned task; while running, jump to the pause note |
| `?` | help |
| `Esc` | close help; on Review, back to Today; on Spot, back to Study; on Practice, drop the problem (not while you type an answer) |
| `n` | on Spot and Practice, after the answer is shown: next |

On the Review screen, before the answer is shown, `0`–`9` set the confidence (`0` is 100%, `7` is
70%) and `Enter` or `Space` shows the answer. After that, `1`–`4` grade it.

### Running it as a service

`pm ui --install` writes the same kind of systemd user unit as `pm watch --install`, running
`pm ui --no-open`, and prints the line to start it:

```
$ pm ui --install
wrote ~/.config/systemd/user/pm-ui.service
start it: systemctl --user daemon-reload && systemctl --user enable --now pm-ui
```

It doesn't start the service itself. Logs: `journalctl --user -u pm-ui`.

If **Open** or **Show in folder** does nothing when the app runs as the service, the service lacks
your desktop's display environment. Run
`systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP` and restart the
service (`systemctl --user restart pm-ui`); or run `pm ui` from a terminal, which always works.

### Is it safe?

It listens only on `127.0.0.1`, so it isn't reachable from your network. It refuses requests from
other web sites: it checks the `Host` and `Origin` headers and requires JSON. Any program on your
own machine can still call it, so it's a single-user tool, not a shared one. It works offline, needs
nothing beyond `pm`, follows your system's light/dark setting, and under 700 px wide it becomes one
column, with the nav at the bottom scrolling sideways.

`PM_DB` and `PM_NOW` work with `pm ui` exactly as with every other command (see
[Trying things safely](#trying-things-safely)).

## Studying with spaced repetition

Study mode turns parts of your own notes, slides and code into review items, and uses **FSRS** (a modern
spaced-repetition algorithm) to decide when you should see each one again. You review at the moment
you're about to forget, which is the most efficient time to do it.

### Topics

A **topic** groups related items and carries the exam date and how much it matters.

```
pm topic add scheduling --course os --exam +10 --weight 2
pm topic add paging --course os --exam +10 --needs scheduling
```

- `--exam`: when it's tested. The closer the exam, the more urgent the topic.
- `--weight`: how much it matters (default 1). Give a topic weight 2 if it's worth twice the marks.
- `--needs`: a prerequisite topic in the same course; it must already exist. You can repeat it. If the
  prerequisite is weak, `pm study next` sends you there first.

```
pm topic ls
#1  os/scheduling  exam 2026-11-20  weight 2  mastery 0%  items 1
#2  os/paging  exam 2026-11-20  weight 1  mastery 0%  items 1  needs scheduling
```

### Mastery: what it's made of

**Mastery** answers "how much of this topic could I handle right now?". It is two things multiplied:

1. **Coverage**: how much of the topic's material you have review items for. `pm` counts the sections
   of each file the topic uses (the same sections `--all` would add) and how many of them have an
   item. Adding a file's whole text, without a locator, covers all of it.
2. **How well you do**, a blend of three parts:
   - **memory**: the average chance (from FSRS) that you'd recall the topic's items right now. It goes
     up as you review and slowly decays.
   - **understanding**: spot-the-error cards you've answered (`pm spot`).
   - **application**: practice and test answers (see [Practice](#practice) and [Testing yourself](#testing-yourself)).

Each part counts by how much evidence it has: five answers or items make a part count fully, one
answer counts a fifth as much, and old answers fade (half the weight after 30 days). Application
counts double. A part with no data at all is left out, not counted as zero, so a topic you've only
reviewed is judged on memory alone. One wrong practice answer lowers a strong topic a little; it
never sends it to zero.

A worked topic:

```
pm study why paging --course os
os/paging  mastery 56%
  coverage 75% (9 of 12 sections)
  memory 81% (9 items)
  understanding 67% (6 answers)
  application - (no practice yet)
```

Here memory and understanding blend to 74%, and covering 9 of 12 sections makes it 75% of that.
To raise it, add the three missing sections (`pm study add notes.md --all --topic paging` skips the
ones already there) or review the weak ones.

`pm` learns which files belong to a topic when you add items from them. Tell it about a file you
haven't added anything from yet with `pm topic file paging ~/os/paging.md`, so its sections count as
not covered; `--rm` stops counting a file. The daemon recounts changed files every hour. Mastery
never reads your notes itself.

Two more views of the same record:

```
pm study misses           # confident mistakes: you said 70% or more and got it wrong
2026-11-08  os/paging  said 90%  review  notes.md#TLB
pm study ready            # per course with an exam ahead: weighted mastery of its topics
os  62%  next exam 2026-11-20  (4 topics)
```

### Items and locators

An **item** points to a piece of a file. You don't copy anything: `pm` reads the excerpt from the
file when you review, so fixes to your notes show up automatically.

```
pm study add ~/courses/os/notes.md#Scheduling --topic scheduling --prompt "How does round robin pick the next process?"
item #1 added to scheduling, due now
```

| Locator | Means | Example |
|---|---|---|
| *(none)* | the whole text file | `cheatsheet.md` |
| `#Heading` | that Markdown section, down to the next heading of the same or a higher level | `notes.md#Paging` |
| `#L10-25` | lines 10 to 25 | `shell.c#L10-25` |
| `#p12` | page 12 of a PDF (needs `pdftotext`) | `slides.pdf#p12` |

- `--prompt` is the question shown *before* the excerpt. Without one you just see the topic name, which
  is weaker practice. Write prompts as real questions.
- Use `--course` if the same topic name exists in several courses.
- New items are due immediately.

### Adding a whole file

Instead of one locator at a time, `--all` turns a file's sections into items:

```
$ pm study add ~/courses/os/notes.md --all --topic scheduling
added 12 items to scheduling
```

- **Markdown:** a section is picked by default when its heading has no subheadings and the section has
  at least 3 non-blank lines of its own (before the next heading). A parent heading repeats what its
  children already cover, and a one-line section makes a poor card, so neither becomes one by default.
- **PDF:** every page is picked, up to the first 500. Listing the pages needs `pdfinfo` (poppler).
- Sections already in that topic are skipped, and the count is printed:
  `added 1 item to scheduling (3 already there)`. When nothing is left it prints `nothing to add`.
- A plain text file has no sections, so `--all` prints `nothing to add`; add it as a single item with
  no locator instead.

The app's **Add items from a file** on the Study screen does the same, with checkboxes. Give the
path (for example `~/courses/os/notes.md`), press **Show sections**, then tick what you want: the
default pick arrives ticked, and sections already in the topic you picked are greyed out and say `already added` (pick another
topic and they can be ticked again: the same section may sit in two topics).
Choose an existing topic, or `new topic…` and give it a name and course. When you tick more than
`new_per_day`, it tells you how many will come up each day. A text file with no sections is offered
as one item, "the whole file".

### The daily cap on new items

At most `new_per_day` never-reviewed items enter the queue in a day (default 10, allowed 1–200):

```
$ pm set new_per_day 10
new_per_day = 10
```

When more new items are due, `pm review` stops at the cap and says how many wait:

```
$ pm review
...
reviewed 10
12 new items wait for another day (pm set new_per_day)
```

After an item's first review it is a normal review item: it comes back when FSRS says so, even if the
day's new-item allowance is used up. New items enter in the order you added them; the rest join on
later days, as the allowance resets each day.

The cap exists because a bulk add of 40 sections would otherwise put 40 new cards in one day, bury the
reviews that matter, and leave a pile of FSRS intervals that fall due together. Spacing the new cards
out keeps the daily queue honest.

### What to study

```
pm study next
study next: os/scheduling  mastery 0%
ranking:
  os/scheduling  exam 2026-11-20  mastery 0%  score 0.20
  os/paging  exam 2026-11-20  mastery 0%  score 0.10
```

The score is `weight × (1 − mastery) ÷ days until the exam`: important, weak topics with a close exam
come first. If the winner has a prerequisite under 60% mastery, `pm` points you to the prerequisite
instead.

### Reviewing

```
pm review              # up to 20 due items
pm review --limit 5
```

For each item:

1. Read the prompt and **say your confidence** (0–100) that you can recall the answer. Do this before
   you look.
2. The excerpt is shown. Compare it with what you remembered.
3. **Grade yourself**: `1` again (forgot), `2` hard, `3` good, `4` easy. Be honest. FSRS uses the
   grade to pick the next review date.

Type `q` or press Ctrl-D to stop early. Reviews you've already graded are kept, and a grade can't be changed afterwards. Each card is scheduled from the moment you grade it.

### Questions and answers

For Markdown and text items, the app splits an excerpt at an answer marker and shows the question
before you set your confidence. The split is at the first line, outside a code fence, that starts with
bold `**Answer**`, `**Solution**` or `**Model answer**` (any case; `**Answer.**`, `**Answer:**` and
`**Model answer**:` all match). Everything before that line is the question, with a leading heading
line and blank lines at the edges removed. That line and everything after it is the answer. Indented
code (four spaces or a tab) and lines inside fenced code blocks do not count as markers. If there is
no marker, or the question would be empty, there is no split and the whole excerpt is shown after
you set your confidence.

```markdown
### Q3
What is a TLB?

**Answer.** A cache of page-table entries.
```

The app shows `What is a TLB?` before you set your confidence, and
`**Answer.** A cache of page-table entries.` after it. `pm review` prints the whole excerpt, so the
split is an app feature.

### Reviewing in the app

Open **Review** in the nav or press `3`. It shows one item at a time: the progress (`3 of 7`), the
topic, the title and the question when there is one.

1. Say your confidence with the slider, or `0`–`9` (`7` is 70%, `0` is 100%), then press
   **Show answer** (or `Enter` / `Space`).
2. The excerpt appears, rendered. Markdown gets bold, lists, tables and maths; a PDF page is shown as
   an image when `pdftoppm` is installed, and as its text otherwise. Maths needs MathJax from a CDN
   the first time, so it needs the network; offline the TeX source is still readable.
3. Grade with **Again**, **Hard**, **Good** or **Easy** (or `1`–`4`). Each button shows when that
   grade comes back: `Good · in 3d`.

The answer is never sent to the page before you commit a confidence: the first request carries the
title and question, never the excerpt; the excerpt is fetched when you press **Show answer**. That is
what keeps you honest.

If the file has moved or gone, the reveal says `can't show this item: …`; grade it from memory or
**Suspend** it. Suspending takes the item out of the review queue and out of the topic's mastery; it
stays in the database. The app asks before suspending, and the Study screen lists suspended items
with a **Resume** button. From the terminal: `pm study ls TOPIC` shows a topic's items with their
numbers, `pm study suspend ID` and `pm study resume ID` switch one off and on, and `pm study rm ID`
removes an item you added by mistake (if it already has reviews it is suspended instead, so the
history stays). `pm topic rename OLD NEW` fixes a topic's name.

When you finish the queue you get a line like
`reviewed 7 · recalled 5 · you said 80% on average, recalled 71%` (a grade of 2 or higher counts as
recalled), plus how many new items wait for another day. `Esc` goes back to Today.

### Are you overconfident?

```
pm study calib
reviews 1  Brier 0.090  (0 is perfect, 0.25 is always guessing 50%)
  said 60-80%: recalled 100% of 1
you underrate yourself by 30 points
```

The confidence numbers you gave during reviews are compared with whether you actually recalled the
item (grade 1 counts as "not recalled").

- **Brier score**: 0 is perfect calibration, 0.25 is no better than always saying 50%.
- **Per bucket**: "when you said 60–80%, you recalled X%". Ideally X falls inside the bucket.
- **Overrate / underrate**: if you overrate yourself, you'll walk into exams thinking you know more
  than you do. Review more.

### Spot the error (needs a model)

Recall is one skill; noticing a wrong statement is another, and exams test it. `pm spot` shows one
of your own notes with **one line quietly changed to say something false**. You bet how sure you'll
be, then pick the line:

```
pm set llm_cmd "my-llm --model small"   # any command that reads stdin and prints a reply
pm llm say hi                           # check it works
pm spot --make 3                        # makes up to 3 cards from items you've reviewed
made 3 cards
pm spot
[1/3] os/paging: notes.md#TLB
  1  The TLB caches page-table entries.
  2  A TLB miss always causes a page fault.
  3  ...
confidence 0-100 (q quits): 70
which line is wrong? (q quits): 2
right: line 2
was:   A TLB miss means walking the page table.
shown: A TLB miss always causes a page fault.
answered 1
```

- The model only writes the card. **It never grades you**: right or wrong is just whether you
  picked the changed line, and the check that exactly one line changed is done by `pm`.
- Cards are made only from text and Markdown items you've recalled at least once (not PDFs), so
  you're testing something you've learned.
- `llm_cmd` is run directly (never through a shell) with a 2-minute limit;
  when the limit passes, the command and anything it started are stopped. Nothing else in `pm`
  needs it; without it, everything else works as before.
- The app's Study screen has the same: **Make 3 cards** and the Spot screen, where the lines are
  only clickable after you've locked in your confidence.

## Testing yourself

Reviews ask "do you remember it?". A test asks "can you do it, now, against the clock?". `pm` keeps a
**question bank**; every question remembers where it came from and how much it can be trusted:

- `source`: taken from your notes or a real paper;
- `checked` and `unverified`: questions from outside sources (a model's variants, LearnHarness practice), shown with a small tag in a test;
- `verified`: checked by hand against a key, and every generated question (its answer is computed;
  see [Practice](#practice)).

### Filling the bank

From your notes: any section with an `**Answer**` paragraph is already a question.

```
pm q import ~/prod-max/notes-site/docs/os/paging.md --topic paging
added 6 questions to paging
```

By hand, with an answer `pm` can check itself:

```
pm q add "Page faults for 7 0 1 2 0 3 0 4 with 3 frames, FIFO?" --topic paging --number 7
pm q add "Which policy suffers from Belady's anomaly?" --topic paging --choice "FIFO;LRU;OPT" --correct 1
```

A past paper: register it, then list its questions in a text file, one per line.

```
pm paper add "2025 midsem" --course os --file ~/papers/os-2025-midsem.pdf --minutes 90
```

```text
# label | marks | topic | where | answer
Q1a | 5 | paging | p2
Q1b | 3 | paging | p2 | =12
Q2  | 4 | scheduling | p3 | =6.25~0.01
Q3  | 8 | deadlock |  | Safe; one safe order is P1 P3 P4 P0 P2.
```

```
pm paper import 1 midsem.txt
added 4 questions
```

`where` is the page the question is on (it is shown as an image during the test); `=12` makes a
number question, `=6.25~0.01` one with a tolerance; other text is the model answer you'll mark
against. A bad line is reported with its line number, and the good ones are imported anyway; run
the import again after fixing it and only the missing lines are added.

### Taking a test

```
pm mock new --course os -n 10       # or: pm mock new --paper 1
test #3: 10 questions, 30m (pm mock take 3)
pm mock take 3
```

A sampled test spreads its questions over the course's topics by weight, preferring well-trusted
questions you haven't seen lately. Answer each question, then say how sure you are. Blank means
"don't know" (scored 0, but honest). `q` pauses: everything typed so far is saved, and
`pm mock take` carries on where you stopped. Numbers can be typed as `6.25 ms`, `6,250` or `25/4`;
something it can't read (`about 6`) counts as wrong and is listed in the result.

At the end `pm` marks the typed answers itself and shows each open answer next to the model
answer, asking for your marks. Be strict: the marks go into the topic's mastery.

In the app (`0`), the clock runs on the server, so you can close the page and come back; past the
limit it shows `over by 4:10` and still lets you finish.

### Reading the result

```
pm mock show 3
test #3  os mock 2026-11-09
score 31 of 50 (62%)  predicted 55%
time: 4m over
  paging  12 of 20
  scheduling  19 of 30
said 70% on average, scored 62%
missed: 2, 5, 9 (pm mock retry 3)
```

- **predicted** is the course's readiness when the test was built: if you score well under it, your
  reviews are telling you more than you can actually do.
- the per-topic lines show where the marks went;
- **said … scored** compares your confidence with your score;
- `pm mock retry 3` builds a new test from the missed questions.

Each marked question becomes one *application* answer for its topic, so `pm study why` shows it.

## Practice

A question bank runs out; a generator doesn't. `pm` has five generators for the operating-systems
problems that come up in every exam, and each one works out its own answer with a real solver, so a
problem can be as fresh as you like and still be marked exactly:

| Generator | Variants | What it asks |
|---|---|---|
| `paging` | `count`, `final`, `fewest` | page faults under FIFO, LRU or OPT; the pages left in memory; which of FIFO and LRU faults less |
| `cpu` | `avg_wait`, `order`, `which` | the average waiting time or the finishing order under FCFS, SJF, SRTF or round robin; which policy drew a Gantt chart |
| `disk` | `movement`, `order` | total head movement or service order under FCFS, SSTF, SCAN, C-SCAN, LOOK or C-LOOK |
| `banker` | `safe_order`, `request` | one safe order (every safe order is accepted); whether to grant a request |
| `hashing` | `table`, `probes` | the table after linear or quadratic probing; the total probes |

### Linking generators to topics

A generator serves a topic once you link it:

```
pm practice link cpu --topic scheduling
linked cpu to os/scheduling
pm practice gens
banker  Banker's algorithm  safe_order, request
cpu  CPU scheduling  avg_wait, order, which  → os/scheduling
…
```

Linking also brings the topic into mock tests: a test for the course then includes generated
questions for it (half of the topic's seats when it also has bank questions, all of them when it has
none). They are marked by code like any typed answer.

### A session

`pm practice` takes the first topic in study-next order that has a generator (or the one you name),
and within it the generator you practised longest ago:

```
pm practice
os/scheduling  CPU scheduling
| Process | Arrival | Burst |
|---|---|---|
| P1 | 0 | 2 |
| P2 | 5 | 2 |
| P3 | 4 | 6 |
| P4 | 1 | 2 |

What is the average waiting time under FCFS? Give it to 2 decimal places.

Waiting time is completion minus arrival minus burst. Ties go to the process that arrived first, then to the lower number.
answer (blank = don't know, q quits): 2.25
confidence 0-100 (q quits): 70
wrong: the answer is 1.5 (±0.005)
FCFS: P1 0–2 | P4 2–4 | P3 4–10 | P2 10–12

- P1 waits 0
- P2 waits 5
- P3 waits 0
- P4 waits 1

Average waiting time: 6 / 4 = 1.50
…
practised 1, 0 right
```

Answers are read loosely: `P2, P1, P3`, `p2 → p1 → p3` and `P2 P1 P3` are the same order, `6.25 ms`
and `25/4` are the same number, and an answer rounded to the places asked for is right within half
the last digit. Each answer is one *application* answer for the topic (`pm study why` shows it), with
your confidence counted in calibration. The **Practice** screen (`p`) does the same, and has the
link/unlink buttons per topic.

### The conventions

Textbooks disagree on a few details. Every problem states the ones it uses, and they are:

- **Paging**: the frames start empty and every first load is a fault. OPT evicts the page used
  furthest in the future; a page never used again goes first, and among several of those, the one
  loaded earliest.
- **CPU**: waiting time is completion − arrival − burst. Ties go to the process that arrived first,
  then the lower number. SJF is non-preemptive; SRTF preempts only for a strictly shorter remaining
  time. In round robin, a process arriving at the instant a quantum ends joins the queue before the
  preempted one.
- **Disk**: SCAN and C-SCAN go to the end of the disk (0 or 199) before turning; LOOK and C-LOOK turn
  at the last request. **The return sweep of C-SCAN and C-LOOK counts as movement**: on the classic
  queue (98 183 37 122 14 124 65 67, head 53, moving up) that gives C-SCAN 382 and C-LOOK 322, where
  some texts say 183 and 153. SSTF ties go to the lower cylinder.
- **Hashing**: h(k) = k mod m; the i-th probe looks at (h + i) mod m (linear) or (h + i²) mod m
  (quadratic); a probe is one slot looked at, the home slot included.

The solvers were checked against the textbook cases in your own notes (Silberschatz's reference
string: FIFO 15, LRU 12, OPT 9; Belady's anomaly 9 → 10; SRTF waiting 6.5 and SJF 7.75; every disk
total above; the banker's state with its grant, wait and unsafe requests) and they agree.

### Your own formula problems: templates

For formula problems (queueing, effective access time, disk I/O time…) write a template. `pm template
dir` prints the folder (`templates` next to the database); put `.toml` files there:

```toml
id = "mm1-wait"
version = 1
title = "M/M/1 time in system"
text = "Jobs arrive at {lam} per hour and one server finishes {mu} per hour. What is the mean time a job spends in the system, in minutes?"
answer = "60 / (mu - lam)"
decimals = 2
steps = "W = 1 / (mu − lam) hours = 60 / ({mu} − {lam}) = {answer} minutes."
constraints = ["mu > lam", "(6000 / (mu - lam)) % 1 == 0"]

[params]
lam = { int = [2, 20] }
mu = { int = [3, 30] }

[original]
params = { lam = 8, mu = 12 }
answer = 15
```

- `params`: each is `{ int = [lo, hi] }`, `{ choice = [1, 2, 4] }` or `{ decimal = [lo, hi, places] }`;
  up to 12. They are drawn in file order, and a draw that breaks a constraint is thrown away.
- `answer` and `constraints` are arithmetic: numbers, the parameter names, `+ - * / // % **`,
  comparisons, `and`/`or`/`not`, `a if c else b` and the functions `min max abs round floor ceil sqrt
  gcd comb factorial log exp`. Nothing else is accepted (no strings, attributes or other names), and
  `pm` reads it with its own small evaluator; it is never run as Python.
- `{name}` in `text` and `steps` is replaced by the value; `{answer}` in `steps` by the answer as shown.
  Anything else in braces stays as written.
- **The trust check:** `[original]` is the problem you took the template from, with its known answer.
  The template loads only if its formula gives that answer for those numbers; otherwise
  `the template doesn't reproduce its original answer: got 14.5, expected 15`. A template without
  `[original]` doesn't load.

Check a file before you rely on it:

```
pm template check ~/.local/share/prod-max/templates/mm1.toml
ok: mm1-wait reproduces its original answer; 200 of 200 seeds gave a problem
pm practice link t:mm1-wait --topic queueing
```

`pm template ls` lists what loaded and why the rest didn't. Change a template's formula or ranges
and raise its `version`: a mock test built from the old version then leaves that question out of
its score instead of marking it against the new answer.

## Studying with LearnHarness

LearnHarness is a separate desktop app: an AI tutor that teaches a topic, quizzes you with
multiple-choice checks, sets practice problems and keeps flashcards. The two tools split the work:

- **pm decides what to study.** It knows your exams, deadlines and mastery, and picks the next topic.
- **LearnHarness teaches it.** You have the conversation there.
- **pm reads the results back.** Quiz answers, practice verdicts and flashcards become evidence in
  the topic's mastery. `pm` only ever reads LearnHarness's folder; it never writes there and never
  starts the app.

### The daily loop

1. Open **Today**. The **study** card lists what is waiting: reviews, spot-the-error cards,
   flashcards ready in LearnHarness, and `tutor next: os / paging`.
2. Press **Copy opening message** (or **Copy for practice**) and paste it into a new LearnHarness
   session. From the terminal, `pm learn paging --copy` does the same.
3. Study in LearnHarness.
4. The daemon (`pm watch`) reads the session on its next tick, or press **Sync now** on the Study
   screen, or run `pm lh sync`.

The opening message looks like this:

```text
[pm:topic=12] I want to study "paging" (course: os).
My exam is on 2026-11-20, in 11 days.
From my planner: mastery 52%. Memory 81%, understanding 67%, no practice yet. I have covered 9 of 15 sections of my notes.
Recent answers I got wrong while being confident:
- notes.md#TLB (I said 90%)
My notes for this topic:
- /home/u/prod-max/notes-site/docs/os/paging.md
Please check what I already know first, then teach what is missing.
```

### The tag

The `[pm:topic=12]` at the start is how `pm` knows which topic a session belongs to: it reads the
first message you sent. A session without the tag (you started it by hand) still imports, with no
topic. Today then shows `1 LearnHarness session has no topic`; give it one on the Study screen, or
with `pm lh map chat_… paging`. A mapping you make by hand survives later syncs.

### What is imported, and how much it counts

| From LearnHarness | Becomes | Counts toward |
|---|---|---|
| A quiz answer (check or probe) | an answer graded by code: the app compared your pick with the key | *understanding*, and calibration when you gave a confidence |
| A prediction question | the same, without a facet | calibration only |
| A practice problem's verdict (solved, solved with hints, gave up) | 1, 0.5 or 0, judged by LearnHarness's model | *application*, never calibration |
| A multiple-choice question, a finished practice problem | a question bank entry, trust `unverified` | mock tests |
| A flashcard in review | its recall probability today | *memory* |

`pm lh sync` is safe to run any number of times: an unchanged file isn't read again and nothing is
counted twice. A file changed in the last ten seconds waits for the next sync, since LearnHarness may
still be writing it. A session saved by a newer LearnHarness than `pm` understands is listed as
skipped (once, in the daemon's log) and left alone until `pm` learns the new format. The flashcard
file's format isn't documented by LearnHarness, so anything unexpected in it skips the cards and
keeps the ones read before.

### The tutor's plugin

`pm lh install` copies a small LearnHarness plugin, **pm planner bridge**, into LearnHarness's
`plugins/` folder (only its two files; nothing else there is touched). Enable it in LearnHarness
under Settings → Community plugins and restart the app. From then on the tutor has four tools:

| Tool | What the tutor gets |
|---|---|
| `pm_context` | the tagged topic's exam date, mastery and its parts, covered sections, recent confident mistakes, prerequisites and note files |
| `pm_notes` | a search of your notes: only files under `notes_dir` and files a topic tracks, never the rest of the index (so not your Downloads) |
| `pm_exam_questions` | real questions for the topic from your past papers and notes (trust `source`), with their answers |
| `pm_problem` | a problem whose answer `pm` computed with a generator, or a verified bank question; the tutor is told to pose it word for word |

After each turn the plugin asks `pm` to sync, so the session's answers show up within seconds.
The plugin talks to `pm ui` on this machine; when `pm ui` isn't running, each tool says
`pm isn't available right now` and the lesson carries on without it. If you use the plugin daily, run
`pm ui` as a service: `pm ui --install` writes the unit and prints the `systemctl` line that starts it.

**Privacy.** Whatever these tools return is sent to the model provider LearnHarness is set up with,
like everything else in the lesson: your topic's numbers, matching note snippets, and past-paper
questions with their answers. That is why the notes search stays inside your notes folder.

The Study screen says `the tutor can't see pm yet: run pm lh install` when the plugin isn't
installed, and asks you to run it again after an update to `pm` that changed the plugin.

Which model works best with the tools (whether it calls them unprompted and copies a problem
faithfully) is still to be tried.

### Where LearnHarness's data is

`pm` looks in `~/.config/LearnHarness/data`. If yours is elsewhere, `pm set lh_dir <folder>` (the
folder that holds `chats/`). When no folder is found, the Study screen says so and Today leaves out
the LearnHarness rows; the tutor's pick still shows.

## Letting a model help

A model is good at writing things and bad at being trusted, so `pm` uses it only for drafts that
something else checks: code, a second solve, or you. It never grades an answer, never marks its own
work as more than `checked`, and never changes your topics or templates by itself. Everything here
needs `llm_cmd` (see [Settings](#settings)); without it `pm` works exactly as before.

### What runs in the background, and what it costs

Background jobs are off until you give them a daily budget of model calls:

```
pm set agent_daily_calls 40
```

The daemon then looks once an hour for work worth doing and runs at most 5 jobs:

- **spots**: up to 3 new spot-the-error cards when fewer than 5 are waiting (one call per card, two
  when a reply has to be retried);
- **sort-sessions**: a topic suggestion for each LearnHarness session without a tag (one call for up
  to 10 sessions);
- **variants**: new questions like the ones you missed in a marked test. One call writes up to three,
  then each is solved again (one call each, two for an open question, whose second answer is
  compared with the first). So a variants job costs about 4 to 7 calls. A question gets at most 3
  live variants, one varied in the last week waits, and no more than 3 variant jobs queue at once.

You can also queue a job yourself (`pm agent add prereqs os` asks for the prerequisites between your
`os` topics) and run the queue now with `pm agent run`. `pm agent ls` shows each job's calls and
the day's total. When the budget runs out mid-job, the job stops and keeps what it had already
stored; the rest waits for tomorrow. Commands you type (`pm q vary`, `pm paper draft`,
`pm template draft`, `pm spot --make`) run straight away and don't count against the budget.

### What `checked` means

Every question in the bank has a trust level: `source` (your notes or a real paper), `checked`,
or `unverified`. A variant is `checked` when a second, separate solve by the model agrees with the
key it wrote: the same number (within the tolerance) or the same choice. An open variant is
`checked` only when the model judges the two answers the same, and `unverified` otherwise; a number
or choice variant whose two answers disagree is dropped. This catches slips, not a misunderstanding
the model makes twice, so `checked` means "probably right", never "right". Mock tests prefer
better-trusted questions.

### Finding a bad question

After a few marked tests, `pm q review` (or the **Questions to check** card on Exam) lists:

- **suspect**: a `checked` or `unverified` question you got wrong while 80% sure or more. Either you
  had a confident misconception (worth knowing) or the key is wrong (worth fixing). Read the model
  answer against your notes.
- **too easy** / **too hard**: three tries or more with a mean of 95% and up, or 10% and down.

`pm q retire ID wrong key` takes a question out of future tests; `pm q restore ID` brings it back.
Retiring a variant lets a new one be made in its place.

### Three things that wait for you

- **Suggestions** (`pm suggest`, or the **suggestions** card on Study): a topic for an untagged
  LearnHarness session, or "os/deadlock needs os/processes". Nothing changes until you accept. A
  suggestion that no longer fits (the session got a topic since, or the prerequisite would make a
  loop) is closed instead of applied.
- **Template drafts**: `pm template draft 12` turns numeric question #12 into a formula template in
  `templates/drafts/`. It has to reproduce #12's answer before it is saved at all, but read it
  anyway: check the parameter ranges and constraints make sense, then `pm template check` the file
  and look at a few problems before `pm template approve mm1-wait` puts it to use.
- **Paper outlines**: `pm paper draft 3 > midsem.txt` lists the paper's questions in the import
  format. Marks and topics are the model's guesses, and lines that failed a check come back as
  `# ? …` comments with the reason. Fix the list against the paper, then `pm paper import 3 midsem.txt`.

### How well it works

Not measured yet: the jobs were built and tested with fake models, and how often a real model's
variants are wrong after the check, or how much of a paper outline needs fixing, depends on the
model in `llm_cmd`. Try each command on a few real questions before turning the budget on, and
retire what you don't like.

## Bug tracking with `pm run`

Wrap the commands you run while coding (tests, builds) in `pm run --`:

```
pm run -- make test
pm run -- python -m pytest
pm run -- ./test.sh
```

`pm run` passes the output through and exits with the command's exit code, so it works anywhere the
bare command did (scripts, editors, Makefiles).

Behind the scenes:

- A **failure** opens a **bug episode** for that exact command in that folder. More failures add to it.
- The next **success** of the same command in the same folder closes the episode as *fixed* and prints
  a one-line summary:
  ```
  pm: fixed bug #2 after 2 fails, 15m lost [off-by-one]
  ```
- **Time lost** adds up the gaps between runs, each gap capped at 30 minutes (so lunch doesn't count).
- In a **git repo**, `pm` snapshots your working tree on each run and stores the diff between the last
  failing run and the fixing one: the actual fix. It never touches your git index or history.
- **Auto-tags**: `off-by-one`, `overflow`, `uninit`, `null-check` and `bounds` are guessed from the fix
  diff; `segfault`, `abort` and `timeout` come from exit codes.
- An episode with no run for 24h is marked *abandoned*.

Looking back:

```
pm bugs                       # totals, tag counts, "bursts", 10 most recent
pm bug 2                      # one episode with its fix diff
pm bug 2 off-by-one loops     # replace its tags
pm bug 2 none                 # clear its tags
```

A **burst** is a tag that shows up 3 or more times in 7 days, for example "you've had 4 off-by-one bugs
this week". That's a pattern worth noticing.

Note: the episode is keyed on the *exact* command and folder. `pm run -- make test` and
`pm run -- make` are different episodes.

### Bugs in the app

**Bugs** (or `7`) is the same view with the 50 newest episodes instead of 10. Four tiles give fixed,
open, abandoned and time lost, the line under them names any burst in the last 7 days, and tags are
listed with counts: click one to show only its episodes, and **show all** clears the filter. Open an
episode to see its runs, its tags and the fix diff; add a tag with autocomplete or remove one with
×. These are the same tags that `pm bug <id> <tags>` writes.

## File search and the daemon

`pm` can keep a full-text index of folders you choose (by default `~/Downloads`), so you can find "that
PDF about page tables" without remembering its name.

```
pm find page table
~/Downloads/os/lecture7-paging.md  [os]
    …time quantum. # [Paging] A [page] [table] maps virtual [pages] to physical frames.
```

- All the words must match. Stemming is on, so "pages" matches "page" and "matrices" matches "matrix".
- A match in the **file name** counts 5× more than one in the text.
- `--course os` limits results to one course.
- `[os]` is the file's course tag (see below).

### Files in the app

**Files** (or `8`) is search with buttons. With the search box empty it lists the 20 most recently
indexed files; otherwise it shows up to 30 matches with the matched words highlighted. Either way a
course filter narrows the list. The search box treats FTS syntax as plain words, so
`"quotes" AND * (` is just a search for those words.

Each file has:

- **Open** for PDFs, images (png, jpg, jpeg, webp, tif, tiff, bmp), docx, pptx, odt, odp, txt, md,
  tex and csv. `pm` hands only these document types to your desktop; scripts, code and other
  program files are never opened.
- **Show in folder**, which opens the folder that contains the file.
- **Study this**, which opens the add-to-study dialog with that file's path filled in. It works for
  PDFs (by page) and text or Markdown files; for anything else (a .docx, an image) it says the file
  isn't a text file.

### Keeping the index up to date

The index is filled by the **daemon**:

```
pm watch --once        # one pass now, prints what it did
pm watch               # runs forever in the foreground
pm watch --install     # writes a systemd user service, then:
systemctl --user daemon-reload && systemctl --user enable --now pm-watch
journalctl --user -u pm-watch   # its logs
```

Every 10 seconds the daemon indexes up to 20 new or changed files (a file is picked up after it has been
unchanged for 10s, so half-finished downloads are skipped). Every 5 minutes, with `notes_url` set, it
applies what you sent from the [site's Planner box](#sending-things-from-the-phone). Once an hour it
sends [nudges](#nudges), reads the site's study clock and pushes [stats](#the-notes-site).

What's readable: PDFs (scanned ones get OCR on their first 10 pages), images (OCR), docx/pptx/odt/odp,
and plain text and code files. Everything else is found by file name only. Hidden files, symlinks,
files over 50 MB, `node_modules`, `__pycache__`, `venv`, `site-packages` and anything under
`watch_ignore` are skipped.

### Course tags

A file gets a course tag in this order:

1. A code from `course_codes` appears in its name or in the first 3000 characters of its text
   (e.g. `CS F372`, with spaces, `_` and `-` ignored).
2. A course name (from your tasks, topics and `course_codes`) is a whole word in its file name.
3. Otherwise, its top folder under the watched root (`~/Downloads/os/x.pdf` → `os`).

```
pm set course_codes "os=CS F372;dbms=CS F212"
```

Files are retagged automatically when these settings change.

## Nudges

When the daemon runs, it sends a desktop notification (with `notify-send`) for any task whose
**start-by date has arrived** and that you haven't worked on today: "start #1 … today" or
"behind on #1 …". There's at most one nudge per task per day, and only within `nudge_hours`
(default `08-22`).

## The notes site

The site itself is in `notes-site/`; [its README](../notes-site/README.md) says how to put your own copy
online and connect `pm` to it.

```
pm stats             # everything as JSON
pm stats --push      # send it to your notes site
pm inbox             # apply what you added on the site, then push
```

The JSON has day-by-day minutes (total, deep, in your peak hours), reviews and recall, fails and fixes,
time per course and kind, estimate bias, deadlines, study and bug summaries, today's plan, the reviews
due, and which phone entries were applied. With `notes_url` set, `--push` sends it to
`notes_url/api/pm` over HTTPS, and the daemon does this hourly.

The app's **Stats** screen (or `6`) shows the same sections locally, without pushing anything. Its
heatmap also counts the time the site's study clock recorded: once an hour the daemon reads that clock
from the site, and a day shows the larger of the two clocks, never their sum.

### The Planner box

The site's home page has a **Planner** box, drawn from the last push: the day meter (time worked
against `hours_per_day`), today's plan with first steps, `BEHIND` and due dates, and the reviews due.
When the push is more than a day old, the box says so. A site login without pm data sees no box.

Set `notes_dir` to your site's `docs` folder and every review item from a note there links to its page,
at the heading when the item is a heading:

```
pm set notes_dir ~/prod-max/notes-site/docs
```

The app's Review screen then also shows **open on the site** after you reveal the answer.

### Sending things from the phone

The Planner box has a small form: **Add to pm** (a title, a length like `1h` and an optional due date
like `+3`), and on each planned task **+ time** and **done**. The laptop picks entries up within 5
minutes while the daemon runs, or when you run `pm inbox`, or when it wakes from sleep (an entry keeps
the time you sent it, never a time in the future). Each entry is applied once, even if the laptop sees
it twice.

Until the laptop answers, the box lists the entry as *Waiting for your laptop*. If the laptop refuses
one (a length like `soon`, a task that is already done), the box shows its message with a **dismiss**
button; nothing was changed on the laptop. Offline, the entry stays on the phone and is sent the next
time the page loads.

### What leaves the laptop

The push contains per-day totals, task titles, courses and first steps, due dates and risk, estimate
ratios, topic names and mastery, review item titles (a prompt or a heading, or the note's name when it
has a site address), note addresses on the site, bug programs and tags, and the ids of applied phone
entries with any error. It never contains file paths, working directories, diffs, pause notes or full
command lines. An item from a file outside `notes_dir` is shown as `item #12`. `pm` only reads the
site's backup (for the study clock) and never writes to it.

Credentials come from `~/.netrc`, which must be readable only by you:

```
machine your-site.pages.dev login USER password PASS
```
```
chmod 600 ~/.netrc
```

## Settings

`pm set KEY VALUE` changes a setting and prints `key = value`. `pm set` alone lists them all with
their values, and `pm set KEY` shows one. An empty value clears a text setting: `pm set llm_cmd ""`.

| Key | Default | What it changes |
|---|---|---|
| `hours_per_day` | `4` | Focused hours per day (0.1–16). The most important setting: `risk`, `today` and nudges all use it. Be realistic, not aspirational. |
| `peak` | `09-12` | Your best hours. Shown on `today`; the stats page counts "peak" minutes in it. |
| `nudge_hours` | `08-22` | Nudges are only sent in this window. There is no off switch: narrow the window, or stop the daemon. |
| `watch` | `~/Downloads` | Folders to index, `:`-separated (`~/Downloads:~/courses`). |
| `watch_ignore` | *(empty)* | Folders under `watch` to skip, `:`-separated. |
| `course_codes` | *(empty)* | `name=CODE` pairs separated by `;`, for course tags. |
| `notes_url` | *(empty)* | `https://…` of your notes site, for `stats --push`. |
| `notes_dir` | *(empty)* | The site's `docs` folder, e.g. `~/prod-max/notes-site/docs`, so review items link to their page on the site. |
| `llm_cmd` | *(empty)* | A command that reads a prompt and prints a reply. Only the model features use it; see [Letting a model help](#letting-a-model-help). |
| `agent_daily_calls` | `0` | Model calls the background jobs may make a day (0–500); `0` is off. |
| `new_per_day` | `10` | At most this many never-reviewed items enter the review queue in a day (1–200); the rest wait. |
| `lh_dir` | *(empty)* | LearnHarness's data folder, the one holding `chats/`. Empty means `~/.config/LearnHarness/data`. `pm` only reads it. |

### Settings in the app

**Settings** (or `9`) lists every setting above with its current value. Each one saves on its own
**Save** button, and the checks are the same as `pm set`: a bad value is refused with the same
message and the old value stays. The screen also shows the database file and how many files are
indexed.

## Backup and undo

```
pm backup                         # a dated copy in ~/.local/share/prod-max/backups/
pm backup ~/usb/pm-before-exams.db
```

`pm backup` is safe while the daemon and the app are running. A plain `cp pm.db` is not: the newest
changes sit in a second file for a while and the copy can miss them. It never overwrites a file. To
restore, stop the daemon and the app, then copy the backup over `~/.local/share/prod-max/pm.db`.
When a new version of `pm` upgrades an older database, it first keeps a copy next to it
(`pm.db.v12.bak`), once per version.

What you can take back:

| Slip | Undo |
|---|---|
| finished or dropped the wrong task | `pm ls --done`, then `pm reopen N` |
| forgot to stop the timer | `pm stop --as 45m` |
| a typo in a task or topic | `pm edit N --title …`, `pm topic rename OLD NEW` |
| added the wrong study item | `pm study ls TOPIC`, then `pm study rm ID` |
| suspended an item | `pm study resume ID`, or **Resume** on the Study screen |
| retired a question | `pm q restore ID` |
| a LearnHarness session under the wrong topic | `pm lh map` |

What you can't: a review grade once given, and time once logged. Both feed what `pm` learns about
you, so there is no edit for them; the next reviews and tasks even a slip out.

To stop the background parts: `systemctl --user disable --now pm-watch` (and `pm-ui`), and delete
`~/.config/systemd/user/pm-watch.service` to remove the unit. Model jobs are off while
`agent_daily_calls` is `0`, and no model is called at all while `llm_cmd` is empty.

## Trying things safely

Two environment variables let you experiment without touching your real data:

```
export PM_DB=/tmp/pm-test.db        # a throwaway database
export PM_NOW=2026-11-20T10:00      # pretend it's this moment
```

`PM_NOW` is great for asking "what if": add tasks, jump forward a few days, and run `pm risk`.

---

## A typical two days with pm

Here's a real session, shown with actual output. It's Monday 9 Nov, 09:00. You have an OS lab due
Friday, a DBMS pset due Sunday and an email to send. The OS exam is on Friday 20 Nov.

### Monday morning: plan the week

```
$ pm set hours_per_day 5
hours_per_day = 5

$ pm add "OS lab 4: shell" --est 3h --due +4 --course os --kind lab --first "read the handout"
added #1

$ pm add "DBMS pset 2" --est 2h --due +6 --course dbms --kind pset
added #2

$ pm add "email TA about regrade" --est 20m --shallow
added #3
```

What's the plan, and is anything at risk?

```
$ pm today
Deep work (peak 09-12):
  #1 OS lab 4: shell  ~4h30m  first step: read the handout
  #2 DBMS pset 2  ~30m

$ pm risk
#1  OS lab 4: shell  due 2026-11-13  late 1%  start by 2026-11-11
#2  DBMS pset 2  due 2026-11-15  late 0%  start by 2026-11-12
crunch risk 1%  start the queue by 2026-11-11
```

Note `~4h30m` for a 3h estimate: with no history yet, `pm` assumes everything takes 1.5× longer. The
risk is low, but the lab is first, so start it.

```
$ pm start 1
started #1 OS lab 4: shell
first step: read the handout
```

At 11:30, stop and write down where you are:

```
$ pm stop "parser done, next: pipes"
stopped #1 after 2h30m
```

### Tuesday: pick up where you left off

```
$ pm start 1
started #1 OS lab 4: shell
first step: read the handout
where you left off: parser done, next: pipes
```

While coding, run the tests through `pm run`. The first two runs fail:

```
$ pm run -- ./test.sh          # exit 1
$ pm run -- ./test.sh          # exit 1
```

You find the bug: a loop used `i <= n` instead of `i < n`. You fix it and run again:

```
$ pm run -- ./test.sh
pm: fixed bug #2 after 2 fails, 15m lost [off-by-one]
```

`pm` saw the fix diff and tagged it. You can look at it later:

```
$ pm bug 2
#2 fixed  ./test.sh  ~/courses/os/lab4
opened 2026-11-10 10:05  closed 2026-11-10 10:20  2 fails  lost 15m
tags: off-by-one

diff --git a/shell.c b/shell.c
--- a/shell.c
+++ b/shell.c
@@ -1 +1 @@
-for (i = 0; i <= n; i++)
+for (i = 0; i < n; i++)
```

You sent the TA email earlier without the timer, so log it, then finish both tasks:

```
$ pm log 3 15m
logged 15m on #3

$ pm done 3
done #3: 15m logged, estimated 20m

$ pm done 1
done #1: 4h30m logged, estimated 3h

$ pm bias
all  n=2  median x1.19
```

`pm` has now learned from two real tasks, and future forecasts will use that instead of the x1.5
default.

### Tuesday noon: set up studying for the exam

Your OS notes are in `~/courses/os/notes.md`, with `# Scheduling` and `# Paging` sections.

```
$ pm topic add scheduling --course os --exam +10 --weight 2
topic #1 scheduling

$ pm topic add paging --course os --exam +10 --needs scheduling
topic #2 paging

$ pm study add ~/courses/os/notes.md#Scheduling --topic scheduling --prompt "How does round robin pick the next process?"
item #1 added to scheduling, due now

$ pm study add ~/courses/os/notes.md#Paging --topic paging
item #2 added to paging, due now

$ pm study next
study next: os/scheduling  mastery 0%
ranking:
  os/scheduling  exam 2026-11-20  mastery 0%  score 0.20
  os/paging  exam 2026-11-20  mastery 0%  score 0.10
```

Scheduling wins because it has double the weight (and paging needs it anyway). Do one review:

```
$ pm review --limit 1
[1/1] os/scheduling: How does round robin pick the next process?
confidence 0-100 (q quits): 70
# Scheduling
Round robin gives each process a fixed time quantum.
grade 1 again, 2 hard, 3 good, 4 easy: 3
next review 2026-11-10 12:10
reviewed 1
```

Then you need the paging slides the professor uploaded:

```
$ pm find page table
~/Downloads/os/lecture7-paging.md  [os]
    …time quantum. # [Paging] A [page] [table] maps virtual [pages] to physical frames.
```

### The daily rhythm, in short

```
pm today                   # morning: what to do
pm start N                 # see the first step / where you left off
pm run -- <your tests>     # while coding
pm stop "next: ..."        # leave a note for future you
pm review                  # flashcards that are due
pm risk                    # evening: anything slipping?
pm done N                  # when finished; this is how pm learns
```

Weekly: check `pm bias` (are estimates getting better?), `pm study calib` (overconfident?) and
`pm bugs` (any bursts?).

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: ...` and exit code 1 | Bad input (wrong date or duration format) or something not found (wrong task id or topic name). The message says which. |
| `pm today` doesn't show a task | Today's `hours_per_day` is already filled by earlier deadlines. It isn't today's job. |
| `pm bias` says `assuming x1.50` | No finished tasks yet. Use `pm done` when you finish things. |
| `pm run` never says "fixed" | The success must be the *same command* in the *same folder* as the failure. |
| No fix diff in `pm bug N` | The folder isn't a git repo, or `git` isn't installed. |
| `pm find` finds nothing | The daemon hasn't indexed yet. Run `pm watch --once`, and check `watch` and `watch_ignore`. |
| PDF text not found | Install `pdftotext` (poppler); for scans also `pdftoppm` + `tesseract`. |
| No desktop nudges | The daemon isn't running (`pm doctor` says), `notify-send` is missing, or it's outside `nudge_hours`. |
| `error: the database is busy` | Another `pm` (the daemon or the app) was writing at that moment. Run the command again. |
| `give a unit: 90m or 90h` | Durations need `m` or `h`. |
| The daemon log says `tick failed: …` | One file or reply upset it; it carries on and tries its hourly work again in an hour. The line names the cause. |
| An app screen says "Couldn't load this screen" | Press **Try again**; if `pm ui` was restarted, reload the page. |
| `stats --push` fails | `notes_url` must be `https://`, and `~/.netrc` must exist with `chmod 600`. |
