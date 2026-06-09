import asyncio
import json
import shlex
from datetime import datetime
from typing import Any, Optional, Dict

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


PLUGIN_NAME = "astrbot_plugin_maante_group_management"

COMMAND_DESCRIPTIONS = [
    ("/gm help", "显示本帮助和所有子指令说明。"),
    ("/gm sid", "查看当前控制群的 UMO、群号、平台和发送者 QQ。"),
    ("/gm list", "列出已配置的被管理目标群和目标别名。"),
    ("/gm info <目标>", "查询目标群信息；目标可以是单群或多群别名。"),
    ("/gm send <目标> <内容>", "向目标群发送普通文本消息。"),
    ("/gm atall <目标> <内容>", "向目标群发送 @全员 消息。"),
    ("/gm notice <目标> <公告内容>", "向目标群发布群公告。"),
    ("/gm mute <目标> <QQ号> <分钟>", "在目标群禁言指定 QQ 号。"),
    ("/gm unmute <目标> <QQ号>", "在目标群解除指定 QQ 号的禁言。"),
    ("/gm kick <目标> <QQ号> [reject]", "从目标群踢出指定 QQ 号；加 reject 会拒绝再次入群。"),
    ("/gm wholeban <目标> on|off", "开启或关闭目标群全员禁言。"),
    ("/gm card <目标> <QQ号> <群名片>", "设置指定 QQ 号在目标群的群名片。"),
    ("/gm admin <目标> <QQ号> on|off", "设置或取消指定 QQ 号在目标群的管理员权限。"),
    ("/gm maante check", "立即检查 MaaNTE 最新 Release。"),
    ("/gm maante status", "查看 MaaNTE Release 监控状态。"),
    ("/gm maante push <目标> [版本]", "手动推送 MaaNTE Release 信息到目标群；不指定版本则推送最新版本。"),
]


