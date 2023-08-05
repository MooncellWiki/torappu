import asyncio
import argparse

from torappu.core.main import run

from ..models import Version

parser = argparse.ArgumentParser(
    prog="torappu",
)
parser.add_argument("client_version")
parser.add_argument("res_version")
parser.add_argument(
    "prev_client_version",
)
parser.add_argument("prev_res_version")
args = parser.parse_args()
version = Version(res_version=args.res_version, client_version=args.client_version)
prev = None
if args.prev_client_version is not None and args.prev_res_version is not None:
    prev = Version(
        res_version=args.prev_res_version, client_version=args.prev_client_version
    )
asyncio.run(run(version, prev))
