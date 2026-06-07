import json
import shlex
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


PLUGIN_NAME = "astrbot_plugin_maante_group_management"


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

    @filter.command("gm")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def group_management(self, event: AstrMessageEvent):
        """跨群管理指令入口。"""
        event.stop_event()

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
        target = self._resolve_target(args[0])
        message = " ".join(args[1:]).strip()
        if not message:
            raise CommandError("发送内容不能为空。")

        await self._call_onebot(
            event,
            "send_group_msg",
            group_id=target.group_id,
            message=message,
        )
        return f"已向 {target.display_name} 发送消息。"

    async def _cmd_at_all(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm atall <目标> <内容>")
        target = self._resolve_target(args[0])
        message = " ".join(args[1:]).strip()
        if not message:
            raise CommandError("@全员消息内容不能为空。")

        await self._call_onebot(
            event,
            "send_group_msg",
            group_id=target.group_id,
            message=[
                {"type": "at", "data": {"qq": "all"}},
                {"type": "text", "data": {"text": f" {message}"}},
            ],
        )
        return f"已向 {target.display_name} 发送 @全员消息。"

    async def _cmd_notice(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm notice <目标> <公告内容>")
        target = self._resolve_target(args[0])
        content = " ".join(args[1:]).strip()
        if not content:
            raise CommandError("公告内容不能为空。")

        await self._call_onebot(
            event,
            "_send_group_notice",
            group_id=target.group_id,
            content=content,
        )
        return f"已向 {target.display_name} 发布群公告。"

    async def _cmd_mute(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm mute <目标> <QQ号> <分钟>")
        target = self._resolve_target(args[0])
        user_id = self._parse_qq(args[1])
        minutes = self._parse_positive_int(args[2], "禁言分钟数")
        duration = minutes * 60

        await self._call_onebot(
            event,
            "set_group_ban",
            group_id=target.group_id,
            user_id=user_id,
            duration=duration,
        )
        return f"已在 {target.display_name} 禁言 {user_id} {minutes} 分钟。"

    async def _cmd_unmute(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm unmute <目标> <QQ号>")
        target = self._resolve_target(args[0])
        user_id = self._parse_qq(args[1])

        await self._call_onebot(
            event,
            "set_group_ban",
            group_id=target.group_id,
            user_id=user_id,
            duration=0,
        )
        return f"已在 {target.display_name} 解除 {user_id} 的禁言。"

    async def _cmd_kick(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm kick <目标> <QQ号> [reject]")
        target = self._resolve_target(args[0])
        user_id = self._parse_qq(args[1])
        reject = len(args) >= 3 and args[2].lower() in {"reject", "true", "yes", "1", "拒绝"}

        await self._call_onebot(
            event,
            "set_group_kick",
            group_id=target.group_id,
            user_id=user_id,
            reject_add_request=reject,
        )
        reject_text = "，并拒绝再次入群" if reject else ""
        return f"已从 {target.display_name} 踢出 {user_id}{reject_text}。"

    async def _cmd_whole_ban(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 2, "用法：/gm wholeban <目标> on|off")
        target = self._resolve_target(args[0])
        enable = self._parse_bool(args[1], "全员禁言开关")

        await self._call_onebot(
            event,
            "set_group_whole_ban",
            group_id=target.group_id,
            enable=enable,
        )
        return f"已{'开启' if enable else '关闭'} {target.display_name} 的全员禁言。"

    async def _cmd_card(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm card <目标> <QQ号> <群名片>")
        target = self._resolve_target(args[0])
        user_id = self._parse_qq(args[1])
        card = " ".join(args[2:]).strip()
        if not card:
            raise CommandError("群名片不能为空。")

        await self._call_onebot(
            event,
            "set_group_card",
            group_id=target.group_id,
            user_id=user_id,
            card=card,
        )
        return f"已在 {target.display_name} 设置 {user_id} 的群名片。"

    async def _cmd_admin(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 3, "用法：/gm admin <目标> <QQ号> on|off")
        target = self._resolve_target(args[0])
        user_id = self._parse_qq(args[1])
        enable = self._parse_bool(args[2], "管理员开关")

        await self._call_onebot(
            event,
            "set_group_admin",
            group_id=target.group_id,
            user_id=user_id,
            enable=enable,
        )
        return f"已在 {target.display_name} {'设置' if enable else '取消'} {user_id} 的管理员权限。"

    async def _cmd_info(self, event: AstrMessageEvent, args: list[str]) -> str:
        self._require_args(args, 1, "用法：/gm info <目标>")
        target = self._resolve_target(args[0])
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
        return (
            f"{target.display_name}\n"
            f"群号：{target.group_id}\n"
            f"群名：{group_name}\n"
            f"人数：{member_count}/{max_member_count}"
        )

    async def _call_onebot(self, event: AstrMessageEvent, action: str, **payload: Any) -> Any:
        client = getattr(event, "bot", None)
        if client is None or not hasattr(client, "api"):
            raise CommandError("当前事件没有可用的 OneBot 客户端，请确认正在通过 NapCat/aiocqhttp 接入。")

        logger.info(f"{PLUGIN_NAME} call {action}: {payload}")
        return await client.api.call_action(action, **payload)

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

    def _resolve_target(self, raw_target: str) -> "ManagedTarget":
        target_aliases = self._target_aliases()
        target_value = str(target_aliases.get(raw_target, raw_target)).strip()
        group_id = self._extract_group_id(target_value)

        if not group_id:
            raise CommandError(f"无法识别目标群：{raw_target}")

        if not self._is_managed_target(target_value, group_id):
            raise CommandError(
                f"目标群不在 managed_targets 白名单中：{raw_target}\n"
                "请在插件配置中加入该群的 UMO 或群号。"
            )

        display_name = raw_target
        if raw_target == target_value:
            display_name = f"群 {group_id}"
        else:
            display_name = f"{raw_target}({group_id})"

        return ManagedTarget(group_id=group_id, display_name=display_name)

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
        return "\n".join(lines)

    def _alias_for_value(self, aliases: dict[str, Any], value: str, group_id: str) -> str:
        for alias, alias_value in aliases.items():
            alias_value = str(alias_value).strip()
            if alias_value == value or self._extract_group_id(alias_value) == group_id:
                return str(alias)
        return ""

    def _target_aliases(self) -> dict[str, Any]:
        value = self.config.get("target_aliases", {}) or {}
        if isinstance(value, dict):
            return value

        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise CommandError(f"target_aliases 不是合法 JSON：{exc}") from exc
            if not isinstance(parsed, dict):
                raise CommandError("target_aliases 必须是 JSON 对象，例如 {\"main\": \"123456789\"}。")
            return parsed

        return {}

    def _extract_group_id(self, value: str) -> str:
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
        return (
            "UMO 群管理插件\n"
            f"当前 UMO：{event.unified_msg_origin}\n"
            f"当前群号：{event.get_group_id() or '-'}\n\n"
            "指令：\n"
            "/gm sid\n"
            "/gm list\n"
            "/gm info <目标>\n"
            "/gm send <目标> <内容>\n"
            "/gm atall <目标> <内容>\n"
            "/gm notice <目标> <公告内容>\n"
            "/gm mute <目标> <QQ号> <分钟>\n"
            "/gm unmute <目标> <QQ号>\n"
            "/gm kick <目标> <QQ号> [reject]\n"
            "/gm wholeban <目标> on|off\n"
            "/gm card <目标> <QQ号> <群名片>\n"
            "/gm admin <目标> <QQ号> on|off\n\n"
            "目标可以是 target_aliases 里的别名、群号，或 aiocqhttp:GroupMessage:群号。"
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

    async def terminate(self):
        logger.info(f"{PLUGIN_NAME} terminated")


class ManagedTarget:
    def __init__(self, group_id: str, display_name: str):
        self.group_id = group_id
        self.display_name = display_name


class CommandError(Exception):
    pass
