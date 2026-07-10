# LOG — session log & spend ledger

Append-only, newest entry first. This file is the authoritative spend-to-date (rule 10); KICKOFF's STATUS block copies it forward. Entry format:

```
## YYYY-MM-DD · W_D_ · <one-line title>
- Measured: <numbers observed this session — eval results, cache hit rates, token counts; "none" if none>
- Changed: <what was built or modified, and the measured failure it targets (rule 1)>
- Cost: $X.XX this session · $Y.YY total of $500
- Reward-hack flags: <count + one-liners, or "none">
- Next: <carryover and the first task for next session>
```

---

## 2026-07-10 · W0D0 · Project initialized
- Measured: none
- Changed: repo scaffolded with CLAUDE.md (mentor rules), PLAN.md (schedule + budget + references), KICKOFF.md (session template), LOG.md (this file)
- Cost: $0.00 this session · $0.00 total of $500
- Reward-hack flags: none
- Next: Day 1 — read the three primary sources; set up Python env, git, logging skeleton
