#!/usr/bin/env node
/**
 * 远程执行命令的临时通道。
 * 账号、密码、主机从项目根目录 .env 读取（已 gitignore）。
 * 用法: node scripts/remote.cjs "nvidia-smi"
 */
require('./load-env.cjs');
const fs = require('fs');
const os = require('os');
const path = require('path');

function findSsh2() {
  const roots = [
    path.join(process.env.LOCALAPPDATA || '', 'npm-cache', '_npx'),
    path.join(os.homedir(), '.npm', '_npx'),
  ];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    for (const dir of fs.readdirSync(root)) {
      const p = path.join(root, dir, 'node_modules', 'ssh2');
      if (fs.existsSync(p)) return p;
    }
  }
  throw new Error('未找到 ssh2 模块（请先运行过一次 ssh-mcp-server）');
}

const { Client } = require(findSsh2());

const host = process.env.REMOTE_HOST;
const port = Number(process.env.REMOTE_PORT || 22);
const username = process.env.REMOTE_USER;
const password = process.env.REMOTE_PASSWORD;

const command = process.argv.slice(2).join(' ') || 'echo ok';
if (!host || !username || !password) {
  console.error('缺少 REMOTE_HOST / REMOTE_USER / REMOTE_PASSWORD，请在项目根目录 .env 中配置');
  process.exit(1);
}

const conn = new Client();
conn
  .on('ready', () => {
    conn.exec(command, (err, stream) => {
      if (err) {
        console.error(err.message);
        conn.end();
        process.exit(1);
      }
      stream
        .on('close', (code) => {
          conn.end();
          process.exit(code ?? 0);
        })
        .on('data', (d) => process.stdout.write(d))
        .stderr.on('data', (d) => process.stderr.write(d));
    });
  })
  .on('error', (err) => {
    console.error(`连接失败 ${host}:${port} - ${err.message}`);
    process.exit(1);
  })
  .connect({ host, port, username, password, readyTimeout: 20000 });
