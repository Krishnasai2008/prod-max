# notes-site

The study-notes website that goes with `pm`: your Markdown notes as a private site behind a login, with
progress ticks, a to-do list, a study clock, a stats page and a Planner box fed by `pm`. It is free to host on
Cloudflare Pages. How it works inside: [ARCHITECTURE.md](ARCHITECTURE.md).

## Put your copy online (once, about 15 minutes)

You need a GitHub account with your copy of this repo (fork it) and a free Cloudflare account.

1. **Create the site.** Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git, and pick your
   repo. Build settings:
   - Build command: `bash build.sh`
   - Build output directory: `site`
   - Root directory: `notes-site`
2. **Add your login.** In the Pages project → Settings → Variables and Secrets, add `SITE_USER` and
   `SITE_PASSWORD` (choose the type "Secret" for the password). For a second person, add `SITE_USER_2` and
   `SITE_PASSWORD_2`. Each login keeps its own progress, stats and planner.
3. **Add storage.** Workers & Pages → KV → Create a namespace (any name). Then in the Pages project →
   Settings → Bindings → Add → KV namespace, with the variable name `BACKUP` and that namespace.
4. **Set the address.** Put your site's address (`https://<project>.pages.dev/`) as `site_url` in
   `mkdocs.yml`, commit and push. Every push to `main` rebuilds the site. Open the address and log in.

## Write notes

Each top-level folder in `docs/` is one subject, and every `.md` file in it is a note. The first `# ` heading
is the note's title. A `.nav.yml` with `title: …` names the folder. Delete `docs/example/` once you have your
own. Leave `docs/javascripts/`, `docs/stylesheets/` and `docs/stats.md` alone: they are the site itself.
`docs/index.md` and each folder's `index.md` are generated at build time.

Commit and push to publish. Never commit a password: the login lives only in Cloudflare's settings.

## Connect pm

```sh
pm set notes_url https://<project>.pages.dev
pm set notes_dir ~/prod-max/notes-site/docs     # wherever your clone is
```

Then give `pm` the login, in `~/.netrc` (pm ignores the file unless only you can read it):

```
machine <project>.pages.dev login USER password PASS
```

```sh
chmod 600 ~/.netrc
pm stats --push      # prints "pushed N KB to <project>.pages.dev"
```

The daemon (`pm watch --install`) pushes every hour and picks up what you add on the site's home page every
5 minutes. The stats page is at `/stats/`.

## Tests

```sh
node --test tests/
python3 -m unittest discover -s tests
```
