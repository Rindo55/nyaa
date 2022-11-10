import os
import re
import time
import random
import traceback
import requests
from io import BytesIO
from ftplib import FTP, FTP_TLS
from urllib.parse import quote
from django.conf import settings
from django.utils import timezone
from django.core.files import File
from django.core.files.base import ContentFile

import feedparser
from adfly import AdflyApi
from pymediainfo import MediaInfo
from torrentool.api import Torrent

from automin.celery import app
from core import models, feeders, handlers, encoders, proxies, utils

task = app.task

def guv(obj):
    return obj.__class__.objects.get(pk=obj.pk)

def before_start():
    check_models = [
        models.Anime,
        models.SeedBox,
        models.Tracker,
        models.UploadSite,
        models.QBitTorrent,
        models.AdflyCredential
    ]

    for m in check_models:
        m_objs = m.objects.exists()
        if not m_objs:
            raise Exception(f'No {m.__name__} found')

def get_sb_session():
    seedbox_obj = models.SeedBox.objects.all().first()
    if not seedbox_obj:
        raise Exception('No seedboxes found')

    f = FTP_TLS()
    f.connect(seedbox_obj.hostname, seedbox_obj.port)
    f.login(seedbox_obj.username, seedbox_obj.password)
    f.prot_p()
    return f

def get_adfly_session():
    adfly_cred = models.AdflyCredential.objects.first()
    if not adfly_cred:
        raise Exception('No adfly credential found')

    return AdflyApi(
        user_id=adfly_cred.user_id,
        public_key=adfly_cred.public_key,
        secret_key=adfly_cred.secret_key,
    )

def do_seedbox_upload(args=[]):

    if not args:
        return

    seedbox_session = get_sb_session()

    for path, content in args:
        seedbox_session.storbinary(path, content)

    seedbox_session.quit()

@task
def do_torrent_upload(episode_id, upload_site_id, adfly_api, video_path):
    adfly_api = adfly_api or get_adfly_session()
    trackers = models.Tracker.objects.all()
    episode_obj = models.Episode.objects.get(id=episode_id)
    upload_site = models.UploadSite.objects.get(id=upload_site_id)
    file_name = episode_obj.file_name

    announce_urls = []
    announce_urls.extend(upload_site.trackers.get_trackers())
    for track in trackers.exclude(id=upload_site.trackers.id):
        announce_urls.extend(track.get_trackers())

    torrent_obj, created = models.TorrentFile.objects.get_or_create(
        episode=episode_obj, upload_site=upload_site
    )

    if not created:
        new_torrent = Torrent.from_string(torrent_obj.file.read())
    else:
        new_torrent = Torrent.create_from(video_path)
        new_torrent.announce_urls = announce_urls

    torrent_obj.file_name = f'{file_name}.torrent'
    torrent_obj.magnet_url = new_torrent.get_magnet()
    torrent_obj.trackers = '\n'.join(announce_urls)
    if torrent_obj.file:
        torrent_obj.file.delete(save=False)
        torrent_obj.save()
    torrent_obj.file.save(f'{file_name}.torrent', ContentFile(new_torrent.to_string()), save=False)
    torrent_obj.save()

    try:
        upload_response = utils.retry(upload_site.upload, func_kwargs=dict(
            torrent_name=f'{file_name}.torrent',
            torrent_file=new_torrent.to_string(),
            resolution=episode_obj.resolution,
            release_group=episode_obj.info.release_group,
            screenshot_urls=['https://ssanime.ga' + s.picture.url for s in episode_obj.screenshots.all()],
            subtype=episode_obj.subtype,
            torrent_file_url=episode_obj.torrent_url.replace('/download/torrent/', '/direct_download/torrent/'),
        ), wait=60*5)
        if not upload_response:
            raise Exception(f'Error upload torrent {file_name}.torrent')
    except:
        torrent_obj.torrent_status = 2
        torrent_obj.error_message = traceback.format_exc()
        torrent_obj.save()
        return False

    torrent_url, upload_response_data = upload_response
    torrent_obj.torrent_url = torrent_url
    torrent_obj.upload_response_data = upload_response_data
    torrent_obj.torrent_status = 1
    torrent_obj.save()

    short_urls = {
        'data':[
            {'short_url': torrent_obj.torrent_url},
            {'short_url': torrent_obj.magnet_url}
        ]
    }
    try:
        short_urls = adfly_api.shorten([
            torrent_obj.torrent_url,
            torrent_obj.magnet_url,
        ])
    except:
        traceback.print_exc()

    short_urls = short_urls['data']

    torrent_link_obj = models.TorrentShortLink()
    torrent_link_obj.torrent_file = torrent_obj
    torrent_link_obj.short_torrent_url = short_urls[0]['short_url']
    torrent_link_obj.short_magnet_url = short_urls[1]['short_url']
    torrent_link_obj.save()
    return True

