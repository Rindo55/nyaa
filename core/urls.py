from django.urls import path

from core import views

urlpatterns = [
    path('direct_download/batch/torrent/<uuid:batch_uuid>/<file_name>', views.download_batch_torrent, name='direct_download_batch_torrent'),
    path('download/batch/torrent/<uuid:batch_uuid>/<file_name>', views.download_batch_torrent, name='download_batch_torrent'),
    path('download/batch/magnet/<uuid:batch_uuid>', views.download_batch_magnet, name='download_batch_magnet'),

    path('direct_download/torrent/<uuid:episode_uuid>/<file_name>', views.download_torrent, name='direct_download_episode_torrent'),
    path('download/torrent/<uuid:episode_uuid>/<file_name>', views.download_torrent, name='download_episode_torrent'),
    path('download/magnet/<uuid:episode_uuid>', views.download_magnet, name='download_episode_magnet'),
    path('download/<uuid:episode_uuid>', views.download, name='download_episode'),
]
