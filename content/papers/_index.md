---
title: "Papers"
cascade:
  # Default: no standalone HTML page per paper, only a listing row.
  # To give one paper a detail page (ticket 16), override this cascade in
  # that paper's own front matter and give the file a body, e.g.:
  #   build: {"render": "always"}
  # (one line, matching every other field in content/papers/*.md — the
  # papers-detection automation's front-matter parser only understands
  # flow-style values, not nested YAML block syntax.
  # `list: always` is inherited from here and needs no override.)
  - target:
      kind: page
    build:
      render: never
      list: always
---