@task
def handle_seedbox_upload(episode_id, video_path):
    episode_obj = models.Episode.objects.get(id=episode_id)
    seedbox_torrent_file = episode_obj.seedbox_torrent_file

    if not seedbox_torrent_file:
        raise FileNotFoundError('Seedbox torrent file not found')

    file_name = episode_obj.file_name

    do_seedbox_upload([
        (f'STOR /home/username/files/{file_name}', open(video_path, 'rb')),
        (f'STOR /home/username/rwatch/{file_name}.torrent', BytesIO(seedbox_torrent_file.read()))
    ])

def handle_torrent_upload(adfly_api, episode_id, video_path):

    for upload_site in models.UploadSite.objects.filter(enabled=True):
        do_torrent_upload(episode_id, upload_site.id, adfly_api, video_path)

@task
def generate_episode_screenshots(episode_id, output_file_path):
    episode_obj = models.Episode.objects.get(pk=episode_id)

    screenshot_files = encoders.GenerateScreenshots(output_file_path, episode_obj.subtype).output_files

    for screenshot_file_name, screenshot_file in screenshot_files:
        screenshot_obj = models.Screenshot()
        screenshot_obj.anime = episode_obj.anime
        screenshot_obj.episode = episode_obj
        screenshot_obj.picture.save(screenshot_file_name, screenshot_file, save=False)
        screenshot_obj.save()

def encode_video(task_instance, adfly_api, episode_id, file_path, output_file_path, episode_config):
    file_name = os.path.basename(file_path)
    output_file_name = os.path.basename(output_file_path)

    episode_obj = models.Episode.objects.get(pk=episode_id)

    episode_obj.episode_status = 'enc'
    episode_obj.save()

    if episode_config['hardsubs'] is True:
        encode_file_size = encoders.EncodeVideoMP4(
            file_path, output_file_path, episode_config
        ).file_size
    else:
        encode_file_size = encoders.EncodeVideoMKV(
            file_path, output_file_path, episode_config
        ).file_size

    if not os.path.exists(output_file_path):
        raise Exception('Encoded episode not found at output path')

    episode_obj.file.save(output_file_name, open(output_file_path, 'rb'), save=False)
    episode_obj.save()

    episode_obj.info.new_file_size = encode_file_size
    episode_obj.episode_status = 'genscr'
    episode_obj.info.save()

    try:
        generate_episode_screenshots(episode_id, episode_obj.file.path)
    except:
        episode_obj.error_message = traceback.format_exc()
        episode_obj.save()

