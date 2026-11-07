#!/usr/bin/env node
// 常驻运行本地 NeteaseCloudMusicApi（默认 3000 端口，可用 PORT 覆盖）
// 进程异常退出后会自动重启；已在运行则直接退出，避免端口冲突。
const { spawn } = require('child_process')
const net = require('net')
const path = require('path')

const pkgDir = path.join(
  __dirname,
  '..',
  'tools',
  'netease-api',
  'node_modules',
  'NeteaseCloudMusicApi',
)
const port = Number(process.env.PORT || 3000)

let child = null
let stopping = false

function isPortOpen() {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port }, () => {
      socket.destroy()
      resolve(true)
    })
    socket.setTimeout(1000, () => {
      socket.destroy()
      resolve(false)
    })
    socket.on('error', () => resolve(false))
  })
}

async function start() {
  if (await isPortOpen()) {
    console.log(`[netease] ${port} 端口已在监听，视为已在运行`)
    process.exit(0)
  }

  child = spawn(process.execPath, [path.join(pkgDir, 'app.js')], {
    cwd: pkgDir,
    stdio: 'inherit',
    env: { ...process.env, PORT: String(port) },
  })

  child.on('exit', async (code) => {
    child = null
    if (stopping) {
      process.exit(code ?? 0)
    }
    console.log(`[netease] 进程退出（code=${code}），5 秒后重启`)
    await new Promise((resolve) => setTimeout(resolve, 5000))
    start()
  })
}

function shutdown() {
  stopping = true
  if (child) child.kill('SIGINT')
  else process.exit(0)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

start()
