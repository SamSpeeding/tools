#!/bin/zsh
set -eu
cd -- "${0:A:h}/.."
export PATH="$HOME/.cargo/bin:$PATH"
npm ci
npm run tauri -- build --bundles app
mkdir -p release
ditto src-tauri/target/release/bundle/macos/HongguoDesktop.app release/HongguoDesktop.app
printf '\n应用已生成：%s/release/HongguoDesktop.app\n' "$PWD"
