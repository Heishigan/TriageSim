# For AI assistants working on TriageSim

Read `docs/DECISIONS.md` and `README.md` first, and follow them.
- `data/` and `outputs/` are OFF LIMITS: never open, list, search, copy or modify anything
  in them, and never point a tool at the user's real data folder. Tests use invented tables only.
- Never read, print or commit patient-level data.
- Ask Albert before deleting anything.
- Small steps; explain each change; add or update tests; run `pytest`.
- Record every design decision in `docs/DECISIONS.md` in the same step.
- Commits are Albert's alone: never add Co-Authored-By, AI session links or any AI attribution
  to commit messages or pull requests.
