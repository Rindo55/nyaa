from django import forms
from django.utils.translation import gettext_lazy as _

from . import models


class BatchForm(forms.ModelForm):

    class Meta:
        model = models.Batch
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        anime = cleaned_data.get('anime')
        episodes = cleaned_data.get('episodes')
        resolution = cleaned_data.get('resolution')
        subtype = cleaned_data.get('subtype')

        if not all(episode.anime == anime for episode in episodes):
            raise forms.ValidationError({
                'episodes': _('Episode and selected batch anime does not match')
            })

        e_res, e_subtype = None, None
        for episode in episodes:
            if not e_res:
                e_res = episode.resolution
            if not e_subtype:
                e_subtype = episode.subtype
            if episode.resolution != e_res:
                raise forms.ValidationError({
                    'episodes': _('All selected episodes are not of same resolution')
                })
            if episode.subtype != e_subtype:
                raise forms.ValidationError({
                    'episodes': _('All selected episodes are not of same subtitle type. Harsubs and Softsubs are mixed.')
                })

        if resolution != e_res:
            cleaned_data['resolution'] = e_res

        if subtype != e_subtype:
            cleaned_data['subtype'] = e_subtype

        return cleaned_data


class BatchBundleForm(forms.ModelForm):

    class Meta:
        model = models.BatchBundle
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        anime = cleaned_data.get('anime')
        episode_titles = cleaned_data.get('episodes')
        resolutions = [int(r) for r in cleaned_data.get('resolutions')]
        subtype = cleaned_data.get('subtype')

        if not all(episode.anime == anime for episode_title in episode_titles.all() for episode in episode_title.episodes.all()):
            raise forms.ValidationError({
                'episodes': _('Episode and selected batch anime does not match')
            })

        e_subtype = None
        for res in resolutions:
            for episode_title in episode_titles.all():
                found = False
                for episode in episode_title.episodes.filter(resolution=res):
                    found = True
                    if not e_subtype:
                        e_subtype = episode.subtype

                    if episode.subtype != e_subtype:
                        raise forms.ValidationError({
                            'episodes': _('All selected episodes are not of same subtitle type. Harsubs and Softsubs are mixed.')
                        })

                if not found:
                    raise forms.ValidationError({
                        'episodes': _('One or more of selected episode titles does not have the episode in the selected resolutions')
                    })

        cleaned_data['resolution'] = resolutions

        if subtype != e_subtype:
            cleaned_data['subtype'] = e_subtype

        return cleaned_data
