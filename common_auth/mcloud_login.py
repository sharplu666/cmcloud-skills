#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动云盘 mCloud 13.2.4 登录脚本 (密码登录 / 短信登录)

目标: 用账号密码完成登录, 全程自动处理滑块图形验证码; 需要短信验证码时
      暂停并读取用户输入; 最终把 token / Authorization / 服务端下发的云盘地址
      等落到 session.json, 供后续管理云盘文件复用。

逆向依据 (静态还原自 APK):
  * 后端 UserDomain (新平台, 主用): https://user-njs.yun.139.com
      POST user/thirdlogin     POST user/verfycode
      POST user/sms/getSmsCode POST user/sms/checkSmsCode
    报文 JSON (Gson), 字段取自 NewPlatformLoginInput / GetSmsCodeInput / CheckSmsCodeInput
  * 后端 AAS (旧平台, 回退): https://aas.caiyun.feixin.10086.cn
      POST tellin/thirdlogin.do   POST tellin/verfycode.do
    报文 XML (simple-xml, @Root(name="root"))
  * 密码字段 secinfo = HEX_UPPER(SHA1("fetion.com.cn:" + 明文密码))
  * 滑块验证码: type=2 拉图, 响应含 picture(背景) + puzzle(滑块图, 96x400, alpha 才是真形状)
      + puzzleLeft(服务端签发的校验令牌)。App 由用户拖动得到偏移量再回传校验值;
      实测服务端只认令牌, 令牌就是每次挑战随图下发的 puzzleLeft。脚本自动拉取挑战,
      本地用归一化互相关(NCC)算出真实缺口 x 做可视化/校验, 再回传令牌完成校验。
  * 短信验证码: user/sms/getSmsCode 触发下发, user/sms/checkSmsCode 校验; 脚本在此读用户输入。
  * 登录响应 data 为加密块: hex 密文 + AES/ECB/PKCS5, Release 密钥 qPqDw263XgFgL3u8
      (非 Release 为 2ErfJus1Ofr@2o24); 无密文时退化为明文 JSON。
  * AAS 响应 hex 密文 + AES/ECB/PKCS5, 密钥 = MD5(MD5(dycpwd) 或 secinfo + "GErfJus#Ofr%")[0:16].upper()

依赖: 标准库即可运行; 有 numpy + Pillow 时额外启用缺口自动识别。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

USER_DOMAIN_BASE = "https://user-njs.yun.139.com"
AAS_BASE = "https://aas.caiyun.feixin.10086.cn"

VERSION_CODE = "30132408"
CLIENT_TYPE = "414"
CPID = "58"
SALT = "fetion.com.cn:"
SYSTEM_NAME = "mobile:"

PIN_TYPE_ACCOUNT = "9"
PIN_TYPE_SMS = "8"
PIN_TYPE_SMS_HK = "23"

LOGIN_MODE_HAND = "1"
VER_TYPE_SLIDE = "2"

UD_KEY_RELEASE = "qPqDw263XgFgL3u8"
UD_KEY_DEBUG = "2ErfJus1Ofr@2o24"
AAS_RESP_SALT = "GErfJus#Ofr%"

RET_NEED_VERIFY = ("200059525", "200059526", "200059537", "200059538", "200059540")
RET_NEED_CAPTCHA = "200059554"
RET_CAPTCHA_INVALID = ("9103", "200050400", "200050401", "200050402", "200050403")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captcha_debug")


def log(msg):
    print(msg, flush=True)


def secinfo_of(password):
    return hashlib.sha1((SALT + password).encode("utf-8")).hexdigest().upper()


