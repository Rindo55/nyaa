import os
import uuid
import auto_prefetch
from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe

from tinymce.models import HTMLField
from multiselectfield import MultiSelectField

from automin.celery import app as celery_app
from core import feeders, utils, uploaders, watchers, tasks

SITE_CHOICES = models.TextChoices('Sites', ' '.join(feeders.__all__))
UPLOAD_CHOICES = models.TextChoices('Uploaders', ' '.join(uploaders.__all__))
RESOLUTION_CHOICES = (
    (1080, '1080p'),
    (720, '720p'),
    (480, '480p'),
)


class BaseModel(auto_prefetch.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, db_index=True)
    added_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class UploadSite(BaseModel):
    name = models.CharField(unique=True, max_length=200,
                            choices=UPLOAD_CHOICES.choices, db_index=True)
    api_url = models.URLField(max_length=1000)
    api_key = models.TextField()
    trackers = auto_prefetch.OneToOneField(
        'Tracker', on_delete=models.CASCADE, related_name='tracker')
    enabled = models.BooleanField(
        default=True, help_text='Disable to stop uploading to this site', db_index=True)
    visible = models.BooleanField(
        default=True, help_text='Set if links for this site should be shown on site', db_index=True)

    def __str__(self):
        return self.name

    def upload(self, *args, **kwargs):
        UploadClass = eval('uploaders.{}'.format(self.name))
        return UploadClass(
            api_url=self.api_url,
            api_key=self.api_key,
            *args,
            **kwargs
        ).upload()


class Feed(BaseModel):
    site = models.CharField(
        max_length=100, choices=SITE_CHOICES.choices, db_index=True)
    anime = auto_prefetch.ForeignKey(
        'Anime', on_delete=models.CASCADE, related_name='feeds')
    url = models.URLField(max_length=10000, unique=True)
    last_check_date = models.DateTimeField(
        default=timezone.now, editable=False, db_index=True)
    data = models.JSONField(default=list, editable=False)
    deinterlace = models.BooleanField(default=False)
    uncensored = models.BooleanField(default=False)
    bluray = models.BooleanField(default=False)
    upload_seedbox = models.BooleanField(
        default=True, help_text='Upload to seedbox', editable=settings.DEBUG)
    upload_torrent = models.BooleanField(
        default=False, help_text='Upload to torrent sites')
    upload_last_episode_torrent = models.BooleanField(
        default=False, help_text='Upload only last episode to torrent sites')
    extra_tags = models.TextField(blank=True, null=True)
    enabled = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return self.anime.title

    def update_data(self, data):
        self.data = data
        self.save()

    def update_last_check(self):
        self.last_check_date = timezone.now()
        self.save()

# class BatchFeed(BaseModel):
#     site = models.CharField(max_length=100, choices=SITE_CHOICES.choices, db_index=True)
#     anime = auto_prefetch.ForeignKey('Anime', on_delete=models.CASCADE, related_name='feeds')
#     url = models.URLField(max_length=10000, unique=True)
#     last_check_date = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
#     data = models.JSONField(default=list, editable=False)
#     bluray = models.BooleanField(default=False)
#     upload_seedbox = models.BooleanField(default=True, help_text='Upload to seedbox')
#     upload_torrent = models.BooleanField(default=False, help_text='Upload to torrent sites')
#     upload_last_episode_torrent = models.BooleanField(default=False, help_text='Upload only last episode to torrent sites')
#     enabled = models.BooleanField(default=True, db_index=True)
#
#     BATCH_FEED_STATUSES = (
#         ('add', 'Added'),
#         ('dl', 'Downloading'),
#         ('ee', 'Encoding Episodes'),
#         ('err', 'Error'),
#     )
#     status = models.CharField(max_length=100, choices=BATCH_FEED_STATUSES)
#
#     def __str__(self):
#         return self.anime.title
#
#     def update_data(self, data):
#         self.data = data
#         self.save()
#
#     def update_last_check(self):
#         self.last_check_date = timezone.now()
#         self.save()


