"use strict";

const fs = require("fs");
const path = require("path");

const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".tif",
  ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
  ".exe", ".dll", ".so", ".dylib", ".bin", ".wasm", ".pyc", ".class",
  ".iso", ".dmg", ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
  ".ttf", ".otf", ".woff", ".woff2", ".eot",
  ".sqlite", ".sqlite3", ".db",
]);

function isBinaryFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (BINARY_EXTENSIONS.has(ext)) {
    return true;
  }
  try {
    const fd = fs.openSync(filePath, "r");
    try {
      const buffer = Buffer.alloc(4096);
      const bytesRead = fs.readSync(fd, buffer, 0, 4096, 0);
      for (let i = 0; i < bytesRead; i++) {
        if (buffer[i] === 0) {
          return true;
        }
      }
    } finally {
      fs.closeSync(fd);
    }
  } catch {}
  return false;
}

module.exports = {
  BINARY_EXTENSIONS,
  isBinaryFile,
};
