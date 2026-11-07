#!/usr/bin/env node
/**
 * 从远程服务器下载文件（SFTP）。
 * 账号/密码/主机从项目根目录 .env 读取。
 *
 * 用法: node scripts/remote_get.cjs <远端路径> <本地路径>
 * 注意：Git Bash 下远端路径前加 MSYS_NO_PATHCONV=1，避免 /home/... 被转成 Windows 路径。
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

const [remotePath, localPath] = process.argv.slice(2);
if (!host || !username || !password) {
  console.error('缺少 REMOTE_HOST / REMOTE_USER / REMOTE_PASSWORD，请在项目根目录 .env 中配置');
  process.exit(1);
}
if (!remotePath || !localPath) {
  console.error('用法: node scripts/remote_get.cjs <远端路径> <本地路径>');
  process.exit(1);
}

const conn = new Client();
conn
  .on('ready', () => {
    conn.sftp((err, sftp) => {
      if (err) {
        console.error('SFTP 不可用:', err.message);
        conn.end();
        process.exit(1);
      }
      sftp.fastGet(remotePath, localPath, (e) => {
        if (e) {
          console.error('下载失败:', e.message);
          conn.end();
          process.exit(1);
        }
        console.log(`下载完成 ${(fs.statSync(localPath).size / 1024).toFixed(0)}KB -> ${localPath}`);
        conn.end();
      });
    });
  })
  .on('error', (err) => {
    console.error(`连接失败: ${err.message}`);
    process.exit(1);
  })
  .connect({ host, port, username, password, readyTimeout: 20000 });
