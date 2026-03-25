"""Download historical MOS forecasts and daily observations from IEM.

Usage:
    python scripts/download_iem_data.py                          # all stations
    python scripts/download_iem_data.py --station KNYC           # single station
    python scripts/download_iem_data.py --station KNYC --obs-only  # obs only
    python scripts/download_iem_data.py --station KNYC --mos-only  # MOS only
    python scripts/download_iem_data.py --fast                     # async obs download (~5x faster)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_loader import build_forecast_obs_pairs, save_pairs
from src.iem_client import download_mos_bulk, download_obs_bulk, download_obs_bulk_async
from src.stations import PHASE1_STATIONS, get_station

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download IEM weather data")
    parser.add_argument(
        "--station",
        type=str,
        default=None,
        help="ICAO station code (KNYC, KMDW, KMIA). Default: all Phase 1 stations.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="GFS",
        help="NWP model name (default: GFS)",
    )
    parser.add_argument(
        "--mos-only",
        action="store_true",
        help="Download only MOS forecasts, skip observations",
    )
    parser.add_argument(
        "--obs-only",
        action="store_true",
        help="Download only observations, skip MOS forecasts",
    )
    parser.add_argument(
        "--no-pairs",
        action="store_true",
        help="Skip building forecast-obs pairs after download",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use async concurrent downloads for observations (~5x faster)",
    )
    args = parser.parse_args()

    stations = [args.station] if args.station else PHASE1_STATIONS

    for icao in stations:
        station = get_station(icao)
        logger.info(f"=== {station.name} ({station.icao}) ===")

        if not args.obs_only:
            logger.info(f"Downloading MOS {args.model}...")
            download_mos_bulk(station, model=args.model)

        if not args.mos_only:
            logger.info("Downloading observations...")
            if args.fast:
                asyncio.run(download_obs_bulk_async(station))
            else:
                download_obs_bulk(station)

        if not args.no_pairs:
            logger.info("Building forecast-obs pairs...")
            pairs = build_forecast_obs_pairs(station, model=args.model)
            if not pairs.empty:
                save_pairs(pairs, station)
                logger.info(
                    f"Pairs: {len(pairs)} days, "
                    f"{pairs['year'].min()}-{pairs['year'].max()}"
                )
            else:
                logger.warning(f"No pairs built for {station.icao}")

    logger.info("Done.")


if __name__ == "__main__":
    main()
