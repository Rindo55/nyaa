import os
import re
import requests
import feedparser
from io import BytesIO
from urllib.parse import urlencode, urlparse, urljoin

from lxml import html
from bs4 import BeautifulSoup
from tzlocal import get_localzone

from core import proxies, utils

__all__ = ('NyaaSi', 'NyaaNet', 'Anidex', 'SubsPlease')


class BaseFeeders:

    def __init__(self, feed_url):
        self.feed_url = feed_url
        self.skip_words = [
            r'\(\s*\d+\s*\-\s*\d*\s*\)',
            r'\[v0\]',
        ]
        self.site_headers = utils.get_header(
            '/'.join(self.feed_url.split('/')[:3])
        )

    def get_feed(self):
        filtered_feeds = []

        for feed in self.all_feeds:
            title = feed['title']

            if any(bool(re.findall(t, title)) for t in self.skip_words):
                continue

            filtered_feeds.append(feed)

        return sorted(filtered_feeds, key=lambda k: k['title'])


class BasePageFeeders(BaseFeeders):

    def __init__(self, feed_url):
        super(BasePageFeeders, self).__init__(feed_url)
        self.req_headers = utils.get_header()
        self.req = requests.get(self.feed_url)
        self.soup = BeautifulSoup(self.req.content, 'lxml')
        self.purl = urlparse(feed_url)
        self.surl = feed_url.split('/')
        self.domain = '/'.join(self.surl[:3])

    def json(self, req=None):
        try:
            return (req or self.req).json()
        except:
            return False

    def get_image(self, image_url):
        img_chunks = requests.get(
            image_url, headers=self.req_headers, stream=True)

        img_temp = BytesIO()
        for chunk in img_chunks.iter_content(1024*64):
            if chunk:
                img_temp.write(chunk)

        img_name = '00' + os.path.splitext(image_url)[1]
        return img_name, img_temp

# MAIN FEEDERS


class SubsPlease(BasePageFeeders):

    def __init__(self, feed_url):
        super(SubsPlease, self).__init__(feed_url)
        api_query = {
            'f': 'show',
            'tz': str(get_localzone()),
            'sid': self.soup.select_one('table#show-release-table').attrs['sid']
        }
        api_url = '/'.join([self.domain, 'api', '']) + \
            '?' + urlencode(api_query)
        self.api_req = requests.get(api_url, headers=self.req_headers)

    def magnet_1080(self, data):
        for item in data['downloads']:
            if item['res'] == '1080':
                return item.get('magnet')
        return None

    def torrent_1080(self, data):
        for item in data['downloads']:
            if item['res'] == '1080':
                return item.get('torrent')
        return None

    @property
    def all_feeds(self):
        entries = self.json(self.api_req)['episode']

        episodes = []
        for episode, entry in entries.items():
            try:
                torrent_id = re.findall(
                    r'view/(\d+)/torrent', self.torrent_1080(entry))

                if not torrent_id:
                    continue
            except:
                continue

            torrent_id = torrent_id[0]
            torrent_url = 'https://nyaa.si/download/{}.torrent'.format(
                torrent_id)
            episodes.append({
                'title': '[SubsPlease] {} [1080p].mkv'
                    .format(episode.replace('–', '-')),
                'torrent_magnet': self.magnet_1080(entry),
                'torrent_url': torrent_url,
            })

        return episodes

    @property
    def details(self):
        img_src = urljoin(self.domain, self.soup.select_one(
            'div#secondary img').attrs['src'])
        img = self.get_image(img_src)
        return {
            'image_name': img[0],
            'image_data': img[1],
            'release_count': len(self.get_feed()),
            'title':
                self.soup.select_one('h1.entry-title').text.replace('–', '-')
        }


class NyaaSi(BaseFeeders):

    @property
    def all_feeds(self):
        try:
            feed_content = requests.get(self.feed_url, **proxies.proxies)
        except:
            feed_content = requests.get(self.feed_url, headers=self.req_headers)
        entries = feedparser.parse(feed_content.text).get('entries')
        episodes = []
        for entry in entries:
            episodes.append({
                'title': entry['title'],
                'torrent_magnet': None,
                'torrent_url': entry['link']
            })

        return episodes


class NyaaNet(BaseFeeders):

    @property
    def all_feeds(self):
        entries = feedparser.parse(self.feed_url).get('entries')
        episodes = []
        for entry in entries:
            episodes.append({
                'title': entry['title'],
                'torrent_magnet': None,
                'torrent_url': entry['link']
            })

        return episodes


class Anidex(BaseFeeders):

    @property
    def all_feeds(self):
        pass
