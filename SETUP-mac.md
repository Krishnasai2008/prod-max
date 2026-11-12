# Setting up pm on a Mac

This guide takes you from nothing to a fully working `pm` on macOS, one step at a time. It has the same
steps as the [Linux guide](SETUP-linux.md); only the installing and the background services differ. Steps
1–6 are the core (about 15 minutes). Steps 7–12 are optional; each one adds a feature, and `pm` works
without it. The [README](README.md) has every command and setting in full, and the
[usage guide](docs/usage-guide.md) explains why things work the way they do.

**Joining a friend's scoreboard?** Do steps 1, 2, 4 and 11. The rest can wait.

`pm` has not been run on a real Mac yet. After installing, run its tests once (step 1) and tell whoever
sent you here what failed.

At any point, `pm doctor` shows what is set up and what is missing. It is the quickest way to find your
place in this guide.

| Step | What you get | Needed? |
|---|---|---|
| [1. Install](#1-install) | the `pm` command | yes |
| [2. Your day](#2-your-day) | plans that fit your hours | yes |
| [3. Files and courses](#3-files-and-courses) | search over your downloads, tagged by course | recommended |
| [4. The daemon](#4-the-daemon) | indexing, nudges and pushes in the background | recommended |
| [5. The app](#5-the-app) | the planner in your browser | recommended |
| [6. First tasks and topics](#6-first-tasks-and-topics) | something to plan and review | yes |
| [7. The notes site](#7-the-notes-site) | stats and a planner box on your phone | optional |
| [8. A model (`llm_cmd`)](#8-a-model-llm_cmd) | spot-the-error cards, question variants, drafts | optional |
| [9. LearnHarness](#9-learnharness) | a tutor that knows your topics | optional |
| [10. Backups](#10-backups) | a copy you can restore | recommended |
| [11. Join a scoreboard](#11-join-a-scoreboard) | a daily study contest with friends | optional |
| [12. Host a scoreboard](#12-host-a-scoreboard) | the site your friends' `pm` syncs with | optional |

**Already using pm and just updated?** Run `pm doctor`, restart the services that are running (see
*Updating later* below), and go through the steps for anything `doctor` says is not set.

---

## 1. Install

You need macOS, Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git. With
[Homebrew](https://brew.sh):

```sh
brew install python@3.12 uv git
git clone <your copy of this repo> ~/prod-max
cd ~/prod-max
uv tool install --editable .     # puts `pm` on your PATH
pm doctor
```

The first command creates the database at `~/.local/share/prod-max/pm.db`, the same place as on Linux.
Everything `pm` knows lives in that one file.

Then run the tests once, from the repo folder:

```sh
uv run python -m unittest discover -s tests
```

It should end with `OK` (some tests say `skipped` when an optional program is missing; that is fine).

`doctor`'s bottom half lists optional programs. Install the ones it marks missing, for the features you want:

| Program | Homebrew | Used for |
|---|---|---|
| `pdftotext`, `pdfinfo`, `pdftoppm` | `brew install poppler` | PDF text, page counts, PDF pages in the app |
| `tesseract` | `brew install tesseract` | text from scans and images |
| `node` | `brew install node` | only the LearnHarness plugin (step 9) and pm's own JS tests |

Desktop nudges (`osascript`) and opening files (`open`) come with macOS, so they need nothing extra.

**Updating later:** `git pull` in the repo is enough, because the install is editable. Then restart the
services that are running, so they run the new code:

```sh
launchctl unload ~/Library/LaunchAgents/dev.prod-max.pm-watch.plist && launchctl load -w ~/Library/LaunchAgents/dev.prod-max.pm-watch.plist
launchctl unload ~/Library/LaunchAgents/dev.prod-max.pm-ui.plist && launchctl load -w ~/Library/LaunchAgents/dev.prod-max.pm-ui.plist
```

The first command after an update upgrades the database by itself and keeps a copy of the old one next
to it (`pm.db.v12.bak`).

## 2. Your day

Three settings shape every plan. `pm set` alone lists them all; `pm set KEY VALUE` changes one.

```sh
pm set hours_per_day 4      # focused hours you really get per day (0.1–16)
pm set peak 09-12           # your sharpest hours; deep work is planned here
pm set nudge_hours 08-22    # desktop nudges only come in these hours
```

Be honest with `hours_per_day`: the deadline risk is simulated at that rate, so an optimistic number
gives optimistic risks. Once you have rated your energy on 10 sessions (`pm stop --energy 4`),
`pm energy` suggests a better `peak`.

## 3. Files and courses

The daemon indexes the folders in `watch` for `pm find` and the app's Files screen.

```sh
pm set watch ~/Downloads:~/uni              # folders to index, separated by :
pm set watch_ignore ~/Downloads/Data        # folders under them to skip
pm set course_codes "os=CS F372;dbms=CS F212"
```

`course_codes` tags a file with a course when its code appears in the file's name or the start of its text;
use the codes printed on your handouts. Without it, a file's course is its top folder under the watched one.

## 4. The daemon

The daemon indexes new files every 10 seconds, sends nudges when a task should start, syncs the
scoreboard (once step 11 is done) and (once step 7 is done) pushes stats every hour and picks up what you
add on your phone every 5 minutes. On a Mac it runs as a launchd agent:

```sh
pm watch --install
```

It prints the file it wrote and the line that starts it:

```
wrote /Users/you/Library/LaunchAgents/dev.prod-max.pm-watch.plist
start it: launchctl load -w /Users/you/Library/LaunchAgents/dev.prod-max.pm-watch.plist
```

Run that `launchctl load -w …` line. The agent starts at login from then on, and launchd starts it again
if it stops.

The agent keeps the `PATH` your terminal had when you ran `pm watch --install`, so Homebrew's programs
are found. If you install Homebrew or change your `PATH` later, run `pm watch --install` again, then
unload and load the agent.

Check it with `pm doctor` (the `daemon` line). The agent's output is not kept anywhere. To see what the
daemon does, unload the agent and run it in a terminal instead (`pm watch`; Ctrl-C stops it), then load
the agent again. To try a single round by hand: `pm watch --once`.

## 5. The app

```sh
pm ui                       # opens http://127.0.0.1:8321 in your browser; Ctrl-C stops it
```

To have it always running instead:

```sh
pm ui --install
launchctl load -w ~/Library/LaunchAgents/dev.prod-max.pm-ui.plist
```

Then bookmark `http://127.0.0.1:8321`. It only listens on your own machine. Press `?` in the app for its
keys.

## 6. First tasks and topics

Add the things with deadlines:

```sh
pm add "OS lab 3" --est 3h --due fri --course os --kind lab --first "read the handout"
pm today                    # today's plan
pm risk                     # chance each deadline slips, and when to start
```

`pm` assumes things take 1.5× your estimate until you finish a few tasks with `pm start` / `pm stop` /
`pm done`; after that it uses what it has learned about you.

For study, make a topic per exam chapter and add your notes to it:

```sh
pm topic add paging --course os --exam 2026-12-04
pm study add ~/notes/os/paging.md --all --topic paging     # one review item per section
pm review                   # due items: bet your confidence, see the answer, grade it
```

The app's Study screen does the same with **Add items from a file**. `pm study next` tells you what to study
first. Practice problems, past papers and mock tests are in the README under *Practice* and *Tests and past
papers*.

## 7. The notes site

The site in `notes-site/` shows your stats and a Planner box on your phone, and sends tasks and logged
time back. To put your copy online (free, on Cloudflare Pages), follow
[notes-site/README.md](notes-site/README.md). Then connect `pm`:

```sh
pm set notes_url https://<project>.pages.dev
pm set notes_dir ~/prod-max/notes-site/docs      # so review items link to their note
```

`pm` logs in with `~/.netrc`, which must be readable only by you:

```
machine <project>.pages.dev login <USER> password <PASSWORD>
```

```sh
chmod 600 ~/.netrc
pm stats --push             # prints "pushed N KB to <project>.pages.dev"
```

The daemon keeps it up to date from now on. On a laptop with `pm ui` running, the Planner box's
**Open the pm app** link opens the app.

## 8. A model (`llm_cmd`)

`llm_cmd` is the command `pm` runs when it wants a language model's help. `pm` writes the prompt to the
command's standard input and reads the reply from its standard output, so any program that works like
this will do:

```sh
echo "say hi" | <your command>      # must print the reply and exit 0
```

`pm` runs it directly (not through a shell), stops it after 2 minutes, and uses it only for:

- **spot-the-error cards** (`pm spot --make 3`): the model changes one line of a note you've reviewed, and
  you find it. The model never grades; the line number decides.
- **question variants** (`pm q vary ID`): new questions like one you missed, each kept only when a second
  solve agrees.
- **drafts** you check before use: past-paper question lists (`pm paper draft`), formula templates
  (`pm template draft`), and topic and prerequisite suggestions (`pm suggest`).

Nothing else needs it. Whatever the command talks to sees parts of your notes and questions.

**Pick one:**

| You have | `llm_cmd` | Notes |
|---|---|---|
| Claude Code | `~/.local/bin/claude -p --tools "" --no-session-persistence --model haiku` | `--tools ""` means it can only answer, never read or run anything. Uses your Claude plan. |
| Ollama | `ollama run qwen2.5:7b` | Stays on your machine. Needs Ollama running and the model pulled (`ollama pull qwen2.5:7b`). Small models make weaker cards. |
| [`llm`](https://llm.datasette.io) | `llm -m <model>` | Any provider `llm` has a plugin for. |

Use the full path to the program (`~/.local/bin/claude`, not `claude`; `which claude` prints it): the
daemon only knows the `PATH` it was installed with (step 4). `pm doctor` says `(not found on PATH)` when it
can't find it.

```sh
pm set llm_cmd '~/.local/bin/claude -p --tools "" --no-session-persistence --model haiku'
pm llm "Reply with just the word: ok"     # should print: ok
pm spot --make 3                           # needs a few reviewed text items first
```

**Background jobs.** Commands you type use the model straight away. To also let the daemon make spot cards
and variants once an hour by itself, give it a daily budget of calls (0, the default, keeps it off):

```sh
pm set agent_daily_calls 20
pm agent ls                 # recent jobs, then "budget: 3 of 20 calls used today"
```

Start low and check what it made (`pm suggest`, `pm q review`) before raising it. To turn the model off
again: `pm set llm_cmd ""`.

## 9. LearnHarness

[LearnHarness](https://learnharness.ai) is a separate tutor app. `pm` reads its sessions and flashcards
back as evidence for your topics, and a plugin lets the tutor ask `pm` about your topics, notes and past
papers. Install LearnHarness first, then:

```sh
pm doctor                   # the "learnharness" line should show its data folder
pm set lh_dir ~/path/to/LearnHarness/data   # only if doctor didn't find it
pm lh install               # needs node; then enable "pm-bridge" in LearnHarness
                            # under Settings → Community plugins, and restart it
```

`pm` looks in `~/.config/LearnHarness/data` by default; if LearnHarness keeps its data elsewhere on your
Mac, point `lh_dir` at the folder that holds `chats/`.

The plugin needs `pm ui` running (step 5). Start a session with `pm learn paging | pbcopy` and paste the
message into LearnHarness (`--copy` uses Linux clipboard tools, so on a Mac it only prints a message);
the daemon syncs the session back. `pm` never writes to LearnHarness's folder.

## 10. Backups

```sh
pm backup                   # a dated copy in ~/.local/share/prod-max/backups/
```

It is safe while the daemon and app run (a plain `cp` of `pm.db` is not). To restore, unload both agents
and copy a backup over `pm.db`. Time Machine covers the backups folder if it backs up your home folder.

## 11. Join a scoreboard

Versus is a daily study contest with friends. Each player's `pm` sends one site, the hub, a card of
numbers per day (minutes studied, reviews done, quiz and test answers right, syllabus gained) and gets
everyone's cards back. No task titles or file names go into it. The [README](README.md#versus) says how a
day is won.

You need the hub's address and a login for it from whoever runs it (step 12). You don't need a notes
site of your own.

```sh
pm set versus_url https://<hub>.pages.dev
```

Add the hub's login to `~/.netrc`, on a line of its own (next to your notes site's line, if you have one):

```
machine <hub>.pages.dev login <USER> password <PASSWORD>
```

```sh
chmod 600 ~/.netrc
pm versus --sync            # sends your numbers and prints the board
```

The login's user name is your name on the board. From now on the daemon (step 4) syncs once an hour.
`pm versus` prints the last board without going online, and the app's Versus screen (`v`) has
**Sync now**. If you have your own notes site (step 7), its home page shows a Versus box under the
Planner box. To stop playing: `pm set versus_url ""`.

## 12. Host a scoreboard

Your notes site from step 7 can be the hub. It needs the current `notes-site/` (the `/api/versus`
route); if you put your site online before that, push the update first.

Play yourself with the same address as `notes_url`; your `~/.netrc` line already covers it:

```sh
pm set versus_url https://<project>.pages.dev
pm versus --sync
```

For each friend, in the Pages project → Settings → Variables and Secrets, add `VERSUS_USER` and
`VERSUS_PASSWORD` (type "Secret" for the password). More friends: `VERSUS_USER_2` + `VERSUS_PASSWORD_2`,
`VERSUS_USER_3` + `VERSUS_PASSWORD_3`, and so on. Then redeploy (push a commit, or retry the latest
deployment) so the site sees the new variables.

Send each friend the site's address and their login, and point them to step 11 (or
[SETUP-linux.md](SETUP-linux.md#11-join-a-scoreboard) on Linux). A scoreboard login opens `/api/versus`
and nothing else: not your notes, your stats or your backup. A friend's user name must differ from your
`SITE_USER` names. Every `SITE_USER` login can play too, each with its own card. It is an honour system:
the board shows whatever each `pm` sends.

## Check everything

```sh
pm doctor
```

A finished setup looks like this (yours shows your own paths):

```
database    /Users/you/.local/share/prod-max/pm.db  (1.2 MB)
daemon      running
watching    /Users/you/Downloads
watching    /Users/you/uni
model       /Users/you/.local/bin/claude
model jobs  20 calls a day
notes site  https://<project>.pages.dev
learnharness  /Users/you/.config/LearnHarness/data
ok          pdftotext: text from PDFs, for search and excerpts
…
```
