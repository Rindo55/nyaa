import re
import requests
import feedparser
from django.db.models import Q
from urllib.parse import urlencode, urljoin
from lxml import html
from bs4 import BeautifulSoup
from tzlocal import get_localzone

from core import models, feeders, utils


class BaseWatcher:

    def __init__(self, watcher_id):
        self.req_headers = utils.get_header()
        self.watcher_obj = models.SiteWatcher.objects.get(pk=watcher_id)
        self.url = self.watcher_obj.url
        self.surl = self.url.split('/')
        self.domain = '/'.join(self.surl[:3])

    def get_req(self, url):
        return requests.get(url, headers=self.req_headers)

    def get_content(self, url):
        return BeautifulSoup(self.get_req(url).content, 'lxml')

    def set_update(self, updates):
        updates = list(updates)
        self.watcher_obj.data = updates
        self.watcher_obj.save()
        return updates

    #MAIN

    def check_updates(self):
        updates_list = self.get_updates()
        cached_list = self.watcher_obj.data
        to_update = []
        if not cached_list:
            to_update = self.set_update(updates_list)
        else:
            for update in updates_list:
                if update == cached_list[0]:
                    break
                to_update.append(update)

            if to_update:
                self.set_update(updates_list)

        return self.do_updates(to_update)


class SubsPleaseWatcher(BaseWatcher):

    def __init__(self, watcher_id, page_number=0):
        super(SubsPleaseWatcher, self).__init__(watcher_id)
        api_query = {
            'f': 'latest',
            'tz': get_localzone().zone,
            'p': page_number
        }
        api_url = '/'.join([self.domain, 'api', '']) + \
            '?' + urlencode(api_query)
        self.api_data = requests.get(api_url, headers=self.req_headers).json()

    def get_updates(self):
        title_words = ['[Batch]', '(Batch)']
        episodes = self.api_data
        updates = []
        for title, episode in episodes.items():
            if not any(tw in title for tw in title_words):
                updates.append({
                    'title': title.replace('–', '-'),
                    'href': '/'.join([self.domain, 'shows', episode['page'], ''])
                })

        return updates

    def episode_difference(self, sp, anime):
        m_ep_titles = models.EpisodeTitle.objects.filter(anime=anime)
        ep_titles = sp.all_feeds

        m_episode_titles = [e.title for e in m_ep_titles]
        episode_titles = [
            utils.extract_names(
                e['title'],
                anime.title,
                anime.get_alt_names()
            )[1] for e in ep_titles
        ]
        ep_diff = list(set(episode_titles) - set(m_episode_titles))

        return len(ep_diff)

    def do_updates(self, to_update):
        updates_args = []
        for update in to_update:
            if isinstance(update, list) and update:
                update = update[0]
            href = update.get('href')
            found = models.Feed.objects.filter(
                Q(site=self.watcher_obj.site) &
                Q(url__icontains=href.rstrip('/'))
            )
            if found and found[0].enabled:
                updates_args.append(found[0].id)
            elif not found and self.watcher_obj.add_missing:
                sp = feeders.SubsPlease(href)
                anime = models.Anime.create_using_json({
                    **sp.details,
                    'pic_type': True
                })
                upload_condition = self.episode_difference(sp, anime) < 4
                f, created = models.Feed.objects.get_or_create(
                    site=self.watcher_obj.site,
                    anime=anime,
                    url=href,
                    upload_seedbox=True,
                    upload_torrent=upload_condition,
                    upload_last_episode_torrent=(not upload_condition),
                    enabled=True,
                )
                updates_args.append(f.id)

        self.watcher_obj.update_last_check()

        return updates_args