class SiteWatcher(BaseModel):
    enabled = models.BooleanField(default=True, db_index=True)

    site = models.CharField(
        max_length=100, choices=SITE_CHOICES.choices, db_index=True)
    last_check_date = models.DateTimeField(
        default=timezone.now, editable=False, db_index=True)
    offset_seconds = models.PositiveIntegerField(default=0)
    add_missing = models.BooleanField(
        default=False, help_text='Automatically add missing anime?')
    url = models.URLField(max_length=1000)

    data = models.JSONField(default=list)

    def __str__(self):
        return str(self.get_site_display())

    def check_updates(self):
        WatchClass = eval('watchers.{}Watcher'.format(self.site))
        return WatchClass(self.id).check_updates()

    def update_last_check(self):
        self.last_check_date = timezone.now()
        self.save()


class Tracker(BaseModel):
    trackers = models.TextField(help_text='Use next line to seperate trackers')

    def __str__(self):
        return self.get_trackers()[0]

    def save(self, *args, **kwargs):
        self.trackers = '\n'.join(utils.remove_duplicates(self.get_trackers()))
        super(type(self), self).save(*args, **kwargs)

    def get_trackers(self):
        return [t.strip() for t in self.trackers.split('\n')]


class Anime(BaseModel):
    title = models.CharField(unique=True, max_length=1000, db_index=True)
    feed_title = models.CharField(
        unique=True, blank=True, null=True, max_length=1000, db_index=True)

    def image_path(self, filename):
        return os.path.join('anime', str(self.uuid), filename)

    picture = models.ImageField(upload_to=image_path)

    PICTURE_CHOICES = (
        (False, 'Landscape'), (True, 'Portrait')
    )
    picture_type = models.BooleanField(default=False, choices=PICTURE_CHOICES)
    alt = models.TextField(help_text='Seperate by lines',
                           blank=True, null=True)

    #settings
    crf = models.FloatField(default=24.2)
    smartblur = models.BooleanField(default=True)

    DEBLOCK_CHOICES = (
        ('-2,-2', 'Lighter Lighter (-2,-2)'),
        ('-2,-1', 'Lighter Light (-2,-1)'),
        ('-2,0', 'Lighter Disabled (-2,0)'),
        ('-2,1', 'Lighter Medium (-2,1)'),
        # ('-1,-2', 'Light Lighter (-1,-2)'),
        ('-1,-1', 'Light Light (-1,-1)'),
        ('-1,0', 'Light Disabled (-1,0)'),
        ('-1,1', 'Light Medium (-1,1)'),
        # ('0,-2', 'Disabled Lighter (0,-2)'),
        # ('0,-1', 'Disabled Light (0,-1)'),
        ('0,0', 'Disabled (0,0)'),
        ('1,0', 'Medium Disabled (1,0) (Recommended Minimum)'),
        ('1,1', 'Medium (1,1) (Default)'),
        ('2,2', 'Strong (2,2) (Not Recommended)'),
    )
    deblock = models.CharField(
        max_length=50, default='1,1', choices=DEBLOCK_CHOICES)

    PSY_RD_CHOICES = (
        (1.0, '1 - Minimum'),
        (1.25, '1.25 - Mildly Strong'),
        (1.5, '1.5 - Recommended'),
        (2.0, '2 - Very Strong'),
    )
    psy_rd = models.FloatField(
        default=1, verbose_name='psy-rd', choices=PSY_RD_CHOICES)

    PSY_RDOQ_CHOICES = (
        (1.0, '1 - Recommended'),
        (1.5, '1.5 - Light'),
        (2.0, '2.0 - Movie'),
        (3.0, '3.0 - Strong'),
        (4.0, '3.0 - Too Strong (Not Recommended)'),
    )
    psy_rdoq = models.FloatField(
        default=1, verbose_name='psy-rdoq', choices=PSY_RDOQ_CHOICES)

    AQ_STRENGTH_CHOICES = (
        (0.7, '0.7 - Movie with less dark scenes'),
        (0.8, '0.8'),
        (0.9, '0.9 - Movie with more dark scenes'),
        (1.0, '1 - Medium'),
        (1.25, '1.25 - Recommended'),
    )
    aq_strength = models.FloatField(
        default=1, verbose_name='aq-strength', choices=AQ_STRENGTH_CHOICES)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def create_using_json(data):
        anime_obj = Anime.objects.filter(title__iexact=data['title']).first()
        if not anime_obj:
            anime_obj = Anime(title=data['title'],
                              picture_type=data['pic_type'])
            image_data = data['image_data']
            image_data.seek(0)
            anime_obj.picture.save(data['image_name'], image_data, save=False)
            anime_obj.save()
        return anime_obj

    def get_settings(self):
        return {
            'crf': self.crf,
            'smartblur': self.smartblur,
            'deblock': self.deblock,
            'psy_rd': self.psy_rd,
            'psy_rdoq': self.psy_rdoq,
            'aq_strength': self.aq_strength,
        }

    def get_alt_names(self):
        return [t.strip() for t in self.alt.split('\n') if t] if self.alt else []

    def thumbnail(self):
        return mark_safe(f'<img src="{self.picture.url}" alt="{self.title}" width="300"/>')


