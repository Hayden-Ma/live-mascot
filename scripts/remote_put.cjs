#!/usr/bin/env node
/**
 * 通过 SFTP 上传/下载文件到远程服务器。
 * 账号/密码/主机从项目根目录 .env 读取。
 *
 * 用法: node scripts/remote_put.cjs <本地路径> <远端路径>
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

const [localPath, remotePath] = process.argv.slice(2);
if (!host || !username || !password) {
  console.error('缺少 REMOTE_HOST / REMOTE_USER / REMOTE_PASSWORD，请在项目根目录 .env 中配置');
  process.exit(1);
}
if (!localPath || !remotePath) {
  console.error('用法: node scripts/remote_put.cjs <本地路径> <远端路径>');
  process.exit(1);
}

const conn = new Client();
conn
  .on('ready', () => {
    // 走 exec + cat，避免部分服务器 sftp 子系统不可用
    const started = Date.now();
    const quoted = `'${remotePath.replace(/'/g, `'\\''`)}'`;
    conn.exec(`cat > ${quoted}`, (err, stream) => {
      if (err) {
        console.error('执行失败:', err.message);
        conn.end();
        process.exit(1);
      }
      stream
        .on('close', (code) => {
          if (code !== 0) {
            console.error(`写入失败, exit ${code}`);
            conn.end();
            process.exit(1);
          }
          const size = fs.statSync(localPath).size;
          console.log(
            `上传完成 ${(size / 1024).toFixed(0)}KB -> ${remotePath} (${Date.now() - started}ms)`
          );
          conn.end();
        })
        .on('error', (e) => {
          console.error('传输失败:', e.message);
          conn.end();
          process.exit(1);
        });
      const rs = fs.createReadStream(localPath);
      rs.pipe(stream);
      rs.on('end', () => {
        // 有些 sshd 不会及时回 close，写入完成后强制结束
        setTimeout(() => {
          const size = fs.statSync(localPath).size;
          console.log(
            `上传完成 ${(size / 1024).toFixed(0)}KB -> ${remotePath} (${Date.now() - started}ms)`
          );
          process.exit(0);
        }, 500);
      });
      stream.stderr.on('data', (d) => process.stderr.write(d));
    });
  })
  .on('error', (err) => {
    console.error(`连接失败: ${err.message}`);
    process.exit(1);
  })
  .connect({ host, port, username, password, readyTimeout: 20000 });
