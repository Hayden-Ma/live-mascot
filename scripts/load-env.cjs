#!/usr/bin/env node
/**
 * 轻量 .env 加载器（不依赖 dotenv 包）。
 *
 * 用法: require('./load-env.cjs');  // 会把项目根目录 .env 读进 process.env
 * 已存在的环境变量优先，便于临时覆盖；不会打印任何值。
 */
const fs = require('fs');
const path = require('path');

const ENV_FILE = path.join(__dirname, '..', '.env');
const ESCAPES = { n: '\n', r: '\r', t: '\t', '"': '"', '\\': '\\' };

function unquote(value) {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      const inner = value.slice(1, -1);
      // 单引号内保持字面量；双引号按 dotenv 常规处理转义
      return first === "'" ? inner : inner.replace(/\\([nrt"\\])/g, (_, code) => ESCAPES[code]);
    }
  }
  return value;
}

if (fs.existsSync(ENV_FILE)) {
  const lines = fs.readFileSync(ENV_FILE, 'utf8').split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const body = line.startsWith('export ') ? line.slice(7).trim() : line;
    const eq = body.indexOf('=');
    if (eq <= 0) continue;
    const key = body.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    if (process.env[key] === undefined) {
      process.env[key] = unquote(body.slice(eq + 1).trim());
    }
  }
}

module.exports = { ENV_FILE };