class LinkSite(BaseModel):
    name = models.CharField(max_length=250, unique=True, db_index=True)

    def path(self, filename):
        return os.path.join('logo', str(self.uuid), filename)

    logo = models.ImageField(upload_to=path)

    def __str__(self):
        return self.name


class AnimeLink(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='links', db_index=True)
    site = auto_prefetch.ForeignKey(
        LinkSite, on_delete=models.CASCADE, related_name='links', db_index=True)
    url = models.URLField(max_length=10000)

    class Meta:
        unique_together = ('site', 'url')

    def __str__(self):
        return self.anime.title


class TorrentFile(BaseModel):
    episode = auto_prefetch.ForeignKey(
        'Episode', on_delete=models.CASCADE, blank=True, null=True, related_name='torrent_files')
    batch = auto_prefetch.ForeignKey(
        'Batch', on_delete=models.CASCADE, blank=True, null=True, related_name='torrent_files')
    upload_site = auto_prefetch.ForeignKey(
        UploadSite, on_delete=models.CASCADE, related_name='torrent_files', db_index=True)
    torrent_url = models.URLField(max_length=1000, blank=True, null=True)
    magnet_url = models.TextField(blank=True, null=True)
    trackers = models.TextField()

    TORRENT_STATUSES = (
        (0, 'Torrent Saved'),
        (1, 'Torrent Uploaded'),
        (2, 'Error')
    )

    torrent_status = models.IntegerField(default=0, choices=TORRENT_STATUSES)
    error_message = models.TextField(blank=True, null=True)

    def path(self, filename):
        return os.path.join('t', str(self.uuid), filename)

    file = models.FileField(upload_to=path, blank=True, null=True)
    file_name = models.TextField(blank=True, null=True)
    upload_response_data = models.JSONField(default=list, editable=False)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.CheckConstraint(
                check=models.Q(episode__isnull=False) | models.Q(
                    batch__isnull=False),
                name='not_both_null'
            )
        ]

    def __str__(self):
        return self.episode.name if self.episode else self.batch.name

    def set_torrent_status(self, status_number):
        self.torrent_status = status_number
        self.save()


class TorrentShortLink(BaseModel):
    torrent_file = auto_prefetch.OneToOneField(
        TorrentFile, on_delete=models.CASCADE, related_name='short_urls', db_index=True)
    short_torrent_url = models.URLField(max_length=1000)
    short_magnet_url = models.URLField(max_length=1000)

    def __str__(self):
        return self.torrent_file.__str__()