@task(bind=True)
def handle_feed(self, feed_id):

    before_start()

    adfly_api = get_adfly_session()

    feed_obj = models.Feed.objects.get(pk=feed_id)
    anime_obj = feed_obj.anime
    feed_updates = feed_obj.data

    for feed_iter, feed_update in enumerate(feed_updates):
        if not guv(feed_obj).enabled:
            break

        title = feed_update['title'].strip()
        torrent_magnet = feed_update['torrent_magnet']
        torrent_url = feed_update['torrent_url']

        original_episode_name, episode_name, episode_resolution, release_group = \
            utils.extract_names(title, feed_obj.anime.title, feed_obj.anime.get_alt_names())

        if not (original_episode_name and episode_name and episode_resolution and release_group):
            print('Error extracting names')
            continue

        if episode_resolution != 1080:
            continue

        all_resolutions = [1080, 720, 480]

        existing_episodes = {
            res: models.Episode.objects.filter(
                anime=anime_obj,
                resolution=res,
                name__icontains=episode_name,
                bluray=feed_obj.bluray,
                uncensored=feed_obj.uncensored,
                info__release_group=release_group,
            ).exists() for res in all_resolutions
        }

        if all(existing_episodes.values()):
            continue

        ot_torrent, ot_name = None, ''
        if torrent_url:
            ot_file = requests.get(
                torrent_url,
                headers=utils.get_header(),
                **(proxies.proxies if feed_obj.site == 'NyaaSi' else {})
            ).content
            ot_torrent = Torrent.from_string(ot_file)
            ot_name = f'{ot_torrent.name}.torrent'

            episode_dl = handlers.DownloadEpisode(
                torrent_file=ot_file
            ).download()
        else:
            episode_dl = handlers.DownloadEpisode(
                magnet_url=torrent_magnet
            ).download_from_magnet()

            ot_name = episode_dl['file_name']
            ot_name = f'{ot_name}.torrent'

        episode_dl_file_name, episode_dl_file_path, episode_dl_file_size = \
            episode_dl['file_name'], episode_dl['file_path'], episode_dl['file_size']

        episode_dl_info = MediaInfo.parse(filename=episode_dl_file_path)

        for episode_resolution in all_resolutions:

            if models.Episode.objects.filter(
                    anime=anime_obj,
                    resolution=episode_resolution,
                    name__icontains=episode_name,
                    bluray=feed_obj.bluray,
                    uncensored=feed_obj.uncensored,
                    info__release_group=release_group,
                ).exists():
                continue

            new_episode_title, created = models.EpisodeTitle.objects.get_or_create(
                anime=anime_obj, title=episode_name
            )

            new_episode = models.Episode()

            new_episode.name = episode_name
            new_episode.title = new_episode_title
            new_episode.resolution = episode_resolution
            new_episode.anime = anime_obj
            if episode_dl_info.text_tracks:
                new_episode.subtype = 'softsubs'
            else:
                new_episode.subtype = 'hardsubs'
            new_episode.bluray = feed_obj.bluray
            new_episode.uncensored = feed_obj.uncensored

            new_episode.old_file_name = original_episode_name

            if ot_torrent:
                new_episode.original_torrent_file.save(ot_name, ContentFile(ot_torrent.to_string()), save=False)

            new_name = utils.GenerateFileName(
                episode_name, episode_resolution,
                extra_tags={'bluray': feed_obj.bluray, 'uncensored': feed_obj.uncensored, 'others': guv(feed_obj).extra_tags},
                file_ext='mkv' if episode_dl_info.text_tracks else 'mp4',
            ).episode
            new_episode.file_name = new_name
            new_episode.save()

            new_episode_info = models.EpisodeInfo()
            new_episode_info.episode = new_episode
            new_episode_info.original_torrent_url = torrent_url
            new_episode_info.original_magnet_url = torrent_magnet
            new_episode_info.original_file_size = int(episode_dl['file_size'])
            new_episode_info.release_group = release_group
            new_episode_info.save()

            watch_url = f'{settings.SITE_URL}/watch/{new_episode.uuid}'
            download_url = f'{settings.SITE_URL}/download/{new_episode.uuid}'
            torrent_url = '{}/download/torrent/{}/{}.torrent'.format(settings.SITE_URL, new_episode.uuid, quote(new_episode.file_name))
            magnet_url = f'{settings.SITE_URL}/download/magnet/{new_episode.uuid}'

            new_episode.watch_url = watch_url
            new_episode.download_url = download_url
            new_episode.torrent_url = torrent_url
            new_episode.magnet_url = magnet_url
            new_episode.episode_status = 'dlfin'
            new_episode.save()

            output_file_path = os.path.join(utils.create_and_get_path(
                os.path.join(settings.BASE_DIR, 'episodes')
            ), new_name)

            try:
                encode_video(
                    self,
                    adfly_api,
                    new_episode.id,
                    episode_dl['file_path'],
                    output_file_path,
                    {
                        **anime_obj.get_settings(),
                        'resolution': episode_resolution,
                        'hardsubs': new_episode.subtype == 'hardsubs',
                        'deinterlace': feed_obj.deinterlace,
                    }
                )

                new_episode = models.Episode.objects.get(id=new_episode.id)

                seedbox_torrent_file = Torrent.create_from(output_file_path)

                all_announce_urls = []
                trackers = models.Tracker.objects.all()
                for track in trackers:
                    all_announce_urls.extend(track.get_trackers())
                seedbox_torrent_file.announce_urls = all_announce_urls

                new_episode.seedbox_torrent_file.save(f'{new_name}.torrent', ContentFile(seedbox_torrent_file.to_string()), save=False)
                new_episode.save()

                new_episode.episode_status = 'ups'
                new_episode.info.save()

                if guv(feed_obj).upload_seedbox:
                    utils.retry(handle_seedbox_upload, [new_episode.id, output_file_path])

                new_episode.episode_status = 'upt'
                new_episode.info.save()

                if guv(feed_obj).upload_torrent:
                    handle_torrent_upload(adfly_api, new_episode.id, output_file_path)
                else:
                    updated_feed_obj = guv(feed_obj)
                    if updated_feed_obj.upload_last_episode_torrent and (len(feed_updates)-1) == feed_iter:
                        handle_torrent_upload(adfly_api, new_episode.id, output_file_path)

            except Exception as e:
                new_episode.episode_status = 'err'
                new_episode.error_message = traceback.format_exc()
                new_episode.save()
                raise e

            short_urls = {
                'data':[
                    {'short_url': watch_url},
                    {'short_url': download_url},
                    {'short_url': torrent_url},
                    {'short_url': magnet_url}
                ]
            }

            try:
                short_urls = adfly_api.shorten([
                    watch_url, download_url, torrent_url, magnet_url
                ])
            except:
                traceback.print_exc()

            short_urls = short_urls['data']
            new_episode = models.Episode.objects.get(pk=new_episode.id)

            new_episode.episode_status = 'fin'
            new_episode.short_watch_url = short_urls[0]['short_url']
            new_episode.short_download_url = short_urls[1]['short_url']
            new_episode.short_torrent_url = short_urls[2]['short_url']
            new_episode.short_magnet_url = short_urls[3]['short_url']
            new_episode.published_at = timezone.now()
            new_episode.save()

            utils.check_and_delete(output_file_path)

        utils.check_and_delete(episode_dl['file_path'])

    feed_obj = guv(feed_obj)
    if feed_obj.upload_last_episode_torrent:
        feed_obj.upload_last_episode_torrent = False
        feed_obj.upload_torrent = True
        feed_obj.save()

