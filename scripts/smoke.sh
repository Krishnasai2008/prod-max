#!/bin/sh
# Smoke test: runs pm against a throwaway database, never the real one.
set -eux
d=$(mktemp -d)
trap 'rm -rf "$d"' EXIT
export PM_DB="$d/pm.db" PM_NOW=2026-11-09T10:00:00
uv run pm add "OS lab" --est 4h --due +3 --course os --kind lab
uv run pm add "<b>x</b> & co" --est 30m --shallow
uv run pm ls
uv run pm today
uv run pm risk
uv run pm edit 1 --title "OS lab 3" --no-due
uv run pm drop 2
uv run pm ls
uv run pm link 1 https://example.com/lab
uv run pm link 1
uv run pm start 1 --no-open
uv run pm stop "half way" --energy 4
uv run pm energy
uv run pm set llm_cmd cat
uv run pm llm echo me
uv run pm spot
uv run pm topic add paging --course os --exam +5
printf '# TLB\nThe TLB caches page table entries.\na\nb\n' > "$d/tlb.md"
uv run pm study add "$d/tlb.md#TLB" --topic paging
uv run pm topic file paging "$d/tlb.md"
uv run pm study why paging
uv run pm study misses
uv run pm study ready
uv run pm q add "What is a TLB?" --topic paging --answer "a cache of page-table entries"
uv run pm q add "Faults with 3 frames?" --topic paging --number 7
uv run pm q add "Which policy has Belady's anomaly?" --topic paging --choice "FIFO;LRU;OPT" --correct 1
uv run pm q ls
uv run pm mock new --course os -n 3
uv run pm mock ls
uv run pm practice link paging --topic paging
uv run pm practice gens
printf 'q\n' | uv run pm practice
uv run pm learn paging
uv run pm lh ls
uv run pm template ls
uv run pm q review
uv run pm suggest
uv run pm agent ls
uv run pm
uv run pm set
uv run pm ls --done
uv run pm doctor
uv run pm backup "$(dirname "$PM_DB")/copy.db"