class EpisodeTitle(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='episode_titles', db_index=True)
    title = models.TextField(unique=True)

    class Meta:
        ordering = ['-title']

    def __str__(self):
        return self.title


class Episode(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='episodes', db_index=True)
    title = auto_prefetch.ForeignKey(
        EpisodeTitle, on_delete=models.CASCADE, related_name='episodes', db_index=True)
    name = models.TextField()
    uncensored = models.BooleanField(default=False)
    bluray = models.BooleanField(default=False)
    published_at = models.DateTimeField(
        blank=True, null=True, editable=False, db_index=True)

    SUBTYPES = (
        ('hardsubs', 'Hardsubs'),
        ('softsubs', 'Softsubs'),
    )
    subtype = models.CharField(
        max_length=100, default='softsubs', choices=SUBTYPES)
    resolution = models.IntegerField(
        default=1080, choices=RESOLUTION_CHOICES, db_index=True)
    old_file_name = models.TextField()
    file_name = models.TextField()

    def torrent_path(self, filename):
        return os.path.join('ot', str(self.uuid), filename)

    def seedbox_torrent_path(self, filename):
        return os.path.join('sb', str(self.uuid), filename)

    original_torrent_file = models.FileField(
        upload_to=torrent_path, blank=True, null=True)
    seedbox_torrent_file = models.FileField(
        upload_to=seedbox_torrent_path, blank=True, null=True)

    def episode_path(self, filename):
        return os.path.join('e', str(self.uuid), filename)

    def original_episode_path():
        return utils.create_and_get_path(os.path.join(settings.BASE_DIR, 'episodes'))

    file = models.FileField(upload_to=episode_path, blank=True, null=True)

    watch_url = models.URLField(max_length=10000, blank=True, null=True)
    short_watch_url = models.URLField(max_length=10000, blank=True, null=True)

    download_url = models.URLField(max_length=10000, blank=True, null=True)
    short_download_url = models.URLField(
        max_length=10000, blank=True, null=True)

    torrent_url = models.URLField(max_length=10000, blank=True, null=True)
    short_torrent_url = models.URLField(
        max_length=10000, blank=True, null=True)

    magnet_url = models.URLField(max_length=10000, blank=True, null=True)
    short_magnet_url = models.URLField(max_length=10000, blank=True, null=True)

    EPISODE_STATUSES = (
        ('dlfin', 'Downloaded'),
        ('enc', 'Encoding'),
        ('genscr', 'Generating Screenshots'),
        ('ups', 'Uploading to Seedbox'),
        ('upt', 'Uploading Torrent'),
        ('fin', 'Finished'),
        ('err', 'Error'),
    )
    episode_status = models.CharField(
        max_length=50, default='dlfin', choices=EPISODE_STATUSES, db_index=True)

    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-added_at']

    def __str__(self):
        episode_str = str(self.get_resolution_display())
        episode_str += ' | {}'.format(self.name)
        if self.uncensored:
            episode_str += ' | Uncensored'
        if self.info and self.info.release_group:
            episode_str += ' | {}'.format(self.info.release_group)
        return episode_str

    @property
    def thumbnail(self):
        thumb = self.screenshots.first()
        return thumb.picture if thumb else None