def md5_hex(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()


def msisdn_type(account):
    if re.fullmatch(r"\d*", account):
        return "10" if len(account) == 11 else "5"
    return "11" if "@" in account else "2"


def basic_auth(account, token):
    raw = (SYSTEM_NAME + account + ":" + token).encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def local_ip():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "10.0.0.1"

class Http:
    """极简 HTTP 客户端; 有 requests 用 requests, 没有用 urllib, 都会留存 cookie。"""

    def __init__(self, timeout=25):
        self.timeout = timeout
        self.cookies = {}
        self.last_status = None
        self.last_headers = {}
        try:
            import requests
            self._requests = requests.Session()
            self._requests.verify = False
        except Exception:
            self._requests = None

    def post_json(self, url, payload, headers):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs = dict(headers)
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        return self._post(url, raw, hdrs, "json")

    def post_xml(self, url, xml, headers):
        raw = xml.encode("utf-8")
        hdrs = dict(headers)
        hdrs.setdefault("Content-Type", "text/xml; charset=utf-8")
        return self._post(url, raw, hdrs, "xml")

    def _post(self, url, raw, headers, kind):
        if self._requests is not None:
            try:
                resp = self._requests.post(url, data=raw, headers=headers, timeout=self.timeout)
                self.last_status = resp.status_code
                self.last_headers = dict(resp.headers)
                self.cookies.update(resp.cookies.get_dict())
                return {"status": resp.status_code, "text": resp.text, "kind": kind}
            except Exception as exc:
                log("[http] requests 失败, 回落 urllib: %r" % (exc,))
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
                self.last_status = resp.status
                self.last_headers = dict(resp.headers)
                for c in resp.headers.get_all("Set-Cookie") or []:
                    if "=" in c:
                        self.cookies[c.split("=", 1)[0].strip()] = c.split("=", 1)[1].split(";")[0]
                return {"status": resp.status, "text": resp.read().decode("utf-8", "replace"), "kind": kind}
        except urllib.error.HTTPError as exc:
            self.last_status = exc.code
            self.last_headers = dict(exc.headers or {})
            return {"status": exc.code, "text": exc.read().decode("utf-8", "replace"), "kind": kind}
        except Exception as exc:
            self.last_status = None
            self.last_headers = {}
            return {"status": None, "text": "", "kind": kind, "error": repr(exc)}


def json_headers(account, nation_code):
    return {
        "Accept": "application/json",
        "x-SvcType": "1",
        "x-MM-Source": "000",
        "x-NationCode": nation_code,
        "x-ExpRoute-Code": "routeCode=%s,type=%s" % (account, msisdn_type(account)),
        "User-Agent": "okhttp/3.14.9",
    }


def xml_headers(account, nation_code):
    h = json_headers(account, nation_code)
    h["Accept"] = "application/xml"
    return h


_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d]


def _xtime(a):
    a <<= 1
    return (a ^ 0x1b) & 0xff if a & 0x100 else a


def _mul(a, b):
    res = 0
    for _ in range(8):
        if b & 1:
            res ^= a
        b >>= 1
        a = _xtime(a)
    return res


def _aes_expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    return w


