

---

## 1. How To Run

```bash
# From the ig_multi_matrix_engine folder:
python matrix_runner.py --status        # check scorecard anytime
python matrix_runner.py --all           # run all 6 accounts (day mode)
python matrix_runner.py --account 1     # run single account only
```

**Important**: `matrix_state.json` still contains OLD counters (e.g. bat shows C:22 L:35 S:33 from the old aggressive run) and dead-account entries for accounts that died BEFORE these fixes. For a **clean measurement**, reset the state file before the 2-3 day test:

```bash
# Delete old state so counters start fresh:
del matrix_state.json
```

> If you delete state, the engine re-creates it. This gives you a clean baseline to measure which pattern survives longest.

---
