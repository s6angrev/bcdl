# Bandcamp Collection Download
The process do download your purchases from [Bandcamp](https://bandcamp.com) is not very user friendly.
From their `purchases` view the user has to click the `download album` button, which opens a new tab.
In the new tab one needs to wait until the link is ready to be clickable, after which one can download a `zip` of the album.
The `zip` file needs to be extracted to the local disc and possibly put in its respective folder.
Especially if one wants to download multiple albums this process is very tedious.
The cli in this repository is what I use to download my purchases to my local disc.

The cli utilizes [typer](https://typer.tiangolo.com) as UI (mostly because I wanted to check it out).

The albums will be downloaded with the structure
`library/artist/album/{track,album_art}`

Downloading an album happens asyncronously, so all the files are downloaded simultaneously, but one album at a time.

## setup
After cloning the repo and installation of `requirements.txt` (possibly in a virtual environment) you can run
```
$ python main.py configure
```
You will be asked to setup 2 values needed for interactions with your bandcamp collection:
* **fan_id:** you can find this if you are logged into you account and go to https://bandcamp.com/api/fan/2/collection_summary
* **identity cookie:** got to the storage section of you browser while logged into bandcamp, look for the cookie with the name `identity` and copy its value.

Finally you can specify a custom path where you want to download your music to.

All this info will be saved in a file `config.json` and can be manually updated later.

## locally caching your collection
Once you set up your configuration you can download your collection by running
```
$ python main.py update-collection
```

## download albums from your collection
If you run
```
$ python main.py view-collection
```
you will see a list of your albums with the timestamp when you bought.
Every purchase has a number that you use to specify the list of items you want to download.
The prompt expects a comma sepaparated list, a number range like 3-7 or combination of the two.
Example:
```
choose albums to download by number: 0, 3-7, 9, 10
```
**Note:** a track is only downloaded if a file by that name doesn't exist yet. If you want to redownload a track you have to delete it first.

## download an album from url
An alternative way to download an album is to specify the url directly:
```
python main.py download https://soulglophl.bandcamp.com/album/songs-to-yeet-at-the-sun
```
