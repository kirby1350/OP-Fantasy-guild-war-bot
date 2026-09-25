import nonebot
from nonebot.adapters.qq import Adapter as QQAdapter

nonebot.init(driver="~fastapi+~httpx")

app = nonebot.get_asgi()

driver = nonebot.get_driver()
driver.register_adapter(QQAdapter)

if nonebot.load_plugin("src.plugins.guild_war") is None:
    raise RuntimeError("工会战插件加载失败，请检查启动日志。")

if __name__ == "__main__":
    nonebot.run()
