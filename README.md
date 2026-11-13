# pm — a planner that learns how long things really take

`pm` is a local, single-user command-line planner (new here? start with [docs/quick-start.md](docs/quick-start.md); for a walk-through with explanations and a worked example, see [docs/usage-guide.md](docs/usage-guide.md); for the browser app screen by screen, [docs/app-guide.md](docs/app-guide.md)). It does six things:

- **Time tracking.** It learns how far off your time estimates are.
- **Deadline risk.** It simulates the chance that each deadline slips and tells you when to start.
- **Daily plan.** It plans your day around your peak hours.
- **Studying.** It schedules spaced-repetition reviews (FSRS) and tracks how well-calibrated your confidence is.
- **Bug tracking.** It logs failing commands, finds the diff that fixed them and tags the kind of bug.
- **Files.** It indexes your Downloads for full-text search. It also nudges you when a task should start and pushes a stats page to your notes site.

Everything is stored in one SQLite file, `~/.local/share/prod-max/pm.db`, created by the first command you run. Four things can send data off your machine, and each is off until you set it up: the stats push to your notes site (`notes_url`), the scoreboard sync (`versus_url`: numbers per day only, see [Versus](#versus)), prompts to a model (`llm_cmd`: parts of your notes and questions go to whatever that command talks to), and the LearnHarness tutor plugin (what its tools return goes to LearnHarness's model provider). The daemon also reads your study clock and phone inbox from the notes site.

## Install

```
uv tool install git+https://github.com/Krishnasai2008/prod-max    # puts `pm` on your PATH
uv tool install --editable .      # or this, inside a clone, to change the code
```

It needs Linux with systemd or macOS, Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). Windows is not supported; WSL works like Linux, except that opening files and desktop nudges don't. Clone the repo if you want the notes site too. The notes site that goes with `pm` is in `notes-site/`; its [README](notes-site/README.md) says how to put your own copy online.

Without installing, run `uv run pm <cmd>` from this folder. The `--install` commands (`pm watch --install`, `pm ui --install`) need the installed `pm`, because the service has to find it.

Setting up from scratch, step by step (settings, daemon, app, notes site, model, LearnHarness, scoreboard): [SETUP-linux.md](SETUP-linux.md) or [SETUP-mac.md](SETUP-mac.md).

`pm doctor` shows what is set up: where the database is, whether the daemon is running, the folders it watches, the model command, and which of the optional programs below are installed.

These programs are optional. `pm` works without them and skips the feature that needs them:

| Program | Used for |
|---|---|
| `pdftotext` (poppler) | Text from PDFs: search, and `#p12` study excerpts |
| `pdfinfo` (poppler) | A PDF's page count, for listing its pages |
| `pdftoppm` (poppler) | PDF pages as pictures in the app, and OCR of scans |
| `tesseract` | Text from images (OCR) |
| `notify-send` (Linux) | Desktop nudges |
| `xdg-open` (Linux) | Opening files and links |
| `git` | The fix diff of a bug in `pm run` |

On macOS, nudges go through `osascript` and files open with `open`; both come with the system.

## Formats used everywhere

| What | Accepted | Examples |
|---|---|---|
| Duration | hours and/or minutes, always with the unit (`90` alone is refused: it could mean either) | `90m`, `4h`, `1h30m`, `2.5h` |
| Date | ISO date, `+N` days from today, `today`, `tomorrow`, or a weekday (the next one after today) | `2026-11-20`, `+3`, `fri` |
| Hours range | `start-end` in whole hours, 0–24 | `09-12`, `08-22` |

## Tasks and time

| Command | What it does |
|---|---|
| `pm add "title" --est 3h [--due D] [--course C] [--kind K] [--shallow] [--first "step"]` | Adds a task. `--kind` (lab, exam, pset, …) is the bucket your estimate bias is learned in (default `task`). `--shallow` marks low-focus work; the default is deep work. `--first` is a tiny first step that is shown when you start. Prints `added #N`, and a note when the due date is already past. |
| `pm start N [--no-open]` | Starts the timer on task N, stopping any timer that's running (`stopped #2 after 40m`). Shows the first step and your last "where you left off" note, then opens the task's links (`opened 2 links`; a file that is gone prints `skipped: gone …`). `--no-open` lists them instead. |
| `pm stop ["note"] [--as 45m] [--energy 1-5]` | Stops the timer. The note is where you left off, and `start` shows it next time. `--as` records a shorter length if you forgot to stop. `--energy` rates how alert you felt (1 drained … 5 sharp) and prints `energy N`. After a session longer than 6h you get a warning. Exits 1 if nothing is running. |
| `pm link N [PATH \| URL]` | Links a file or an `http(s)` page to task N (`linked #N: ~/os/lab4.pdf`); `pm start` opens its links. A relative path is taken from where you are. Without a target it lists the links, numbered; `pm link N --rm 2` removes link 2. Only documents and images open, the same rule as Files; for any other file (a script, an HTML page) its folder opens instead. |
| `pm log N 1h` | Logs time you've already worked, ending now. |
| `pm done N` | Finishes the task and closes its timer. Prints logged vs. estimated time. Only finished tasks teach `pm` your bias. |
| `pm edit N [--title T] [--est D] [--due D \| --no-due] [--course C] [--kind K] [--deep \| --shallow] [--first S]` | Changes an open task and prints `edited #N`. `--course ""` and `--first ""` clear those fields; `--no-due` removes the due date. The estimate can change only while no time is logged. With nothing to change it prints `error: nothing to change`. Finished and dropped tasks can't be edited. |
| `pm drop N` | Drops an open task without finishing it, stopping its timer if it's running. Prints `dropped #N`. A dropped task leaves `pm ls`, `pm today` and `pm risk`, and isn't counted in estimate bias or on-time history, but its logged time still counts as time worked. |
| `pm ls` | Open tasks with kind/course, due date, estimate and logged time. `▶` marks the running one. |
| `pm ls --done` | The last 20 finished or dropped tasks, newest first, with their numbers. |
| `pm reopen N` | Undoes `pm done` or `pm drop`: the task is open again with its logged time (`reopened #N title`). |
| `pm` | With no command: the same as `pm today`. |

## Planning

| Command | What it does |
|---|---|
| `pm bias` | How far off your estimates are: the median ratio of actual to estimated time, overall and per kind (`x1.40` = things take 40% longer than you think). Before you finish any task it assumes x1.5. |
| `pm risk` | For each task with a due date: the **chance it's late**, the date you should **start by** (to finish on time 95% of the time) and `BEHIND` if that date has passed. Then the **crunch risk**, the chance that *anything* is late. It runs 10,000 simulations, working tasks earliest deadline first at `hours_per_day`, with each task's length scaled by your learned bias. |
| `pm energy` | Your rated energy by clock hour (from `pm stop --energy`), with the minutes behind each, and after at least 10 rated sessions and 5 hours a suggested 3-hour `peak` (`suggested peak 10-13 (now 09-12): pm set peak 10-13`). Sessions over 6h are left out. |
| `pm today` | Fills today's hours (`hours_per_day`) earliest deadline first, using bias-corrected remaining time. Deep work is listed first under your `peak` hours, then shallow work. |

## The app

`pm ui` serves a local web app over the same database: a second front end for the things you do most, while the CLI stays as it is. It has nine screens. **Today** shows the running timer with its ticking clock, first step, your "where you left off" note, a pause-note field, Stop, Done and a "Stop as…" fold-out for a forgotten timer (it opens itself after 6 hours). When nothing runs, one button starts the first planned task. Then the day meter (time worked today against `hours_per_day`), today's plan split into deep work under your peak hours and shallow work — each card with ~minutes today, due date, a late-risk bar (green under 20%, orange under 50%, red), `BEHIND` or "start today", first step, and Start / Log / Done — and the number of reviews due. **Tasks** has an add form (same formats as `pm add`; course and kind autocomplete), the open tasks in deadline order with logged/estimate, due, late risk and start-by, each with Start, Log, Done, Edit and Drop (Drop asks first; the estimate field is locked once time is logged), and the last 10 finished tasks with their actual/estimate ratio and on time / late.

**Review** takes one due item at a time: title and question first, then you set your confidence with the slider or the number keys and press **Show answer**. The answer is not sent to the page before that, so you can't peek. The excerpt is rendered — Markdown with maths and tables, or a PDF page as an image when `pdftoppm` is installed and its text otherwise — each grade button says when that grade brings it back (`Good · in 3d`), and **Suspend** takes an item out of the queue (it asks first; **Study** lists suspended items with **Resume**). After a review session it compares what you said with what you recalled: `reviewed 7 · recalled 5 · you said 80% on average, recalled 71%`. Maths is typeset by MathJax from a CDN, so it needs the network the first time; offline the TeX stays readable.

**Study** has the study-next pick and the top 5, your topics by course with a prerequisite graph and mastery bars, a form to add topics and edit their exam date and weight, the calibration chart (with the same numbers in a table under it) and the queue line. **Add items from a file** takes a path, lists the file's sections with the default pick ticked, and adds the ones you tick to a topic you choose or create.

**Risk** is the deadline forecast as a timeline: each task's likely (50%) and worst-case (95%) finish against its due date, a days-late column, and two what-if sliders for hours a day and days lost before you start. Moving them recomputes without saving anything; **Use N h a day** saves `hours_per_day`, and **Reset** puts them back. **Stats** shows the same numbers as `pm stats`, locally and without pushing. **Bugs** has fixed/open/abandoned/time-lost tiles, the 7-day burst line, tags with counts (click to filter, **show all** to clear) and the 50 newest episodes; open one for its runs, tags (add with autocomplete, remove with ×) and fix diff. **Files** lists the 20 most recently indexed files, or up to 30 matches with the matched words highlighted and a course filter; each file has **Open** for document types only, **Show in folder**, and **Study this** to add part of it to a topic. **Settings** lists every setting with its current value and saves them one at a time, with the same checks and messages as `pm set`. **Versus** (`v`) shows the scoreboard from the last sync, with **Sync now** (see [Versus](#versus)).

Also: on **Tasks**, each task's links as chips (open one, remove one, or add a path or address); on **Today**, **Start** opens the task's links, a card asks how your energy was for a session you stopped in the last 30 minutes, and once there's enough data a hint offers the suggested peak hours with a button to use them; on **Study**, a spot-the-error line with **Make 3 cards** (when `llm_cmd` is set) and a link to the **Spot** screen (`#/spot`), which works like Review: bet first, then click the wrong line.

The header always shows the running timer with a Stop button, the crunch risk and reviews due, on every screen.

The page refreshes after every click, when you switch back to its tab, and every minute — so a timer started with `pm start` in a terminal appears there — and it never wipes what you are typing. It works offline, needs no install beyond `pm`, follows the system light/dark setting, and under 700 px wide becomes one column, with the nav at the bottom scrolling sideways.

| Command | What it does |
|---|---|
| `pm ui` | Starts the app on `http://127.0.0.1:8321` and opens it in your browser. Ctrl-C stops it. If it's already running there, it prints `pm ui is already running: http://127.0.0.1:8321`, opens the page and exits 0. |
| `pm ui --port 8399 --no-open` | Starts it on another port (1024–65535) without opening a browser. If another program has the port: `error: port 8399 is in use; try pm ui --port 8400`. |
| `pm ui --install` | Writes the systemd user unit `pm-ui.service` (which runs `pm ui --no-open`) and prints the `systemctl --user daemon-reload && systemctl --user enable --now pm-ui` line to start it. On macOS it writes the launchd agent `~/Library/LaunchAgents/dev.prod-max.pm-ui.plist` instead and prints `start it: launchctl load -w <path>`. It doesn't start it itself. |

Keys, not while typing in a field: `1` Today, `2` Tasks, `3` Review, `4` Study, `5` Risk, `6` Stats, `7` Bugs, `8` Files, `9` Settings, `0` Exam, `p` Practice, `v` Versus, `/` jump to Files and focus the search box, `n` new task, `s` start the first planned task (or, while running, jump to the pause note), `?` help, `Esc` close help. On Review: before the answer is shown, `0`–`9` set the confidence (`0` is 100%, `7` is 70%) and `Enter` or `Space` shows it; then `1`–`4` grade it, and `Esc` goes back to Today.

It listens only on `127.0.0.1` and refuses requests from other web sites (it checks the `Host` and `Origin` headers and requires JSON). Any program on your own machine can still use it. `PM_DB` and `PM_NOW` work as usual.

## Settings

`pm set KEY VALUE` changes a setting and prints `key = value`. `pm set` alone lists every setting with its value, and `pm set KEY` shows one. To clear a text setting, give an empty value: `pm set llm_cmd ""`.

| Key | Default | Meaning |
|---|---|---|
| `hours_per_day` | `4` | Focused hours per day (0.1–16). Drives `risk`, `today` and the nudges. |
| `peak` | `09-12` | Your best hours, shown on `today` and used for the stats page's "peak" minutes. |
| `nudge_hours` | `08-22` | The only hours in which desktop nudges are sent. Nudges can't be switched off here; narrow the range (`pm set nudge_hours 12-13`) or stop the daemon. |
| `watch` | `~/Downloads` | Folders to index, `:`-separated. `pm set watch` warns about one that isn't a folder. |
| `watch_ignore` | *(empty)* | Folders under `watch` to skip, `:`-separated, e.g. `~/Downloads/Data`. |
| `course_codes` | *(empty)* | `name=CODE` pairs separated by `;`, e.g. `os=CS F372;dbms=CS F212`. Used to tag files by course (see `find`). |
| `notes_url` | *(empty)* | Your notes site, `https://…`, for `stats --push` and `inbox`. |
| `notes_dir` | *(empty)* | The site's `docs` folder, e.g. `~/prod-max/notes-site/docs`. Review items from notes in it link to their page on the site (`/os/paging/#tlb`), in the push and as **open on the site** in the app's Review screen. |
| `llm_cmd` | *(empty)* | A command that reads a prompt on stdin and prints the reply, e.g. `my-llm --model small`. It is run directly, never through a shell, with a 2-minute limit (past it, the command and anything it started are stopped). Only `pm llm`, `pm spot --make` and the model jobs (below) use it, and nothing else needs it. |
| `new_per_day` | `10` | At most this many never-reviewed items enter the review queue each day (1–200); the rest wait. |
| `lh_dir` | *(empty)* | LearnHarness's data folder (the one that holds `chats/`). Empty means `~/.config/LearnHarness/data`. `pm` only reads it. |
| `agent_daily_calls` | `0` | How many model calls the background jobs may make a day (0–500). `0` turns them off; commands you type yourself (`pm q vary`, `pm paper draft`, …) don't count against it. |
| `versus_url` | *(empty)* | The scoreboard's hub site, `https://…` (yours or a friend's), for `pm versus`. Checked like `notes_url`. Empty turns the scoreboard off. |

