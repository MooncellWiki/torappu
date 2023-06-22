import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from torappu.core.game_server import poll

logging.basicConfig()
logging.getLogger("apscheduler").setLevel(logging.DEBUG)


scheduler = AsyncIOScheduler()
# job = scheduler.add_job(poll, "interval", minutes=10, max_instances=1)
# scheduler.start()
# try:
#     asyncio.get_event_loop().run_forever()
# except (KeyboardInterrupt, SystemExit):
#     pass
asyncio.get_event_loop().run_until_complete(poll())