@task
def check_feed_updates():
    for feed in models.Feed.objects.filter(enabled=True):
        fc = eval('feeders.{}'.format(feed.site))(feed.url)
        freq = fc.get_feed()
        if feed.data != freq:
            feed.update_data(freq)
            handle_feed.delay(feed.id)
        feed.update_last_check()
        time.sleep(30)

def handle_batch_upload(adfly_api, batch_id, batch_path, screenshots):
    batch_obj = models.Batch.objects.get(pk=batch_id)
    seedbox_torrent_file = batch_obj.seedbox_torrent_file

    seedbox_obj = models.SeedBox.objects.first()
    if not seedbox_obj:
        raise Exception('No seedboxes found')

    seedbox_addtorrent_url = f'https://{seedbox_obj.alt_hostname}/rutorrent/php/addtorrent.php'

    seedbox_session = requests.Session()
    seedbox_session.auth = (seedbox_obj.username, seedbox_obj.password)
    seedbox_session.post(f'https://{seedbox_obj.alt_hostname}/')

    data={
        'not_add_path': 1,
        'dir_edit': f'/home/{seedbox_obj.username}/files/'
    }
    files={
        'torrent_file': (f'{batch_obj.file_name}.torrent', seedbox_torrent_file.open('rb'))
    }

    seedbox_response = seedbox_session.post(seedbox_addtorrent_url, data=data, files=files, allow_redirects=False)

    if 'result[]=Success' not in seedbox_response.headers['Location']:
        raise Exception('Error uploading batch torrent file')

    trackers = models.Tracker.objects.all()

    for upload_site in models.UploadSite.objects.filter(enabled=True):
        if models.TorrentFile.objects.filter(batch=batch_obj, upload_site=upload_site).exists():
            continue

        new_torrent = Torrent.create_from(batch_path)
        new_torrent.name = batch_obj.file_name

        announce_urls = []
        announce_urls.extend(upload_site.trackers.get_trackers())
        for track in trackers.exclude(id=upload_site.trackers.id):
            announce_urls.extend(track.get_trackers())
        new_torrent.announce_urls = announce_urls

        torrent_obj = models.TorrentFile()
        torrent_obj.batch = batch_obj
        torrent_obj.upload_site = upload_site
        torrent_obj.file_name = f'{batch_obj.file_name}.torrent'
        torrent_obj.magnet_url = new_torrent.get_magnet()
        torrent_obj.trackers = '\n'.join(announce_urls)
        torrent_obj.file.save(f'{batch_obj.file_name}.torrent', ContentFile(new_torrent.to_string()), save=False)
        torrent_obj.save()

        upload_response = upload_site.upload(
            torrent_name=f'{batch_obj.file_name}.torrent',
            torrent_file=new_torrent.to_string(),
            resolution=batch_obj.resolution,
            release_group=batch_obj.release_group,
            torrent_file_url=batch_obj.torrent_url.replace('/download/batch/', '/direct_download/batch/'),
            screenshot_urls=screenshots,
            subtype=batch_obj.subtype,
            batch=True,
        )

        if not upload_response:
            torrent_obj.set_torrent_status(2)
            raise Exception(f'Error uploading {batch_obj.file_name}.torrent file.')

        torrent_url, upload_response_data = upload_response
        torrent_obj.torrent_url = torrent_url
        torrent_obj.upload_response_data = upload_response_data
        torrent_obj.torrent_status = 1
        torrent_obj.save()

        short_urls = {
            'data':[
                {'short_url': torrent_obj.torrent_url},
                {'short_url': torrent_obj.magnet_url}
            ]
        }
        try:
            short_urls = adfly_api.shorten([
                torrent_obj.torrent_url,
                torrent_obj.magnet_url,
            ])
        except:
            traceback.print_exc()

        short_urls = short_urls['data']

        torrent_link_obj = models.TorrentShortLink()
        torrent_link_obj.torrent_file = torrent_obj
        torrent_link_obj.short_torrent_url = short_urls[0]['short_url']
        torrent_link_obj.short_magnet_url = short_urls[1]['short_url']
        torrent_link_obj.save()

