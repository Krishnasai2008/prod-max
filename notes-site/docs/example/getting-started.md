# Getting started

_Added: 2026-11-13_

This is an example note. Delete the `example` folder once you have your own notes.

Each top-level folder in `docs/` is one subject. Write notes in Markdown; maths works too: $e^{i\pi} + 1 = 0$.

## Headings become links

`pm` can turn a heading into a review item:

```sh
pm topic add example
pm study add "docs/example/getting-started.md#Headings become links" --topic example
```

It then comes up in `pm review`.
