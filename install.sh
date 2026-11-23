#!/bin/bash
# dashdl 一键安装脚本：把脚本放到 ~/bin 并检查依赖
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/bin"
TARGET="${BIN_DIR}/dashdl"

# 1) 安装脚本
mkdir -p "${BIN_DIR}"
cp "${HERE}/dashdl" "${TARGET}"
cp "${HERE}/dashdl_widevine.py" "${BIN_DIR}/dashdl_widevine.py"
chmod +x "${TARGET}"

# 2) 确保 ~/bin 在 PATH（zsh/bash 常见配置）
case ":$PATH:" in
  *":${BIN_DIR}:"*) : ;;
  *) echo "提示: 请把 ${BIN_DIR} 加入 PATH，例如在 ~/.zshrc 末尾添加:" >&2
     echo '  export PATH="$HOME/bin:$PATH"' >&2 ;;
esac

echo "已安装: ${TARGET}"
echo ""

# 3) 检查依赖
fail=0
for bin in N_m3u8DL-RE ffmpeg ffprobe mp4decrypt; do
  if command -v "${bin}" >/dev/null 2>&1; then
    echo "  ✓ ${bin}"
  else
    echo "  ✗ ${bin} 未找到"
    fail=1
  fi
done

echo ""
if [ "${fail}" -ne 0 ]; then
  echo "缺少依赖，安装方式:"
  echo "  brew install ffmpeg bento4          # ffmpeg/ffprobe/mp4decrypt"
  echo "  # N_m3u8DL-RE 从 GitHub 下载官方 macOS 二进制:"
  echo "  #   https://github.com/nilaoda/N_m3u8DL-RE/releases"
  exit 1
fi

echo "全部依赖就绪，运行 'dashdl --help' 开始使用。"
