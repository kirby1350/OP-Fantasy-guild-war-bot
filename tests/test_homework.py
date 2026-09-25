"""运行：python -m unittest discover -s tests -v。无需连接 QQ。"""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from nonebot.adapters.qq import Message, MessageSegment
from support import event, make_bot

from src.plugins.guild_war import database, homework


class Reply(Exception):
    pass


async def finish(message):
    raise Reply(message)


class HomeworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = make_bot()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(self.tmp.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        await database.init_db()
        buf = BytesIO()
        Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
        self.png = buf.getvalue()

    async def test_persistence_replacement_and_group_isolation(self):
        await database.save_homework("100", "默认", self.png, "123456")
        await database.save_homework("100", "火队", b"named", "123456")
        await database.init_db()  # 重启时建表不应覆盖已有作业
        self.assertEqual(await database.get_homework("100", "默认"), self.png)
        self.assertIsNone(await database.get_homework("200", "默认"))
        await database.save_homework("100", "默认", b"replacement", "123456")
        self.assertEqual(await database.get_homework("100", "默认"), b"replacement")
        self.assertEqual(await database.get_homework("100", "火队"), b"named")

    async def test_only_configured_openid_can_set(self):
        bot = self.bot
        self.assertTrue(await homework.set_homework_cmd.permission(bot, event()))
        self.assertFalse(
            await homework.set_homework_cmd.permission(bot, event(user_id=222))
        )
        self.assertTrue(await homework.homework_cmd.permission(bot, event(user_id=222)))

    async def test_set_and_read_image_bytes(self):
        args = Message("火队") + MessageSegment.image("https://example.com/image.png")
        args["image"][0].data["url"] = "https://example.com/image.png"
        with (
            patch.object(homework, "download_image", AsyncMock(return_value=self.png)),
            patch.object(homework.set_homework_cmd, "finish", finish),
        ):
            with self.assertRaises(Reply) as result:
                await homework.handle_set_homework(self.bot, event(), args)
            self.assertIn("已保存", str(result.exception))
        with patch.object(homework, "reply", AsyncMock()) as send:
            await homework.handle_homework(
                self.bot, event(user_id=222), Message("火队")
            )
            self.assertEqual(send.await_args.args[2], self.png)
        self.assertEqual(
            await database.get_homework("qq:999:group:100", "火队"), self.png
        )
        self.assertIsNone(await database.get_homework("100", "火队"))

    async def test_missing_image_and_missing_homework(self):
        with patch.object(homework.set_homework_cmd, "finish", finish):
            with self.assertRaises(Reply) as result:
                await homework.handle_set_homework(self.bot, event(), Message())
            self.assertIn("用法", str(result.exception))
        with patch.object(homework.homework_cmd, "finish", finish):
            with self.assertRaises(Reply) as result:
                await homework.handle_homework(self.bot, event(), Message())
            self.assertIn("尚未设置", str(result.exception))

    async def test_failed_download_preserves_old_image(self):
        await database.save_homework("qq:999:group:100", "默认", self.png, "123456")
        args = Message(MessageSegment.image("https://example.com/image.png"))
        with (
            patch.object(
                homework,
                "download_image",
                AsyncMock(side_effect=httpx.ReadTimeout("timeout")),
            ),
            patch.object(homework.set_homework_cmd, "finish", finish),
        ):
            with self.assertRaises(Reply):
                await homework.handle_set_homework(self.bot, event(), args)
        self.assertEqual(
            await database.get_homework("qq:999:group:100", "默认"), self.png
        )

    async def test_download_validation_and_size_limit(self):
        def response(request):
            return httpx.Response(200, content=self.png)

        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        with patch.object(homework.httpx, "AsyncClient", return_value=client):
            self.assertEqual(
                await homework.download_image("https://example.com/image.png"), self.png
            )
        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        with (
            patch.object(homework.httpx, "AsyncClient", return_value=client),
            patch.object(homework, "MAX_IMAGE_BYTES", 1),
        ):
            with self.assertRaisesRegex(ValueError, "10 MB"):
                await homework.download_image("https://example.com/image.png")
        with self.assertRaises(ValueError):
            homework.validate_image(b"not an image")
        with self.assertRaises(ValueError):
            await homework.download_image("file:///private.png")


if __name__ == "__main__":
    unittest.main()