def _aes_decrypt_block(w, block):
    nr = len(w) // 4 - 1
    s = [list(block[i::4]) for i in range(4)]

    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    def inv_shift_rows():
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]

    def inv_sub_bytes():
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]

    def inv_mix_columns():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
            s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
            s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
            s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)

    add_round_key(nr)
    for rnd in range(nr - 1, 0, -1):
        inv_shift_rows()
        inv_sub_bytes()
        add_round_key(rnd)
        inv_mix_columns()
    inv_shift_rows()
    inv_sub_bytes()
    add_round_key(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _key_bytes(key):
    """密钥统一成字节: 常规密钥都是 16 字节 ASCII; 非 ASCII 时按 latin-1 保字节。"""
    if isinstance(key, bytes):
        return key
    try:
        return key.encode("ascii")
    except Exception:
        return key.encode("latin-1")


def aes_ecb_decrypt_bytes(key, data):
    """AES/ECB/PKCS5 解密字节串, 纯 Python 实现 (无第三方依赖), 返回脱填充后的字节。"""
    if not data or len(data) % 16:
        return None
    try:
        rk = _aes_expand_key(_key_bytes(key))
        out = bytearray()
        for i in range(0, len(data), 16):
            out += _aes_decrypt_block(rk, data[i:i + 16])
        pad = out[-1]
        if 1 <= pad <= 16 and len(out) >= pad:
            out = out[:-pad]
        return bytes(out)
    except Exception:
        return None


def aes_ecb_decrypt_hex(key, hex_cipher):
    """AES/ECB/PKCS5 解密 hex 密文, 结果是 UTF-8 文本时返回 str, 否则 None。"""
    try:
        raw = aes_ecb_decrypt_bytes(key, bytes.fromhex(hex_cipher))
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except Exception:
        return None

def decrypt_userdomain_data(data):
    """UserDomain 响应 data: hex 密文 -> AES/ECB/PKCS5 -> JSON 文本。"""
    if data is None or isinstance(data, dict):
        return data if isinstance(data, dict) else None
    if not isinstance(data, str):
        return None
    text = data.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            return None
    if re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 32 == 0:
        for key in (UD_KEY_RELEASE, UD_KEY_DEBUG):
            plain = aes_ecb_decrypt_hex(key, text)
            if plain and plain.lstrip().startswith("{"):
                try:
                    return json.loads(plain)
                except Exception:
                    continue
    return None


def aas_response_key(pintype, secinfo, dycpwd):
    md5 = md5_hex(dycpwd)
    if pintype == "9":
        md5 = secinfo
    return md5_hex(md5 + AAS_RESP_SALT)[:16].upper()


def solve_slide_offset(bg_bytes, puzzle_bytes, save_prefix=None):
    """返回 (x, meta)。x = 缺口左边缘在背景图上的像素坐标。

    puzzle 是 96x400 条带, alpha 通道才是真实滑块形状; 背景中的缺口被半透明灰遮罩,
    因此掩码内的归一化互相关(NCC)比像素差(SAD)稳健得多。
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:
        log("[captcha] 缺少 numpy/Pillow, 跳过本地缺口识别: %r" % (exc,))
        return None, {}
    bg_img = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
    pz_img = Image.open(io.BytesIO(puzzle_bytes)).convert("RGBA")
    bg = np.asarray(bg_img).astype(np.float64)
    pz = np.asarray(pz_img)
    alpha = pz[..., 3]
    rgb = pz[..., :3].astype(np.float64)
    mask = alpha > 200
    ys, _ = np.nonzero(mask)
    if ys.size == 0:
        return None, {}
    y0, y1 = int(ys.min()), int(ys.max())
    sub = rgb[y0:y1 + 1][mask[y0:y1 + 1]]
    band = bg[y0:y1 + 1]
    width = band.shape[1]
    pw = rgb.shape[1]
    if width < pw or sub.size == 0:
        return None, {}
    sub_c = sub - sub.mean(axis=0)
    sub_n = float(np.sqrt((sub_c ** 2).sum()))
    scores = []
    for x in range(0, width - pw + 1):
        seg = band[:, x:x + pw][mask[y0:y1 + 1]]
        seg_c = seg - seg.mean(axis=0)
        seg_n = float(np.sqrt((seg_c ** 2).sum()))
        scores.append(float((sub_c * seg_c).sum() / (sub_n * seg_n + 1e-9)))
    best_x = int(max(range(len(scores)), key=lambda i: scores[i]))
    meta = {
        "picWidth": width,
        "picHeight": band.shape[0],
        "pieceWidth": pw,
        "pieceY": [y0, y1],
        "ncc": round(scores[best_x], 4),
        "top5": sorted([(round(s, 4), i) for i, s in enumerate(scores)], reverse=True)[:5],
    }
    if save_prefix:
        os.makedirs(os.path.dirname(save_prefix), exist_ok=True)
        bg_img.save(save_prefix + "_bg.jpg", quality=92)
        overlay = Image.new("RGBA", pz_img.size, (255, 0, 255, 255))
        overlay.alpha_composite(pz_img)
        overlay.convert("RGB").save(save_prefix + "_piece.png")
        draw_bg = bg_img.copy()
        from PIL import ImageDraw
        ImageDraw.Draw(draw_bg).rectangle([best_x, y0, best_x + pw - 1, y1], outline=(255, 0, 0), width=3)
        draw_bg.save(save_prefix + "_solved.png")
    return best_x, meta


def fetch_puzzle_ud(http, account, nation_code):
    res = http.post_json(USER_DOMAIN_BASE + "/user/verfycode",
                         {"account": account, "type": VER_TYPE_SLIDE},
                         json_headers(account, nation_code))
    try:
        body = json.loads(res.get("text") or "{}")
    except Exception:
        body = {}
    data = body.get("data") if isinstance(body.get("data"), dict) else None
    if not data:
        return {"ok": False, "raw": res.get("text"), "code": body.get("code"), "message": body.get("message")}
    out = {"ok": True, "code": body.get("code"), "message": body.get("message")}
    for k in ("picture", "puzzle", "puzzleLeft", "picWidth", "picHeight", "puzzleWidth", "picType"):
        out[k] = data.get(k)
    return out


def fetch_puzzle_aas(http, account, nation_code):
    xml = "<root><account>%s</account><type>%s</type></root>" % (account, VER_TYPE_SLIDE)
    res = http.post_xml(AAS_BASE + "/tellin/verfycode.do", xml, xml_headers(account, nation_code))
    text = res.get("text") or ""
    out = {"ok": False, "raw": text}
    for tag in ("return", "desc", "picture", "puzzle", "puzzleLeft",
                "picWidth", "picHeight", "puzzleWidth", "picType"):
        m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), text, re.S)
        if m:
            out[tag] = m.group(1).strip()
    out["ok"] = bool(out.get("puzzleLeft"))
    out["code"] = out.get("return")
    out["message"] = out.get("desc")
    return out


def solve_captcha(http, account, nation_code, backend, max_try=6, save_debug=False):
    """自动处理滑块图形验证码, 返回可提交的 verfycode 校验令牌。"""
    for attempt in range(1, max_try + 1):
        puzzle = fetch_puzzle_ud(http, account, nation_code) if backend == "userdomain" \
            else fetch_puzzle_aas(http, account, nation_code)
        if not puzzle.get("ok"):
            log("[captcha] 第%d次拉取失败: code=%s message=%s"
                % (attempt, puzzle.get("code"), puzzle.get("message")))
            time.sleep(1.0)
            continue
        token = puzzle.get("puzzleLeft")
        if puzzle.get("picture") and puzzle.get("puzzle"):
            try:
                prefix = os.path.join(DEBUG_DIR, "slide_%s_%d" % (account, attempt)) if save_debug else None
                x, meta = solve_slide_offset(base64.b64decode(puzzle["picture"]),
                                             base64.b64decode(puzzle["puzzle"]), prefix)
                if x is not None:
                    log("[captcha] 第%d次: 自动识别缺口 x=%s (ncc=%s, 图 %sx%s, 块宽 %s, y=%s %s)"
                        % (attempt, x, meta.get("ncc"), meta.get("picWidth"), meta.get("picHeight"),
                           meta.get("pieceWidth"), meta.get("pieceY"), "" if not prefix else "已存调试图"))
            except Exception as exc:
                log("[captcha] 图像解析失败: %r" % (exc,))
        log("[captcha] 第%d次: 取得服务端校验令牌 puzzleLeft=%s..., 自动回传" % (attempt, (token or "")[:16]))
        return token
    raise RuntimeError("图形验证码处理失败: 超过 %d 次重试" % max_try)

class LoginResult:
    def __init__(self):
        self.raw = {}
        self.plain = {}
        self.code = None
        self.message = None
        self.success = False
        self.need_captcha = False
        self.need_verify = False

    def __repr__(self):
        return "LoginResult(code=%s, success=%s, need_verify=%s)" % (
            self.code, self.success, self.need_verify)


def parse_ud_response(text):
    """解析 UserDomain 统一响应 {success, code, message, data}"""
    r = LoginResult()
    try:
        env = json.loads(text)
    except Exception:
        r.raw = {"text": text}
        return r
    r.raw = env
    r.code = str(env.get("code") or "")
    r.message = env.get("message")
    r.success = bool(env.get("success"))
    inner = decrypt_userdomain_data(env.get("data"))
    if inner:
        r.plain = inner
        if inner.get("return") is not None:
            r.code = str(inner.get("return"))
        if inner.get("desc"):
            r.message = inner.get("desc")
        r.success = r.code in ("0", "0000") or r.success
    r.need_captcha = r.code == RET_NEED_CAPTCHA
    r.need_verify = r.code in RET_NEED_VERIFY
    return r


def parse_aas_response(text, pintype, secinfo, dycpwd):
    r = LoginResult()
    if not text:
        return r
    body = text
    if "<root>" not in text:
        key = aas_response_key(pintype, secinfo, dycpwd)
        plain = aes_ecb_decrypt_hex(key, text.strip())
        if plain:
            body = plain
    r.raw = {"text": body}

    def pick(tag):
        m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), body, re.S)
        return m.group(1).strip() if m else None

    r.code = pick("return")
    r.message = pick("desc")
    r.success = r.code in ("0",)
    r.need_captcha = r.code == RET_NEED_CAPTCHA
    r.need_verify = r.code in RET_NEED_VERIFY
    fields = {}
    for tag in ("token", "authToken", "userid", "loginid", "deviceid", "expiretime",
                "atExpiretime", "userName", "account", "areaCode", "provCode", "sbc",
                "imspwd", "svnuser", "svnpwd", "svnlist", "htslist", "domain",
                "expiryDate", "srvInfoVer", "userDomainId"):
        v = pick(tag)
        if v is not None:
            fields[tag] = v
    if fields:
        r.plain = fields
    return r


def ud_password_login(http, account, password, nation_code, verfycode, login_mode, request_ip):
    payload = {
        "msisdn": account,
        "clienttype": CLIENT_TYPE,
        "cpid": CPID,
        "pintype": PIN_TYPE_ACCOUNT,
        "secinfo": secinfo_of(password),
        "verfycode": verfycode or "",
        "verType": VER_TYPE_SLIDE if (verfycode and len(verfycode) > 4) else "",
        "version": VERSION_CODE,
        "srvInfoVer": "0",
        "loginMode": login_mode,
        "requestip": request_ip,
        "extInfo": {},
    }
    res = http.post_json(USER_DOMAIN_BASE + "/user/thirdlogin", payload, json_headers(account, nation_code))
    return parse_ud_response(res.get("text") or "")


def ud_sms_login(http, account, sms_code, nation_code, verfycode, login_mode, request_ip):
    pintype = PIN_TYPE_SMS_HK if nation_code == "+852" else PIN_TYPE_SMS
    payload = {
        "msisdn": account,
        "clienttype": CLIENT_TYPE,
        "cpid": CPID,
        "pintype": pintype,
        "dycpwd": sms_code,
        "verfycode": verfycode or "",
        "verType": VER_TYPE_SLIDE if (verfycode and len(verfycode) > 4) else "",
        "version": VERSION_CODE,
        "srvInfoVer": "0",
        "loginMode": login_mode,
        "requestip": request_ip,
        "extInfo": {},
    }
    res = http.post_json(USER_DOMAIN_BASE + "/user/thirdlogin", payload, json_headers(account, nation_code))
    return parse_ud_response(res.get("text") or "")


def aas_password_login(http, account, password, nation_code, verfycode, login_mode, request_ip):
    sec = secinfo_of(password)
    parts = [
        "<msisdn>%s</msisdn>" % account,
        "<clienttype>%s</clienttype>" % CLIENT_TYPE,
        "<cpid>%s</cpid>" % CPID,
        "<pintype>%s</pintype>" % PIN_TYPE_ACCOUNT,
        "<secinfo>%s</secinfo>" % sec,
        "<version>%s</version>" % VERSION_CODE,
        "<srvInfoVer>0</srvInfoVer>",
        "<loginMode>%s</loginMode>" % login_mode,
        "<requestip>%s</requestip>" % request_ip,
    ]
    if verfycode:
        parts.append("<verfycode>%s</verfycode>" % verfycode)
        if len(verfycode) > 4:
            parts.append("<verType>%s</verType>" % VER_TYPE_SLIDE)
    xml = "<root>%s</root>" % "".join(parts)
    res = http.post_xml(AAS_BASE + "/tellin/thirdlogin.do", xml, xml_headers(account, nation_code))
    return parse_aas_response(res.get("text") or "", PIN_TYPE_ACCOUNT, sec, "")


def ud_get_sms_code(http, account, nation_code, req_type, random_str, puzzle_token):
    payload = {
        "phoneNumber": account,
        "reqType": req_type,
        "mode": "0",
        "lang": "zh",
        "clientType": CLIENT_TYPE,
        "random": random_str,
        "puzzleVerfycode": puzzle_token or "",
        "aaaPasswd": "",
        "userDomainId": "",
    }
    res = http.post_json(USER_DOMAIN_BASE + "/user/sms/getSmsCode", payload, json_headers(account, nation_code))
    try:
        return json.loads(res.get("text") or "{}")
    except Exception:
        return {"raw": res.get("text")}


def ud_check_sms_code(http, account, nation_code, req_type, secinfo, record_id, code, only_verify="1"):
    payload = {
        "phoneNumber": account,
        "reqType": req_type,
        "secinfo": secinfo or "",
        "recordID": record_id or "",
        "pwd": code,
        "onlyVerify": only_verify,
        "aaaPasswd": "",
        "userDomainId": "",
    }
    res = http.post_json(USER_DOMAIN_BASE + "/user/sms/checkSmsCode", payload, json_headers(account, nation_code))
    try:
        return json.loads(res.get("text") or "{}")
    except Exception:
        return {"raw": res.get("text")}


def request_and_ask_sms_code(http, account, nation_code, req_types, record_id, puzzle_token, prompt):
    """触发短信下发(自动过滑块), 然后暂停等待用户在终端输入验证码。"""
    random_str = uuid.uuid4().hex[:8]
    sent = None
    for rt in req_types:
        resp = ud_get_sms_code(http, account, nation_code, rt, random_str, puzzle_token)
        code = str(resp.get("code") or "")
        log("[sms] getSmsCode reqType=%s -> code=%s message=%s" % (rt, code, resp.get("message")))
        if resp.get("success") or code in ("0", "0000"):
            sent = rt
            data = resp.get("data") or {}
            log("[sms] 已向 %s 触发验证码下发 (剩余次数=%s)" % (account, data.get("remainGetTimes")))
            break
    if sent is None:
        log("[sms] 未确认下发结果, 仍继续让用户输入验证码")
    log("-" * 60)
    log("请查收短信验证码 (%s)" % prompt)
    while True:
        code = input(">>> 请输入短信验证码: ").strip()
        if code:
            return code

def build_session(account, result, backend, http, password=None):
    plain = result.plain or {}
    token = plain.get("token") or plain.get("authToken") or ""
    session = {
        "backend": backend,
        "account": account,
        "userName": plain.get("userName") or plain.get("account") or account,
        "userid": plain.get("userid"),
        "loginid": plain.get("loginid"),
        "userDomainId": plain.get("userDomainId"),
        "deviceId": plain.get("deviceId") or plain.get("deviceid"),
        "token": token,
        "authToken": plain.get("authToken") or token,
        "tokenExpire": plain.get("expiretime"),
        "atExpiretime": plain.get("atExpiretime"),
        "imspwd": plain.get("imspwd"),
        "sbc": plain.get("sbc"),
        "areaCode": plain.get("areaCode"),
        "provCode": plain.get("provCode"),
        "serverinfo": plain.get("serverinfo"),
        "routerInfo": plain.get("routerInfo"),
        "svnuser": plain.get("svnuser"),
        "svnpwd": plain.get("svnpwd"),
        "svnlist": plain.get("svnlist"),
        "htslist": plain.get("htslist"),
        "domain": plain.get("domain"),
        "loginTime": int(time.time()),
        "loginCode": result.code,
        "cookies": dict(http.cookies),
        "loginEndpoints": {"userDomain": USER_DOMAIN_BASE, "aas": AAS_BASE},
        "authHeader": basic_auth(account, token) if token else "",
        "requestHeaders": json_headers(account, "+86"),
        "loginRaw": result.raw,
    }
    if password:
        session["secinfo"] = secinfo_of(password)
    return session


def verify_session(session, http):
    """用会话调一个云盘接口, 证明凭据可用。"""
    account = session["account"]
    headers = dict(session.get("requestHeaders") or json_headers(account, "+86"))
    if session.get("authHeader"):
        headers["Authorization"] = session["authHeader"]
    out = {"endpoint": "/user/disk/getPersonalDiskInfo"}
    res = http.post_json(USER_DOMAIN_BASE + "/user/disk/getPersonalDiskInfo",
                         {"userDomainId": session.get("userDomainId") or ""}, headers)
    try:
        env = json.loads(res.get("text") or "{}")
    except Exception:
        env = {"raw": res.get("text")}
    out["status"] = res.get("status")
    out["code"] = env.get("code")
    out["message"] = env.get("message")
    out["data"] = env.get("data")
    out["ok"] = bool(env.get("success")) or str(env.get("code")) in ("0", "0000")
    return out


def do_login(args):
    http = Http()
    account = args.account
    nation_code = args.nation_code
    request_ip = args.request_ip or local_ip()
    backend = args.backend

    log("=" * 68)
    log("mCloud 登录  账号=%s  模式=%s  后端=%s  请求IP=%s" % (account, args.mode, backend, request_ip))
    log("=" * 68)

    captcha_token = ""
    if args.captcha != "off":
        captcha_token = solve_captcha(http, account, nation_code, backend,
                                      max_try=args.captcha_retry, save_debug=args.captcha_debug)
        log("[captcha] verfycode=%s" % captcha_token)

    if args.mode == "sms":
        code = args.sms_code or request_and_ask_sms_code(
            http, account, nation_code, ("1", "3", "12"), "", captcha_token, "短信登录")
        result = ud_sms_login(http, account, code, nation_code, captcha_token, LOGIN_MODE_HAND, request_ip)
    elif backend == "aas":
        result = aas_password_login(http, account, args.password, nation_code,
                                    captcha_token, LOGIN_MODE_HAND, request_ip)
    else:
        result = ud_password_login(http, account, args.password, nation_code,
                                   captcha_token, LOGIN_MODE_HAND, request_ip)
    log("[login] code=%s message=%s" % (result.code, result.message))

    if str(result.code) in RET_NEED_VERIFY:
        ext = (result.plain or {}).get("extInfo") or {}
        record_id = ext.get("protectRecordId") or ext.get("logInAuthInfoRecordId") or ""
        log("[login] 需要二次校验 / 短信验证, recordId=%s" % record_id)
        # 第一个滑块令牌已被本次登录消费, 申请短信必须换新令牌
        sms_captcha = captcha_token
        if args.captcha != "off":
            sms_captcha = solve_captcha(http, account, nation_code, backend,
                                        max_try=args.captcha_retry, save_debug=args.captcha_debug)
        code = args.sms_code or request_and_ask_sms_code(
            http, account, nation_code, ("3", "1", "12", "2"), record_id, sms_captcha, "登录保护校验")
        # 主路径(实网验证): 账密登陆保护的出口 = 短信登录 pintype=8, dycpwd=验证码
        sms_captcha2 = ""
        if args.captcha != "off":
            sms_captcha2 = solve_captcha(http, account, nation_code, backend,
                                         max_try=args.captcha_retry, save_debug=args.captcha_debug)
        result = ud_sms_login(http, account, code, nation_code, sms_captcha2,
                              LOGIN_MODE_HAND, request_ip)
        log("[login] 保护校验后短信登录 code=%s message=%s" % (result.code, result.message))
        if not (result.success or str(result.code) in ("0", "0000")):
            # 回退路径: checkSmsCode(客户端原样载荷) + 密码重登
            random_str = uuid.uuid4().hex[:8]
            chk = ud_check_sms_code(http, account, nation_code, "3",
                                    md5_hex(random_str + account + code), record_id, code)
            log("[login] 回退 checkSmsCode -> code=%s message=%s" % (chk.get("code"), chk.get("message")))
            if chk.get("success") or str(chk.get("code")) in ("0", "0000"):
                if backend == "aas":
                    result = aas_password_login(http, account, args.password, nation_code,
                                                sms_captcha2, LOGIN_MODE_HAND, request_ip)
                else:
                    result = ud_password_login(http, account, args.password, nation_code,
                                               sms_captcha2, LOGIN_MODE_HAND, request_ip)
                log("[login] 二次校验后重试 code=%s message=%s" % (result.code, result.message))

    if str(result.code) in ("0", "0000"):
        session = build_session(account, result, backend, http, args.password)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(session, fh, ensure_ascii=False, indent=2)
        log("[login] 登录成功, 会话已写入 %s" % os.path.abspath(args.out))
        log("[login] token=%s" % (str(session.get("token"))[:24] + "..."))
        log("[login] Authorization: %s" % session.get("authHeader"))
        if session.get("serverinfo"):
            log("[login] 服务端下发地址: %s" % json.dumps(session["serverinfo"], ensure_ascii=False)[:400])
        if args.verify:
            v = verify_session(session, http)
            log("[verify] %s -> ok=%s code=%s message=%s" % (v["endpoint"], v["ok"], v["code"], v["message"]))
        log("RESULT=OK")
        return 0

    log("[login] 失败: code=%s message=%s" % (result.code, result.message))
    log("RESULT=FAIL code=%s" % result.code)
    return 3


def build_argparser():
    ap = argparse.ArgumentParser(
        description="中国移动云盘 mCloud 13.2.4 登录 (自动过滑块验证码, 短信验证码由用户输入)")
    ap.add_argument("--account", required=True, help="手机号 / 账号")
    ap.add_argument("--password", default="", help="明文密码 (密码登录必填)")
    ap.add_argument("--mode", choices=("password", "sms"), default="password", help="登录方式")
    ap.add_argument("--sms-code", default="", help="短信验证码 (不填则交互式输入)")
    ap.add_argument("--backend", choices=("userdomain", "aas"), default="userdomain",
                    help="登录后端: 新平台 userdomain / 旧平台 aas")
    ap.add_argument("--nation-code", default="+86", help="国家码, 港澳填 +852")
    ap.add_argument("--captcha", choices=("auto", "off"), default="auto", help="图形验证码处理策略")
    ap.add_argument("--captcha-retry", type=int, default=6, help="图形验证码最大重试次数")
    ap.add_argument("--captcha-debug", action="store_true", help="保存滑块调试图到 captcha_debug/")
    ap.add_argument("--request-ip", default="", help="请求里上报的 requestip")
    ap.add_argument("--out", default="session.json", help="会话输出文件")
    ap.add_argument("--verify", action="store_true", help="登录后用会话调云盘接口自检")
    return ap


def main(argv=None):
    args = build_argparser().parse_args(argv)
    if args.mode == "password" and not args.password:
        log("错误: 密码登录需要 --password")
        return 2
    return do_login(args)


if __name__ == "__main__":
    sys.exit(main())
