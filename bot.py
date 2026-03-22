import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBot11Adapter

nonebot.init()

app = nonebot.get_asgi()

driver = nonebot.get_driver()
driver.register_adapter(OneBot11Adapter)

nonebot.load_plugin("src.plugins.guild_war")

if __name__ == "__main__":
    nonebot.run(app="bot:app")
