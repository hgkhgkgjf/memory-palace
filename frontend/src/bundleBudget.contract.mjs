import childProcess from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

const MAX_ENTRY_CHUNK_BYTES = 500 * 1024
const MAX_ASYNC_CHUNK_BYTES = 90 * 1024
const MAX_TOTAL_JS_GZIP_BYTES = 240 * 1024
const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const NPM_EXECUTABLE = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const BUILD_ENV = { ...process.env }

delete BUILD_ENV.NODE_OPTIONS
delete BUILD_ENV.VITEST
delete BUILD_ENV.VITEST_MODE
delete BUILD_ENV.VITEST_POOL_ID
delete BUILD_ENV.VITEST_WORKER_ID
BUILD_ENV.NODE_ENV = 'production'
BUILD_ENV.BABEL_ENV = 'production'

const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'memory-palace-frontend-build-'))

try {
  childProcess.execFileSync(
    NPM_EXECUTABLE,
    ['run', 'build', '--', '--outDir', outDir],
    {
      cwd: FRONTEND_ROOT,
      stdio: 'pipe',
      env: BUILD_ENV,
    }
  )

  const assetsDir = path.join(outDir, 'assets')
  const jsFiles = fs.readdirSync(assetsDir).filter((fileName) => fileName.endsWith('.js'))
  const entryFile = jsFiles.find((fileName) => fileName.startsWith('index-')) ?? jsFiles[0] ?? null

  if (!entryFile) {
    throw new Error('Bundle budget check failed: no JS assets were generated.')
  }

  const entryChunkBytes = fs.statSync(path.join(assetsDir, entryFile)).size
  const asyncChunkBytes = jsFiles
    .filter((fileName) => fileName !== entryFile)
    .map((fileName) => ({
      fileName,
      bytes: fs.statSync(path.join(assetsDir, fileName)).size,
    }))
  const largestAsyncChunk = asyncChunkBytes.reduce(
    (largest, current) => current.bytes > largest.bytes ? current : largest,
    { fileName: null, bytes: 0 }
  )
  const totalJsGzipBytes = jsFiles.reduce(
    (sum, fileName) =>
      sum + zlib.gzipSync(fs.readFileSync(path.join(assetsDir, fileName))).byteLength,
    0
  )

  if (entryChunkBytes > MAX_ENTRY_CHUNK_BYTES) {
    throw new Error(
      `Bundle budget exceeded for entry chunk: ${entryChunkBytes} > ${MAX_ENTRY_CHUNK_BYTES}`
    )
  }

  if (largestAsyncChunk.bytes > MAX_ASYNC_CHUNK_BYTES) {
    throw new Error(
      `Bundle budget exceeded for async chunk ${largestAsyncChunk.fileName}: ${largestAsyncChunk.bytes} > ${MAX_ASYNC_CHUNK_BYTES}`
    )
  }

  if (totalJsGzipBytes > MAX_TOTAL_JS_GZIP_BYTES) {
    throw new Error(
      `Bundle budget exceeded for total gzipped JS: ${totalJsGzipBytes} > ${MAX_TOTAL_JS_GZIP_BYTES}`
    )
  }

  console.log(
    `Bundle budget OK: entry=${entryChunkBytes}B largestAsync=${largestAsyncChunk.bytes}B totalGzip=${totalJsGzipBytes}B files=${jsFiles.length}`
  )
} finally {
  fs.rmSync(outDir, { recursive: true, force: true })
}
