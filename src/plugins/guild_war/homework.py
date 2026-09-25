"""官方 QQ 群作业图片命令。"""

import asyncio
from io import BytesIO
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError
from nonebot import on_command
from nonebot.adapters.qq import Bot, Message
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.params import CommandArg
from .qq_gateway import ADMIN, get_context, reply

from .database import get_homework, save_homework

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def validate_image(data: bytes):
    try:
        with Image.open(BytesIO(data)) as img:
            if img.width * img.height > 25_000_000:
                raise ValueError("图片分辨率过大，请压缩后重试。")
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法识别图片，请发送有效的图片。") from exc


async def download_image(url: str) -> bytes:
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("未取得图片下载地址，请直接发送图片。")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError("图片不能超过 10 MB，请压缩后重试。")
    image = bytes(data)
    await asyncio.to_thread(validate_image, image)
    return image


set_homework_cmd = on_command("设置作业", permission=ADMIN, block=True)
homework_cmd = on_command("作业", aliases={"查看作业", "抄作业"}, block=True)


@set_homework_cmd.handle()
async def handle_set_homework(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    name = args.extract_plain_text().strip() or "默认"
    if len(name) > 50:
        await set_homework_cmd.finish("❌ 作业名称不能超过 50 个字符。")
    images = args["image"]
    if len(images) != 1:
        await set_homework_cmd.finish(
            "用法：设置作业 [名称] + 一张图片（文字和图片在同一条消息中发送）。"
        )
    url = images[0].data.get("url", "")
    if not url:
        await set_homework_cmd.finish("❌ 图片缺少下载地址，请重新发送原图。")
    try:
        image = await download_image(url)
    except ValueError as exc:
        await set_homework_cmd.finish(f"❌ {exc}")
    except httpx.HTTPError:
        await set_homework_cmd.finish(
            "❌ 图片下载失败，请重新发送图片。原作业保持不变。"
        )
    ctx = await get_context(bot, event)
    await save_homework(ctx.group_id, name, image, ctx.user_id)
    command = "作业" if name == "默认" else f"作业 {name}"
    await set_homework_cmd.finish(
        f"✅ 已保存作业「{name}」，成员发送「{command}」即可查看。"
    )


@homework_cmd.handle()
async def handle_homework(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    name = args.extract_plain_text().strip() or "默认"
    ctx = await get_context(bot, event)
    image = await get_homework(ctx.group_id, name)
    if image is None:
        await homework_cmd.finish(f"本群尚未设置作业「{name}」，请联系机器人管理员。")
    await reply(bot, event, image)