@register(
    PLUGIN_NAME,
    "Watanabehato",
    "在一个控制群中管理 UMO 白名单内的 NapCat QQ 群",
    "0.1.0",
)
class MaanteGroupManagementPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.last_notified_version = None
        self.check_task = None
        self.session = None
        self.bot_client = None  # 保存 bot 客户端引用

        if self.config.get("maante_check_enabled", False):
            self.check_task = asyncio.create_task(self._start_release_check_loop())

    @filter.command("gm")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def group_management(self, event: AstrMessageEvent):
        """跨群管理指令入口，发送 /gm help 查看子指令说明。"""
        event.stop_event()

        # 保存 bot 客户端引用，供后台任务使用
        if self.bot_client is None and hasattr(event, "bot"):
            self.bot_client = event.bot

        if not self._is_authorized(event):
            yield event.plain_result(
                "无权限使用 /gm。\n"
                "请确认当前群在 controller_umos 中，并且发送者在 operator_user_ids 中；"
                "如果想允许控制群全员使用，请显式开启 allow_all_users_in_controller。"
            )
            return

        try:
            args = self._extract_args(event.message_str)
        except ValueError as exc:
            yield event.plain_result(f"参数解析失败：{exc}")
            return

        if not args or args[0] in {"help", "帮助", "菜单"}:
            yield event.plain_result(self._help_text(event))
            return

        command = args[0].lower()
        try:
            if command in {"sid", "whoami"}:
                yield event.plain_result(self._sid_text(event))
            elif command in {"list", "ls", "列表"}:
                yield event.plain_result(self._target_list_text())
            elif command == "maante":
                yield event.plain_result(await self._cmd_maante(event, args[1:]))
            elif command in {"send", "say", "通知"}:
                yield event.plain_result(await self._cmd_send(event, args[1:]))
            elif command in {"atall", "all", "全员消息"}:
                yield event.plain_result(await self._cmd_at_all(event, args[1:]))
            elif command in {"notice", "announce", "公告"}:
                yield event.plain_result(await self._cmd_notice(event, args[1:]))
            elif command in {"mute", "ban", "禁言"}:
                yield event.plain_result(await self._cmd_mute(event, args[1:]))
            elif command in {"unmute", "解禁"}:
                yield event.plain_result(await self._cmd_unmute(event, args[1:]))
            elif command in {"kick", "踢"}:
                yield event.plain_result(await self._cmd_kick(event, args[1:]))
            elif command in {"wholeban", "allban", "全员禁言"}:
                yield event.plain_result(await self._cmd_whole_ban(event, args[1:]))
            elif command in {"card", "名片"}:
                yield event.plain_result(await self._cmd_card(event, args[1:]))
            elif command in {"admin", "管理员"}:
                yield event.plain_result(await self._cmd_admin(event, args[1:]))
            elif command in {"info", "群信息"}:
                yield event.plain_result(await self._cmd_info(event, args[1:]))
            else:
                yield event.plain_result(f"未知子指令：{args[0]}\n发送 /gm help 查看用法。")
        except CommandError as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:
            logger.exception(f"{PLUGIN_NAME} command failed: {exc}")
            yield event.plain_result(f"执行失败：{exc}")

    async def _cmd_send(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm send <目标> <内容>")
        targets = self._resolve_targets(args[0])
        message = " ".join(args[1:]).strip()
        if not message:
            raise CommandError("发送内容不能为空。")

        for target in targets:
            await self._call_onebot(
                event,
                "send_group_msg",
                group_id=target.group_id,
                message=message,
            )
        return f"已向 {self._targets_text(targets)} 发送消息。"

    async def _cmd_at_all(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm atall <目标> <内容>")
        targets = self._resolve_targets(args[0])
        message = " ".join(args[1:]).strip()
        if not message:
            raise CommandError("@全员消息内容不能为空。")

        for target in targets:
            await self._call_onebot(
                event,
                "send_group_msg",
                group_id=target.group_id,
                message=[
                    {"type": "at", "data": {"qq": "all"}},
                    {"type": "text", "data": {"text": f" {message}"}},
                ],
            )
        return f"已向 {self._targets_text(targets)} 发送 @全员消息。"

    async def _cmd_notice(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm notice <目标> <公告内容>")
        targets = self._resolve_targets(args[0])
        content = " ".join(args[1:]).strip()
        if not content:
            raise CommandError("公告内容不能为空。")

        for target in targets:
            await self._call_onebot(
                event,
                "_send_group_notice",
                group_id=target.group_id,
                content=content,
            )
        return f"已向 {self._targets_text(targets)} 发布群公告。"

    async def _cmd_mute(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm mute <目标> <QQ号> <分钟>")
        targets = self._resolve_targets(args[0])
        user_id = self._parse_qq(args[1])
        minutes = self._parse_positive_int(args[2], "禁言分钟数")
        duration = minutes * 60

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_ban",
                group_id=target.group_id,
                user_id=user_id,
                duration=duration,
            )
        return f"已在 {self._targets_text(targets)} 禁言 {user_id} {minutes} 分钟。"

    async def _cmd_unmute(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm unmute <目标> <QQ号>")
        targets = self._resolve_targets(args[0])
        user_id = self._parse_qq(args[1])

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_ban",
                group_id=target.group_id,
                user_id=user_id,
                duration=0,
            )
        return f"已在 {self._targets_text(targets)} 解除 {user_id} 的禁言。"

    async def _cmd_kick(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm kick <目标> <QQ号> [reject]")
        targets = self._resolve_targets(args[0])
        user_id = self._parse_qq(args[1])
        reject = len(args) >= 3 and args[2].lower() in {"reject", "true", "yes", "1", "拒绝"}

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_kick",
                group_id=target.group_id,
                user_id=user_id,
                reject_add_request=reject,
            )
        reject_text = "，并拒绝再次入群" if reject else ""
        return f"已从 {self._targets_text(targets)} 踢出 {user_id}{reject_text}。"

    async def _cmd_whole_ban(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm wholeban <目标> on|off")
        targets = self._resolve_targets(args[0])
        enable = self._parse_bool(args[1], "全员禁言开关")

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_whole_ban",
                group_id=target.group_id,
                enable=enable,
            )
        return f"已{'开启' if enable else '关闭'} {self._targets_text(targets)} 的全员禁言。"

    async def _cmd_card(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm card <目标> <QQ号> <群名片>")
        targets = self._resolve_targets(args[0])
        user_id = self._parse_qq(args[1])
        card = " ".join(args[2:]).strip()
        if not card:
            raise CommandError("群名片不能为空。")

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_card",
                group_id=target.group_id,
                user_id=user_id,
                card=card,
            )
        return f"已在 {self._targets_text(targets)} 设置 {user_id} 的群名片。"

    async def _cmd_admin(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm admin <目标> <QQ号> on|off")
        targets = self._resolve_targets(args[0])
        user_id = self._parse_qq(args[1])
        enable = self._parse_bool(args[2], "管理员开关")

        for target in targets:
            await self._call_onebot(
                event,
                "set_group_admin",
                group_id=target.group_id,
                user_id=user_id,
                enable=enable,
            )
        return f"已在 {self._targets_text(targets)} {'设置' if enable else '取消'} {user_id} 的管理员权限。"

    async def _cmd_info(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 1, "用法：/gm info <目标>")
        targets = self._resolve_targets(args[0])
        lines = []
        for target in targets:
            info = await self._call_onebot(
                event,
                "get_group_info",
                group_id=target.group_id,
                no_cache=True,
            )

            data = info.get("data", info) if isinstance(info, dict) else {}
            group_name = data.get("group_name", "未知群名")
            member_count = data.get("member_count", "?")
            max_member_count = data.get("max_member_count", "?")
            lines.append(
                f"{target.display_name}\n"
                f"群号：{target.group_id}\n"
                f"群名：{group_name}\n"
                f"人数：{member_count}/{max_member_count}"
            )
        return "\n\n".join(lines)

    async def _cmd_maante(self, event: AstrMessageEvent, args: list[str]) -> str:
        if not args:
            raise CommandError("用法：/gm maante check|status|push")

        subcommand = args[0].lower()
        if subcommand in {"check", "检查"}:
            release = await self._fetch_latest_release()
            if not release:
                return "未能获取 MaaNTE Release 信息。"

            version = release.get("tag_name", "未知版本")
            name = release.get("name", "")
            is_prerelease = release.get("prerelease", False)
            published_at = release.get("published_at", "")

            release_type = "公测版" if is_prerelease else "正式版"
            return (
                f"MaaNTE 最新 Release：\n"
                f"版本：{version} ({release_type})\n"
                f"标题：{name}\n"
                f"发布时间：{published_at}"
            )
        elif subcommand in {"status", "状态"}:
            check_enabled = self.config.get("maante_check_enabled", False)
            check_interval = self.config.get("maante_check_interval", 3600)
            last_version = self.last_notified_version or "未知"
            task_running = self.check_task is not None and not self.check_task.done()

            return (
                f"MaaNTE Release 监控状态：\n"
                f"监控开关：{'已开启' if check_enabled else '已关闭'}\n"
                f"检查间隔：{check_interval} 秒\n"
                f"后台任务：{'运行中' if task_running else '未运行'}\n"
                f"上次通知版本：{last_version}"
            )
        elif subcommand in {"push", "推送"}:
            return await self._cmd_maante_push(event, args[1:])
        else:
            raise CommandError("未知子指令，用法：/gm maante check|status|push")

    async def _cmd_maante_push(self, event: AstrMessageEvent, args: list[str]) -> str:
        """手动推送 MaaNTE Release 信息到目标群"""
        if not args:
            raise CommandError("用法：/gm maante push <目标> [版本]\n目标可以是群号、别名或 UMO；不指定版本则推送最新版本。")

        target_arg = args[0]
        version_arg = args[1] if len(args) > 1 else None

        # 解析目标群
        targets = self._resolve_targets(target_arg)

        # 获取 Release 信息
        if version_arg:
            release = await self._fetch_release_by_version(version_arg)
            if not release:
                return f"未找到版本 {version_arg} 的 Release 信息。"
        else:
            release = await self._fetch_latest_release()
            if not release:
                return "未能获取 MaaNTE Release 信息。"

        # 构建推送消息
        version = release.get("tag_name", "未知版本")
        name = release.get("name", "")
        body = release.get("body", "")
        published_at = release.get("published_at", "")
        is_prerelease = release.get("prerelease", False)

        release_type = "公测版" if is_prerelease else "正式版"
        custom_message = self.config.get("maante_custom_message", "")

        message_parts = [f"MaaNTE {release_type}更新通知"]
        if custom_message:
            message_parts.append(custom_message)
        message_parts.extend([
            f"\n版本：{version}",
            f"标题：{name}",
            f"发布时间：{published_at}",
            f"\nChangelog：\n{body}"
        ])

        message = "\n".join(message_parts)

        # 推送到目标群
        success_count = 0
        failed_targets = []

        for target in targets:
            try:
                await self._send_group_message_via_onebot(event, target.group_id, message)
                success_count += 1
                logger.info(f"{PLUGIN_NAME} manually pushed release {version} to group {target.group_id}")
            except Exception as exc:
                failed_targets.append(target.display_name)
                logger.error(f"{PLUGIN_NAME} failed to push release to {target.group_id}: {exc}")

        result_parts = [f"已向 {success_count} 个群推送 {version} 的 Release 信息。"]
        if failed_targets:
            result_parts.append(f"推送失败的群：{', '.join(failed_targets)}")

        return "\n".join(result_parts)

    async def _send_group_message_via_onebot(self, event: AstrMessageEvent, group_id: str, message: str):
        """通过 OneBot API 直接发送群消息"""
        await self._call_onebot(
            event,
            "send_group_msg",
            group_id=int(group_id),
            message=message,
        )

    async def _call_onebot(self, event: AstrMessageEvent, action: str, **payload: Any) -> Any:
        client = getattr(event, "bot", None)
        if client is None or not hasattr(client, "api"):
            raise CommandError("当前事件没有可用的 OneBot 客户端，请确认正在通过 NapCat/aiocqhttp 接入。")

        logger.info(f"{PLUGIN_NAME} call {action}: {payload}")
        try:
            return await client.api.call_action(action, **payload)
        except Exception as exc:
            if self._should_ignore_send_timeout(action, exc):
                logger.warning(
                    f"{PLUGIN_NAME} ignored NapCat send timeout for {action}; "
                    f"message may already be sent: {exc}"
                )
                return {"status": "ok", "retcode": 0, "message": "ignored NapCat send timeout"}
            raise

    def _should_ignore_send_timeout(self, action: str, exc: Exception) -> bool:
        if not self.config.get("ignore_send_timeout_1200", True):
            return False

        send_actions = {"send_group_msg", "send_msg", "_send_group_notice"}
        if action not in send_actions:
            return False

        retcode = getattr(exc, "retcode", None)
        if retcode != 1200:
            return False

        message = str(exc)
        return "Timeout" in message and "sendMsg" in message

    def _is_authorized(self, event: AstrMessageEvent) -> bool:
        controller_umos = self._string_set(self.config.get("controller_umos", []))
        current_group_id = event.get_group_id() or ""
        current_candidates = {event.unified_msg_origin}
        if current_group_id:
            current_candidates.add(str(current_group_id))

        if not controller_umos or controller_umos.isdisjoint(current_candidates):
            return False

        operator_user_ids = self._string_set(self.config.get("operator_user_ids", []))
        if operator_user_ids:
            return str(event.get_sender_id()) in operator_user_ids

        return bool(self.config.get("allow_all_users_in_controller", False))

    def _resolve_targets(self, raw_target: str) -> list["ManagedTarget"]:
        target_aliases = self._target_aliases()
        target_values = self._target_values(raw_target, target_aliases)
        targets: list[ManagedTarget] = []
        seen_group_ids: set[str] = set()

        for target_value in target_values:
            group_id = self._extract_group_id(target_value)

            if not group_id:
                raise CommandError(f"无法识别目标群：{target_value}")

            if group_id in seen_group_ids:
                continue

            if not self._is_managed_target(target_value, group_id):
                raise CommandError(
                    f"目标群不在 managed_targets 白名单中：{target_value}\n"
                    "请在插件配置中加入该群的 UMO 或群号。"
                )

            targets.append(
                ManagedTarget(
                    group_id=group_id,
                    display_name=self._target_display_name(raw_target, target_value, group_id),
                )
            )
            seen_group_ids.add(group_id)

        if not targets:
            raise CommandError(f"目标为空：{raw_target}")

        return targets

    def _target_values(self, raw_target: str, aliases: dict[str, Any]) -> list[str]:
        alias_value = aliases.get(raw_target, raw_target)
        if isinstance(alias_value, list):
            values = [str(item).strip() for item in alias_value if str(item).strip()]
            if not values:
                raise CommandError(f"别名 {raw_target} 的目标群列表为空。")
            return values

        value = str(alias_value).strip()
        if not value:
            raise CommandError(f"目标为空：{raw_target}")
        return [value]

    def _target_display_name(self, raw_target: str, target_value: str, group_id: str) -> str:
        if raw_target == target_value:
            return f"群 {group_id}"
        return f"{raw_target}({group_id})"

    def _targets_text(self, targets: list["ManagedTarget"]) -> str:
        return "、".join(target.display_name for target in targets)

    def _is_managed_target(self, target_value: str, group_id: str) -> bool:
        managed_targets = self._string_set(self.config.get("managed_targets", []))
        if not managed_targets:
            return False

        target_umo = self._group_umo(group_id)
        allowed = {target_value, group_id, target_umo}
        for item in managed_targets:
            allowed.add(self._extract_group_id(item))

        return not managed_targets.isdisjoint(allowed)

    def _target_list_text(self) -> str:
        managed_targets = self._string_list(self.config.get("managed_targets", []))
        target_aliases = self._target_aliases()

        if not managed_targets:
            return "managed_targets 为空，目前不会允许管理任何目标群。"

        lines = ["已配置的被管理目标："]
        for item in managed_targets:
            group_id = self._extract_group_id(item) or "?"
            alias = self._alias_for_value(target_aliases, item, group_id)
            prefix = f"{alias} -> " if alias else ""
            lines.append(f"- {prefix}{item} (群号 {group_id})")
        return "\n".join(lines) + self._alias_list_text(target_aliases)

    def _alias_for_value(self, aliases: dict[str, Any], value: str, group_id: str) -> str:
        for alias, alias_value in aliases.items():
            alias_values = alias_value if isinstance(alias_value, list) else [alias_value]
            for item in alias_values:
                item = str(item).strip()
                if item == value or self._extract_group_id(item) == group_id:
                    return str(alias)
        return ""

    def _alias_list_text(self, aliases: dict[str, Any]) -> str:
        if not aliases:
            return ""

        lines = ["", "已配置的目标别名："]
        for alias, alias_value in aliases.items():
            if isinstance(alias_value, list):
                group_ids = [self._extract_group_id(item) or str(item) for item in alias_value]
                lines.append(f"- {alias} -> {', '.join(group_ids)}")
            else:
                group_id = self._extract_group_id(alias_value) or str(alias_value)
                lines.append(f"- {alias} -> {group_id}")
        return "\n".join(lines)

    def _validate_aliases(self, aliases: dict[str, Any]) -> dict[str, Any]:
        for alias, alias_value in aliases.items():
            if isinstance(alias_value, list):
                if not alias_value:
                    raise CommandError(f"target_aliases.{alias} 不能为空列表。")
                continue
            if isinstance(alias_value, str):
                continue
            raise CommandError(
                f"target_aliases.{alias} 必须是字符串或字符串数组，"
                "例如 \"123456789\" 或 [\"123456789\", \"987654321\"]。"
            )
        return aliases

    def _target_aliases(self) -> dict[str, Any]:
        value = self.config.get("target_aliases", {}) or {}
        if isinstance(value, dict):
            return self._validate_aliases(value)

        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise CommandError(f"target_aliases 不是合法 JSON：{exc}") from exc
            if not isinstance(parsed, dict):
                raise CommandError("target_aliases 必须是 JSON 对象，例如 {\"main\": \"123456789\"}。")
            return self._validate_aliases(parsed)

        return {}

    def _extract_group_id(self, value: Any) -> str:
        value = str(value).strip()
        if value.isdigit():
            return value

        parts = value.split(":", 2)
        if len(parts) == 3 and parts[1].lower() == "groupmessage" and parts[2].isdigit():
            return parts[2]

        return ""

    def _group_umo(self, group_id: str) -> str:
        platform_id = str(self.config.get("platform_id", "aiocqhttp")).strip() or "aiocqhttp"
        return f"{platform_id}:GroupMessage:{group_id}"

    def _extract_args(self, message: str) -> list[str]:
        text = (message or "").strip()
        if text.startswith("/gm"):
            text = text[3:].strip()
        elif text.lower().startswith("gm"):
            text = text[2:].strip()

        return shlex.split(text)

    def _help_text(self, event: AstrMessageEvent) -> str:
        command_lines = "\n".join(f"{usage} - {description}" for usage, description in COMMAND_DESCRIPTIONS)
        return (
            "UMO 群管理插件\n"
            f"当前 UMO：{event.unified_msg_origin}\n"
            f"当前群号：{event.get_group_id() or '-'}\n\n"
            f"指令：\n{command_lines}\n\n"
            "目标可以是 target_aliases 里的别名、群号，或 aiocqhttp:GroupMessage:群号；"
            "别名可以对应单个群或多个群。"
        )

    def _sid_text(self, event: AstrMessageEvent) -> str:
        return (
            "当前会话信息：\n"
            f"UMO：{event.unified_msg_origin}\n"
            f"平台：{event.get_platform_name()}\n"
            f"群号：{event.get_group_id() or '-'}\n"
            f"发送者：{event.get_sender_id()}"
        )

    def _require_args(self, args: list[str], minimum: int, usage: str) -> None:
        if len(args) < minimum:
            raise CommandError(usage)

    def _parse_qq(self, raw: str) -> str:
        value = str(raw).strip()
        if value.startswith("@"):
            value = value[1:]
        if not value.isdigit():
            raise CommandError(f"QQ号格式不正确：{raw}")
        return value

    def _parse_positive_int(self, raw: str, label: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise CommandError(f"{label} 必须是整数：{raw}") from exc
        if value <= 0:
            raise CommandError(f"{label} 必须大于 0。")
        return value

    def _parse_bool(self, raw: str, label: str) -> bool:
        value = str(raw).lower()
        if value in {"on", "true", "yes", "1", "enable", "开", "开启"}:
            return True
        if value in {"off", "false", "no", "0", "disable", "关", "关闭"}:
            return False
        raise CommandError(f"{label} 只能是 on 或 off。")

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [line.strip() for line in value.splitlines() if line.strip()]
        return []

    def _string_set(self, value: Any) -> set[str]:
        return set(self._string_list(value))

    async def _fetch_latest_release(self) -> Optional[Dict[str, Any]]:
        if self.session is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/vnd.github.v3+json"
            }
            self.session = aiohttp.ClientSession(headers=headers)

        mirror_url = self.config.get("maante_mirror_url", "")
        notify_prerelease = self.config.get("maante_notify_prerelease", True)

        # 使用 /releases 而不是 /releases/latest 来获取包括 prerelease 的版本
        urls = [
            f"{mirror_url}/https://api.github.com/repos/1bananachicken/MaaNTE/releases" if mirror_url else None,
            "https://api.github.com/repos/1bananachicken/MaaNTE/releases",
            "https://ghproxy.net/https://api.github.com/repos/1bananachicken/MaaNTE/releases",
        ]

        for api_url in urls:
            if api_url is None:
                continue
            try:
                async with self.session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        releases = await resp.json()
                        if not releases or not isinstance(releases, list):
                            continue

                        # 根据配置过滤：如果通知 prerelease，返回最新的任意版本；否则只返回正式版
                        for release in releases:
                            is_prerelease = release.get("prerelease", False)
                            if notify_prerelease or not is_prerelease:
                                logger.info(f"{PLUGIN_NAME} fetched release from: {api_url}")
                                return release

                        logger.debug(f"{PLUGIN_NAME} no matching release found in {api_url}")
                        continue
                    logger.debug(f"{PLUGIN_NAME} fetch failed from {api_url}: HTTP {resp.status}")
            except Exception as exc:
                logger.debug(f"{PLUGIN_NAME} fetch error from {api_url}: {exc}")
                continue

        logger.warning(f"{PLUGIN_NAME} failed to fetch MaaNTE release from all sources")
        return None

    async def _fetch_release_by_version(self, version: str) -> Optional[Dict[str, Any]]:
        """根据版本号获取指定的 Release"""
        if self.session is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/vnd.github.v3+json"
            }
            self.session = aiohttp.ClientSession(headers=headers)

        # 规范化版本号，确保有 v 前缀
        if not version.startswith("v"):
            version = f"v{version}"

        mirror_url = self.config.get("maante_mirror_url", "")

        urls = [
            f"{mirror_url}/https://api.github.com/repos/1bananachicken/MaaNTE/releases" if mirror_url else None,
            "https://api.github.com/repos/1bananachicken/MaaNTE/releases",
            "https://ghproxy.net/https://api.github.com/repos/1bananachicken/MaaNTE/releases",
        ]

        for api_url in urls:
            if api_url is None:
                continue
            try:
                async with self.session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        releases = await resp.json()
                        if not releases or not isinstance(releases, list):
                            continue

                        # 查找匹配的版本
                        for release in releases:
                            tag_name = release.get("tag_name", "")
                            if tag_name == version:
                                logger.info(f"{PLUGIN_NAME} fetched release {version} from: {api_url}")
                                return release

                        logger.debug(f"{PLUGIN_NAME} version {version} not found in {api_url}")
                        continue
                    logger.debug(f"{PLUGIN_NAME} fetch failed from {api_url}: HTTP {resp.status}")
            except Exception as exc:
                logger.debug(f"{PLUGIN_NAME} fetch error from {api_url}: {exc}")
                continue

        logger.warning(f"{PLUGIN_NAME} failed to fetch release {version} from all sources")
        return None

    async def _start_release_check_loop(self):
        if not self.config.get("maante_check_enabled", False):
            logger.info(f"{PLUGIN_NAME} MaaNTE release check is disabled")
            return

        check_interval = self.config.get("maante_check_interval", 3600)
        logger.info(f"{PLUGIN_NAME} starting MaaNTE release check loop, interval: {check_interval}s")

        while True:
            try:
                await asyncio.sleep(check_interval)
                await self._check_and_notify_release()
            except asyncio.CancelledError:
                logger.info(f"{PLUGIN_NAME} release check loop cancelled")
                break
            except Exception as exc:
                logger.exception(f"{PLUGIN_NAME} release check loop error: {exc}")

    async def _check_and_notify_release(self):
        release = await self._fetch_latest_release()
        if not release:
            return

        version = release.get("tag_name", "")
        is_prerelease = release.get("prerelease", False)
        name = release.get("name", "")
        body = release.get("body", "")
        published_at = release.get("published_at", "")

        notify_prerelease = self.config.get("maante_notify_prerelease", True)
        if is_prerelease and not notify_prerelease:
            logger.debug(f"{PLUGIN_NAME} skipping prerelease notification: {version}")
            return

        if self.last_notified_version == version:
            return

        logger.info(f"{PLUGIN_NAME} new MaaNTE release detected: {version}")
        self.last_notified_version = version

        release_type = "公测版" if is_prerelease else "正式版"
        custom_message = self.config.get("maante_custom_message", "")

        message_parts = [f"MaaNTE {release_type}更新通知"]
        if custom_message:
            message_parts.append(custom_message)
        message_parts.extend([
            f"\n版本：{version}",
            f"标题：{name}",
            f"发布时间：{published_at}",
            f"\nChangelog：\n{body}"
        ])

        message = "\n".join(message_parts)

        managed_targets = self._string_list(self.config.get("managed_targets", []))
        if not managed_targets:
            logger.warning(f"{PLUGIN_NAME} no managed targets configured, skipping notification")
            return

        for target_value in managed_targets:
            group_id = self._extract_group_id(target_value)
            if not group_id:
                continue

            try:
                await self._send_group_message_direct(group_id, message)
                logger.info(f"{PLUGIN_NAME} sent release notification to group {group_id}")
            except Exception as exc:
                logger.error(f"{PLUGIN_NAME} failed to send release notification to {group_id}: {exc}")

    async def _send_group_message_direct(self, group_id: str, message: str):
        """直接发送群消息（用于后台任务，无 event 对象）"""
        if self.bot_client is None:
            raise CommandError("Bot 客户端未初始化，请先使用 /gm 命令触发插件初始化")

        if not hasattr(self.bot_client, "api"):
            raise CommandError("Bot 客户端没有可用的 API")

        logger.info(f"{PLUGIN_NAME} call send_group_msg: group_id={group_id}")
        try:
            await self.bot_client.api.call_action(
                "send_group_msg",
                group_id=int(group_id),
                message=message,
            )
        except Exception as exc:
            # 检查是否是 NapCat 的 1200 超时错误
            if self._should_ignore_send_timeout("send_group_msg", exc):
                logger.warning(
                    f"{PLUGIN_NAME} ignored NapCat send timeout for send_group_msg; "
                    f"message may already be sent: {exc}"
                )
                return
            raise

    async def terminate(self):
        if self.check_task is not None and not self.check_task.done():
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass

        if self.session is not None:
            await self.session.close()

        logger.info(f"{PLUGIN_NAME} terminated")


class ManagedTarget:
    def __init__(self, group_id: str, display_name: str):
        self.group_id = group_id
        self.display_name = display_name


class CommandError(Exception):
    pass
