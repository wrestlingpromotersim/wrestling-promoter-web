const els = {
  status: document.getElementById('status'),
  screen: document.getElementById('screen'),
  choices: document.getElementById('choices'),
  btnNew: document.getElementById('btnNew'),
  btnSave: document.getElementById('btnSave'),
  btnLoad: document.getElementById('btnLoad'),
  btnReset: document.getElementById('btnReset'),
};

const STORAGE_KEY = 'wps_web_saves_v1';

function loadAllSaves() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
  catch { return {}; }
}
function saveAllSaves(obj) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
}

let pyodide = null;
let engine = null;
let state = null;

function render() {
  if (!engine || !state) return;
  const status = engine.status_line(state);
  els.status.textContent = status;
  els.screen.textContent = state.screen || '';

  els.choices.innerHTML = '';
  const choices = engine.get_choices(state);
  choices.forEach((c, idx) => {
    const btn = document.createElement('button');
    btn.className = 'choice';
    btn.type = 'button';
    btn.innerHTML = `<span class="num">${idx+1}</span><span class="label">${c.label}</span>`;
    btn.addEventListener('click', () => {
      state = engine.choose(state, c.id);
      render();
    });
    els.choices.appendChild(btn);
  });

  // enable save/load buttons once initialized
  els.btnSave.disabled = false;
  els.btnLoad.disabled = false;
  els.btnReset.disabled = false;
}

async function init() {
  els.status.textContent = 'Loading Python (Pyodide)…';
  pyodide = await loadPyodide({ indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.2/full/' });

  // load our python engine
  const code = await (await fetch('./py/game_engine.py')).text();
  await pyodide.runPythonAsync(code);
  engine = pyodide.globals.get('___main__') || pyodide.globals;

  // get module symbols from __main__
  const new_game = pyodide.globals.get('new_game');
  state = new_game();

  // bind a lightweight JS facade for calls
  engine = {
    status_line: (st) => pyodide.globals.get('status_line')(st),
    get_choices: (st) => {
      const arr = pyodide.globals.get('get_choices')(st);
      // convert python list[Choice] to JS array
      return arr.toJs({ dict_converter: Object.fromEntries });
    },
    choose: (st, id) => pyodide.globals.get('choose')(st, id),
  };

  // buttons
  els.btnNew.addEventListener('click', () => {
    state = pyodide.globals.get('new_game')();
    render();
  });

  els.btnSave.addEventListener('click', () => {
    const name = prompt('Save name on this device:', 'slot1');
    if (!name) return;
    const saves = loadAllSaves();
    saves[name] = state.toString(); // fallback
    // better: serialize via pyodide to JSON
    try {
      const json = pyodide.runPython(`import json\njson.dumps(${state})`);
      saves[name] = json;
    } catch {
      // if serialize fails, keep fallback
    }
    saveAllSaves(saves);
    alert(`Saved as ${name}`);
  });

  els.btnLoad.addEventListener('click', () => {
    const saves = loadAllSaves();
    const names = Object.keys(saves);
    if (!names.length) return alert('No saves on this device');
    const name = prompt('Type save name to load:\n' + names.join('\n'), names[0]);
    if (!name || !saves[name]) return;
    try {
      const py = pyodide.runPython(`import json\njson.loads(${JSON.stringify(saves[name])})`);
      // Not wired yet — we need a proper from_dict in the engine.
      alert('Loaded save data, but restore is not wired in MVP yet. (Next step)');
    } catch {
      alert('Failed to load save');
    }
  });

  els.btnReset.addEventListener('click', () => {
    if (!confirm('Clear all saves on this device?')) return;
    localStorage.removeItem(STORAGE_KEY);
    alert('Cleared');
  });

  render();
}

init().catch((e) => {
  console.error(e);
  els.status.textContent = 'Failed to load.';
  els.screen.textContent = String(e);
});
