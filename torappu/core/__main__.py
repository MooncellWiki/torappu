import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from torappu.core.game_server import poll
from torappu.core.utils import LoguruHandler

aps_logger = logging.getLogger("apscheduler")
aps_logger.setLevel(logging.DEBUG)
aps_logger.handlers.clear()
aps_logger.addHandler(LoguruHandler())

scheduler = AsyncIOScheduler()
job = scheduler.add_job(poll, "interval", minutes=0.5, max_instances=1)
scheduler.start()
try:
    asyncio.get_event_loop().run_forever()
except (KeyboardInterrupt, SystemExit):
    pass