## Study (spaced repetition)

| Command | What it does |
|---|---|
| `pm topic add NAME [--course C] [--exam D] [--weight 1.0] [--needs OTHER]…` | Adds a topic. `--exam` is when it's tested. `--weight` is how much it matters. `--needs` names a prerequisite topic (repeatable; it must already exist in the same course). |
| `pm topic ls` | Topics with exam date, weight, **mastery**, item count and prerequisites. Mastery is coverage (how many of the topic's file sections have items) times a blend of memory (the items' recall probability now), understanding (spot cards) and application (practice), each counted by how much evidence it has; see `pm study why`. |
| `pm topic rename NAME NEW [--course C]` | Renames a topic (`topic #3 is now Graphs`). |
| `pm topic file NAME PATH [--course C] [--rm]` | Counts a file toward the topic's coverage (`tracking ~/os/paging.md for paging (15 sections)`), even before you add items from it. `--rm` stops counting it. Files you add items from are counted already. |
| `pm study add PATH[#LOCATOR] --topic NAME [--course C] [--prompt "question"]` | Adds something to review. It's due immediately. Locators: `notes.md#Heading` (that section), `file.py#L10-25` (lines), `slides.pdf#p12` (a PDF page, which needs a page number). Without a locator you get the whole text file. `--prompt` is the question shown before the answer. Pass `--course` when the topic name exists in several courses. Adding the same thing to the same topic twice is refused. |
| `pm study add FILE --all --topic NAME [--course C]` | Adds a file's sections in one go: Markdown headings that have no subheadings and at least 3 non-blank lines of their own, or every PDF page (the first 500). Sections already in that topic are skipped (the same section can sit in two topics). Prints `added 12 items to paging` or `added 1 item to paging (3 already there)`, or `nothing to add`. |
| `pm study ls NAME [--course C]` | The topic's items with their numbers; `(suspended)` marks one that is out of reviews. |
| `pm study rm ID` | Removes an item added by mistake. An item with reviews or spot cards is suspended instead, so its history stays. |
| `pm study suspend ID` / `pm study resume ID` | Takes an item out of reviews, or puts it back. |
| `pm study next` | What to study now: the topic with the highest `weight × (1 − mastery) / days to exam`. If that topic has a prerequisite under 60% mastery, it sends you to the prerequisite first, and says so when that topic has nothing in it yet. It also shows the top 5. |
| `pm review [--limit 20]` | Reviews due items. For each one: say your confidence (0–100), see the excerpt, then grade it (1 again, 2 hard, 3 good, 4 easy). FSRS picks the next review date from the moment you grade. At most `new_per_day` never-reviewed items join the queue each day; when more are due it ends with `12 new items wait for another day (pm set new_per_day)`. `q` or Ctrl-D stops early. |
| `pm spot` | Spot the error: each card is one of your reviewed text items with one line quietly made false. Bet your confidence, then pick the line; it shows the line as it was and as shown. Right or wrong is decided by the line number, never by a model. `q` or Ctrl-D stops. |
| `pm spot --make 3` | Makes up to 3 new cards from text items you've already reviewed, by asking `llm_cmd` to change one line. A bad reply is retried once and then skipped (`skipped #4: …`); if the command itself fails, it stops. Prints `made 3 cards`. |
| `pm llm WORDS…` | Sends the words to `llm_cmd` and prints the reply, to check your setup. |
| `pm study why NAME [--course C]` | What the topic's mastery is made of: coverage, memory, understanding and application, each with its evidence, or `-` when there is none yet. |
| `pm study misses` | Confident mistakes: answers where you said 70% or more and got it wrong, newest first. |
| `pm study ready` | Per course with an exam ahead: the weighted mastery of its upcoming topics, the next exam and how many topics. |
| `pm study calib` | Confidence calibration: Brier score (0 is perfect, 0.25 is coin-flipping), recall per confidence bucket, and whether you overrate or underrate yourself. Grade 1 counts as "not recalled". With answers from more than one source (reviews, spot cards, practice) it counts them all, a half-marks answer as 0.5, and adds a line per source. Answers graded by a model never count. |

