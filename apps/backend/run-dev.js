const { spawnSync } = require('child_process');
const path = require('path');

const venvRoot = path.resolve(__dirname, '..', '..', '.venv');
const python = process.platform === 'win32'
  ? path.join(venvRoot, 'Scripts', 'python.exe')
  : path.join(venvRoot, 'bin', 'python');

const result = spawnSync(python, ['manage.py', 'runserver'], { stdio: 'inherit', cwd: __dirname });
process.exit(result.status ?? 1);
