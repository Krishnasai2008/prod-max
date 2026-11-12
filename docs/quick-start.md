# pm quick start

Your first day with `pm`, in about 15 minutes. This page has only what you need to get going. The
[usage guide](usage-guide.md) explains every feature in depth, and the [README](../README.md) lists
every command and setting.

**About the examples:** names such as `maths`, `differentiation`, `Maths problem set 3` and
`~/notes/calculus.md` are made up. Use your own courses, topics, tasks and files in their place.

## 1. Install and check

Follow step 1 of [SETUP-linux.md](../SETUP-linux.md#1-install) or [SETUP-mac.md](../SETUP-mac.md#1-install),
then:

```
pm doctor          # shows what is set up and what is missing
```

## 2. Tell pm about your day

```
pm set hours_per_day 4      # focused hours you really work, not hours awake
pm set peak 09-12           # when your brain works best
```

## 3. Add a task

```
$ pm add "Maths problem set 3" --est 2h --due +3 --course maths --kind pset --first "read question 1"
added #1
```

- `--est` is your honest guess and always carries a unit: `90m`, `2h`, `1h30m`. Don't pad it.
- `--due` takes a date (`2026-11-20`), days from today (`+3`), `today`, `tomorrow` or a weekday (`fri`).
- `--kind` is the type of work (`pset`, `lab`, `exam`…). Keep to a few kinds: `pm` learns how wrong your
  estimates are for each one.
- `--first` is a tiny first step, shown when you start.

`pm ls` lists your open tasks with their numbers.

## 4. Work on it

```
$ pm start 1
started #1 Maths problem set 3
first step: read question 1

$ pm stop "q1-2 done, next: q3"
stopped #1 after 50m

$ pm done 1
done #1: 1h50m logged, estimated 2h
```

- `start` and `stop` can repeat over several days; the time adds up. The note you give `stop` is shown
  the next time you start.
- `done` is what teaches `pm`: it compares the logged time with your estimate.
- Forgot the timer? `pm stop --as 45m` records 45 minutes, and `pm log 1 1h` adds time afterwards.
- Gave up on a task? `pm drop 1`. Marked the wrong one? `pm reopen 1`.

## 5. Ask pm what to do

```
$ pm today
Deep work (peak 09-12):
  #1 Maths problem set 3  ~3h  first step: read question 1

$ pm risk
#2  Physics lab report  due 2026-11-20  late 0%  start by 2026-11-18
crunch risk 0%  start the queue by 2026-11-18
```

- `pm today` (or just `pm`) fills today's hours, earliest deadline first. The `~3h` is your 2h estimate
  corrected for how long things really take you (`pm` assumes 1.5 times longer until it has learned
  your own number; see it with `pm bias`).
- `pm risk` gives the chance each task is late and the last safe day to start. **crunch risk** is the
  chance that any deadline slips; above about 20%, start earlier or cut something.

## 6. Study from your notes

```
$ pm topic add differentiation --course maths --exam +10
topic #1 differentiation

$ pm study add ~/notes/calculus.md --all --topic differentiation
added 2 items to differentiation

$ pm review
```

- A **topic** is a chapter with an exam date. An **item** is a flashcard that points at a section of
  your notes file; `--all` makes one per section.
- `pm review` shows each due item: say how confident you are (0–100), read the answer, then grade
  yourself `1` forgot, `2` hard, `3` good, `4` easy. `pm` picks the next date from the grade.
- `pm study next` says which topic to study when you have free time.

## 7. Open the app

```
pm ui
```

The same tasks, timer, plan and reviews in your browser, at `http://127.0.0.1:8321`. Press `?` there
for the keys. The app and the commands share one database, so mix them freely. The
[app guide](app-guide.md) covers every screen.

## Every day

| When | Do |
|---|---|
| Morning | `pm today`, then `pm start N` |
| Pausing | `pm stop "where I left off"` |
| Finished a task | `pm done N` |
| Once a day | `pm review` and a look at `pm risk` |
| New work arrives | `pm add …` |

## Try it without touching your real data

```
export PM_DB=/tmp/pm-test.db     # a throwaway database for this terminal
```

## Where next

| You want | Read |
|---|---|
| Background indexing, nudges, the app as a service | [SETUP-linux.md](../SETUP-linux.md) or [SETUP-mac.md](../SETUP-mac.md), steps 3–5 |
| Mock tests, practice problems, the question bank | [Testing yourself](usage-guide.md#testing-yourself), [Practice](usage-guide.md#practice) |
| Mastery and overconfidence | [Studying with spaced repetition](usage-guide.md#studying-with-spaced-repetition) |
| The study contest with friends | [Versus](usage-guide.md#versus-studying-against-friends) |
| Backups and undo | [Backup and undo](usage-guide.md#backup-and-undo) |
