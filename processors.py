import asyncio
import csv
import logging
import os
import re
from datetime import date, timedelta
from typing import Callable, Optional

import aiohttp
from tqdm.asyncio import tqdm_asyncio


class CPUList:
    def __init__(
        self, processors: dict[str, dict[str, str]], attributes: dict[str, Callable[[str], str]], link_base: str
    ) -> None:
        self.processors = processors
        self.attributes = attributes
        self.link_base = link_base
        self.changed_something = False

    async def fetch_html(self, url: str, session: aiohttp.ClientSession, **kwargs) -> Optional[str]:
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

    def update_dict(self, cpu_id: str, response_text: Optional[str]) -> None:
        if not response_text:
            return
        processor = self.processors[cpu_id]
        cpu_name = processor["Name"]
        for key, method in self.attributes.items():
            try:
                processor[key] = method(response_text).strip()
            except IndexError:  # noqa: PERF203
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

    async def bulk_crawl_and_write(self, my_csv: str) -> None:
        """Crawl & write concurrently to `file` for multiple `urls`."""
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            tasks = tuple(self.update_one(cpu_id, session=session) for cpu_id in self.processors)
            await tqdm_asyncio.gather(*tasks)

        print_table(self.attributes.keys(), self.processors)

        if self.changed_something:
            write_csv([*self.attributes.keys(), "Link", "Updated"], self.processors, my_csv)


def write_csv(header, processors, filename):
    with open(filename, "w", newline="") as csvfile:
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


def prefill_with_csv(my_csv, processors, link_base):
    try:
        with open(my_csv) as csvfile:
            csvreader = csv.reader(csvfile)
            header = csvreader.__next__()
            link_index = header.index("Link")
            for row in csvreader:
                key = row[link_index][len(link_base) :]
                if key in processors:
                    for i, item in enumerate(row):
                        processors[key][header[i]] = item
    except IOError as ioe:
        logging.info("Error on reading %s: %s", my_csv, str(ioe))
    return processors


async def main():
    attributes: dict[str, Callable[[str], str]] = {
        "Name": lambda html: re.findall(r'<span class="cpuname"> *([^@<]*) *(@[^<]*)?</span>', html)[0][0],
        "First Seen": lambda html: re.findall(
            r'<strong class="bg-table-row">CPU First Seen on Charts:</strong>(&nbsp;)*([^<]*)</p>', html
        )[0][1],
        "Single Thread": lambda html: re.findall(
            r"<div[^>]*>\s*Single Thread Rating:?\s*</div>\s*<div[^>]*>\s*(\d+)\s*</div>", html
        )[0],
        "Multi Thread": lambda html: re.findall(
            r"<div[^>]*>\s*Multithread Rating:?\s*</div>\s*<div[^>]*>\s*(\d+)\s*</div>",
            html,
        )[0],
        "TDP": lambda html: re.findall(r"<strong>Typical TDP:</strong> *(\d+) *W(<sup>\d+</sup>)?</p>", html)[0][0],
        # "Cores": lambda html: re.findall(r'<strong>No of Cores:</strong> *([^<]+) *</p>', html)[0]
        "Cores": lambda html: "{} ({})".format(
            *re.findall(r"<strong>Cores:?</strong>:? *(\d+) *<strong>Threads:?</strong>:? *(\d+) *</p>", html)[0]
        ),
        "# Samples": lambda html: re.findall(r"<strong> *Samples: *</strong> *(\d+)\s*\*?\s*<br/?>", html)[0],
    }
    link_base = "https://www.cpubenchmark.net/cpu.php?id="
    processors = {
        "1850": {"Name": "Intel Core i5-3337U"},
        "828": {"Name": "Intel Core i5-3570K"},
        "3323": {"Name": "Intel Core i5-8265U"},
        "3150": {"Name": "Intel Core i5-8350U"},
        "3447": {"Name": "Intel Core i5-8365U"},
        "3286": {"Name": "Intel Core i5-8400H"},
        "3448": {"Name": "Intel Core i5-9300H"},
        "3542": {"Name": "Intel Core i5-10210U"},
        "3646": {"Name": "Intel Core i5-10300H"},
        "3581": {"Name": "Intel Core i5-1035G4"},
        "3308": {"Name": "Intel Core i7-8565U"},
        "3549": {"Name": "Intel Core i7-10510U"},
        "3466": {"Name": "Intel Core i7-1065G7"},
        # "3451": {"Name": "Intel Core i9-9980HK"},
        "3421": {"Name": "AMD Ryzen 5 3500U"},
        "3403": {"Name": "AMD Ryzen 5 3550H"},
        "3577": {"Name": "AMD Ryzen 5 3580U"},
        "3500": {"Name": "AMD Ryzen 5 PRO 3500U"},
        "3702": {"Name": "AMD Ryzen 5 4500U"},
        "3743": {"Name": "AMD Ryzen 5 PRO 4500U"},
        "3725": {"Name": "AMD Ryzen 5 4600U"},
        "3708": {"Name": "AMD Ryzen 5 4600H"},
        "3766": {"Name": "AMD Ryzen 5 PRO 4650U"},
        "3426": {"Name": "AMD Ryzen 7 3700U"},
        "3433": {"Name": "AMD Ryzen 7 PRO 3700U"},
        "3441": {"Name": "AMD Ryzen 7 3750H"},
        "3587": {"Name": "AMD Ryzen 7 3780U"},
        "3699": {"Name": "AMD Ryzen 7 4700U"},
        "3740": {"Name": "AMD Ryzen 7 PRO 4750U"},
        "3721": {"Name": "AMD Ryzen 7 4800U"},
        "3697": {"Name": "AMD Ryzen 7 4800HS"},
        "3676": {"Name": "AMD Ryzen 7 4800H"},
    }

    my_csv = os.path.join(os.path.dirname(os.path.realpath(__file__)), "processors.csv")

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
