const { spawnSync } = require('child_process');
const fs   = require('fs');
const path = require('path');

// Resolve the Python interpreter to use.
// Priority 1: the active venv's Python (VIRTUAL_ENV env var set by activate script).
// Priority 2: the .venv folder at the repo root (conventional location).
// Priority 3: whatever 'python' resolves to on PATH.
function resolvePython() {
    const isWin = process.platform === 'win32';
    const bin   = isWin ? ['Scripts', 'python.exe'] : ['bin', 'python'];

    const candidates = [
        process.env.VIRTUAL_ENV && path.join(process.env.VIRTUAL_ENV, ...bin),
        path.resolve(__dirname, '..', '..', '.venv', ...bin),
    ].filter(Boolean);

    for (const p of candidates) {
        if (fs.existsSync(p)) return p;
    }

    // Fall back to PATH python so the command at least produces a clear error.
    return isWin ? 'python.exe' : 'python';
}

const python = resolvePython();
const result = spawnSync(python, ['manage.py', 'runserver'], { stdio: 'inherit', cwd: __dirname });
process.exit(result.status ?? 1);
