from django.shortcuts import render, get_object_or_404, HttpResponseRedirect
from django.http import FileResponse

from io import BytesIO
from torrentool.api import Torrent

from core import models, utils

class MagnetRedirect(HttpResponseRedirect):
    allowed_schemes = ['magnet']

def download_batch_torrent(request, batch_uuid, file_name):
    batch = get_object_or_404(models.Batch, uuid=batch_uuid, file_name=file_name.rstrip('.torrent'))
    seedbox_torrent_file = batch.seedbox_torrent_file

    new_torrent = Torrent.from_file(seedbox_torrent_file.path)
    announce_urls = utils.flatten_trackers_tiers(new_torrent.announce_urls)

    new_announce_urls = []
    for aurl in announce_urls:
        if 'explodie' not in aurl:
            new_announce_urls.append(aurl)

    new_torrent.announce_urls = sorted(new_announce_urls)
    return FileResponse(BytesIO(new_torrent.to_string()), filename=f'{batch.file_name}.torrent', as_attachment=True)

def download_batch_magnet(request, batch_uuid):
    batch = get_object_or_404(models.Batch, uuid=batch_uuid)
    seedbox_torrent_file = batch.seedbox_torrent_file

    new_torrent = Torrent.from_file(seedbox_torrent_file.path)
    return MagnetRedirect(new_torrent.get_magnet())

def download_torrent(request, episode_uuid, file_name):
    episode = get_object_or_404(models.Episode, uuid=episode_uuid, file_name=file_name.rstrip('.torrent'))
    seedbox_torrent_file = episode.seedbox_torrent_file

    new_torrent = Torrent.from_file(seedbox_torrent_file.path)
    announce_urls = utils.flatten_trackers_tiers(new_torrent.announce_urls)

    new_announce_urls = []
    for aurl in announce_urls:
        if 'explodie' not in aurl:
            new_announce_urls.append(aurl)

    new_torrent.announce_urls = sorted(new_announce_urls)
    return FileResponse(BytesIO(new_torrent.to_string()), filename=f'{episode.file_name}.torrent', as_attachment=True)

def download_magnet(request, episode_uuid):
    episode = get_object_or_404(models.Episode, uuid=episode_uuid)
    seedbox_torrent_file = episode.seedbox_torrent_file

    new_torrent = Torrent.from_file(seedbox_torrent_file.path)
    return MagnetRedirect(new_torrent.get_magnet())

def download(request, episode_uuid):
    episode = get_object_or_404(models.Episode, uuid=episode_uuid)
    return FileResponse(episode.file.open('rb'), filename=episode.file_name, as_attachment=True)
