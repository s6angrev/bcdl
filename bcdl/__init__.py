import asyncio
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Iterable, Union

from bs4 import BeautifulSoup
import requests
import aiofiles
from aiohttp import ClientSession
import typer

logging.basicConfig(
    format="%(asctime)s: %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__file__)

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
LIBRARY_FOLDER_DEFAULT = Path().cwd() / "library"

app = typer.Typer()


class NotPurchasedException(Exception):
    """raise if requester does not own album."""


@dataclass
class Config:
    library_folder: Path
    fan_id: str
    identity_cookie: str
    collection: list

    @classmethod
    def from_file(cls, fpath: Union[str, Path] = CONFIG_FILE):
        fpath = Path(fpath) if isinstance(fpath, str) else fpath
        if not fpath.exists():
            typer.echo(f"please run 'bcdl configure")
            raise typer.Exit()

        with open(fpath) as f:
            conf = json.load(f)
        conf["library_folder"] = Path(conf["library_folder"])
        return cls(**conf)

    def save(self, fpath: Union[str, Path] = CONFIG_FILE):
        conf_dict = asdict(self)
        conf_dict["library_folder"] = str(conf_dict["library_folder"])
        with open(fpath, "w") as f:
            f.write(json.dumps(conf_dict, indent=4))


async def fetch_async(url: str, method: str, session: ClientSession, **kwargs):
    """GET request wrapper to download track.

    kwargs are passed to `session.request()`.
    """
    resp = await session.request(method=method, url=url, **kwargs)
    resp.raise_for_status()
    content = await resp.content.read()
    return content


async def download_file(file: Path, url: str, session: ClientSession, **kwargs) -> None:
    """Write the found HREFs from `url` to `file`."""
    track = await fetch_async(url=url, method="GET", session=session, **kwargs)
    if not track:
        return None
    async with aiofiles.open(file, "wb") as f:
        await f.write(track)
        logger.info("Downloaded: %s", file)


async def download_files(download_list: Iterable, cookie: str) -> None:
    cookies = {"identity": cookie}

    async with ClientSession() as session:
        tasks = [
            download_file(
                file=elem["target_file_name"],
                url=elem["source_url"],
                session=session,
                cookies=cookies,
            )
            for elem in download_list
            if not elem["target_file_name"].exists()
        ]
        await asyncio.gather(*tasks)


async def get_album_data_from_head(album_url: str, session):
    """javascript:
    var album = JSON.parse(
        document.querySelector('script[data-tralbum]')
                .getAttribute("data-tralbum")
    );
    """
    album_html = await fetch_async(url=album_url, method="GET", session=session)
    album = BeautifulSoup(album_html, "html.parser")
    scripts = album.head.find_all("script")
    tralbum_data_list = [
        s.attrs.get("data-tralbum") for s in scripts if s.attrs.get("data-tralbum")
    ]
    if len(tralbum_data_list) == 0:
        logger.exception("no script with attribute 'data-tralbum' found!")
        return None
    elif len(tralbum_data_list) > 1:
        logger.warning(
            "multiple script with attribute 'data-tralbum' found! returning first one!"
        )
    return json.loads(tralbum_data_list[0])


def generate_file_names(tralbum_data, folder, album_art_url: str = None):

    for track in tralbum_data["trackinfo"]:
        fname = folder.joinpath(
            f"{track['track_num']:02d} - {track['title'].replace('/', ' ')}.mp3"
        )
        source_file = track["file"]
        if not source_file:
            logger.warning(f"could not find url for track {fname}, skipping")
            continue
        source_url = source_file.get("mp3-128") or source_file.get("mp3-v0")
        if source_url is None or source_url.startswith(
            "https://bandcamp.com/stream_redirect"
        ):
            source_url = list(source_file.items())[0][1]
        yield {"target_file_name": fname, "source_url": source_url}
    if album_art_url:
        yield {
            "target_file_name": folder.joinpath(
                f"albumart.{album_art_url.split('.')[-1]}"
            ),
            "source_url": album_art_url,
        }


async def download_album(*, album_url: str, album_art_url: str = None) -> None:
    config = Config.from_file()
    cookies = {"identity": config.identity_cookie}

    async with ClientSession(cookies=cookies) as session:
        tralbum_data = await get_album_data_from_head(
            album_url=album_url, session=session
        )
        if not tralbum_data["is_purchased"]:
            raise NotPurchasedException("you do not own this album!")

        folder = (
            config.library_folder
            / tralbum_data["artist"]
            / tralbum_data["current"]["title"]
        )
        folder.mkdir(exist_ok=True, parents=True)

        download_list = (
            url_and_local_path
            for url_and_local_path in generate_file_names(
                tralbum_data, folder, album_art_url
            )
        )
        tasks = [
            download_file(
                file=elem["target_file_name"], url=elem["source_url"], session=session
            )
            for elem in download_list
            if not elem["target_file_name"].exists()
        ]

        await asyncio.gather(*tasks)


def get_collection(fan_id, titles_per_page: int = 25):
    url = "https://bandcamp.com/api/fancollection/1/collection_items"
    now_tst = int(datetime.utcnow().replace(tzinfo=timezone.utc).timestamp())

    more_available = True
    older_than_token = f"{now_tst}:0:a::"
    while more_available:
        data = {
            "fan_id": fan_id,
            "older_than_token": older_than_token,
            "count": titles_per_page,
        }
        res = requests.post(url=url, json=data)
        collection_data = res.json()
        more_available = collection_data["more_available"]
        older_than_token = collection_data["items"][-1]["token"]
        for item in collection_data["items"]:
            yield item


def range_str_to_number_set(range_str: str):
    ranges = range_str.split("-")
    if len(ranges) == 2:
        try:
            yield from range(int(ranges[0]), int(ranges[1]) + 1)
        except ValueError:
            typer.echo(f"could not resolve {range_str} to number range")
    elif len(ranges) == 1:
        yield int(ranges[0])
    else:
        typer.echo(f"could not resolve {range_str}, allowed formats: 1, 3-5")


def number_input_to_list(input_str: str) -> set:
    return {
        no
        for range_str in input_str.split(",")
        for no in range_str_to_number_set(range_str)
    }


@app.command()
def view_collection():
    config = Config.from_file()
    for no, album in enumerate(config.collection):
        typer.echo(
            f"[{no}] {album['purchased']} {album['band_name']}, {album['album_title']}"
        )

    download = typer.confirm("\ndownload any?")
    if not download:
        typer.Exit()

    album_number_list_input = typer.prompt("\nchoose albums to download by number")
    album_number_list = number_input_to_list(album_number_list_input)

    typer.echo("\nyou chose:\n")
    for album in [config.collection[idx] for idx in album_number_list]:
        typer.echo(f"{album['purchased']} {album['band_name']} {album['album_title']}")

    confirm_selection = typer.confirm("\ndownload these?")
    if confirm_selection:
        with typer.progressbar(album_number_list) as progress:
            for idx in progress:
                album = config.collection[idx]
                asyncio.run(
                    download_album(
                        album_url=album["item_url"], album_art_url=album["item_art_url"]
                    )
                )


@app.command()
def update_collection():
    typer.echo("updating local collection cache...")
    config = Config.from_file()
    config.collection = list(get_collection(fan_id=config.fan_id))
    config.save()


@app.command()
def download(album_url: str):
    try:
        asyncio.run(download_album(album_url=album_url))
    except NotPurchasedException:
        typer.echo(
            typer.style(
                f"you do not own this album: {album_url}",
                fg=typer.colors.RED,
                bold=True,
            ),
            err=True,
        )


@app.command()
def configure(
    fan_id=typer.Option(..., prompt=True),
    identity_cookie=typer.Option(..., prompt=True),
    library_folder=typer.Option(LIBRARY_FOLDER_DEFAULT, prompt=True),
):
    config = Config(
        fan_id=fan_id,
        identity_cookie=identity_cookie,
        library_folder=library_folder,
        collection=[],
    )
    config.save()


if __name__ == "__main__":
    app()
