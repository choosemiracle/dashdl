#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashdl 的 Widevine key 提取 + Firefox 自动化子模块。

职责：
1. 自动定位/抽取 CDM 设备文件 (device.wvd)
2. 用本机 pywidevine 从 license 服务器派生 CONTENT keys
3. 驱动 Firefox (geckodriver) 打开页面，注入捕获钩子，
   抓取 PSSH + license 请求(URL/headers) + MPD 地址

对外入口：
- find_device_wvd()          -> 设备文件路径
- derive_keys(...)           -> [(kid_hex, key_hex), ...]
- pick_license(cap)          -> license dict(url, headers) 或 None
- firefox_capture(url, ...)  -> dict(pssh, license, posts, mpds, page_url)
"""

import base64
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    from pywidevine.device import Device
    from pywidevine.cdm import Cdm
    from pywidevine.pssh import PSSH
    _HAS_PYWV = True
except Exception:  # pragma: no cover
    _HAS_PYWV = False

FIREFOX_APP = "/Applications/Firefox.app/Contents/MacOS/firefox"
ADDON_ID = "{1382d9a7-5b85-4180-ab3d-5adf3e1d49f5}"

# 重放 license 请求时剔除的、由客户端自动生成的 header
_DROP_HEADERS = {
    "host", "content-length", "connection", "accept-encoding",
}

# 判定 license 请求的 URL 特征（用于在多个 POST 里挑出 license 请求）
_LICENSE_URL_RE = re.compile(
    r"license|widevine|drm|acquire|cenc|getkey|cdm|\.key\b", re.I
)


# ───────────────────────── 设备文件定位 ─────────────────────────

def firefox_profiles():
    base = os.path.expanduser("~/Library/Application Support/Firefox/Profiles")
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, d) for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))]


def extract_device_from_profile(profile_dir, out_path):
    """从已安装的 widevine-l3-decrypter 扩展 xpi 里抽出 device.wvd。"""
    ext_dir = os.path.join(profile_dir, "extensions")
    if not os.path.isdir(ext_dir):
        return None
    for fn in os.listdir(ext_dir):
        if fn == ADDON_ID + ".xpi":
            try:
                with zipfile.ZipFile(os.path.join(ext_dir, fn)) as z:
                    if "device.wvd" in z.namelist():
                        with open(out_path, "wb") as f:
                            f.write(z.read("device.wvd"))
                        return out_path
            except Exception:
                continue
    return None


def find_device_wvd(explicit=None):
    """按优先级返回 device.wvd 路径：参数 > ~/.config/dashdl > 从扩展自动抽取。"""
    if explicit and os.path.isfile(explicit):
        return explicit
    cfg = os.path.expanduser("~/.config/dashdl/device.wvd")
    if os.path.isfile(cfg):
        return cfg
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    for prof in firefox_profiles():
        if extract_device_from_profile(prof, cfg):
            return cfg
    return None


# ───────────────────────── 原生 key 派生 ─────────────────────────

def _norm_pssh(pssh):
    """接受 base64(str) / hex(str) / bytes，返回 PSSH 对象。"""
    if isinstance(pssh, bytes):
        return PSSH(pssh)
    s = pssh.strip()
    if re.fullmatch(r"[0-9a-fA-F]+", s) and len(s) % 2 == 0 and len(s) > 40:
        return PSSH(bytes.fromhex(s))
    return PSSH(base64.b64decode(s))


def derive_keys(device_path, pssh, lic_url, lic_headers=None, timeout=30):
    """用本地 pywidevine 请求 license 并返回 CONTENT keys，[(kid_hex, key_hex), ...]。"""
    if not _HAS_PYWV:
        raise RuntimeError("未安装 pywidevine（pip install pywidevine）")

    device = Device.load(device_path)
    cdm = Cdm.from_device(device)
    session_id = cdm.open()
    try:
        challenge = cdm.get_license_challenge(session_id, _norm_pssh(pssh))

        headers = {k: v for k, v in (lic_headers or {}).items()
                   if k.lower() not in _DROP_HEADERS}
        headers.setdefault("Content-Type", "application/octet-stream")

        if requests is not None:
            r = requests.post(lic_url, data=challenge, headers=headers, timeout=timeout)
            licence = r.content
        else:
            import urllib.request
            req = urllib.request.Request(lic_url, data=challenge,
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                licence = resp.read()

        cdm.parse_license(session_id, licence)
        return [(key.kid.hex, key.key.hex)
                for key in cdm.get_keys(session_id) if key.type == "CONTENT"]
    finally:
        cdm.close(session_id)


# ───────────────────────── Firefox 捕获 ─────────────────────────

# 注入到页面里的捕获脚本（fetch/XHR 钩子 + generateRequest 钩子 + pssh 事件）
CAPTURE_JS = r"""
(function(){
  if (window.__dashdl) return;
  window.__dashdl = {pssh:null, license:null, posts:[], mpds:[], pageURL:location.href};
  var pushMpd = function(u){ if (/\.mpd($|[?#])/.test(u) && window.__dashdl.mpds.indexOf(u)<0) window.__dashdl.mpds.push(u); };
  var isLic = function(u){ return /license|widevine|drm|acquire|cenc|getkey|cdm|\.key\b/i.test(u); };
  var grabPssh = function(buf){
    try {
      var bytes = new Uint8Array(buf), hex='';
      for (var i=0;i<bytes.length;i++) hex += bytes[i].toString(16).padStart(2,'0');
      var m = hex.match(/000000..70737368.*/);
      if (m) {
        var h = m[0], bin='';
        for (var j=0;j<h.length;j+=2) bin += String.fromCharCode(parseInt(h.substr(j,2),16));
        window.__dashdl.pssh = btoa(bin);
      }
    } catch(e){}
  };
  // fetch 钩子
  var _f = window.fetch;
  window.fetch = function(){
    var u = (typeof arguments[0]==='string') ? arguments[0] : ((arguments[0]&&arguments[0].url)||'');
    var o = arguments[1]||{};
    pushMpd(u);
    if (o.method && String(o.method).toUpperCase()==='POST') {
      var hdrs = {};
      if (o.headers) { try { new Headers(o.headers).forEach(function(v,k){ hdrs[k]=v; }); } catch(e){} }
      window.__dashdl.posts.push({url:u, headers:hdrs});
      if (!window.__dashdl.license && isLic(u)) window.__dashdl.license = {url:u, headers:hdrs};
    }
    return _f.apply(this, arguments);
  };
  // XHR 钩子
  var _o = XMLHttpRequest.prototype.open, _s = XMLHttpRequest.prototype.send,
      _h = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function(m,u){ this.__u=u; this.__m=m; this.__hdrs={}; return _o.apply(this,arguments); };
  XMLHttpRequest.prototype.setRequestHeader = function(k,v){ this.__hdrs=this.__hdrs||{}; this.__hdrs[k]=v; return _h.apply(this,arguments); };
  XMLHttpRequest.prototype.send = function(b){
    var u=this.__u||''; pushMpd(u);
    if ((this.__m||'').toUpperCase()==='POST') {
      var hdrs=this.__hdrs||{};
      window.__dashdl.posts.push({url:u, headers:hdrs});
      if (!window.__dashdl.license && isLic(u)) window.__dashdl.license = {url:u, headers:hdrs};
    }
    return _s.apply(this, arguments);
  };
  // generateRequest 钩子
  try {
    var _gr = MediaKeySession.prototype.generateRequest;
    MediaKeySession.prototype.generateRequest = function(t,d){ if(!window.__dashdl.pssh) grabPssh(d); return _gr.apply(this, arguments); };
  } catch(e){}
  // 扩展 (widevine-l3-decrypter) 也会在 document 上派发 pssh 事件
  document.addEventListener('pssh', function(e){ if(!window.__dashdl.pssh && e.detail) window.__dashdl.pssh = e.detail; });
})();
"""

READ_JS = "return JSON.stringify(window.__dashdl || {});"


def pick_license(cap):
    """从捕获结果里挑出最可能的 license 请求 dict。"""
    lic = cap.get("license")
    if lic and lic.get("url"):
        return lic
    posts = cap.get("posts") or []
    for p in posts:
        if _LICENSE_URL_RE.search(p.get("url", "")):
            return p
    return posts[-1] if posts else None


_PROFILE_IGNORE = {
    "lock", "parent.lock", ".parentlock", "cache2", "startupCache",
    "saved-telemetry-pings", "crashes", "minidumps", "shader-cache",
}


def _copy_profile(src):
    """复制 Firefox profile 到临时目录（排除锁文件和大缓存），返回副本路径。"""
    dst = tempfile.mkdtemp(prefix="dashdl-profile-")
    def _ignore(d, names):
        return [n for n in names
                if n in _PROFILE_IGNORE or n.endswith((".lock",))]
    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
    # 关闭会话恢复/首次运行弹窗，避免慢启动
    with open(os.path.join(dst, "user.js"), "w") as f:
        f.write('user_pref("browser.sessionstore.resume_from_crash", false);\n'
                'user_pref("browser.startup.page", 0);\n'
                'user_pref("browser.sessionstore.max_tabs_undo", 0);\n'
                'user_pref("app.normandy.first_run", false);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("datareporting.policy.firstRunURL", "");\n')
    return dst


def firefox_capture(url, profile_dir=None, wait=45, poll=1.0, binary=FIREFOX_APP,
                    headless=False):
    """驱动 Firefox 打开页面并捕获 (pssh, license, posts, mpds)。

    返回 dict。若超时未捕获到 pssh/license/mpds，返回已捕获的部分（可能不完整）。
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
    except ImportError:
        raise RuntimeError("未安装 selenium（pip install selenium）")

    if profile_dir is None:
        profs = firefox_profiles()
        profile_dir = next((p for p in profs if "default-release" in p),
                           profs[0] if profs else None)
    if not profile_dir or not os.path.isdir(profile_dir):
        raise RuntimeError("未找到 Firefox profile（可用 --profile 指定）")

    # 复制一份 profile（原 profile 可能正被主 Firefox 占用/锁库）
    work_profile = _copy_profile(profile_dir)

    opts = Options()
    opts.binary_location = binary
    # SPA 页面可能永不触发 load 事件，用 eager 在 DOMContentLoaded 后就返回，
    # 既避免挂起，又能更早注入捕获钩子
    opts.page_load_strategy = "eager"
    if headless:
        opts.add_argument("--headless")
    opts.add_argument("-profile")
    opts.add_argument(work_profile)

    # 直接指定 geckodriver 路径，绕开 Selenium Manager 的联网版本检查
    # （在访问 github 受限的网络下，联网检查会挂起数分钟）
    gecko = shutil.which("geckodriver")
    service = Service(executable_path=gecko) if gecko else None
    driver = webdriver.Firefox(options=opts, service=service)
    try:
        driver.get(url)
        time.sleep(1)
        driver.execute_script(CAPTURE_JS)

        deadline = time.time() + wait
        result = {}
        while time.time() < deadline:
            try:
                result = json.loads(driver.execute_script(READ_JS) or "{}")
            except Exception:
                result = {}
            if result.get("pssh") and result.get("mpds") and (result.get("license") or result.get("posts")):
                break
            time.sleep(poll)
        result.setdefault("page_url", url)
        return result
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        try:
            shutil.rmtree(work_profile, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    print("pywidevine:", "OK" if _HAS_PYWV else "MISSING")
    dev = find_device_wvd()
    print("device.wvd:", dev)
    if dev and _HAS_PYWV:
        d = Device.load(dev)
        cdm = Cdm.from_device(d)
        sid = cdm.open()
        fake = PSSH(b"\x00\x00\x002pssh\x00\x00\x00\x00"
                    b"\xed\xef\x8b\xa9\x79\xd6\x4a\xce\xa3\xc8\x27\xdc\xd5\x1d\x21\xed")
        ch = cdm.get_license_challenge(sid, fake)
        print("challenge 长度:", len(ch), "bytes (派生正常)")
        cdm.close(sid)
    print("firefox profiles:", firefox_profiles())
