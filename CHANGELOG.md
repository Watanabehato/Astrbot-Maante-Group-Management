# 更改记录

## 新增功能：MaaNTE Release 更新监控

### 文件修改统计
- README.md: +44 行
- _conf_schema.json: +30 行  
- main.py: +165 行
- requirements.txt: 新建文件

### main.py 主要更改

#### 1. 新增导入
```python
import asyncio
from datetime import datetime
from typing import Any, Optional, Dict
import aiohttp
```

#### 2. 类初始化增强
```python
def __init__(self, context: Context, config: AstrBotConfig):
    super().__init__(context)
    self.config = config
    self.last_notified_version = None  # 记录上次通知的版本
    self.check_task = None  # 后台检查任务
    self.session = None  # aiohttp 会话
    
    # 如果启用监控，自动启动后台任务
    if self.config.get("maante_check_enabled", False):
        self.check_task = asyncio.create_task(self._start_release_check_loop())
```

#### 3. 新增命令处理
在 `group_management` 方法中添加：
```python
elif command == "maante":
    yield event.plain_result(await self._cmd_maante(event, args[1:]))
```

#### 4. 新增方法（共 6 个）

**`_cmd_maante()`** - 处理 `/gm maante` 子命令
- `check` - 立即检查最新 Release
- `status` - 查看监控状态

**`_fetch_latest_release()`** - 从 gh-proxy 镜像站获取最新 Release
- 使用 aiohttp 异步请求
- 支持自定义镜像站地址
- 30 秒超时

**`_start_release_check_loop()`** - 后台定期检查循环
- 按配置的间隔定期检查
- 自动处理 CancelledError

**`_check_and_notify_release()`** - 检查并通知新版本
- 获取 Release 信息
- 过滤公测版（可配置）
- 版本去重
- 格式化通知消息
- 群发到所有被管理群

**`_send_group_message_direct()`** - 直接向群发送消息
- 使用 MessageChain API
- 不依赖 event 对象
- 支持后台任务调用

**`terminate()`** - 资源清理增强
- 取消后台检查任务
- 关闭 aiohttp session

### _conf_schema.json 新增配置项

```json
{
  "maante_check_enabled": {
    "description": "是否启用 MaaNTE Release 更新检查。",
    "type": "bool",
    "default": false
  },
  "maante_check_interval": {
    "description": "MaaNTE Release 检查间隔（秒）。",
    "type": "int",
    "default": 3600
  },
  "maante_notify_prerelease": {
    "description": "是否通知 MaaNTE 公测版（prerelease）更新。",
    "type": "bool",
    "default": true
  },
  "maante_custom_message": {
    "description": "MaaNTE 更新通知的自定义消息。",
    "type": "text",
    "default": ""
  },
  "maante_mirror_url": {
    "description": "GitHub API 镜像站地址。",
    "type": "string",
    "default": "https://gh-proxy.com"
  }
}
```

### README.md 更新

1. **功能列表**：添加 "MaaNTE Release 监控" 说明
2. **配置示例**：添加 5 个新配置项的示例值
3. **指令表**：添加 `/gm maante check` 和 `/gm maante status`
4. **新增章节**："MaaNTE Release 监控" 详细说明
   - 配置说明
   - 通知格式
   - 手动检查方法

### requirements.txt 新建

```
aiohttp>=3.8.0
```

### COMMAND_DESCRIPTIONS 更新

添加两条新指令说明：
```python
("/gm maante check", "立即检查 MaaNTE 最新 Release。"),
("/gm maante status", "查看 MaaNTE Release 监控状态。"),
```

## 设计特点

1. **遵循项目架构**：完全符合"控制群 → 被管理群"的设计模式
2. **异步非阻塞**：后台任务不影响主命令处理
3. **优雅降级**：网络失败时记录日志但不中断服务
4. **资源管理**：正确清理 aiohttp session 和 asyncio task
5. **灵活配置**：支持间隔、版本过滤、自定义消息、镜像站等多维度配置
6. **版本去重**：记录上次通知版本，避免重复推送
7. **镜像加速**：使用 gh-proxy.com 提升国内访问速度