def set_batch_screenshots(batch_id):
    batch_obj = models.Batch.objects.get(pk=batch_id)

    screenshots = []
    for episode in batch_obj.episodes.all():
        episodes_ss = [s for s in episode.screenshots.all()]
        screenshots.extend(episodes_ss)

    if not screenshots:
        return []

    filtered_screenshots = []
    for i in range(5):
        rand_ss = random.choice(screenshots)
        while rand_ss in filtered_screenshots:
            rand_ss = random.choice(screenshots)
        filtered_screenshots.append(rand_ss)

    for s in filtered_screenshots:
        batch_obj.screenshots.add(s)
    batch_obj.save()

    return ['https://ssanime.ga' + s.picture.url for s in filtered_screenshots]

@task
def missing_batch_uploads(batch_id):
    adfly_api = get_adfly_session()

    batch_obj = models.Batch.objects.get(pk=batch_id)

    batch_path = utils.create_and_get_path(
        os.path.join(
            utils.create_and_get_path(os.path.join(settings.BASE_DIR, 'batches')),
            str(batch_obj.uuid)
        )
    )

    for episode in batch_obj.episodes.all():
        be_file_path = os.path.join(batch_path, episode.file_name)
        be_file = open(be_file_path, 'wb')
        be_file.write(episode.file.read())

    seedbox_torrent_file = Torrent.create_from(batch_path)
    seedbox_torrent_file.name = batch_obj.file_name

    all_announce_urls = []
    trackers = models.Tracker.objects.all()
    for track in trackers:
        all_announce_urls.extend(track.get_trackers())
    seedbox_torrent_file.announce_urls = all_announce_urls

    batch_obj.seedbox_torrent_file.save(f'{batch_obj.file_name}.torrent', ContentFile(seedbox_torrent_file.to_string()), save=False)
    batch_obj.save()

    handle_batch_upload(adfly_api, batch_id, batch_path, batch_obj.screenshots or set_batch_screenshots(batch_id))

    utils.check_and_delete_dir(batch_path)

