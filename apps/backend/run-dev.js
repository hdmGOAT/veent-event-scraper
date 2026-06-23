const { spawnSync } = require('child_process');
const path = require('path');

const python = process.platform === 'win32'
  ? path.join(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')
  : path.join(__dirname, '..', '..', '.venv', 'bin', 'python');

const result = spawnSync(python, ['manage.py', 'runserver'], { stdio: 'inherit' });
process.exit(result.status ?? 1);
