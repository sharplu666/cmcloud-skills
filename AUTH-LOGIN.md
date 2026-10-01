# 登录脚本与鉴权说明

## 一、登录脚本

`common_auth/mcloud_login.py` —— 中国移动云盘 mCloud 13.2.4 账号登录脚本。
自动过滑块图形验证码；需要短信验证码时暂停并读取终端输入；最终把 token / Authorization /
服务端下发地址写入 `session.json`，供本包所有 skill 复用。

```bash
python common_auth/mcloud_login.py --account 18802936999 --password '<密码>' \
       --out common_auth/session.json
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--account` | 手机号 / 账号（必填） |
| `--password` | 明文密码（密码登录必填） |
| `--mode {password,sms}` | 登录方式，默认 `password` |
| `--sms-code` | 短信验证码；不填则交互式输入 |
| `--backend {userdomain,aas}` | 登录后端，默认新平台 `userdomain` |
| `--nation-code` | 国家码，默认 `+86`（港澳 `+852`） |
| `--captcha {auto,off}` | 图形验证码策略，默认 `auto` |
| `--captcha-retry` | 滑块最大重试次数，默认 6 |
| `--out` | 会话输出文件，默认 `session.json` |
| `--verify` | 登录后用会话调 `user/disk/getPersonalDiskInfo` 自检 |

命中 200059526（账密登录保护）时脚本会自动发短信并提示输入；成功后输出
`RESULT=OK`，失败输出 `RESULT=FAIL code=<码>`。

## 二、会话文件 `session.json`

```jsonc
{
  "backend": "userdomain",
  "account": "<手机号>",
  "userDomainId": "<userDomainId>",
  "deviceId": "<deviceId>",
  "token": "<登录成功后写入的 token>",
  "tokenExpire": "2592000",          // 30 天
  "authHeader": "<登录成功后写入的 Authorization>",
  "secinfo": "<SHA1(密码)>",          // 仅密码登录时写入
  "routerInfo": [ …各业务网关地址… ],
  "loginRaw": { …登录原始响应… }
}
```

> `session.json` 是**真实凭据**（token 30 天有效），交接/上传前脱敏或删除。

## 三、本包如何使用会话

```
common_auth/cm_cloud_auth.py   ──┐
common/mclaw/api/auth.py       ──┼─→ build_native_headers(session)
common/mclaw/api/app_endpoint_map.py ─┘        │
                                              ▼
   POST https://<业务网关>/…   Authorization: Basic base64("mobile:"+account+":"+token)
                               + x-yun-api-version / x-yun-client-info / x-yun-device-id /
                                 x-yun-user-agent / x-yun-app-channel / x-yun-net-type /
                                 x-yun-svc-type / x-yun-module-type / x-yun-uni / x-yun-tid
```

- 会话路径：`CM_CLOUD_SESSION_FILE`（相对路径按包根解析），缺省 `common_auth/session.json`。
- 鉴权是**单一模式**：不存在其它后端开关，也没有任何密文 token 文件/网关白名单依赖。
- 缺会话或字段不全时抛 `AuthConfigError`，提示重跑登录脚本。

## 四、坑位清单

1. **服务端只认最新一条短信**；旧码重放一定 `9441`，一条码只用一次。
2. **滑块令牌一次性**：登录消费后拿去发短信会 `200059555`；同一令牌重复登录 `200059553`。三个环节各取一次新令牌。
3. **发短信是打给真实手机号**，别用真实号码做探测；探测用占位号。
4. `user/verfycode` 只认 `type=2`；`type=1` 返回空 data，`type=3` 报 `9103`。
5. `checkSmsCode` 的 `onlyVerify` 填 `0/1/空/不填` 都返回 0000 但 `data` 全 null；它**不是** 526 的出口，只当回退手段。
6. 账号短信下发次数有上限（`remainGetTimes`），用完当天再发会被限流 `200050437`；重跑请等次日或换号。
7. 登录响应 `data` 为加密块（hex 密文 + AES/ECB/PKCS5）；无密文时退化为明文 JSON。

## 五、会话失效与刷新

- 业务网关返回 `01000002 / 05050006 / 04000005` 等鉴权码，或 `AuthConfigError` 提示找不到会话 → 重跑登录脚本。
- 有效期 `tokenExpire=2592000`（30 天）；换账号直接覆盖 `session.json` 即可。