class Batch(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='batches', db_index=True)
    episodes = models.ManyToManyField(Episode, related_name='batch')
    name = models.TextField(blank=True, null=True)
    file_name = models.TextField(blank=True, null=True)
    uncensored = models.BooleanField(default=False)
    bluray = models.BooleanField(default=False)
    published_at = models.DateTimeField(
        blank=True, null=True, editable=False, db_index=True)

    SUBTYPES = (
        ('hardsubs', 'Hardsubs'),
        ('softsubs', 'Softsubs'),
    )
    subtype = models.CharField(
        max_length=100, default='softsubs', choices=SUBTYPES)
    resolution = models.IntegerField(
        default=1080, choices=RESOLUTION_CHOICES, db_index=True)
    screenshots = models.ManyToManyField('Screenshot', blank=True)

    def torrent_path(self, filename):
        return os.path.join('batch', str(self.uuid), 'ot', filename)

    def seedbox_torrent_path(self, filename):
        return os.path.join('batch', str(self.uuid), 'sb', filename)

    original_torrent_file = models.FileField(
        upload_to=torrent_path, blank=True, null=True)
    seedbox_torrent_file = models.FileField(
        upload_to=seedbox_torrent_path, blank=True, null=True)

    def batch_path(self, filename):
        return os.path.join('batch', str(self.uuid), filename)

    total_size = models.BigIntegerField(default=0)
    release_group = models.CharField(max_length=1000, blank=True, null=True)

    torrent_url = models.URLField(max_length=10000, blank=True, null=True)
    short_torrent_url = models.URLField(
        max_length=10000, blank=True, null=True)

    magnet_url = models.URLField(max_length=10000, blank=True, null=True)
    short_magnet_url = models.URLField(max_length=10000, blank=True, null=True)

    BATCH_STATUSES = (
        (0, 'Added'),
        (1, 'Collecting Files'),
        (2, 'Uploading Torrent'),
        (3, 'Finished'),
        (4, 'Error')
    )
    batch_status = models.IntegerField(
        default=0, choices=BATCH_STATUSES, db_index=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-added_at']
        verbose_name_plural = 'Batches'
        unique_together = ('anime', 'name', 'resolution', 'bluray')

    def __str__(self):
        return self.name or self.anime.title

    def clean(self):
        if self.anime and not self.name:
            self.name = self.anime.title

    def save(self, *args, **kwargs):
        adding = self._state.adding
        super(Batch, self).save(*args, **kwargs)

        if adding:
            tasks.handle_batch.apply_async((self.id,), countdown=60)

    def get_total_file_size(self):
        return utils.humansize(self.total_size)


class BatchBundle(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='batchebundles', db_index=True)
    episodes = models.ManyToManyField(EpisodeTitle, related_name='batchbundle')
    name = models.TextField(blank=True, null=True)
    resolutions = MultiSelectField(
        choices=RESOLUTION_CHOICES, max_choices=3, max_length=100, default=['1080', '720', '480'])
    uncensored = models.BooleanField(default=False)
    bluray = models.BooleanField(default=False)
    published_at = models.DateTimeField(
        blank=True, null=True, editable=False, db_index=True)

    batches = models.ManyToManyField(Batch, related_name='batches', blank=True)

    SUBTYPES = (
        ('hardsubs', 'Hardsubs'),
        ('softsubs', 'Softsubs'),
    )
    subtype = models.CharField(
        max_length=100, default='softsubs', choices=SUBTYPES)

    class Meta:
        ordering = ['-added_at']
        unique_together = ('anime', 'name', 'uncensored', 'bluray')

    def clean(self):
        if self.anime and not self.name:
            self.name = self.anime.title


class Screenshot(BaseModel):
    anime = auto_prefetch.ForeignKey(
        Anime, on_delete=models.CASCADE, related_name='screenshots', db_index=True)
    episode = auto_prefetch.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name='screenshots', db_index=True)
    caption = models.CharField(blank=True, null=True, max_length=10000)

    def screenshot_path(self, filename):
        return os.path.join('screenshot', str(self.episode.uuid), filename)

    picture = models.ImageField(upload_to=screenshot_path)

    class Meta:
        ordering = ['added_at']

    def __str__(self):
        return self.episode.name

    def thumbnail(self):
        return mark_safe(f'<img src="{self.picture.url}" alt="{self.episode.name} | {self.episode.resolution}" width="400"/>')


