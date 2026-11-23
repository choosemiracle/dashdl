# dashdl

一条命令下载带密钥的 DASH (MPD) / HLS (m3u8) 视频，自动解密、选流、封装。

`dashdl` 是 [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) 的 Python 命令行封装，把它的选流参数、解密引擎、输出命名、多线程等细节收敛成一套简洁的 CLI，让你只关心「地址 + 密钥 + 想要什么画质」。

支持两类加密：

- **CENC**（Widevine / PlayReady）—— `KID:KEY` 密钥对
- **HLS AES-128** —— `key` / `iv` 十六进制值

---

## 依赖

| 组件 | 必需 | 安装方式（macOS） |
|---|---|---|
| [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases) | ✅ | 下载官方 macOS 二进制，放入 `~/bin` 并加入 PATH |
| ffmpeg / ffprobe | ✅ | `brew install ffmpeg` |
| mp4decrypt（[Bento4](https://www.bento4.com/)） | 推荐 | `brew install bento4` |

> 解密引擎可选 `FFMPEG` / `MP4DECRYPT` / `SHAKA_PACKAGER`，默认 `MP4DECRYPT`。

---

## 安装

```bash
# 方式一：一键安装脚本
bash install.sh

# 方式二：手动
cp dashdl ~/bin/dashdl && chmod +x ~/bin/dashdl
```

确保 `~/bin` 在 `PATH` 中（zsh 默认已包含），然后任意目录直接 `dashdl` 即可。

---

## 快速开始

```bash
# 1) 先看有哪些清晰度/音轨/字幕（只解析，不下载）
dashdl "https://…/dash.mpd" --list

# 2) 下载最高清晰度（默认行为：最佳视频 + 最佳音频，不含字幕）
dashdl "https://…/dash.mpd" --key KID:KEY
```

`KID:KEY` 形如：

```
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

> **要最高清晰度，什么都不加，直接 `--key` 就行**（默认即 `-sv best -sa best`）。

---

## 常用场景速查

```bash
# 指定分辨率（按高度，可多个候选）
dashdl "URL" --key K:KEY --res 1080
dashdl "URL" --key K:KEY --res 720,1080

# 选 ≤ 某高度的最佳档（自动发现可用高度）
dashdl "URL" --key K:KEY --max-res 720

# 指定输出目录 + 文件名 + 封装格式
dashdl "URL" --key K:KEY -o ~/Movies/片名.mp4
dashdl "URL" --key K:KEY --dir ~/Movies --name 片名 --format mkv

# 指定音频语言 / 字幕
dashdl "URL" --key K:KEY --audio-lang chi,eng --sub-lang chi

# 带 Cookie / Referer / UA 的签名地址
dashdl "URL" --key K:KEY -H "Cookie: …" -H "Referer: …"

# 只下视频 / 只下音频 / 只下字幕
dashdl "URL" --key K:KEY --video-only --res 720
dashdl "URL" --key K:KEY --audio-only
dashdl "URL" --key K:KEY --sub-only --sub-lang chi

# HLS AES-128 加密
dashdl "…/index.m3u8" --hls-key <hex-key> --hls-iv <hex-iv>

# 多个密钥 / 密钥文件
dashdl "URL" --key KID1:KEY1 --key KID2:KEY2
dashdl "URL" --key-file keys.txt          # 每行一条 KID:KEY

# 预览将执行的命令（不下载）
dashdl "URL" --key K:KEY --dry-run
```

---

## 多线程下载

| 目的 | yt-dlp | dashdl |
|---|---|---|
| 并行下载分片 | `-N 16` | `--threads 16`（默认 8） |
| 音视频流同时下 | 默认行为 | `--concurrent`（默认串行） |
| 分片重试 | `-R 10` | `--retries 10`（默认 10） |
| 限速 | `-r 15M` | `--max-speed 15M` |

```bash
# 分片级并行
dashdl "URL" --key K:KEY --threads 16

# 流级并行（视频/音频/字幕同时下）
dashdl "URL" --key K:KEY --concurrent

# 叠加
dashdl "URL" --key K:KEY --threads 16 --concurrent
```

> `--threads` 建议 8–16，再高收益递减，反而容易被服务器限速/断流。网络波动导致的丢分片要靠 `--retries`，不是靠线程数。

---

## 断点续传

N_m3u8DL-RE 天然支持：**重新运行同一条命令**即可。已下载的分片会自动跳过，只补缺失部分。遇到「分片完整性检查」主动中止（防止产出残缺视频）时，直接重跑即可续传。

---

## 完整参数

```
usage: dashdl [-h] [--key KEY] [--key-file KEY_FILE] [--hls-key HLS_KEY]
              [--hls-iv HLS_IV] [--hls-method HLS_METHOD] [--res RES]
              [--max-res MAX_RES] [--video-codec VIDEO_CODEC] [--video-all]
              [--audio-lang AUDIO_LANG] [--audio-codec AUDIO_CODEC]
              [--audio-all] [--sub-lang SUB_LANG] [--subs] [--sub-all]
              [--video-only] [--audio-only] [--sub-only]
              [--drop-video DROP_VIDEO] [--drop-audio DROP_AUDIO]
              [--drop-sub DROP_SUB] [-o OUTPUT] [-d DIR] [--name NAME]
              [--tmp-dir TMP_DIR] [--format {mp4,mkv,ts}] [--no-mux]
              [--keep-files] [-H HEADER] [--cookie COOKIE]
              [--user-agent USER_AGENT] [--referer REFERER]
              [--append-url-params] [--proxy PROXY] [--no-proxy]
              [--threads THREADS] [--concurrent] [--retries RETRIES]
              [--timeout TIMEOUT] [--max-speed MAX_SPEED]
              [--decrypt-engine {FFMPEG,MP4DECRYPT,SHAKA_PACKAGER}] [--list]
              [--dry-run] [--binary BINARY]
              url
```

### 分组说明

- **密钥**：`--key`（CENC KID:KEY，可重复）、`--key-file`、`--hls-key` / `--hls-iv` / `--hls-method`（HLS AES-128）
- **选流**：`--res` / `--max-res` / `--video-codec` / `--audio-lang` / `--audio-codec` / `--sub-lang` / `--video-only` / `--audio-only` / `--sub-only` / `--*-all` / `--drop-*`
- **输出**：`-o/--output`、`--dir`、`--name`、`--format`、`--tmp-dir`、`--no-mux`、`--keep-files`
- **网络**：`-H/--header`、`--cookie`、`--user-agent`、`--referer`、`--append-url-params`、`--proxy`、`--no-proxy`
- **性能/解密**：`--threads`、`--concurrent`、`--retries`、`--timeout`、`--max-speed`、`--decrypt-engine`
- **其他**：`--list`（只列轨道）、`--dry-run`（只打印命令）、`--binary`

---

## 常见问题

### 为什么 `--output` 指定了文件名，生成的还是 `video.mp4`？

几乎都是**命令被换行拆成了两段**。zsh 里换行处没加续行符 `\`，会把第二行当成独立命令执行，于是第一行跑了但没带 `-o`（输出默认名 `video.mp4`），第二行报 `zsh: command not found: --threads`。

正确写法（二选一）：

```bash
# ① 全部一行
dashdl "URL" --key K:KEY --output 片名.mp4 --threads 16 --concurrent

# ② 换行末尾加 \，且 \ 后不能有空格
dashdl "URL" \
  --key K:KEY \
  --output 片名.mp4 \
  --threads 16 \
  --concurrent
```

### `Muxing… / Rename to video.mp4 / Done` 是错误吗？

不是。N_m3u8DL-RE 用 WARN 级别打印普通进度日志，这些都是正常输出。

### 磁盘写满导致合并失败怎么办？

分片会保留。腾出空间后**重跑同一条命令**即可续传，直接进入合并/解密/封装阶段。

---

## 许可

MIT License — 详见 [LICENSE](LICENSE)。

## 免责声明

本工具仅供学习与个人已获授权的媒体备份使用。请遵守当地法律法规及内容提供方的服务条款，勿用于侵权用途。
