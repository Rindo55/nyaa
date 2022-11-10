import os

from django.contrib import admin
from django.db.models import Q
from django.conf import settings

from core import models, forms, tasks

def set_enabled(modeladmin, request, queryset):
    updates = queryset.update(enabled=True)
    message_bit = "Enabled %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_enabled.short_description = "Enable selected items"

def set_disabled(modeladmin, request, queryset):
    updates = queryset.update(enabled=False)
    message_bit = "Disabled %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_disabled.short_description = "Disable selected items"

def set_upload_torrent_enabled(modeladmin, request, queryset):
    updates = queryset.update(upload_torrent=True)
    message_bit = "Enabled torrent upload for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_upload_torrent_enabled.short_description = "Enable torrent upload for selected items"

def set_upload_torrent_disabled(modeladmin, request, queryset):
    updates = queryset.update(upload_torrent=False)
    message_bit = "Disabled torrent upload for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_upload_torrent_disabled.short_description = "Disable torrent upload for selected items"

def set_upload_last_episode_enabled(modeladmin, request, queryset):
    updates = queryset.update(upload_last_episode_torrent=True)
    message_bit = "Enabled last episode torrent upload for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_upload_last_episode_enabled.short_description = "Enable last episode torrent upload for selected items"

def set_upload_last_episode_disabled(modeladmin, request, queryset):
    updates = queryset.update(upload_last_episode_torrent=False)
    message_bit = "Disabled last episode torrent upload for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_upload_last_episode_disabled.short_description = "Disable last episode torrent upload for selected items"

def set_visible(modeladmin, request, queryset):
    updates = queryset.update(visible=True)
    message_bit = "Visibility set as visible for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_visible.short_description = "Set selected items as visible"

def set_invisible(modeladmin, request, queryset):
    updates = queryset.update(visible=False)
    message_bit = "Visibility set as invisible for %s item(s) successfully." % updates
    modeladmin.message_user(request, message_bit)
set_invisible.short_description = "Set selected items as invisible"

def clear_feed_data(modeladmin, request, queryset):
    updates = queryset.update(data=[])
    message_bit = "Feed data for %s item(s) were cleared successfully." % updates
    modeladmin.message_user(request, message_bit)
clear_feed_data.short_description = "Clear feed data for selected items"

def retry_torrent_upload(modeladmin, request, queryset):
    queryset = queryset.filter(torrent_status=2)
    for torrent_obj in queryset:
        tasks.do_torrent_upload.delay(torrent_obj.episode_id, torrent_obj.upload_site_id, None, None)
    message_bit = "Feed data for %s item(s) were cleared successfully." % queryset.count()
    modeladmin.message_user(request, message_bit)
retry_torrent_upload.short_description = "Retry torrent upload for selected items"

def reupload_seedbox(modeladmin, request, queryset):
    for episode in queryset:
        tasks.handle_seedbox_upload.delay(episode.id, os.path.join(settings.BASE_DIR, episode.file.path))
    message_bit = "%s episode(s) were successfully uploaded." % queryset.count()
    modeladmin.message_user(request, message_bit)
reupload_seedbox.short_description = "Reupload to Seedbox"

def upload_to_missing_sites(modeladmin, request, queryset):
    for batch_obj in queryset.order_by('file_name', 'resolution'):
        tasks.missing_batch_uploads.delay(batch_obj.id)
    message_bit = "Missing upload for %s item(s) were successfully tasked." % queryset.count()
    modeladmin.message_user(request, message_bit)
upload_to_missing_sites.short_description = "Upload batch to missing sites"

class BaseModelAdmin(admin.ModelAdmin):

    class Meta:
        abstract = True

    def get_readonly_fields(self, request, obj=None):
        if getattr(self, 'all_readonly_fields', None):
            extra_readonly_fields = list(set(
                [field.name for field in self.opts.local_fields] +
                [field.name for field in self.opts.local_many_to_many]
            ))
        else:
            extra_readonly_fields = ('uuid', 'added_at', 'modified_at')
        for extra_readonly in extra_readonly_fields:
            if extra_readonly not in self.readonly_fields:
                self.readonly_fields += (extra_readonly, )
        return self.readonly_fields