@task
def handle_batch(batch_id):
    adfly_api = get_adfly_session()

    batch_obj = models.Batch.objects.get(pk=batch_id)
    batch_obj.batch_status = 1
    batch_obj.save()

    batch_path = utils.create_and_get_path(
        os.path.join(
            utils.create_and_get_path(os.path.join(settings.BASE_DIR, 'batches')),
            str(batch_obj.uuid)
        )
    )

    subtypes = []
    for episode in batch_obj.episodes.all():
        subtypes.append(episode.subtype)
        be_file_path = os.path.join(batch_path, episode.file_name)
        be_file = open(be_file_path, 'wb')
        be_file.write(episode.file.read())

    subtypes = utils.remove_duplicates(subtypes)
    batch_obj.subtypes = subtypes[0]

    batch_obj.batch_status = 2
    batch_obj.save()

    file_name = utils.GenerateFileName(
        batch_obj.name, batch_obj.resolution,
        extra_tags={'bluray': batch_obj.bluray, 'uncensored': batch_obj.uncensored}
    ).batch
    release_group = ', '.join(list(batch_obj.episodes.order_by().values_list('info__release_group', flat=True).distinct()))

    seedbox_torrent_file = Torrent.create_from(batch_path)
    seedbox_torrent_file.name = file_name

    batch_obj.file_name = file_name
    batch_obj.release_group = release_group
    batch_obj.total_size = seedbox_torrent_file.total_size

    torrent_url = '{}/download/batch/torrent/{}/{}.torrent'.format(settings.SITE_URL, batch_obj.uuid, quote(batch_obj.file_name))
    magnet_url = f'{settings.SITE_URL}/download/batch/magnet/{batch_obj.uuid}'

    batch_obj.torrent_url = torrent_url
    batch_obj.magnet_url = magnet_url

    short_urls = {
        'data':[
            {'short_url': torrent_url},
            {'short_url': magnet_url}
        ]
    }

    try:
        short_urls = adfly_api.shorten([
            torrent_url,
            magnet_url,
        ])
    except:
        traceback.print_exc()

    short_urls = short_urls['data']

    batch_obj.short_torrent_url = short_urls[0]['short_url']
    batch_obj.short_magnet_url = short_urls[1]['short_url']

    all_announce_urls = []
    trackers = models.Tracker.objects.all()
    for track in trackers:
        all_announce_urls.extend(track.get_trackers())
    seedbox_torrent_file.announce_urls = all_announce_urls

    batch_obj.seedbox_torrent_file.save(f'{file_name}.torrent', ContentFile(seedbox_torrent_file.to_string()), save=False)
    batch_obj.save()

    try:
        handle_batch_upload(adfly_api, batch_id, batch_path, set_batch_screenshots(batch_id))
        batch_obj = models.Batch.objects.get(pk=batch_id)
    except Exception as e:
        batch_obj.error_message = traceback.format_exc()
        batch_obj.save()

    batch_obj.batch_status = 3
    batch_obj.published_at = timezone.now()
    batch_obj.save()

    utils.check_and_delete_dir(batch_path)

