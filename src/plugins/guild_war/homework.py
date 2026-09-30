"""作业（攻略图）上传与查询"""

import uuid
from pathlib import Path
from typing import List

import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, Message, MessageSegment
)
from nonebot.internal.matcher import Matcher
from nonebot.params import Arg, CommandArg
from nonebot.typing import T_State

from .database import add_homework, list_homework, get_homework, delete_homework
from .members import ADMIN
from .models import Homework

HOMEWORK_DIR = Path("data/homework")


def _image_segments(msg: Message) -> List[MessageSegment]:
    return [seg for seg in msg if seg.type == "image"]


async def _download_image(bot: Bot, seg: MessageSegment, group_id: str) -> str:
    """下载图片到本地（QQ图片链接会过期，必须保存）"""
    url = seg.data.get("url")
    if url:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content
    else:
        # 协议端未提供url时，通过 get_image 获取本地缓存文件
        info = await bot.call_api("get_image", file=seg.data["file"])
        content = Path(info["file"]).read_bytes()

    out_dir = HOMEWORK_DIR / group_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{uuid.uuid4().hex}.jpg"
    path.write_bytes(content)
    return str(path)


def _homework_message(hw: Homework) -> Message:
    msg = Message(f"📖 作业 #{hw.id}：{hw.title}")
    for p in hw.image_paths:
        path = Path(p)
        if path.exists():
            msg += MessageSegment.image(path.read_bytes())
    return msg


# ─── 上传作业（管理员） ──────────────────────────────────────────────────────

upload_hw = on_command("上传作业", permission=ADMIN, block=True)

@upload_hw.handle()
async def handle_upload_hw(matcher: Matcher, event: GroupMessageEvent, state: T_State,
                           args: Message = CommandArg()):
    title = args.extract_plain_text().strip()
    if not title:
        await upload_hw.finish(
            "❌ 用法：上传作业 <标题> [图片]\n"
            "可以直接附带图片、回复一条图片消息，或稍后单独发送图片。"
        )
    state["title"] = title

    # 本条消息带图，或回复了一条带图消息，则无需再次索要
    if _image_segments(args):
        matcher.set_arg("images", args)
    elif event.reply and _image_segments(event.reply.message):
        matcher.set_arg("images", event.reply.message)


@upload_hw.got("images", prompt="请发送作业图片（可一次发送多张）")
async def handle_upload_images(bot: Bot, event: GroupMessageEvent, state: T_State,
                               images: Message = Arg()):
    segs = _image_segments(images)
    if not segs:
        await upload_hw.reject("❌ 没有检测到图片，请重新发送图片：")

    group_id = str(event.group_id)
    try:
        paths = [await _download_image(bot, seg, group_id) for seg in segs]
    except Exception as e:
        await upload_hw.finish(f"❌ 图片保存失败：{e}")

    hw_id = await add_homework(group_id, state["title"], paths, str(event.user_id))
    await upload_hw.finish(
        f"✅ 已上传作业 #{hw_id}：{state['title']}（{len(paths)} 张图）"
    )


# ─── 查作业 ─────────────────────────────────────────────────────────────────

query_hw = on_command("查作业", aliases={"作业"}, block=True)

@query_hw.handle()
async def handle_query_hw(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    keyword = args.extract_plain_text().strip()

    if keyword.isdigit():
        hw = await get_homework(group_id, int(keyword))
        if not hw:
            await query_hw.finish(f"❌ 没有编号为 {keyword} 的作业。")
        await query_hw.finish(_homework_message(hw))

    results = await list_homework(group_id, keyword)
    if not results:
        await query_hw.finish("❌ 没有找到相关作业。" if keyword else "暂无作业。")
    if keyword and len(results) == 1:
        await query_hw.finish(_homework_message(results[0]))

    lines = ["📚 作业列表：" if not keyword else f"📚 匹配「{keyword}」的作业："]
    lines += [f"#{hw.id} {hw.title}" for hw in results]
    lines.append("\n发送「查作业 <编号>」查看图片")
    await query_hw.finish("\n".join(lines))


# ─── 删除作业（管理员） ──────────────────────────────────────────────────────

delete_hw = on_command("删除作业", permission=ADMIN, block=True)

@delete_hw.handle()
async def handle_delete_hw(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await delete_hw.finish("❌ 用法：删除作业 <编号>")

    hw = await get_homework(group_id, int(arg))
    if not hw:
        await delete_hw.finish(f"❌ 没有编号为 {arg} 的作业。")
    await delete_homework(group_id, hw.id)
    for p in hw.image_paths:
        Path(p).unlink(missing_ok=True)
    await delete_hw.finish(f"✅ 已删除作业 #{hw.id}：{hw.title}")
