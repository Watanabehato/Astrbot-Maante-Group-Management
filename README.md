# AstrBot MaaNTE Group Management

一个用于 AstrBot + NapCat QQ（OneBot v11 / aiocqhttp）的跨群管理插件。

它的设计目标是：在一个控制群 A 中发送 `/gm` 指令，管理配置在 UMO 白名单里的其他 QQ 群。

## 功能

- 控制群授权：只有 `controller_umos` 中的群可以发起管理指令。
- 操作者授权：默认只允许 `operator_user_ids` 中的 QQ 号操作。
- 目标群白名单：只有 `managed_targets` 中的群可以被管理。
- 目标别名：可以给单个群或多个群设置短别名，减少误操作。
- MaaNTE Release 监控：定期检查 MaaNTE 更新，自动向被管理群发送更新通知。
- NapCat 群管理动作：
  - 发送群消息
  - 发送 @全员消息
  - 发布群公告
  - 单人禁言 / 解禁
  - 踢人
  - 全员禁言
  - 设置群名片
  - 设置 / 取消管理员
  - 查询群信息

## 配置

插件加载后，在 AstrBot WebUI 的插件配置中填写：

```json
{
  "platform_id": "aiocqhttp",
  "controller_umos": [
    "aiocqhttp:GroupMessage:111111111"
  ],
  "operator_user_ids": [
    "123456789"
  ],
  "allow_all_users_in_controller": false,
  "ignore_send_timeout_1200": true,
  "managed_targets": [
    "aiocqhttp:GroupMessage:222222222",
    "333333333"
  ],
  "target_aliases": "{\"test\": \"aiocqhttp:GroupMessage:222222222\", \"main\": \"333333333\", \"batch\": [\"222222222\", \"aiocqhttp:GroupMessage:333333333\"]}",
  "maante_check_enabled": true,
  "maante_check_interval": 3600,
  "maante_notify_prerelease": true,
  "maante_custom_message": "下载地址：https://github.com/1bananachicken/MaaNTE/releases/latest",
  "maante_mirror_url": ""
}
```

`target_aliases` 是一个 JSON 对象。值可以是单个群，也可以是多个群组成的数组：

```json
{
  "main": "333333333",
  "test": "aiocqhttp:GroupMessage:222222222",
  "batch": [
    "222222222",
    "aiocqhttp:GroupMessage:333333333"
  ]
}
```

可以在群里发送 AstrBot 内置命令 `/sid` 获取当前 UMO。UMO 形如：

```text
aiocqhttp:GroupMessage:群号
```

## 指令

所有指令都从控制群发送：

| 指令 | 说明 |
| --- | --- |
| `/gm help` | 显示帮助和所有子指令说明。 |
| `/gm sid` | 查看当前控制群的 UMO、群号、平台和发送者 QQ。 |
| `/gm list` | 列出已配置的被管理目标群和目标别名。 |
| `/gm info <目标>` | 查询目标群信息；目标可以是单群或多群别名。 |
| `/gm send <目标> <内容>` | 向目标群发送普通文本消息。 |
| `/gm atall <目标> <内容>` | 向目标群发送 @全员 消息。 |
| `/gm notice <目标> <公告内容>` | 向目标群发布群公告。 |
| `/gm mute <目标> <QQ号> <分钟>` | 在目标群禁言指定 QQ 号。 |
| `/gm unmute <目标> <QQ号>` | 在目标群解除指定 QQ 号的禁言。 |
| `/gm kick <目标> <QQ号> [reject]` | 从目标群踢出指定 QQ 号；加 `reject` 会拒绝再次入群。 |
| `/gm wholeban <目标> on\|off` | 开启或关闭目标群全员禁言。 |
| `/gm card <目标> <QQ号> <群名片>` | 设置指定 QQ 号在目标群的群名片。 |
| `/gm admin <目标> <QQ号> on\|off` | 设置或取消指定 QQ 号在目标群的管理员权限。 |
| `/gm maante check` | 立即检查 MaaNTE 最新 Release。 |
| `/gm maante status` | 查看 MaaNTE Release 监控状态。 |
| `/gm maante push <目标> [版本]` | 手动推送 MaaNTE Release 信息到目标群；不指定版本则推送最新版本。 |

示例：

```text
/gm mute test 123456789 10
/gm unmute test 123456789
/gm kick test 123456789 reject
/gm wholeban main on
/gm send main 今晚维护，稍后恢复。
/gm atall main 今晚维护，稍后恢复。
/gm notice main 今晚 23:00-23:30 维护，期间可能无法正常使用。
/gm send batch 这条消息会发到 batch 里的每个群。
/gm card test 123456789 新群名片
```

`<目标>` 可以是：

- `target_aliases` 中配置的别名，例如 `test` 或分组别名 `batch`
- QQ 群号，例如 `222222222`
- 完整 UMO，例如 `aiocqhttp:GroupMessage:222222222`

## MaaNTE Release 监控

插件支持自动监控 MaaNTE 的 GitHub Release 更新，并在发现新版本时自动向所有被管理群发送通知。

### 配置说明

- **maante_check_enabled**：是否启用监控，默认 `false`。
- **maante_check_interval**：检查间隔（秒），默认 `3600`（1小时）。建议设置为 1800-7200 秒。
- **maante_notify_prerelease**：是否通知公测版更新，默认 `true`。关闭后只通知正式版。
- **maante_custom_message**：自定义消息内容，会显示在通知开头。可用于添加下载链接、使用说明等。
- **maante_mirror_url**：GitHub API 镜像站地址，默认为空（直连）。可选镜像站：`https://gh-proxy.com`、`https://ghproxy.net`。插件会自动尝试多个源。

### 通知格式

当检测到新版本时，插件会向所有 `managed_targets` 中的群发送以下格式的消息：

```
MaaNTE 正式版/公测版更新通知
[自定义消息]

版本：v1.0.0
标题：Release Title
发布时间：2026-06-09T12:00:00Z

Changelog：
- 新增功能 A
- 修复 Bug B
- 优化性能 C
```

### 手动检查与推送

- **手动检查**：在控制群发送 `/gm maante check` 立即检查最新版本
- **查看状态**：发送 `/gm maante status` 查看监控状态
- **手动推送**：发送 `/gm maante push <目标> [版本]` 手动推送 Release 信息到指定群

手动推送示例：
```
/gm maante push main              # 推送最新版本到 main 别名对应的群
/gm maante push batch v1.1.0      # 推送 v1.1.0 版本到 batch 别名的所有群
/gm maante push 123456789 v1.0.1  # 推送 v1.0.1 版本到指定群号
```

## 注意

- 机器人账号必须在目标群中，并拥有执行对应动作所需的 QQ 群权限。
- `managed_targets` 为空时，插件不会允许管理任何群。
- `operator_user_ids` 为空时，默认不会允许任何人操作，除非显式开启 `allow_all_users_in_controller`。
- `atall`、`notice`、`admin` 和 `kick reject` 属于高风险动作，请谨慎开放给多人。
- NapCat 偶尔会在消息已发出后仍因 QQNT 回执超时抛出 `retcode=1200`。默认 `ignore_send_timeout_1200` 为 `true`，插件会把发送消息和群公告的这类超时按“可能已发送”处理。