@task
def handle_batch_bundle(bb_id):
    bb = models.BatchBundle.objects.get(pk=bb_id)
    bb_resolutions = [int(res) for res in bb.resolutions]
    batches = []
    for res in bb_resolutions:
        episodes = []
        for et in bb.episodes.all():
            episodes.append(et.episodes.filter(resolution=res)[0])
        batch_obj, created = models.Batch.objects.get_or_create(
            name=bb.name,
            anime=bb.anime,
            resolution=res,
            uncensored=bb.uncensored,
            bluray=bb.bluray,
            subtype=bb.subtype,
        )
        if not created:
            continue
        batch_obj.episodes.set(episodes)
        batches.append(batch_obj)
    bb.batches.set(batches)

@task
def check_watcher_updates():
    watchers = models.SiteWatcher.objects.all()
    for w in watchers:
        updates = w.check_updates()


#SIDE TASKS

@task
def generate_short_urls():
    adfly_api = get_adfly_session()

    episodes = models.Episode.objects.filter(episode_status=4)

    for episode_obj in episodes:
        watch_url = f'{settings.SITE_URL}/watch/{episode_obj.uuid}'
        download_url = f'{settings.SITE_URL}/download/{episode_obj.uuid}'
        torrent_url = '{}/download/torrent/{}/{}.torrent'.format(settings.SITE_URL, episode_obj.uuid, quote(episode_obj.file_name))
        magnet_url = f'{settings.SITE_URL}/download/magnet/{episode_obj.uuid}'

        episode_obj.watch_url = watch_url
        episode_obj.download_url = download_url
        episode_obj.torrent_url = torrent_url
        episode_obj.magnet_url = magnet_url

        short_urls = adfly_api.shorten([
            torrent_url,
            magnet_url,
        ])

        short_urls = short_urls['data']

        episode_obj.short_torrent_url = short_urls[0]['short_url']
        episode_obj.short_magnet_url = short_urls[1]['short_url']
        episode_obj.save()
        time.sleep(60)

    batches = models.Batch.objects.filter(batch_status=3)

    for batch_obj in batches:
        torrent_url = '{}/download/batch/torrent/{}/{}.torrent'.format(settings.SITE_URL, batch_obj.uuid, quote(batch_obj.file_name))
        magnet_url = f'{settings.SITE_URL}/download/batch/magnet/{batch_obj.uuid}'

        batch_obj.torrent_url = torrent_url
        batch_obj.magnet_url = magnet_url

        short_urls = adfly_api.shorten([
            torrent_url,
            magnet_url,
        ])

        short_urls = short_urls['data']

        batch_obj.short_torrent_url = short_urls[0]['short_url']
        batch_obj.short_magnet_url = short_urls[1]['short_url']
        batch_obj.save()
        time.sleep(60)

@task
def generate_screenshots():
    episodes = models.Episode.objects.filter(episode_status=4, screenshots__isnull=True)

    for episode_obj in episodes:
        file_path = episode_obj.file.path
        screenshot_files = encoders.GenerateScreenshots(file_path).output_files

        for screenshot_file_name, screenshot_file in screenshot_files:
            screenshot_obj = models.Screenshot()
            screenshot_obj.anime = episode_obj.anime
            screenshot_obj.episode = episode_obj
            screenshot_obj.picture.save(screenshot_file_name, screenshot_file, save=False)
            screenshot_obj.save()

@task
def fix_episode_torrent_errors(episode_id):
    episodes = models.Episode.objects.get(id=episode_id)
    episode_path = os.path.join(utils.create_and_get_path(
        os.path.join(settings.BASE_DIR, 'episodes')
    ), episodes.file_name)

    utils.check_and_delete(episode_path)

@task
def fix_lost_files():
    episodes = models.Episode.objects.filter(episode_status=4, file='')

    for episode_obj in episodes:
        episode_path = utils.find_episode_file(episode_obj)

        if episode_path:
            episode_obj.file.name = episode_path
            episode_obj.save()
        else:
            seedbox_session = get_sb_session()

            ib = BytesIO()

            def set_bytes(data):
                ib.write(data)

            seedbox_session.retrbinary(f'RETR /files/{episode_obj.file_name}', set_bytes)
            seedbox_session.quit()

            ib.seek(0)
            episode_obj.file.save(episode_obj.file_name, ContentFile(ib.read()))
            episode_obj.save()
