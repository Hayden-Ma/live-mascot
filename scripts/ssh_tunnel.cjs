#!/usr/bin/env node
/**
 * 把远端 TTS 服务(45100)通过 SSH 隧道映射到本地 127.0.0.1:45100。
 * SSH 主机/端口/账号/密码从项目根目录 .env 读取。
 *
 * 用法: node scripts/ssh_tunnel.cjs [本地端口] [远端端口]
 *
 * 断开后会自动重连。
 */
require('./load-env.cjs');
const fs = require('fs');
const net = require('net');
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

if (!host || !username || !password) {
  console.error('缺少 REMOTE_HOST / REMOTE_USER / REMOTE_PASSWORD，请在项目根目录 .env 中配置');
  process.exit(1);
}

const localPort = Number(process.argv[2] || 45100);
const remotePort = Number(process.argv[3] || 45100);

function connect() {
  const conn = new Client();
  conn
    .on('ready', () => console.log(`[tunnel] ssh ready, ${host}:${port}`))
    .on('error', (err) => {
      console.error(`[tunnel] ssh error: ${err.message}, 5s 后重连`);
      setTimeout(connect, 5000);
    })
    .on('close', () => {
      console.error('[tunnel] ssh closed, 5s 后重连');
      setTimeout(connect, 5000);
    })
    .connect({ host, port, username, password, keepaliveInterval: 15000, readyTimeout: 20000 });

  const server = net.createServer((sock) => {
    conn.forwardOut('127.0.0.1', sock.remotePort, '127.0.0.1', remotePort, (err, stream) => {
      if (err) {
        console.error('[tunnel] forwardOut failed:', err.message);
        sock.destroy();
        return;
      }
      sock.pipe(stream).pipe(sock);
      sock.on('error', () => stream.destroy());
      stream.on('error', () => sock.destroy());
    });
  });

  server.listen(localPort, '127.0.0.1', () => {
    console.log(`[tunnel] 127.0.0.1:${localPort} -> ${host}:${remotePort}`);
  });
}

connect();
