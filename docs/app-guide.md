# pm app guide

`pm ui` is `pm` in your browser. This guide goes through it one screen at a time: what you see, what
each button does, and what to watch out for. New to `pm`? Read the [quick start](quick-start.md)
first. The [usage guide](usage-guide.md) explains the ideas behind each feature (bias, risk, mastery)
in depth.

**About the examples:** names such as `maths`, `os` and `paging` are made up. You will see your own
courses, topics and tasks.

## Contents

1. [Starting the app](#starting-the-app)
2. [What is on every screen](#what-is-on-every-screen)
3. [Keys](#keys)
4. [Today](#today-key-1)
5. [Tasks](#tasks-key-2)
6. [Review](#review-key-3)
7. [Study](#study-key-4)
8. [Add items from a file](#add-items-from-a-file)
9. [Spot](#spot-no-key)
10. [Risk](#risk-key-5)
11. [Stats](#stats-key-6)
12. [Bugs](#bugs-key-7)
13. [Files](#files-key-8)
14. [Settings](#settings-key-9)
15. [Exam](#exam-key-0)
16. [Practice](#practice-key-p)
17. [Versus](#versus-key-v)
18. [What the app cannot do](#what-the-app-cannot-do)
19. [When something looks wrong](#when-something-looks-wrong)

---

## Starting the app

```
$ pm ui
pm ui on http://127.0.0.1:8321
```

It opens the page in your browser and runs until you press Ctrl-C in that terminal.

| Command | Does |
|---|---|
| `pm ui` | starts the app and opens the page |
| `pm ui --no-open` | starts it without opening the page |
| `pm ui --port 8322` | uses another port (1024 to 65535) |
| `pm ui --install` | sets it up as a background service, so it is always running |

- Run `pm ui` while it is already running and it opens the page and exits.
- If another program has the port, it says `error: port 8321 is in use; try pm ui --port 8322`.
- `pm ui --install` only writes the service file and prints the line that starts it. The setup guides
  ([Linux](../SETUP-linux.md#5-the-app), [Mac](../SETUP-mac.md#5-the-app)) have that step.

The app and the `pm` commands share one database. A timer started in a terminal shows up in the app,
and a task added in the app shows up in `pm ls`.

## What is on every screen

**The top bar** has, from left to right:

- **pm**: a link back to Today.
- **The screen links**: Today, Tasks, Review, Study, Risk, Stats, Bugs, Files, Settings, Exam, Practice,
  Versus.
- **Two badges**: the crunch risk (the chance that any deadline slips) and the number of reviews due.
  Each is hidden when there is nothing to show.
- **The timer chip**: the running task's title, its clock and a Stop button. It is hidden when no timer
  runs.

**Messages:**

- A short message at the bottom (a *toast*) confirms what just happened, for example `saved` or
  `#3 done (undo: pm reopen 3)`.
- A red line under the top bar, `pm ui is not answering`, means the page lost the app. See
  [When something looks wrong](#when-something-looks-wrong).

**Refreshing:** the page reloads its data after every click, when you come back to its tab, and once a
minute. It never wipes a field you are typing in.

**Formats** are the same as on the command line. A duration always carries its unit (`90m`, `2h`,
`1h30m`), and a date is `2026-11-20`, `+3` (days from today), `today`, `tomorrow` or a weekday (`fri`).
A value the command line would refuse, the app refuses with the same message.

**Layout:** the app follows your system's light or dark setting. On a window narrower than 700 px it
becomes one column, and the screen links move to the bottom and scroll sideways.

## Keys

Keys work when you are not typing in a field.

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
| `v` | Versus |
| `/` | go to Files and put the cursor in the search box |
| `n` | new task |
| `s` | start the first planned task; while a timer runs, jump to the pause note |
| `?` | show the key list |
| `Esc` | close the key list |

Review, Spot and Practice have their own keys, listed in their sections.

---

## Today (key `1`)

The screen to keep open while you work. From top to bottom:

### The timer card

**When nothing is running**, it shows one button, **Start: (title)**, for the first task in today's
plan. With no tasks at all it says `nothing to do` and links to Tasks.

**When a timer is running**, it shows:

- the task's title and a ticking clock;
- `first step:` and `where you left off:` (the note from your last stop), when the task has them;
- a **pause note** field. Write where you are leaving off, then press **Stop**;
- **Done**, which stops the timer and finishes the task;
- **Stop as…**, a fold-out with one field. Type `45m` there and press Stop to record 45 minutes instead
  of the real time. Use it when you forgot the timer.

After 6 hours the card says `this has run over 6 hours` and opens **Stop as…** for you.

### The Study card

A list of the study work that is waiting. It appears only when there is something:

- `N reviews due`, a link to Review;
- `N spot-the-error cards`, a link to Spot;
- `N cards ready in LearnHarness`, when you use LearnHarness;
- `tutor next: course / topic` with **Copy opening message** and **Copy for practice**. Each copies a
  ready-made first message for a new LearnHarness session on that topic. If the browser refuses the
  clipboard, the message appears in a box to copy by hand;
- `practise: course / topic`, a link to Practice;
- `a test is in progress`, a link to Exam;
- `N LearnHarness sessions have no topic`, a link to Study, where you give them one.

### The energy card

For 30 minutes after you stop a timer, a card asks `how was your energy?` with buttons **1** to **5**
(1 drained, 5 sharp). The rating is optional. Enough ratings let `pm` suggest your best hours.

### The Day card

A bar of time worked today against your hours a day, for example `1h50m of 4h`.

Once you have rated enough sessions, a line under it says `your best hours look like 10-13` with a
**Use 10-13** button, which saves that as your peak hours.

### Today's plan

Your tasks for today, under **Deep work (peak 09-12)** and then **Shallow**. Each card shows:

| Part | Meaning |
|---|---|
| title, course and kind | what it is |
| `~1h30m today` | the time planned for it today, corrected for how long things really take you |
| `due 2026-11-20 (in 3 days)` | the deadline |
| `BEHIND` | the last safe day to start has passed |
| `start today` | today is the last safe day to start |
| the bar and `late 12%` | the chance it misses its deadline: green under 20%, orange under 50%, red above |
| `first step:` | the small first step you gave it |

Each card has three controls:

- **Start** starts the timer and opens the task's links (files and pages). It reads `running` on the
  task being timed.
- **log** with a field and **Log** adds time you worked without the timer, for example `30m`.
- **Done** finishes the task.

A task that does not fit in today's hours is not shown here. It is still on Tasks.

---

## Tasks (key `2`)

Every task, with the forms to add and change them.

### Add a task

| Field | What to type |
|---|---|
| **title** | the name, up to 200 characters |
| **estimate** | your honest guess, with a unit: `90m`, `2h`, `1h30m`. Required |
| **due** | the deadline: `2026-11-20`, `+3`, `fri`. Optional |
| **course** | free text such as `maths`. It offers the courses you already use |
| **kind** | the type of work (`pset`, `lab`, `exam`…). It offers the kinds you already use |
| **deep / shallow** | deep is focused work; shallow is low-focus work such as email |
| **first step** | a tiny first step, shown when you start |

Press **Add**. The `n` key jumps here from any screen.

### Open tasks

A table in deadline order. The columns:

| Column | Meaning |
|---|---|
| task, course, kind, energy | what you entered (energy is deep or shallow) |
| logged / estimate | time worked so far against your estimate |
| due | the date, and how far away it is |
| late | the chance it misses the deadline. `—` for a task with no due date |
| start by | the last safe day to start, with `BEHIND` when that day has passed |

The buttons on each row:

- **Start** starts the timer. The row of the running task is highlighted and its button reads
  `running`. Unlike Start on Today, this one does not open the task's links.
- **log** and **Log** add time afterwards.
- **Done** finishes the task. The toast shows how to undo it: `pm reopen N`.
- **Edit** turns the row into a form with the same fields as Add. **Save** keeps the changes and
  **Cancel** drops them. Once time is logged, the estimate field is locked and says
  `locked: time is logged`, because `pm` learns from comparing that estimate with the real time.
- **Drop** closes a task you will not do. It asks first, and the logged time is kept.

### Links

Under each task is a row of its links: files and web pages you need for it. They open when you press
Start on Today.

- Type a file path or an `https://` address in the field and press **Add link**.
- Click a link to open it. A document or image opens in its program; for any other file, its folder
  opens instead, so a link can never run a program.
- **×** removes a link.

### Recently finished

The last 10 finished tasks, each with logged and estimated time, the ratio between them (`×1.50`
means it took one and a half times your estimate), and `on time` or `late`.

---

## Review (key `3`)

One due study item at a time. Each item has two steps.

### Step 1: the bet

You see:

- the progress (`3 of 7`) and the course and topic;
- the title: your prompt, or the file and section the item points at;
- the question, when the note has an `**Answer**` line to split on.

Set **confidence**, how sure you are that you can recall the answer, with the slider or a number key.
Then press **Show answer**.

The answer is not on the page yet. The app fetches it only after you commit a confidence, so you
cannot peek.

### Step 2: the answer and the grade

The excerpt from your notes appears: Markdown is drawn with headings, lists, tables and maths, and a
PDF page is shown as a picture (or as its text, when `pdftoppm` is not installed). Under it is the
file and section, with **open on the site** when the note is on your notes site.

Grade yourself with one of four buttons. Each says when that grade brings the item back:

| Button | Key | Meaning |
|---|---|---|
| **Again** | `1` | you forgot it |
| **Hard** | `2` | you got it with effort |
| **Good** | `3` | you got it |
| **Easy** | `4` | you got it at once |

A grade cannot be changed afterwards.

**Suspend** takes the item out of your reviews and out of the topic's mastery. It asks first, and the
item comes back with **Resume** on the Study screen.

If the file has moved, the screen says `can't show this item`. Grade it from memory, or suspend it.

### The end of the queue

After the last item you get a summary such as
`reviewed 7 · recalled 5 · you said 80% on average, recalled 71%`. Hard, Good and Easy count as
recalled. A second line says how many new items wait for another day (see *New study items a day* on
[Settings](#settings-key-9)). With nothing due it says `nothing due`.

### Keys on Review

| Key | Does |
|---|---|
| `0`–`9` | before the answer: set the confidence (`7` is 70%, `0` is 100%) |
| `Enter` or `Space` | show the answer |
| `1`–`4` | after the answer: grade |
| `Esc` | back to Today |

---

## Study (key `4`)

The overview of everything you are learning. It is a long page of cards, in this order.

### Study next

The one topic to study now, for example `study next: maths / limits — mastery 40%`. When that topic
is a prerequisite of the one that would otherwise come first, it adds `(prerequisite of …)`.
**Review now** goes to Review. A topic with no items says to add a note's sections first.

### Ranking

The top five topics with exam date, mastery and score. The score is
`weight × (1 − mastery) ÷ days until the exam`, so important, weak topics with a close exam come
first.

### Topics by course

At the top, one readiness line per course with an exam ahead: `maths 62% ready, exam in 10 days`.

Then, per course:

- **A graph** of the topics and their prerequisites, when the course has any links.
- **A table** with name, exam, weight, mastery, items and due (items due for review now).

The mastery cell has more than one bar:

- the main bar is the topic's mastery, red under 60% and green from there;
- three small bars are its parts: **memory** (reviews), **understanding** (spot-the-error cards) and
  **application** (practice and tests). A faint bar means thin evidence, fewer than five answers. A
  part with no data says `no items yet`, `no checks yet` or `no practice yet`;
- `covered 9 of 15 sections` says how much of the topic's notes have items.

**Edit** on a row changes the topic's exam date and weight.

### Add a topic

| Field | What to type |
|---|---|
| **name** | the topic's name |
| **course** | the course it belongs to |
| **exam** | when it is tested: `2026-12-01` or `+20` |
| **weight** | how much it matters; 1 is normal, 2 is worth twice the marks |
| **needs** | its prerequisites. Only topics of the course you typed can be picked |

Press **Add topic**. Under the form, **Add items from a file** opens the dialog
[described below](#add-items-from-a-file).

### Confident mistakes

Shown when you have any: answers where you said 70% or more and were wrong. Each row has the date,
the topic, what you said, where it happened (review, practice, a test) and what it was. Read this
list before an exam.

### Calibration

Whether your confidence matches your results.

- The first line gives the number of answers and the **Brier** score: 0 is perfect, 0.25 is no better
  than always saying 50%.
- **The chart** plots what you said against what you recalled. Dots on the diagonal line are honest
  confidence; dots under it mean you were surer than you should have been. Bigger dots have more
  answers behind them.
- **The table** under it has the same numbers.
- A second table per source (reviews, practice, tests) appears once you have answers from more than
  one.
- The last line is the verdict: `well calibrated`, `you overrate yourself by 12 points` or
  `you underrate yourself by 12 points`.

### Queue

`7 due now · 2 new items wait for another day`.

### Spot the error

Shown when a language model is set up or cards are ready. **Start** opens the
[Spot screen](#spot-no-key), and **Make 3 more** asks the model for three more cards.

### Suggestions

A model's proposals, when background model jobs are on: a topic for a LearnHarness session, or a
prerequisite between two topics. Nothing changes until you press **Accept**; **Reject** closes one.
The line under them shows the day's model calls: `model jobs: 12 of 40 calls used today, 3 queued`.

### Suspended items

Each suspended item with a **Resume** button, which puts it back in your reviews.

### LearnHarness sessions

Shown when you use LearnHarness, a separate tutor app. Each session is listed with its kind, length
and date. A session without a topic has a menu and **Save** to give it one. **Sync now** reads new
sessions at once.

---

## Add items from a file

A dialog that turns a notes file into review items. Open it with **Add items from a file** on Study,
or **Study this** on Files.

1. Type the file's **path**, for example `~/notes/calculus.md` or `~/slides/week3.pdf`, and press
   **Show sections**.
2. The file's sections appear as checkboxes, each with its number of lines. Good sections arrive
   ticked: for Markdown, sections with at least three lines and no sub-headings; for a PDF, every
   page. **all** and **none** tick or clear them all.
3. Pick the **topic**, or `new topic…` and give it a name and course.
4. Press **Add items**.

- A section already in the chosen topic is greyed out and says `already added`. Pick another topic and
  it can be ticked again, because one section may sit in two topics.
- When you tick more than your daily limit of new items, a line says how many will come up each day.
- A text file with no headings is offered as one item, the whole file.

---

## Spot (no key)

Spot-the-error cards: one of your own notes with one line changed to say something false. Open it
from the Study screen or the Study card on Today. It needs a language model (see *Language model
command* on [Settings](#settings-key-9)) to make the cards.

1. You see the note's lines and `one line was changed to say something false`. Set
   **how sure will you be of your pick?** and press **Lock in**. The lines cannot be clicked before
   that.
2. Click the line you think is wrong.
3. The screen says `right` or `wrong: it was line 4`, and shows the original line (`was:`) next to
   the changed one (`shown:`). **Next** goes to the next card.

The model only writes the cards. Right or wrong is simply whether you picked the changed line.

| Key | Does |
|---|---|
| `n` | after the answer: next card |
| `Esc` | back to Study |

---

## Risk (key `5`)

The deadline forecast, drawn.

- **crunch risk 14%**: the chance that at least one deadline slips. Above about 20%, start earlier or
  cut something.
- **start the queue by 2026-11-18**: the earliest of the tasks' last safe start days.
- **The timeline**: one row per task. The bar runs from the likely finish to the worst case, with a
  marker at the due date and a small triangle at the start-by date. A bar that crosses the due marker
  is a task that can be late.
- **The table**: task, due, late %, start by, likely finish, worst case, and **if late** (about how
  many days late it finishes when it does miss).
- A line at the bottom counts the tasks with no due date. They are not in the forecast.

### The two sliders

They answer "what if?" without saving anything:

- **hours a day** reruns the forecast at another pace.
- **lost days** pretends you lose that many days before you start.

While a slider is moved, the crunch line also shows the real number, for example
`(14% at 4h a day starting today)`. **Reset** puts both sliders back.

If you like the new pace, **Use 5h a day** saves it as your hours a day. It asks first, because
every forecast and today's plan use that setting.

---

## Stats (key `6`)

Your history, in charts. Nothing here can be changed; it is for looking.

- **Four tiles**: the streak (days in a row with 2 hours or more), the review streak, time worked
  today, and the crunch risk.
- **Time**: a heatmap and totals for the recent days.
- **Estimates**: how far off your estimates are, overall and per kind (`×1.40`, `n=6`).
- **Deadlines**: your tasks with a due date and their risk.
- **Study**: reviews per day, and each topic with its exam and a mastery bar.
- **Code issues**: bugs fixed, open and abandoned, and time lost.

This is the same summary that `pm stats --push` sends to your notes site, drawn locally.

---

## Bugs (key `7`)

Failing commands that you ran through `pm run -- <command>`, and what fixed them. With none yet, the
screen says so and shows that command.

- **Four tiles**: fixed, open, abandoned, and time lost.
- A line under them names any **burst** in the last 7 days: several failures close together.
- **Tags**, each with a count. Click one to show only its episodes; **show all** clears the filter.
- **Episodes**: the 50 newest. An episode is one stretch of failures of one command in one folder,
  from the first failure to the run that passed.

Click an episode to open it. You see its status and folder, every run, its tags, and the **fix
diff**: what changed in the code between the last failing run and the passing one. Without git, or
for a bug not yet fixed, it says `no diff`.

In an open episode, **add a tag** takes a new tag (it offers the ones you already use), **×** removes
one, and **Close** goes back to the list.

---

## Files (key `8`)

Search over the folders `pm` watches (see *Watched folders* on [Settings](#settings-key-9)). The `/`
key jumps here with the cursor in the search box.

- With the box empty, it lists the 20 most recently indexed files.
- As you type, it shows up to 30 matches with the matched words highlighted.
- A course filter narrows either list.

Each file has three buttons:

- **Open** opens it in its program. Only documents and images have this button (PDF, png, jpg, docx,
  pptx, odt, odp, txt, md, tex, csv and a few more). Scripts and programs are never opened.
- **Show in folder** opens the folder that holds the file.
- **Study this** opens [Add items from a file](#add-items-from-a-file) with the path filled in. It
  works for PDFs and text or Markdown files.

`nothing indexed yet` means the background service has not run. Start it with `pm watch --install`
(see the setup guide) or run `pm watch --once`.

---

## Settings (key `9`)

Every setting, each with its own **Save** button. A bad value is refused with a message and the old
value stays.

| Setting | What it does |
|---|---|
| **Hours you can work a day** | focused hours, from 0.1 to 16. The plan and the forecast are built on it, so be realistic |
| **Peak hours** | when deep work goes first, like `09-12` |
| **New study items a day** | how many never-reviewed items enter the review queue each day; the rest wait |
| **Nudge hours** | reminders to start a task are only sent between these hours, like `08-22` |
| **Watched folders** | folders to index for Files, separated by `:` |
| **Ignored folders** | folders under the watched ones to skip, separated by `:` |
| **Course codes** | `name=CODE` pairs separated by `;`, used to tag files by course |
| **Notes site address** | `https://…` of your notes site, where the stats summary is sent |
| **Scoreboard address** | `https://…` of the Versus scoreboard; empty turns Versus off |
| **Model calls a day** | how many times background jobs may call the language model each day; 0 turns them off |
| **LearnHarness data folder** | leave empty for the usual place; `pm` only reads it |
| **Language model command** | a command that reads a prompt and prints a reply; needed for spot-the-error cards |
| **Notes folder** | the `docs` folder of your notes site, so review items link to their page |

At the bottom the screen shows where the database file is and how many files are indexed.

---

## Exam (key `0`)

Timed tests from your question bank.

### New test

| Field | Meaning |
|---|---|
| **course** | the course to test |
| **questions** | how many, from 1 to 100 |
| **minutes** | the time limit; leave empty for the default |
| **from** | `sample from the bank`, or one past paper |

Press **Create**. A sampled test spreads its questions over the course's topics by weight and prefers
questions you have not seen lately. With an empty bank, the form is replaced by a line saying to add
questions first.

### Tests

Every test with its number of questions, its length and its state. A marked test shows its score, with
the predicted score beside it. Click one to open it.

### Question bank

How many questions each topic has, and how far they can be trusted when they did not all come from
your own notes or papers. To add some, type the full path of a
notes file under **Import questions from a note** and press **Import**: every section with an
`**Answer**` line becomes a question. Past papers are added on the command line (`pm paper add`,
`pm paper import`).

### Questions to check

Shown when your results flag a question as `suspect`, `too easy` or `too hard`. Read it and decide.
**Retire** takes a question out of future tests. It asks first, and `pm q restore N` brings it back.

### Taking a test

1. Open the test and press **Start**. The clock starts.
2. For each question, type your answer (or tick the correct options), then set
   **how sure are you?**. Tick **don't know** to leave it blank on purpose: it scores 0 but keeps your
   confidence numbers honest.
3. **Previous** and **Next** move between questions. **Finish** ends the test; it asks first when
   questions are blank.

The clock runs in the app, not on the page, so you can close the page and come back. Past the limit
it shows `over by 4:10` and still lets you finish.

### Marking

Answers `pm` can check (numbers, choices) are marked for you. For each open answer, the screen shows
your answer beside the model answer and asks for your marks, with **Save marks**. Be strict: the
marks go into the topic's mastery.

The key, the model answers and the scores are not sent to the page before you finish.

### The result

- your score, with **predicted** beside it: the readiness `pm` expected. A score well under it means
  your reviews say more than you can do;
- a table of the score per topic;
- each question with your answer, the key and the score;
- **Retry the N missed questions**, which builds a new test from them;
- **Make variants of the N missed questions**, when a language model is set up;
- **Back to tests**.

---

## Practice (key `p`)

Fresh problems whose answers `pm` works out itself, so there is no end to them and no model is
involved in the marking.

### The first view

- A menu, `next best topic` or one topic, and **Start**.
- A list of your topics. Each shows how you did lately (`4 tries, 3 right in 30 days`) and its linked
  *generators* as chips. A generator is a problem family, for example CPU scheduling. **×** on a chip
  unlinks it; the menu and **Link** under it add another. Only a topic with a generator can be
  practised, so with none linked the screen says to link one first.
- **templates that didn't load**, when one of your own formula templates has an error.

### A problem

1. Read the problem. It states the conventions it uses, since textbooks differ.
2. Type **your answer**, set **how sure are you?** and press **Check**. Or press **Don't know**.
3. The screen says `right`, or `wrong: the answer is …`, and shows the worked steps.
4. **Next** gives another problem; **Stop** goes back to the first view.

Answers are read loosely: `6.25 ms` and `25/4` are the same number, and `P2, P1, P3` and `P2 P1 P3`
the same order. When `pm` cannot read what you typed, it says so and counts it as wrong.

Each answer counts toward the topic's **application** part of mastery.

| Key | Does |
|---|---|
| `n` | after the answer: next problem |
| `Esc` | drop the problem and go back (not while typing an answer) |

---

## Versus (key `v`)

The study scoreboard against your friends.

**When it is off**, the screen says so and links to Settings, where you set the scoreboard address.
Joining also needs a login; see the setup guide, step 11
([Linux](../SETUP-linux.md#11-join-a-scoreboard), [Mac](../SETUP-mac.md#11-join-a-scoreboard)).

**When it is on**, it shows:

- **today so far**, a table with one column per player and one row per category: minutes studied,
  reviews done, quiz answers right, test answers right and syllabus gained. A ★ marks the sole leader
  of a row, who takes that row's point. A tie gives nobody the point.
- **points**, the last row: who has the most at midnight wins the day.
- who leads today, or `today is level`.
- tiles with each player's **days won**, and the **draws**.
- **Score**: +1 for each day won and −1 for each day of 30 minutes or less, never below zero. The
  line under it counts each player's days of 30 minutes or less.
- **Streak**: who is on a run of wins, and how long.
- **Recent days**: the last 14 finished days with the winner and the points.
- when each friend **last synced**. A day counts once everyone has synced after midnight.

**Sync now** sends your numbers and fetches the others' at once. Otherwise that happens once an hour
while the background service runs.

With only you on the board, it shows your table and `Waiting for another player to sync.`

Only numbers leave your laptop: no task titles, no notes.

---

## What the app cannot do

A few things are command-line only:

| To do this | Use |
|---|---|
| Undo a done or dropped task | `pm reopen N` (`pm ls --done` lists the numbers) |
| Add one item with your own prompt, or by line range | `pm study add FILE#Heading --topic T --prompt "…"` |
| Rename a topic, or remove an item | `pm topic rename OLD NEW`, `pm study rm ID` |
| Add a question by hand, or a past paper | `pm q add …`, `pm paper add …`, `pm paper import …` |
| Back up the database | `pm backup` |
| Check your setup | `pm doctor` |
| Record a failing command | `pm run -- <command>` |

## When something looks wrong

| You see | Do |
|---|---|
| `pm ui is not answering` | The app has stopped. Run `pm ui` again, or restart the service |
| The page stays on `loading…` | Reload the page. If it stays, run `pm doctor` |
| **Open** or **Show in folder** does nothing | The background service cannot reach your desktop. Run `pm ui` from a terminal, or see [Running it as a service](usage-guide.md#running-it-as-a-service) |
| Maths shows as raw text (`$x^2$`) | Maths drawing is fetched from the internet the first time. Go online once |
| A PDF page shows as text, not a picture | Install `pdftoppm` (`pm doctor` lists what is missing) |
| Files says `nothing indexed yet` | Run `pm watch --once`, or set up the background service |
| A value is refused | The message says which format it wants; durations need a unit (`90m`, not `90`) |

Is it safe to leave running? The app listens only on your own machine (`127.0.0.1`), so nobody on
your network can reach it, and it refuses requests from other web sites.
