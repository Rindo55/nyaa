import re
import json
import requests
from lxml import html
from bs4 import BeautifulSoup

from django.conf import settings

from core import proxies, utils

__all__ = ('NyaaSi', 'NyaaNet', 'Anidex', 'TokyoTosho', 'AniRena')

DESCRIPTION = '''
%sp HEVC(x265) AAC %s.
please seed as much as possible.
Visit %s for direct download links for individual episodes and all our releases!
'''.strip()

class BaseUploader:

    def __init__(self, api_url, api_key, torrent_name, torrent_file, resolution, release_group, subtype,\
            screenshot_urls=[], torrent_file_url=None, batch=False):
        self.api_url = api_url
        self.api_key = api_key
        self.torrent_name = torrent_name
        self.torrent_file = torrent_file
        self.resolution = resolution
        self.release_group = release_group
        self.screenshot_urls = screenshot_urls
        self.torrent_file_url = torrent_file_url
        self.batch = batch
        self.subtype = subtype

        subtype_desc = 'Softsubs MKV' if subtype == 'softsubs' else 'Hardsubs MP4'

        self.description = (DESCRIPTION%(self.resolution, subtype_desc, self.release_group, '%s')).strip()

class NyaaSi(BaseUploader):

    def upload(self):
        description = self.description%(f'our [website]({settings.SITE_URL})')
        if self.screenshot_urls:
            screenshots_str = ''.join([f'\n![]({surl})' for surl in self.screenshot_urls])
            description += ('\n\n---\n' + screenshots_str)

        auth = eval(self.api_key)
        files = {
            'torrent': (self.torrent_name, self.torrent_file)
        }
        data = {
            'torrent_data' : json.dumps({
                'category': '1_2',
                'information': settings.SITE_URL,
                'description': description,
                'anonymous': True,
                'hidden': False,
                'complete': self.batch,
                'remake': True,
                'trusted': True,
            })
        }

        try:
            res = requests.post(self.api_url, files=files, data=data, auth=auth, headers=utils.get_header())
        except:
            res = requests.post(self.api_url, files=files, data=data, auth=auth, headers=utils.get_header(), **proxies.proxies)

        jdata = res.json()

        if 'url' in jdata:
            return (jdata['url'].strip(), jdata)

class NyaaNet(BaseUploader):

    def upload(self):
        description = self.description%(f'[{settings.SITE_URL}]({settings.SITE_URL})')
        if self.screenshot_urls:
            screenshots_str = ''.join([f'\n![]({surl})' for surl in self.screenshot_urls])
            description += ('\n\n---\n' + screenshots_str)

        files = {
            'torrent': (self.torrent_name, self.torrent_file)
        }
        data = {
            'username': 'SmallSizedAnimations',
            'c': '3_5',
            'desc': description,
            'languages': ['en'],
            'remake': False,
            'hidden': False,
        }
        headers = {
            'Authorization': self.api_key,
            **utils.get_header()
        }

        res = requests.post(self.api_url, files=files, data=data, headers=headers)
        jdata = res.json()

        if jdata['infos'][0].strip() == 'torrent uploaded successfully!':
            return (jdata['data']['torrent'].strip(), jdata)

class Anidex(BaseUploader):

    def upload(self):
        description = self.description%(f'[url]{settings.SITE_URL}[/url]')
        if self.screenshot_urls:
            screenshots_str = ''.join([f'\n[img]{surl}[/img]' for surl in self.screenshot_urls])
            description += screenshots_str

        files = {
            'file': (self.torrent_name, self.torrent_file)
        }
        data = {
            'subcat_id': 1,
            'group_id': 407,
            'lang_id': 1,
            'api_key': self.api_key,
            'description': description,
            'reencode': 1,
        }

        if self.batch:
            data.update({'batch': 1})

        res = requests.post(self.api_url, data=data, files=files, headers=utils.get_header(), timeout=600)

        text = res.text.strip()
        if text.startswith('https://anidex.info/torrent'):
            return (text, {'text': text})

class TokyoTosho(BaseUploader):

    def upload(self):
        description = self.description%(settings.SITE_URL)
        if not self.torrent_file_url:
            raise Exception('TokyoTosho upload error, no Torrent File Url provided')

        data = {
            'type': 1,
            'apikey': self.api_key,
            'comment': description,
            'website': settings.SITE_URL,
            'url': self.torrent_file_url,
            'send': True
        }

        res = requests.post(self.api_url, data=data, headers=utils.get_header())

        text = res.text.strip()
        if text.startswith('OK'):
            return ('https://www.tokyotosho.info/details.php?id={}'.format(text.split(',')[1].strip()), {'text': text})

class AniRena(BaseUploader):

    def upload(self):
        session = requests.Session()
        session.headers=utils.get_header()

        login_url = 'https://www.anirena.com/ucp.php?mode=login'

        sid_soup = BeautifulSoup(session.get(login_url).content, 'lxml')
        sid_value = sid_soup.select_one('input[name="sid"]').attrs['value']

        auth = eval(self.api_key)
        credentials = {
            "username": auth[0],
            "password": auth[1],
            'redirect': 'index.php',
            'login': 'Login',
            'sid': sid_value,
            'submit': True,
        }

        login_response = session.post(login_url, data=credentials, allow_redirects=False)

        if not login_response.cookies:
            raise Exception('Error logging in to AniRena')

        files = {
            'f': (self.torrent_name, self.torrent_file)
        }

        upload_init_response = session.post(self.api_url, files=files, data={'submit': 'Next'})

        soup = BeautifulSoup(upload_init_response.content, 'lxml')
        upload_form = soup.select_one('form#upload')

        upload_form_data = {}
        for input_element in upload_form.select('input'):
            if input_element.attrs['type'] != 'submit':
                upload_form_data[input_element.attrs['name']] = input_element.attrs['value']

        upload_form_data.update({
            't': 2,
            'c': self.description%(settings.SITE_URL),
            'submit': 'Submit'
        })

        upload_finish_response = session.post(self.api_url, data=upload_form_data)

        found_response = re.findall('Torrent uploaded succesfully under ID\s*\d+', upload_finish_response.text)
        found_id = re.findall('Torrent uploaded succesfully under ID\s*(\d+)', upload_finish_response.text)

        if found_response and found_id:
            return ('https://www.anirena.com/dl/{}'.format(found_id[0]), {'text': found_response[0]})
