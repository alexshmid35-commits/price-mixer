const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const rootDir = path.resolve(__dirname, '..', '..');
const stateDir = path.join(rootDir, 'test-results');
const runtimeRoot = path.join(stateDir, 'e2e-runtime');
const statePath = path.join(stateDir, 'e2e-processes.json');
const serverLogPath = path.join(stateDir, 'e2e-server.log');
const workerLogPath = path.join(stateDir, 'e2e-worker.log');
const baseURL = 'http://127.0.0.1:5011';
const adminUsername = 'e2e-admin';
const adminPassword = 'e2e-test-password-long';

function resolvePythonPath() {
  const configured = String(process.env.PRICE_MIXER_TEST_PYTHON || '').trim();
  if (configured && fs.existsSync(configured)) return configured;
  const candidates = process.platform === 'win32'
    ? [
        path.join(rootDir, '.venv-win', 'Scripts', 'python.exe'),
        path.join(rootDir, '.venv', 'Scripts', 'python.exe'),
      ]
    : [
        path.join(rootDir, '.venv', 'bin', 'python3'),
        path.join(rootDir, '.venv', 'bin', 'python'),
      ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || 'python';
}

function requestStatus(route, authenticated = false) {
  return new Promise((resolve) => {
    const headers = authenticated
      ? {
          Authorization: `Basic ${Buffer.from(
            `${adminUsername}:${adminPassword}`,
          ).toString('base64')}`,
        }
      : {};
    const req = http.get(`${baseURL}${route}`, { headers }, (res) => {
      res.resume();
      resolve(res.statusCode || 0);
    });
    req.on('error', () => resolve(0));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(0);
    });
  });
}

async function waitForReady(timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const healthStatus = await requestStatus('/api/health');
    const workerStatus = await requestStatus('/api/worker-status', true);
    if (healthStatus === 200 && workerStatus === 200) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `Isolated E2E app/worker did not start within ${timeoutMs}ms. ` +
    `See ${serverLogPath} and ${workerLogPath}`,
  );
}

function spawnLogged(pythonPath, args, env, logPath) {
  const out = fs.openSync(logPath, 'w');
  const child = spawn(pythonPath, args, {
    cwd: rootDir,
    detached: process.platform !== 'win32',
    env,
    stdio: ['ignore', out, out],
  });
  child.unref();
  fs.closeSync(out);
  return child;
}

async function startServer() {
  fs.mkdirSync(stateDir, { recursive: true });
  fs.rmSync(runtimeRoot, { recursive: true, force: true });
  const runtimeDirs = {
    state: path.join(runtimeRoot, 'state'),
    data: path.join(runtimeRoot, 'data'),
    cache: path.join(runtimeRoot, 'cache'),
    uploads: path.join(runtimeRoot, 'uploads'),
    logs: path.join(runtimeRoot, 'logs'),
  };
  Object.values(runtimeDirs).forEach((directory) => {
    fs.mkdirSync(directory, { recursive: true });
  });

  const pythonPath = resolvePythonPath();
  const childEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    ADMIN_USERNAME: adminUsername,
    ADMIN_PASSWORD: adminPassword,
    FLASK_SECRET_KEY: 'e2e-flask-secret-key-long-and-isolated',
    PRICE_MIXER_ENV: 'development',
    PRICE_MIXER_PORT: '5011',
    PRICE_MIXER_STATE_DIR: runtimeDirs.state,
    PRICE_MIXER_DATA_DIR: runtimeDirs.data,
    PRICE_MIXER_CACHE_DIR: runtimeDirs.cache,
    PRICE_MIXER_UPLOAD_DIR: runtimeDirs.uploads,
    PRICE_MIXER_LOG_DIR: runtimeDirs.logs,
    PRICE_MIXER_JOB_MODE: 'external',
    PRICE_MIXER_JOB_DB: path.join(runtimeDirs.data, 'jobs.db'),
    PRICE_MIXER_SESSION_STORE_MODE: 'canonical',
  };

  const worker = spawnLogged(
    pythonPath,
    [
      '-m',
      'price_mixer.workers.durable_worker',
      '--poll-interval',
      '0.1',
    ],
    childEnv,
    workerLogPath,
  );
  const server = spawnLogged(
    pythonPath,
    ['app.py'],
    childEnv,
    serverLogPath,
  );
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        started: true,
        pids: [server.pid, worker.pid],
        runtimeRoot,
      },
      null,
      2,
    ),
  );
  await waitForReady();
}

function stopPid(pid) {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], {
      stdio: 'ignore',
    });
    return;
  }
  try {
    process.kill(-Number(pid), 'SIGTERM');
  } catch (_error) {
    try {
      process.kill(Number(pid), 'SIGTERM');
    } catch (_innerError) {
      // Process already exited.
    }
  }
}

function stopServer() {
  if (!fs.existsSync(statePath)) return;
  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  if (!state.started) return;
  for (const pid of state.pids || []) {
    if (pid) stopPid(pid);
  }
}

module.exports = {
  adminPassword,
  adminUsername,
  baseURL,
  startServer,
  stopServer,
};
