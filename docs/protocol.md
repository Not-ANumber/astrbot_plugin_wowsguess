# wowsguess AstrBot 协议 v1（remote 模式）

本协议只用于插件的 `mode=remote`。默认的 `mode=local` 在 AstrBot 进程内直接调用
`wowsguess.app.GameApp`，不经过 HTTP，也不需要 token。

> 当前 v1 只覆盖 text / image / none。local 核心已支持 `/统计`、`/再来一局`、候选确认
> 和官方 Markdown，这些尚未纳入 remote 协议。

remote 模式下，适配器和游戏服务之间只有一个同步 HTTP 端点。适配器不保存游戏状态，
服务端是唯一真相。

## 鉴权

服务端默认应要求 Bearer token：

```http
Authorization: Bearer <AUTH_TOKEN>
```

插件配置里的 `auth_token` 留空时不发送该头；生产部署不建议留空。

## POST /v1/events

请求：

```json
{
  "protocol": 1,
  "request_id": "9f1c...",
  "event": {
    "platform": "aiocqhttp:123456789",
    "account_id": "123456789",
    "channel": { "type": "group", "id": "987654321" },
    "sender": {
      "id": "111222333",
      "name": "舰长",
      "role": "member"
    },
    "message": {
      "id": "msg-123",
      "text": "/秋月",
      "mentions": ["444555666"],
      "reply_to": null,
      "directed": true
    },
    "received_at": 1760000000000
  }
}
```

字段：

| 字段 | 说明 |
|---|---|
| `platform` | `平台名:机器人 ID（self_id）`。不同平台、不同账号不能共用会话 |
| `account_id` | 机器人自身 ID（OneBot 是 QQ 号，官方是 bot openid） |
| `channel.type` | v1 固定 `group` |
| `channel.id` | 群号或 `group_openid`，适配器和服务都应当作不透明字符串 |
| `sender.id` | 发送者 QQ 号或 `member_openid` |
| `sender.name` | 昵称/群名片，已截断到 64 字符 |
| `sender.role` | `owner` / `admin` / `member`；未知时传 `member` |
| `message.id` | 平台消息 ID，用于去重和幂等 |
| `message.text` | 已归一化为 `/...` 的游戏命令；空字符串表示“只 @ 了机器人” |
| `message.mentions` | 本条消息 @ 的其他用户 ID，不含机器人自己和 `all` |
| `message.reply_to` | 引用的消息 ID，没有则为 `null` |
| `message.directed` | v1 固定 `true`；适配器只转发游戏消息 |
| `received_at` | 毫秒时间戳 |

适配器已经把 `#`、`＃`、`！`、`!` 前缀翻译成 `/`，服务端只需要处理 `/` 形式。

响应：

```json
{
  "protocol": 1,
  "request_id": "9f1c...",
  "reply": {
    "type": "image",
    "image": { "mime": "image/png", "base64": "iVBORw0KGgo..." },
    "caption": "第 3 猜 · 秋月 · 剩余 5 次",
    "fallback_text": "完整文本棋盘……"
  }
}
```

`reply.type`：

| 类型 | 字段 | 适配器行为 |
|---|---|---|
| `text` | `text` | 发一条文本 |
| `image` | `image.mime`、`image.base64`，可选 `caption`、`fallback_text` | 发图片；失败时发 `fallback_text` |
| `none` | 无 | 不发消息，并阻止消息继续进 LLM/其他插件 |

服务端错误（船名不存在、冷却中、没开局等）应当作为 `type: "text"` 的正常回复返回，
不要用 HTTP 5xx 表达业务错误。HTTP 4xx 只用于鉴权失败和畸形请求。

## GET /v1/health

```json
{
  "ok": true,
  "protocol": 1,
  "service": "wowsguess-coop",
  "service_version": "0.1.0",
  "data_version": "2026-10-21T23:18:53.000Z",
  "ships": 854
}
```

插件目前不会在启动时阻塞等待健康检查，但运维和联调时应当能直接 `curl` 到这个端点。

## 服务端职责

1. **去重**：按 `(platform, account_id, message.id)` 缓存回复。适配器超时重试或平台重复
   推送时，不能重复消耗猜测次数。建议缓存 10 分钟。
2. **串行**：按 `(platform, account_id, channel.id)` 建异步锁/队列。两次猜测不能交错
   读写同一局。
3. **会话键**：`(platform, account_id, channel.id)`。不要只用群号，否则同群两个机器人
   账号会共用一局。
4. **群白名单**：服务端必须自己校验，不能只依赖适配器配置。
5. **答案隔离**：进行中的回复不得包含答案。日志、错误信息、健康检查都不返回答案。
6. **图片上限**：建议 5MB 以内；适配器硬限制 8MB。
7. **超时**：图片渲染和发送应在 10 秒内完成；适配器默认 15 秒超时。

## 幂等与重试

适配器当前不自动重试。即使以后加上重试，服务端也应当用 `message.id` 实现幂等：
同一个消息重复到达时返回第一次的回复，而不是再猜一次。

如果 `message.id` 缺失，适配器会生成一个 UUID；这种情况下服务端只能按请求级别处理，
无法跨重试去重。平台适配器应尽量提供真实消息 ID。

## 兼容性

- `protocol` 是整数，当前为 `1`。新增可选字段不升版本；删除/改名/改变语义必须升版本。
- 适配器收到非 `1` 的响应会报错并停止处理该消息，不会把未知内容发给群里。
- 数据版本变化由服务端处理：已有会话应当中止，而不是跨版本继续。

## 为什么不把游戏逻辑放进插件

- 答案库和渲染已经在 Node/TypeScript 里实现并有测试；重写一份 Python 版本会产生两套
  规则和两套图片。
- AstrBot、LangBot、NoneBot、Koishi 都可以复用同一个 HTTP 协议，每个适配器只需要
  100–200 行事件映射。
- 服务端的 SQLite 是唯一答案来源，插件和适配器都不接触答案，泄露面更小。
