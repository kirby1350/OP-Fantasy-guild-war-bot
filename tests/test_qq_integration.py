"""官方事件和发送 API 边界测试，所有网络调用均模拟。"""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nonebot.adapters.qq import Bot
from nonebot.message import handle_event

from support import event, make_bot
from src.plugins.guild_war import config, database, handlers, services, scheduler
from src.plugins.guild_war.qq_gateway import QQSettings, get_context, is_admin, reply
from src.plugins.guild_war.models import GuildContext


class QQIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = make_bot()
        hp_patch = patch.object(
            config, "BOSS_HP_BY_ROUND", {1: 6_000_000, 40: 10_250_000_000}
        )
        hp_patch.start()
        self.addCleanup(hp_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(self.tmp.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        await database.init_db()

    async def test_official_group_event_dispatch_and_permission(self):
        with patch.object(Bot, "send", AsyncMock()) as send:
            await handle_event(self.bot, event(user_id=222, content="开启工会战"))
            self.assertIsNone(await database.get_boss_status("qq:999:group:100"))
            await handle_event(self.bot, event(content="/开启工会战"))
            self.assertTrue(
                (await database.get_boss_status("qq:999:group:100")).is_active
            )
            await handle_event(self.bot, event(content="报刀 100"))
            self.assertIn("出刀", str(send.await_args.args[1]))
        records = await database.get_user_today_records(
            "qq:999:user:123456", "qq:999:group:100"
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].damage, 100)
        self.assertIsNone(await database.get_boss_status("100"))

    async def test_permissions_and_identity_are_app_scoped(self):
        other = make_bot("888")
        self.assertTrue(await is_admin(self.bot, event()))
        self.assertFalse(await is_admin(other, event()))
        self.assertFalse(await is_admin(self.bot, event(user_id=222)))
        a = await get_context(self.bot, event())
        b = await get_context(other, event())
        self.assertNotEqual(a.group_id, b.group_id)
        self.assertNotEqual(a.user_id, b.user_id)
        with patch.object(handlers, "reply", AsyncMock()) as send:
            await handlers.handle_identity(self.bot, event())
            self.assertIn("999:123456", send.await_args.args[2])

    async def test_image_upload_and_passive_reply_api(self):
        incoming = event()
        with (
            patch.object(
                Bot,
                "post_group_files",
                AsyncMock(return_value=SimpleNamespace(file_info="media-token")),
            ) as upload,
            patch.object(Bot, "post_group_messages", AsyncMock()) as send,
        ):
            await reply(self.bot, incoming, b"image-content")
            self.assertEqual(upload.await_args.kwargs["group_openid"], "100")
            self.assertEqual(upload.await_args.kwargs["file_type"], 1)
            self.assertEqual(upload.await_args.kwargs["file_data"], b"image-content")
            self.assertFalse(upload.await_args.kwargs["srv_send_msg"])
            self.assertEqual(send.await_args.kwargs["msg_id"], incoming.id)
            self.assertEqual(send.await_args.kwargs["msg_seq"], 1)
            self.assertEqual(send.await_args.kwargs["msg_type"], 7)
            self.assertEqual(send.await_args.kwargs["media"].file_info, "media-token")
            await reply(self.bot, incoming, "文字回复")
            self.assertEqual(send.await_args.kwargs["msg_seq"], 2)
            self.assertEqual(send.await_args.kwargs["msg_type"], 0)

    async def test_official_attachment_message_routes_to_homework(self):
        from src.plugins.guild_war import homework

        incoming = event(
            content="设置作业 火队",
            attachments=[
                {"content_type": "image/png", "url": "https://example.com/team.png"}
            ],
        )
        with (
            patch.object(
                homework, "download_image", AsyncMock(return_value=b"saved-image")
            ),
            patch.object(Bot, "send", AsyncMock()),
        ):
            await handle_event(self.bot, incoming)
        self.assertEqual(
            await database.get_homework("qq:999:group:100", "火队"), b"saved-image"
        )

    async def test_chart_uses_safe_filename_for_official_ids(self):
        from src.plugins.guild_war import chart

        ctx = await get_context(self.bot, event())
        await services.handle_start_gw(ctx)
        await services.handle_report_knife(ctx, "1000")
        with patch.object(chart, "OUTPUT_DIR", Path(self.tmp.name) / "charts"):
            image = await services.handle_chart(ctx)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(list((Path(self.tmp.name) / "charts").glob("*.png"))), 1)

    async def test_reminders_disabled_by_default_and_explicit_targets(self):
        with (
            patch.object(scheduler, "get_plugin_config", return_value=QQSettings()),
            patch.object(scheduler, "get_bot") as get_bot,
        ):
            await scheduler.run_reminders()
            get_bot.assert_not_called()
        await database.create_boss_status("qq:999:group:100")
        settings = QQSettings(
            gw_enable_proactive_reminders=True,
            gw_reminder_targets={"999": ["100", "100"]},
        )
        with (
            patch.object(scheduler, "get_plugin_config", return_value=settings),
            patch.object(scheduler, "get_bot", return_value=self.bot),
            patch.object(Bot, "send_to_group", AsyncMock()) as send,
        ):
            await scheduler.run_reminders()
            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[0], "100")
            self.assertNotIn("全员出刀完毕", send.await_args.args[1])
            self.assertNotIn("msg_id", send.await_args.kwargs)

    async def test_service_works_without_adapter_objects(self):
        ctx = GuildContext("test-group", "test-user", "测试")
        await services.handle_start_gw(ctx)
        await services.handle_report_knife(ctx, "1000")
        self.assertIn("测试", await services.handle_progress(ctx))
        self.assertIn("剩余 2 刀", await services.handle_remind(ctx))
        await services.handle_reserve(ctx)
        self.assertIn("已取消", await services.handle_cancel_reserve(ctx))

    async def test_unknown_hp_stops_reports_and_can_be_calibrated(self):
        ctx = await get_context(self.bot, event())
        await services.handle_start_gw(ctx)
        await services.handle_report_knife(ctx, "6000000")
        status = await database.get_boss_status(ctx.group_id)
        self.assertEqual(status.round_num, 2)
        self.assertEqual(status.max_hp, 0)
        self.assertIn("待配置", await services.handle_boss_status(ctx))
        self.assertIn("待配置", await services.handle_report_knife(ctx, "100"))
        self.assertIn("待配置", await services.handle_compensate(ctx, "100"))
        self.assertEqual(
            await database.get_compensate_count(ctx.user_id, ctx.group_id), 1
        )
        await services.handle_calibrate_boss(ctx, "2 8000000 7000000")
        self.assertEqual(
            (await database.get_boss_status(ctx.group_id)).current_hp, 7_000_000
        )
        self.assertEqual(
            (await database.get_group_boss_stage(ctx.group_id, 2)).hp, 8_000_000
        )
        self.assertEqual((await database.get_group_boss_stage("other-group", 2)).hp, 0)

    async def test_large_hp_repeat_and_unknown_start(self):
        ctx = await get_context(self.bot, event())
        with patch.object(config, "BOSS_HP_BY_ROUND", {40: 10_250_000_000}):
            self.assertIn("未配置", await services.handle_start_gw(ctx))
            self.assertIsNone(await database.get_boss_status(ctx.group_id))
        await services.handle_calibrate_boss(ctx, "40 10250000000")
        self.assertEqual(
            (await database.get_boss_status(ctx.group_id)).max_hp, 10_250_000_000
        )
        await services.handle_report_knife(ctx, "10250000000")
        status = await database.get_boss_status(ctx.group_id)
        self.assertEqual(status.round_num, 41)
        self.assertEqual(status.current_hp, 10_250_000_000)
        for value in ["0", "²", "-1", "9" * 5000]:
            self.assertIn("格式", await services.handle_report_knife(ctx, value))


if __name__ == "__main__":
    unittest.main()