@admin.register(models.UploadSite)
class UploadSiteAdmin(BaseModelAdmin):
    save_on_top = True
    list_display = ['name', 'enabled', 'visible']

    actions = [
        set_enabled, set_disabled,
        set_visible, set_invisible
    ]

@admin.register(models.Feed)
class FeedAdmin(BaseModelAdmin):
    save_on_top = True
    list_display = ['anime', 'site', 'last_check_date', 'enabled', 'upload_torrent', 'upload_last_episode_torrent', 'url']
    list_filter = ['site']
    readonly_fields = ['last_check_date', 'data']
    autocomplete_fields = ['anime']
    search_fields = ['anime__title', 'url']
    radio_fields = {'site': admin.HORIZONTAL}

    actions = [
        set_enabled,
        set_disabled,
        set_upload_torrent_enabled,
        set_upload_torrent_disabled,
        set_upload_last_episode_enabled,
        set_upload_last_episode_disabled,
        clear_feed_data
    ]

@admin.register(models.Tracker)
class TrackerAdmin(BaseModelAdmin):
    pass

@admin.register(models.LinkSite)
class LinkSiteAdmin(BaseModelAdmin):
    search_fields = ['name']

@admin.register(models.AnimeLink)
class AnimeLinkAdmin(BaseModelAdmin):
    list_filter = ['site']
    autocomplete_fields = ['anime', 'site']

@admin.register(models.Anime)
class AnimeAdmin(BaseModelAdmin):
    list_display = ['title', 'thumbnail', 'added_at']
    search_fields = ['title']
    ordering = ['-added_at']

    fieldsets = (
        (None, {
            'fields': ('title', 'picture', 'picture_type', 'alt')
        }),
        ('Advanced Settings', {
            'classes': ('wide', 'extrapretty'),
            'fields': ('crf', 'smartblur', 'deblock', 'psy_rd', 'psy_rdoq', 'aq_strength'),
        }),
    )

@admin.register(models.TorrentFile)
class TorrentFileAdmin(BaseModelAdmin):
    list_display = ['file_name', 'upload_site', 'torrent_status']
    list_filter = ['upload_site', 'torrent_status']
    readonly_fields = ['upload_response_data']
    all_readonly_fields = not settings.DEBUG
    ordering = ['-added_at']

    actions = [
        retry_torrent_upload
    ]

@admin.register(models.TorrentShortLink)
class TorrentShortLink(BaseModelAdmin):
    pass

@admin.register(models.Screenshot)
class ScreenshotAdmin(BaseModelAdmin):
    list_display = ['thumbnail', 'episode']
    search_fields = ['anime__title', 'episode__name']
    ordering = ['-added_at']

@admin.register(models.EpisodeTitle)
class EpisodeTitle(BaseModelAdmin):
    search_fields = ['title', 'added_at']
    all_readonly_fields = not settings.DEBUG
    ordering = ['-added_at']

@admin.register(models.EpisodeInfo)
class EpisodeInfoAdmin(BaseModelAdmin):
    all_readonly_fields = not settings.DEBUG

@admin.register(models.Episode)
class EpisodeAdmin(BaseModelAdmin):
    list_display = ['name', 'resolution', 'release_group', 'episode_size', 'get_episode_status_display']
    list_filter = ['resolution', 'episode_status', 'info__release_group']
    list_select_related = ('info',)
    search_fields = ['anime__title', 'info__release_group', 'name']
    all_readonly_fields = not settings.DEBUG

    actions = [
        reupload_seedbox
    ]

    def release_group(self, obj):
        return obj.info.release_group

    def episode_size(self, obj):
        return obj.info.get_new_file_size() if obj.info.new_file_size > 0 else '-'

