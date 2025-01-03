#!/bin/env python3
import asyncio
import csv
import logging
import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import aiohttp
from tqdm.asyncio import tqdm_asyncio


class CPUList:
    def __init__(
        self, processors: dict[str, dict[str, str]], attributes: dict[str, Callable[[str], str]], link_base: str
    ):
        self.processors = processors
        self.attributes = attributes
        self.link_base = link_base
        self.changed_something = False

    async def fetch_html(self, url: str, session: aiohttp.ClientSession, **kwargs) -> str | None:
        """GET request wrapper to fetch page HTML.

        kwargs are passed to `session.request()`.
        """
        async with session.get(url, **kwargs) as response:
            logging.info("Got response [%s] for URL: %s", response.status, url)
            try:
                html = await response.text()
            except aiohttp.ClientPayloadError:
                logging.error("Payloaderror on url %s", url)
                return None
            logging.debug("Size of html: %i", len(html))
            return html

    def update_dict(self, cpu_id, response_text):
        if not response_text:
            return
        processor = self.processors[cpu_id]
        cpu_name = processor["Name"]
        for key, method in self.attributes.items():
            try:
                processor[key] = method(response_text).strip()
            except IndexError:
                logging.error("Error on key %s and with link %s", key, self.link_base + cpu_id)
                processor[key] = "-"

        if cpu_name != processor["Name"]:
            logging.error("%s is not online %s with cpu_id %s", processor["Name"], cpu_name, cpu_id)
        today = date.today()
        processor["Updated"] = today.strftime("%Y-%m-%d")
        self.changed_something = True

    async def update_one(self, cpu_id: str, session: aiohttp.ClientSession) -> None:
        """Downloading cpu_ids with session."""
        processor = self.processors[cpu_id]
        link = self.link_base + cpu_id
        processor["Link"] = link
        if "Updated" in processor and date.fromisoformat(processor["Updated"]) + timedelta(days=7) > date.today():
            logging.info("skipping update of %s", processor["Name"])
        else:
            logging.debug("Used link: %s", link)
            response_text = await self.fetch_html(link, session=session)
            self.update_dict(cpu_id, response_text)

    async def bulk_crawl_and_write(self, my_csv: Path) -> None:
        """Crawl & write concurrently to `file` for multiple `urls`."""
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            tasks = tuple(self.update_one(cpu_id, session=session) for cpu_id in self.processors)
            await tqdm_asyncio.gather(*tasks)

        print_table(self.attributes.keys(), self.processors)

        if self.changed_something:
            write_csv([*list(self.attributes.keys()), "Link", "Updated"], self.processors, my_csv)


def write_csv(header: list[str], processors: dict, filename: Path):
    with filename.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=header)
        writer.writeheader()
        for processor in processors.values():
            writer.writerow(processor)


def print_table(header, processors):
    print_format = ""
    for i, key in enumerate(header):
        size = max(len(x[key]) for x in processors.values())
        size = max(size, len(key))
        if i == 0:  # First item left binding
            print_format += "{:" + str(size) + "} "
        elif i + 1 == len(header):  # Last item right binding
            print_format += "{:>" + str(size) + "}"
        else:  # all other items centered
            print_format += "{:^" + str(size) + "} "
        # print_format += '%-' + str(size) + 's '
    print(print_format.format(*header))
    for processor in processors.values():
        print(print_format.format(*[processor[key] for key in header]))


def prefill_with_csv(my_csv: Path, processors: dict[str, dict[str, str]], link_base: str) -> dict[str, dict[str, str]]:
    try:
        with my_csv.open() as csvfile:
            csvreader = csv.reader(csvfile)
            header = csvreader.__next__()
            link_index = header.index("Link")
            for row in csvreader:
                key = row[link_index][len(link_base) :]
                if key in processors:
                    for i, item in enumerate(row):
                        processors[key][header[i]] = item
    except OSError as ioe:
        logging.info("Error on reading %s: %s", my_csv, str(ioe))
    return processors


async def main():
    attributes: dict[str, Callable[[str], str]] = {
        "Name": lambda html: re.findall(r'<span class="cpuname"> *([^@<]*) *(@[^<]*)?</span>', html)[0][0],
        "First Seen": lambda html: re.findall(
            r'<strong class="bg-table-row">CPU First Seen on Charts:</strong>(&nbsp;)*([^<]*)</p>', html
        )[0][1],
        "Single Thread": lambda html: re.findall(r"<strong> *Single Thread Rating: *</strong> *(\d+)<br/?>", html)[0],
        "Multi Thread": lambda html: re.findall(
            r'<span style="font-family: Arial, Helvetica, sans-serif;font-size: 44px;	font-weight: bold; color: #F48A18;">(\d+)</span>',
            html,
        )[0],
        "TDP": lambda html: re.findall(r"<strong>Typical TDP:</strong> *(\d+) *W(<sup>\d+</sup>)?</p>", html)[0][0],
        # "Cores": lambda html: re.findall(r'<strong>No of Cores:</strong> *([^<]+) *</p>', html)[0]
        "Cores": lambda html: "{} ({})".format(
            *re.findall(r"<strong>Cores:?</strong>:? *(\d+) *<strong>Threads:?</strong>:? *(\d+) *</p>", html)[0]
        ),
        "# Samples": lambda html: re.findall(r"<strong> *Samples: *</strong> *(\d+)\s*\*?\s*<br/?>", html)[0],
    }
    link_base: str = "https://www.cpubenchmark.net/cpu.php?id="
    processors: dict[str, dict[str, str]] = {
        "1850": {"Name": "Intel Core i5-3337U"},
        "828": {"Name": "Intel Core i5-3570K"},
        "3447": {"Name": "Intel Core i5-8365U"},
        "3560": {"Name": "Intel Core i3-1005G1"},
        "3877": {"Name": "Intel Core i3-1115G4 @ 3.00GHz"},
        "3725": {"Name": "AMD Ryzen 5 4600U"},
        "3708": {"Name": "AMD Ryzen 5 4600H"},
        "4141": {"Name": "AMD Ryzen 5 5500U"},
    }

    my_csv = Path(__file__).parent / "processors.csv"

    processors = prefill_with_csv(my_csv, processors, link_base)
    # update_and_display(processors, attributes, link_base, CSV)
    cpulist = CPUList(processors, attributes, link_base)
    await cpulist.bulk_crawl_and_write(my_csv)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
        # level=logging.DEBUG,
        datefmt="%H:%M:%S",
    )
    asyncio.run(main())
