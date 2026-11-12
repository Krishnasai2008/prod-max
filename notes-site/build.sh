#!/usr/bin/env bash
# Cloudflare Pages build. Settings: build command "bash build.sh", output directory "site".
set -euo pipefail
# Pinned: an unpinned install takes whatever was released that morning. To upgrade, change the numbers and check the preview build.
pip install "zensical==0.1.1" "pagefind[extended]==1.6.0"
python fix_links.py   # safety net: repair links to moved notes
python tidy_markdown.py  # blank lines before lists, "Added" date labels
python make_indexes.py
zensical build --clean
rm -f site/search.json   # the theme's own search index (switched off in mkdocs.yml), 28 MB
python -m pagefind   # search index in small pieces (settings: pagefind.yml)
# shortcut: Cloudflare Pages rejects files over 25 MiB, so those are left out of the site (links to them 404). Move big PDFs to R2 if you need them online.
find site -type f -size +25M -print -delete