@admin.register(models.Batch)
class BatchAdmin(BaseModelAdmin):
    save_on_top = True
    form = forms.BatchForm

    list_display = ['name', 'resolution', 'bluray', 'get_batch_status_display']
    list_filter = ['resolution', 'batch_status']
    filter_horizontal = ('episodes', )
    autocomplete_fields = ['anime']
    search_fields = ['anime__title', 'name']
    readonly_fields = [
        'file_name', 'original_torrent_file', 'seedbox_torrent_file',
        'total_size', 'release_group', 'torrent_url', 'short_torrent_url',
        'magnet_url', 'short_magnet_url', 'batch_status', 'error_message',
        'subtype', 'screenshots'
    ]
    actions = [
        upload_to_missing_sites
    ]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "episodes":
            self_id = request.resolver_match.kwargs.get('object_id')
            if self_id:
                kwargs["queryset"] = models.Episode.objects.filter(Q(batch__id=self_id) | Q(batch=None))
            else:
                kwargs["queryset"] = models.Episode.objects.filter(batch=None)
        return super(BatchAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

@admin.register(models.BatchBundle)
class BatchBundleAdmin(BaseModelAdmin):
    save_on_top = True
    form = forms.BatchBundleForm

    list_display = ['name', 'resolutions', 'bluray']
    filter_horizontal = ('episodes', )
    readonly_fields = ['batches', 'subtype']
    autocomplete_fields = ['anime']
    search_fields = ['anime__title', 'name']

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "episodes":
            # self_id = request.resolver_match.kwargs.get('object_id')
            # if self_id:
            #     kwargs["queryset"] = models.EpisodeTitle.objects.filter(Q(batch__id=self_id) | Q(batch=None))
            # else:
            #     kwargs["queryset"] = models.EpisodeTitle.objects.filter(batch=None)

            kwargs["queryset"] = models.EpisodeTitle.objects.exclude(episodes=None)
        return super(BatchBundleAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

@admin.register(models.SiteWatcher)
class SiteWatcherAdmin(BaseModelAdmin):
    save_on_top = True

    list_display = ['url', 'site', 'last_check_date']
    readonly_fields = ['data']

    actions = [
        set_enabled,
        set_disabled,
        clear_feed_data
    ]

@admin.register(models.SeedBox)
class SeedBoxAdmin(BaseModelAdmin):

    def add_view(self, request, form_url='', extra_context=None):
        sb = models.SeedBox.objects.all().first()
        if sb:
            return self.change_view(request, object_id=str(sb.id))
        else:
            return super(SeedBoxAdmin, self).add_view(request, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.add_view(request)

@admin.register(models.AdflyCredential)
class AdflyCredentialAdmin(BaseModelAdmin):

    def add_view(self, request, form_url='', extra_context=None):
        ac = models.AdflyCredential.objects.all().first()
        if ac:
            return self.change_view(request, object_id=str(ac.id))
        else:
            return super(AdflyCredentialAdmin, self).add_view(request, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.add_view(request)

@admin.register(models.QBitTorrent)
class QBitTorrentAdmin(BaseModelAdmin):

    def add_view(self, request, form_url='', extra_context=None):
        qb = models.QBitTorrent.objects.all().first()
        if qb:
            return self.change_view(request, object_id=str(qb.id))
        else:
            return super(QBitTorrentAdmin, self).add_view(request, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.add_view(request)

@admin.register(models.PostTopic)
class PostTopicAdmin(BaseModelAdmin):
    list_display = ['name']

@admin.register(models.Post)
class PostAdmin(BaseModelAdmin):
    list_display = ['title', 'topic', 'anime']
    save_on_top = True

@admin.register(models.TextPage)
class TextPageAdmin(BaseModelAdmin):

    def add_view(self, request, form_url='', extra_context=None):
        ac = models.TextPage.objects.all().first()
        if ac:
            return self.change_view(request, object_id=str(ac.id))
        else:
            return super(TextPageAdmin, self).add_view(request, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.add_view(request)