class EpisodeInfo(BaseModel):
    episode = auto_prefetch.OneToOneField(
        Episode, on_delete=models.CASCADE, related_name='info', db_index=True)
    release_group = models.CharField(max_length=1000, db_index=True)
    original_torrent_url = models.URLField(
        max_length=1000, blank=True, null=True)
    original_magnet_url = models.TextField(
        max_length=10000, blank=True, null=True)
    original_file_size = models.BigIntegerField(default=0)
    new_file_size = models.BigIntegerField(default=0)

    class Meta:
        ordering = ['-modified_at']

    def __str__(self):
        return self.episode.name

    def get_original_file_size(self):
        return utils.humansize(self.original_file_size)

    def get_new_file_size(self):
        return utils.humansize(self.new_file_size)

    def __str__(self):
        return self.episode.name


class PostTopic(BaseModel):
    name = models.CharField(max_length=255, db_index=True)

    def __str__(self):
        return self.name


class Post(BaseModel):
    title = models.TextField(db_index=True)
    topic = models.ForeignKey(PostTopic, on_delete=models.CASCADE)
    anime = models.ForeignKey(
        Anime, on_delete=models.CASCADE, blank=True, null=True)

    BLOG_POST_STATUS = (
        ('draft', 'Draft'),
        ('published', 'Published')
    )
    publish_status = models.CharField(
        max_length=100, default='draft', choices=BLOG_POST_STATUS)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    content = HTMLField()

    def __str__(self):
        return self.title


class TextPage(BaseModel):
    announcement = HTMLField(blank=True, null=True)
    home_bottom_text = HTMLField(blank=True, null=True)
    request_text = HTMLField(blank=True, null=True)
    aboutus_text = HTMLField(blank=True, null=True)


class SeedBox(BaseModel):
    hostname = models.CharField(max_length=500, unique=True)
    alt_hostname = models.CharField(
        max_length=500, unique=True, blank=True, null=True)
    port = models.PositiveIntegerField(default=21)
    username = models.CharField(max_length=500, unique=True)
    password = models.CharField(max_length=500, unique=True)

    class Meta:
        verbose_name_plural = 'Seed Box'

    def __str__(self):
        return self.hostname

    def save(self, *args, **kwargs):
        if not self.pk and SeedBox.objects.exists():
            raise ValidationError('There can only be one Seedbox instance')
        return super(type(self), self).save(*args, **kwargs)


class AdflyCredential(BaseModel):
    user_id = models.CharField(max_length=250, unique=True)
    public_key = models.CharField(max_length=250, unique=True)
    secret_key = models.CharField(max_length=250, unique=True)

    def __str__(self):
        return self.user_id

    def save(self, *args, **kwargs):
        if not self.pk and AdflyCredential.objects.exists():
            raise ValidationError(
                'There can only be one Adfly Credential instance')
        return super(type(self), self).save(*args, **kwargs)


class QBitTorrent(BaseModel):
    host = models.CharField(default='localhost', max_length=500, unique=True)
    port = models.IntegerField(default=8080, unique=True)
    username = models.CharField(max_length=500, unique=True)
    password = models.CharField(max_length=500, unique=True)

    class Meta:
        verbose_name_plural = 'QBitTorrent'

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if not self.pk and QBitTorrent.objects.exists():
            raise ValidationError('There can only be one QBitTorrent instance')
        return super(type(self), self).save(*args, **kwargs)

# class Task(BaseModel):
#     name = models.CharField(max_length=2000)
#     episode = auto_prefetch.ForeignKey(Episode, on_delete=models.CASCADE)
#     task_id = models.CharField(max_length=100)
#
#     def __str__(self):
#         return self.episode.name
#
#     @property
#     def task_info(self):
#         return AsyncResult(self.task_id)
#
#     def task_info_string(self):
#         task_info = self.task_info
#         return str({
#             'STATE': task_info.state,
#             'INFO': task_info.info,
#         })
