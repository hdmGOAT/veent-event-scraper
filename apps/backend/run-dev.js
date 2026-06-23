const { spawnSync } = require('child_process');
const path = require('path');

const python = process.platform === 'win32'
  ? path.join('venv', 'Scripts', 'python.exe')
  : path.join('venv', 'bin', 'python');

const result = spawnSync(python, ['manage.py', 'runserver'], { stdio: 'inherit' });
process.exit(result.status ?? 1);
