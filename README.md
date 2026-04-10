# Wrestling Promoter Sim (Web)

Mobile-friendly web wrapper using Pyodide.

## Run locally

Because browsers block `fetch()` from `file://`, use a local web server:

```bash
cd wrestling-promoter-web
python3 -m http.server 8000
```

Open: http://localhost:8000

## Deploy on GitHub Pages

1. Create a new GitHub repo (ex: `wrestling-promoter-web`).
2. Copy the contents of this folder into the repo root.
3. Push to GitHub.
4. GitHub → Settings → Pages → Deploy from branch → `main` / root.

Then you can share the Pages URL.

## Notes

- This is an MVP scaffold. The current `py/game_engine.py` is a starter state machine.
- Next step: port your full sim logic from `pro_wrestling_promoter_sim_fixed.py` into `game_engine.py` in a UI-friendly way (no `input()` / `print()`).
