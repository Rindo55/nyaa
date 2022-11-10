import os
import re
import time
import random
import base64
import shutil

from django.conf import settings

from fake_useragent import UserAgent
ua = UserAgent()

user_agent_list = [
   #Chrome
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36',
    'Mozilla/5.0 (Windows NT 5.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.2; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36',
    #Firefox
    'Mozilla/4.0 (compatible; MSIE 9.0; Windows NT 6.1)',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; WOW64; Trident/5.0)',
    'Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (Windows NT 6.2; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.0; Trident/5.0)',
    'Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0)',
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)',
    'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; Trident/6.0)',
    'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0; .NET CLR 2.0.50727; .NET CLR 3.0.4506.2152; .NET CLR 3.5.30729)'
]

def get_user_agent():
    try:
        return ua.random
    except:
        return random.choice(user_agent_list)

def get_header(url=None):
    HEADERS = {
        'User-Agent': get_user_agent()
    }
    if not url:
        return HEADERS
    HEADERS['Referer'] = url
    return HEADERS

def create_and_get_path(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def check_and_delete(path):
    if os.path.exists(path):
        os.remove(path)

def check_and_delete_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)

def wait_state(func1, func2, period=3, timeout=(60 * 60 * 24)):
    must_end = time.time() + timeout
    while time.time() < must_end:
        if func2(*func1()):
            return True
        time.sleep(period)
    return False

suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
def humansize(nbytes):
    i = 0
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
    return '%s %s' % (f, suffixes[i])

def retry(func, func_args=[], func_kwargs={}, retries=3, wait=0):
    while retries > 0:
        try:
            return func(*func_args, **func_kwargs)
        except Exception as e:
            retries -= 1
            if retries == 0:
                raise e
            if wait > 0:
                time.sleep(wait)

def get_magnet_hash(magnet_url):
    extract = magnet_url[magnet_url.find("btih:") + 5:magnet_url.find("&")]
    if len(extract) != 40:
        return base64.b16encode(base64.b32decode(extract)).lower().decode('utf8')
    return extract

def extract_names(title, anime_name, anime_alt_names=[]):

    release_group = re.findall(r'^\[([^\]]*)\]', title)[0]

    if title.endswith('.torrent'):
        title = os.path.splitext(title)[0]

    original_episode_name = str(title)
    episode_name = str(title)

    while any(episode_name.endswith(ext) for ext in ['.mp4', '.mkv']):
        episode_name = os.path.splitext(episode_name)[0]

    episode_name = re.findall(r'([^\[^\]]+)(?![^\[]*\])', episode_name)

    if not episode_name:
        return (None,)*4

    def get_resolution(episode_name):
        rexp1 = [r'\[\D*(\d+)?[p|i]\D*\]', r'\[.*\d+x(\d+)?\.*\]']
        for rexp in rexp1:
            episode_resolution = re.findall(rexp, title)
            if any(episode_resolution):
                for er in episode_resolution:
                    if er: episode_resolution = er
                break

        if not episode_resolution:
            rexp2 = [
                (r'\(\D*(\d+)?p\D*\)', r'\([^\(]*\d+?p[^\)]*\)'),
                (r'\([^\(]*\d+x(\d+)?[^\)]*\)', r'\([^\(]*\d+x\d+?[^\)]*\)')
            ]
            for rexp in rexp2:
                rexp, rexpr = rexp
                if not rexpr: rexpr = rexp
                episode_resolution = re.findall(rexp, title)
                if any(episode_resolution) and re.findall(rexpr, episode_name[0]):
                    episode_name = [re.sub(rexpr, '', episode_name[0])]
                    for er in episode_resolution:
                        if er: episode_resolution = er
                    break

        return episode_name, episode_resolution

    episode_name, episode_resolution = get_resolution(episode_name)
    if not (episode_name and episode_resolution and release_group):
        return (None,)*4

    episode_name = episode_name[0].strip()
    episode_resolution = int(episode_resolution)

    if anime_name not in episode_name:
        for anime_alt_name in anime_alt_names:
            if anime_alt_name in episode_name:
                episode_name = episode_name.replace(anime_alt_name.strip(), anime_name)

    if anime_name not in episode_name:
        return (None,)*4

    return original_episode_name.strip(), episode_name, episode_resolution, release_group

class GenerateFileName:

    def __init__(self, name, resolution, extra_tags={}, file_ext=None):
        self.name = name
        self.resolution = resolution
        self.extra_tags = extra_tags or {}
        self.file_ext = file_ext

    def get_extra_tags(self):
        extra_str = ''
        if self.extra_tags.get('others'):
            extra_str += self.extra_tags.get('others')
        if self.extra_tags.get('uncensored'):
            extra_str += '[Uncensored]'
        if self.extra_tags.get('bluray'):
            extra_str += '[BD]'
        return extra_str

    @property
    def batch(self):
        return '[SSA] {} {}[{}p][Batch]'.format(self.name, self.get_extra_tags(), self.resolution)

    @property
    def episode(self):
        if not self.file_ext:
            raise Exception('File extension not provided')
        return '[SSA] {} {}[{}p].{}'.format(self.name, self.get_extra_tags(), self.resolution, self.file_ext)


def purify_path(path):
    replace_args = [
        ('\\', '\\\\'),
        ('\'', "'\\\\\\''"),
        (':', '\\:'),
        ('[', '\\['),
        (']', '\\]'),
        ('-', '\\-')
    ]
    apath = os.path.abspath(path)
    for r_arg in replace_args:
        apath = apath.replace(*r_arg)
    return apath

def remove_duplicates(str_list):
    return list(set(str_list))

def flatten_trackers_tiers(tracker_list):
    return [item for sublist in tracker_list for item in sublist]

def find_episode_file(episode_obj):
    episode_dir = episode_dir = os.path.join(settings.MEDIA_ROOT, episode_obj.episode_path(''))

    if not os.path.exists(episode_dir):
        return None

    episode_files = [f for f in os.listdir(episode_dir) if os.path.isfile(os.path.join(episode_dir, f))]

    if not episode_files:
        return None

    return episode_obj.episode_path(os.path.basename(episode_files[0]))