## Tests and past papers

Questions live in a bank. Each one remembers where it came from and how far it can be trusted (`source` for anything taken from your own notes or a real paper). Typed answers (numbers, words, orders, sets, multiple choice) are checked by `pm` itself, by matching the text, never by running it; open answers you mark yourself against the model answer. A finished test adds one *application* answer per question to each topic's mastery.

| Command | What it does |
|---|---|
| `pm q add "PROMPT" --topic T [--course C] [--marks 2] [--answer TEXT \| --number 12 [--tol 0.5] \| --choice "FIFO;LRU;OPT" --correct 2]` | Adds a question by hand: open with a model answer, a number (with a tolerance), or multiple choice (`--correct 1,3` for several). Prints `question #12 added to paging`. The same prompt twice is refused. |
| `pm q import NOTE.md --topic T [--course C]` | Every section of the note with an `**Answer**` paragraph becomes an open question (the part above is the question). Prints `added 14 questions to paging (2 already there)`. |
| `pm q ls [--course C]` | The bank: `#12  os/paging  source  open  1 mark  What is a TLB?`. |
| `pm q retire ID [REASON…]` / `pm q restore ID` | Takes a question out of future tests (a wrong key, say), or puts it back. |
| `pm paper add TITLE --course C [--file PAPER.pdf] [--minutes 90]` | Registers a past paper. |
| `pm paper import ID LIST.txt` | Adds its questions from a list, one per line: `label \| marks \| topic \| where \| answer`, e.g. `Q1b \| 3 \| paging \| p2 \| =12`. `where` is a page of the PDF (`p2`); `=12` or `=6.25~0.01` makes a number question, other text is the model answer. Bad lines are reported with their line number (exit 1) and the rest are imported; importing again adds nothing. |
| `pm paper ls` | The papers with their question count and time limit. |
| `pm mock new --course C [-n 10] [--minutes M]` or `pm mock new --paper ID` | Builds a test: a whole paper, or `n` questions sampled by topic weight (best-trusted and least recently seen first). The default time is 1.5 minutes a mark (at least 5). It records the predicted score (the course's readiness). Prints `test #3: 10 questions, 30m (pm mock take 3)`. |
| `pm mock take [ID]` | Sits the test (or the one in progress): each question, your answer (blank for don't know, `q` pauses), your confidence. Answers are saved one by one. At the end it marks the typed ones, asks your marks for the open ones next to the model answer, and shows the result. |
| `pm mock ls` / `pm mock show ID` | The tests with their status, or a marked test's result: the score against the prediction, the time over, the per-topic score, your confidence against your score, answers it couldn't read, and what you missed. |
| `pm mock retry ID` | A new test from the questions you missed. |

The app's **Exam** screen (`0`) does the same (once the bank has questions): build a test, sit it with the clock running (the time is the server's, so closing the page loses nothing; past the limit it says by how much and lets you finish), mark the open answers, and read the result. The answers are never sent to the page before you finish.

## Practice (generated problems)

`pm` can make an endless supply of fresh operating-systems problems and work out their answers itself, with real solvers: page replacement (FIFO, LRU, OPT), CPU scheduling (FCFS, SJF, SRTF, round robin), disk scheduling (FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK), the banker's algorithm and hashing with open addressing. Each problem states its conventions (tie-breaks, what counts as a fault, where the disk head turns), you answer with a confidence bet, and `pm` checks it, shows the worked solution and adds an *application* answer to the topic's mastery. Once a topic has generators linked, mock tests for its course mix in generated questions too (half of the topic's seats when it also has bank questions). Formula problems come from your own templates (below). No model is involved anywhere.

| Command | What it does |
|---|---|
| `pm practice link GEN --topic T [--course C]` / `pm practice unlink GEN --topic T` | Links a generator to a topic (`linked paging to os/paging`), or removes the link. |
| `pm practice gens` | The generators with their variants and linked topics: `paging  Page replacement  count, final, fewest  → os/paging`; then any template that failed to load. |
| `pm practice [TOPIC] [--course C]` | Practises: the topic you name, or the first topic in study-next order that has a generator (the generator you practised longest ago comes first). Each problem: type the answer (blank = don't know, `q` quits), then your confidence; it says `right`, or `wrong: the answer is 12`, and prints the worked solution. Ends with `practised 3, 2 right`. |
| `pm template dir` | Prints the templates folder (`templates` next to the database), creating it. |
| `pm template ls` | The templates that loaded (`t:mm1-wait  M/M/1 time in system  v1`) and the errors of those that didn't. |
| `pm template check FILE` | Checks a template file: `ok: mm1-wait reproduces its original answer; 200 of 200 seeds gave a problem`, or `error: …` (exit 1). |

A template is a TOML file: a question text with `{name}` placeholders, parameter ranges, an answer formula (arithmetic only, read by `pm`'s own small evaluator, never run as code) and **the original problem it came from with its known answer**. A template loads only if its formula reproduces that answer, so a typo in a formula is caught before it ever marks you wrong. The [usage guide](docs/usage-guide.md#practice) shows a full example.

The app's **Practice** screen (`p`) does the same: pick a topic (or the next best), answer, read the verdict and the steps, and link or unlink generators per topic. The key and the steps reach the page only after you answer.

## LearnHarness (tutor sessions)

[LearnHarness](https://learnharness.ai) is a separate desktop tutor app. `pm` picks what to study and reads the results back; it never writes to LearnHarness's folder and never runs it.

| Command | What it does |
|---|---|
| `pm learn TOPIC [--course C] [--practice] [--copy]` | Prints the first message for a new LearnHarness session: a `[pm:topic=N]` tag, your exam date, the topic's mastery and facets, recent confident mistakes and your note files, then "check what I know, then teach" (or, with `--practice`, "give me exam-style problems"). `--copy` also puts it on the clipboard with `wl-copy` or `xclip`. |
| `pm lh sync` | Reads new and changed sessions and the flashcard file: `learnharness: 2 sessions, 6 answers, 3 outcomes, 9 questions, 4 cards`, or `learnharness: nothing new`, then one line per skipped file. The daemon does this on every tick. |
| `pm lh ls` | The sessions read so far: `chat_…  teach  os/paging  4m  2026-11-09  TLB and paging` (`-` when it has no topic). |
| `pm lh map CHAT TOPIC [--course C]` / `pm lh map CHAT --none` | Gives a session without a tag a topic (its answers and questions follow), or takes it away. |
| `pm lh install` | Installs (or updates) the `pm-bridge` plugin in LearnHarness's `plugins/` folder, so the tutor can ask `pm` for the topic's context, your notes, past-paper questions and problems with code-computed answers. Enable it in LearnHarness under Settings → Community plugins and restart the app; it needs `pm ui` running. It writes only the plugin's two files. |

What comes in: a quiz answer becomes a code-graded answer (it counts toward calibration, and a check or probe toward the topic's *understanding*); a practice problem's verdict becomes an *application* answer judged by LearnHarness's model (never counted toward calibration); multiple-choice questions and finished practice problems go into the question bank as `unverified`; flashcards count toward the topic's *memory*. A file that is still being written waits for the next sync, and a session in a newer LearnHarness format is listed as skipped.

In the app, **Today** gathers everything waiting to study in one card (reviews, spot cards, LearnHarness cards, the tutor's next topic with **Copy opening message**, practice, a test in progress, sessions without a topic), and **Study** lists the LearnHarness sessions with a topic picker for the unsorted ones and **Sync now**.

## Letting a model help

With `llm_cmd` set, a model can write material for you to check. It never grades, never sets a question's trust above `checked`, and never changes your topics: everything it suggests waits for you to accept it.

| Command | What it does |
|---|---|
| `pm q vary ID [-n 3]` | Asks the model for up to `n` new questions like #ID (at most 10). Each one is solved a second time by the model; a number or choice question whose two answers disagree is dropped, an open one whose answers differ is kept as `unverified`, the rest are `checked`. Prints `3 variants of #12 added, 1 dropped`. Only original questions can be varied. |
| `pm q review` | Questions to look at after your marked tests: `suspect` (a model-written question you got wrong at 80% confidence or more, so its key may be wrong), `too easy` or `too hard` (3 tries or more, mean 95% and up or 10% and down). Retire a bad one with `pm q retire ID reason`. |
| `pm paper draft ID` | Prints the model's question list for a paper with a PDF, in the `pm paper import` format. Lines that don't check out (an unknown topic, a page the PDF doesn't have) come back commented with the reason. Save it, fix it against the paper, then import it. |
| `pm template draft QUESTION` | Drafts a formula template from a numeric question and saves it under `templates/drafts/` (`drafted t:mm1-wait in ~/.local/share/prod-max/templates/drafts/mm1-wait.toml`). The draft must already reproduce the question's answer; a failed draft is retried once. |
| `pm template approve NAME` | Checks the draft again and moves it into `templates/`, where it starts making problems. |
| `pm suggest` / `pm suggest accept ID` / `pm suggest reject ID` | The model's open suggestions (a topic for an untagged LearnHarness session, or a prerequisite between two topics of a course), then accept or reject one. Accepting applies it then; a suggestion that no longer fits (the session got a topic, a prerequisite would make a loop) is closed. |
| `pm agent add KIND [ARG]` | Queues a job: `variants QUESTION`, `spots`, `sort-sessions` or `prereqs COURSE`. |
| `pm agent ls` | Recent jobs with their status and calls, then `budget: 12 of 40 calls used today`. |
| `pm agent run [--limit N]` | Runs queued jobs now, within today's budget. A job that runs out of calls stops and keeps what it already stored. |

With `agent_daily_calls` above 0 the daemon plans and runs jobs once an hour (at most 5 an hour): spot cards when fewer than 5 wait, sorting untagged LearnHarness sessions, and variants of questions you missed in a marked test (at most 3 per question, a question varied in the last week waits, and at most 3 such jobs queued at once). A session it found no topic for, and an item it couldn't make a spot card from, are not asked about again.

In the app, a marked test on **Exam** offers **Make variants** of the missed questions when `llm_cmd` is set, and lists the questions to check with a **Retire** button; **Study** shows the open suggestions with **Accept** and **Reject**, and the day's model calls; **Settings** has *Model calls a day*.

## Bugs

| Command | What it does |
|---|---|
| `pm run -- CMD ARGS…` | Runs a command (e.g. `pm run -- make test`) and exits with its exit code. A failure opens a **bug episode** for that command in that folder; the next success closes it as fixed and prints the fails, the time lost and the suggested tags. In a git repo it stores the diff between the last failing run and the fix (your git index is never touched). Time lost counts the gaps between runs, each capped at 30 min. An episode with no run for 24h is marked abandoned. |
| `pm bugs` | Episodes fixed/open/abandoned, total time lost, tag counts, "bursts" (a tag 3+ times in 7 days) and the 10 most recent. |
| `pm bug N` | One episode: when it opened and closed, fails, time lost, tags and the fix diff. |
| `pm bug N tag1 tag2…` | Replaces its tags (lowercase words with dashes). `pm bug N none` clears them. |

Auto-tags: `off-by-one`, `overflow`, `uninit`, `null-check` and `bounds` come from the fix diff. `segfault`, `abort` and `timeout` come from the exit codes.

## Files and search

| Command | What it does |
|---|---|
| `pm find WORDS… [--course C]` | Full-text search of the indexed files, ranked by relevance; a match in the file name counts 5× more than one in the text. It finds files that contain all the words, with word stemming ("matrices" finds "matrix"). Prints the path, the course tag and a snippet with `[matches]`. |
| `pm watch` | Runs the daemon in the foreground (usually systemd or launchd runs it). Every 10s it indexes up to 20 new or changed files. Once an hour it sends nudges, syncs the scoreboard and pushes stats. |
| `pm watch --once` | Runs one tick now and prints what it did. |
| `pm watch --install` | Writes the systemd user unit `~/.config/systemd/user/pm-watch.service`. Then run `systemctl --user daemon-reload && systemctl --user enable --now pm-watch`. Logs: `journalctl --user -u pm-watch`. On macOS it writes the launchd agent `~/Library/LaunchAgents/dev.prod-max.pm-watch.plist` and prints `start it: launchctl load -w <path>`; its output is not kept (run `pm watch` in a terminal to see it). |

What gets indexed:
- **Formats with text:**
  - PDF (with `pdftotext`; scanned PDFs are OCR'd with `pdftoppm` + `tesseract`)
  - images: png, jpg, webp, tiff, bmp (with `tesseract`)
  - docx, pptx, odt, odp
  - plain text and code: txt, md, tex, py, c, cpp, h, java, js, ts, go, rs, csv, json, html, ipynb, sql, sh
- **Everything else** (e.g. xlsx, doc, ppt) is searchable by file name only.
- **Skipped:**
  - hidden files and folders
  - partial downloads
  - files over 50 MB (name only)
  - symlinks
  - `node_modules`, `__pycache__`, `venv`, `site-packages`
  - anything under `watch_ignore`
- **Timing:** a file is picked up once it hasn't changed for 10s. Deleted files drop out of the index.
- **Scanned PDFs:** a PDF with under 100 characters of text is treated as a scan, and its first 10 pages are OCR'd (a few seconds a page). Pages after 10 are found by name only.

Course tags: a file gets a course if any `course_codes` code appears in its name or in the first 3000 characters of its text (spaces, `_` and `-` are ignored). A file also gets a course if a course name is a whole word in its file name. Course names come from your tasks, topics and `course_codes`. Otherwise the course is the file's top folder under the watched root (`~/prod-max/notes-site/docs/ai-ml/…/x.md` is `ai-ml`). Files directly in the root get no course. Files are retagged automatically when any of these, or `watch`, change.

Nudges: once per task per day, within `nudge_hours`, for any task whose start-by date has arrived and that you haven't worked on today. The message is "start #N … today" or "behind on #N …".

## The notes site

| Command | What it does |
|---|---|
| `pm stats` | Prints everything as JSON: day-by-day minutes, deep and peak time, reviews, fails and fixes, estimate bias, deadlines, study and bugs, today's plan, the first 30 reviews due, and which phone entries were applied. |
| `pm stats --push` | Sends it to `notes_url` + `/api/pm` (HTTPS only, no redirects) and prints `pushed N KB to host`. The daemon also does this hourly once `notes_url` is set. |
| `pm inbox` | Fetches what you added on the site's home page (`notes_url` + `/api/pm-inbox`), applies each entry once (`inbox: added #7 OS lab 3`, `inbox: logged 45m on #3`, `inbox: done #3`, or `inbox: add failed: …`), then pushes so the phone sees the answer. Nothing new: `inbox empty`. The daemon does this every 5 minutes. |

The site's home page shows a **Planner** box from the push: today's plan, the day meter and the reviews due, each linking to its note when `notes_dir` is set. Its form sends a task, time logged on a planned task, or "done" back to the laptop. With `versus_url` set, a **Versus** box under it shows the scoreboard. On a computer with a mouse the Planner box also links to the app (`http://127.0.0.1:8321`, opened in a new tab). The link works only on the laptop while `pm ui` runs, and it assumes the default port. It is hidden on touch screens. The app itself stays on the laptop: the site can't reach its database, and the app answers no request from another site.

What the push contains: per-day totals, task titles, courses and first steps, due dates and risk, estimate ratios, topic names and mastery, review item titles (a prompt or a heading, or the note's name when it has a site address), note addresses on the site, bug programs and tags, the ids of applied phone entries with any error, and (with `versus_url` set) the scoreboard from the last sync: the players' names and their numbers. It never contains file paths, working directories, diffs, pause notes or full command lines. `pm` only reads your site's study clock (`/api/backup`, every 5 minutes while the daemon runs), so Stats and the scoreboard count time studied on the site, with time the timer ran over the same minutes counted once; it never writes there.

The push logs in with the credentials in `~/.netrc`. Python ignores that file unless only you can read it:

```
machine your-site.pages.dev login USER password PASS
```
```
chmod 600 ~/.netrc
```

## Versus

A daily study contest with friends. Each player's `pm` sends a card to one site, the hub, and fetches everyone's. A card holds numbers per day only: minutes studied, reviews done, quiz answers right, test answers right and the syllabus level. No task titles, topic names or file names leave the laptop in it.

| Command | What it does |
|---|---|
| `pm versus` | Prints the board from the last sync, without going online. Off: `versus is off: pm set versus_url https://the-scoreboard-site`. Before the first sync: `no scoreboard yet: pm versus --sync`. |
| `pm versus --sync` | Sends your card to `versus_url` + `/api/versus`, fetches everyone's, then prints the board. The daemon does this hourly, before the stats push. |

```
versus · 2026-11-13 (live)
                         you     sam
minutes studied          185     140  you
reviews done              42      60  sam
quiz answers right        18      18
test answers right         9       0  you
syllabus gained         +2.1    -0.4  you
today: you 3 · sam 1
wins: you 1 · sam 0 · draws 1
days of 30m or less: you 0 · sam 1
score: you 1 · sam 0
2h+ days in a row: you 1 · sam 1
```

How a day is won: there are five categories. Minutes come from timer sessions, `pm log` and your notes site's study clock, with time both clocks ran counted once (time added with `pm log` never adds on top of site time, and a day is never under its LearnHarness tutor minutes); reviews are review grades; quiz answers are right answers to practice problems, spot cards and other graded answers that aren't reviews or tests; test answers are right answers in mock tests; syllabus is the day's change in your average topic mastery. The one player ahead in a category (with more than 0) takes its point, and the most points wins the day. A day with no sole winner, on which somebody studied, is a draw. A final day on which you studied 30 minutes or less is a penalty day. Your overall score goes up by one for each day won and down by one for each penalty day, and never below zero. Today is live; a day is final once every player's `pm` has synced after it ended. The wins, draws and streak count the final days (up to 400) from the first day every player had started. The last line is each player's study streak, days in a row with 2 hours or more; it is shown, not scored. It is an honour system: the board shows what each `pm` sends.

Joining: `pm set versus_url https://the-hub-site` and a line for that host in `~/.netrc`; your login's user name is your name on the board. The hub owner plays with their normal site login and gives each friend a scoreboard-only login, which opens `/api/versus` and nothing else on the site. Step by step: [SETUP-linux.md](SETUP-linux.md#11-join-a-scoreboard) or [SETUP-mac.md](SETUP-mac.md#11-join-a-scoreboard).

The app's **Versus** screen (`v`) shows the same board with **Sync now** (which also pushes the stats to your notes site, when `notes_url` is set). With `notes_url` set, the push carries the last board too, and your own site's home page shows it in a **Versus** box under the Planner box.

## Backup and undo

| Command | What it does |
|---|---|
| `pm backup [FILE]` | Copies the whole database to FILE, or to a dated file in `~/.local/share/prod-max/backups/`. Safe while the daemon and the app are running (a plain `cp` is not: recent changes can be missing). It never overwrites a file. |

To restore, stop the daemon and the app and copy a backup over `pm.db`. Before `pm` upgrades an older database it keeps a copy next to it, once per version (`pm.db.v12.bak`).

What can be undone: `pm reopen` (done, drop), `pm study resume` (suspend), `pm q restore` (retire), `pm lh map` (a session's topic), `pm edit` and `pm topic rename` (typos), `pm stop --as` and `pm log` (a forgotten timer). What can't: a review grade once given, and logged time.

## Environment variables

| Variable | Effect |
|---|---|
| `PM_DB` | Use another database file (handy for trying things out). |
| `PM_NOW` | Pretend it's this time, e.g. `PM_NOW=2026-11-20T10:00`. |
| `PM_NETRC` | Read credentials from this file instead of `~/.netrc`. |

## A typical day

```
pm today                      # what to do
pm ui                         # or the app: the same plan in a browser
pm start 3                    # shows the first step / where you left off
pm run -- make test           # as you code; logs fails and the fix
pm stop "parser done, next: errors"
pm review                     # due flashcards
pm risk                       # anything slipping?
pm done 3                     # teaches pm your estimate bias (pm reopen 3 if that was a slip)
```

## Development

Tests: `uv run python -m unittest discover -s tests -v` (stdlib unittest only).
