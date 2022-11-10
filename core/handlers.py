import os
import time
from io import BytesIO
from django.conf import settings

import qbittorrentapi
from qbittorrentapi.definitions import TorrentStates
from torrentool.api import Torrent

from core import models, utils

class BaseDownloader:

    def __init__(self, magnet_url=None, torrent_file=None):

        if not (magnet_url or torrent_file):
            raise ValueError('Either magnet url or torrent file should be provided')

        self.file_size = 0
        if magnet_url:
            self.magnet_url = magnet_url
            self.torrent_hash = utils.get_magnet_hash(self.magnet_url)
        else:
            self.torrent_file = Torrent.from_string(torrent_file)
            self.torrent_hash = self.torrent_file.info_hash
            self.torrent_bytes = self.torrent_file.to_string()
            self.file_name = self.torrent_file.files[0].name
            self.file_size = self.torrent_file.total_size

        self.prepare()

    def prepare(self):
        qbt_obj = models.QBitTorrent.objects.all().first()
        if not qbt_obj:
            raise Exception('No QBitTorrent found')

        self.qbt_client = qbittorrentapi.Client(
            host=qbt_obj.host, port=qbt_obj.port, username=qbt_obj.username, password=qbt_obj.password)

        try:
            self.qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            raise Exception(e.message)

    @property
    def qtorrent(self):
        if self.torrent_hash:
            for t in self.qbt_client.torrents_info():
                if self.torrent_hash == t.hash:
                    return t

    @property
    def download_path(self):
        return utils.create_and_get_path(
            os.path.join(settings.BASE_DIR, 'downloads')
        )

    def file_path(self, file_name=''):
        return os.path.join(self.download_path, file_name or self.file_name)

    def func1(self):
        qtorrent = self.qtorrent
        return [qtorrent.progress, qtorrent.state]

    def func2(self, progress, state):
        return int(progress * 100) == 100 and TorrentStates(state).is_complete

    def wait_state(self):
        utils.wait_state(self.func1, self.func2)

class DownloadEpisode(BaseDownloader):

    def download(self):
        qb_response = self.qbt_client.torrents_add(
            torrent_files=BytesIO(self.torrent_bytes),
            save_path=self.download_path
        )

        if qb_response != 'Ok.':
            raise Exception(
                'Error starting download of torrent\n%s' % qb_response)

        time.sleep(3)

        all_announce_urls = []
        for track in models.Tracker.objects.all():
            all_announce_urls.extend(track.get_trackers())
        self.qtorrent.add_trackers(urls=all_announce_urls)

        self.wait_state()

        self.qtorrent.delete(False)

        return {
            'file_name': self.file_name,
            'file_path': self.file_path(),
            'file_size': self.file_size,
        }

    def download_from_magnet(self):
        qb_response = self.qbt_client.torrents_add(
            urls=self.magnet_url,
            save_path=self.download_path
        )

        if qb_response != 'Ok.':
            raise Exception(
                'Error starting download of torrent\n%s' % qb_response)

        time.sleep(3)

        self.file_name = self.qtorrent['name']
        self.file_size = self.qtorrent['total_size']

        all_announce_urls = []
        for track in models.Tracker.objects.all():
            all_announce_urls.extend(track.get_trackers())
        self.qtorrent.add_trackers(urls=all_announce_urls)

        self.wait_state()

        self.qtorrent.delete(False)

        return {
            'file_name': self.file_name,
            'file_path': self.file_path(),
            'file_size': self.file_size,
        }

class DownloadBatch(BaseDownloader):

    def get_data(self):
        data = []
        for f in self.qtorrent.files:
            name = f['name'].strip().replace('{}/'.format(self.qtorrent.name), '')
            data.append({
                'file_name': name,
                'file_path': self.file_path(name),
                'file_size': f['size'],
            })

        return data

    def get_info(self):
        qb_response = self.qbt_client.torrents_add(
            torrent_files=BytesIO(self.torrent_bytes),
            save_path=self.download_path
        )
        self.qtorrent.pause()

        if len(self.qtorrent.files) <= 1:
            return []

        data = self.get_data()

        self.qtorrent.delete(True)
        return sorted(data, key=lambda x: x['file_name'])

    def download(self):
        qb_response = self.qbt_client.torrents_add(
            torrent_files=BytesIO(self.torrent_bytes),
            save_path=self.download_path
        )

        if qb_response != 'Ok.':
            raise Exception(
                'Error starting download of torrent\n%s' % qb_response)

        time.sleep(3)

        all_announce_urls = []
        for track in models.Tracker.objects.all():
            all_announce_urls.extend(track.get_trackers())
        self.qtorrent.add_trackers(urls=all_announce_urls)

        self.wait_state()

        data = self.get_data()

        self.qtorrent.delete(False)

        return data

    def download_from_magnet(self):
        qb_response = self.qbt_client.torrents_add(
            urls=self.magnet_url,
            save_path=DL_PATH
        )

        if qb_response != 'Ok.':
            raise Exception(
                'Error starting download of torrent\n%s' % qb_response)

        time.sleep(3)

        self.file_name = self.qtorrent['name']
        self.file_size = self.qtorrent['total_size']

        all_announce_urls = []
        for track in models.Tracker.objects.all():
            all_announce_urls.extend(track.get_trackers())
        self.qtorrent.add_trackers(urls=all_announce_urls)

        self.wait_state()

        data = self.get_data()

        self.qtorrent.delete(False)

        return data
