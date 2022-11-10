import os
import uuid
import random
from io import BytesIO

from django.conf import settings

import ffmpeg
from pymediainfo import MediaInfo

from core import utils


class BaseEncoder:

    def get_ffmpeg_args(self, audio_bitrate, audio_quality, crf, deblock, psy_rd, psy_rdoq, aq_strength, vf_args, params_args=[], extra_args={}):
        return {
            'c:a': 'aac',
            'c:v': 'libx265',
            'b:a': audio_bitrate,
            # 'qscale:a': audio_quality,
            'profile:v': 'main',
            'x265-params': ':'.join([
                'me=2',
                'rd=4',
                'subme=7',
                'aq-mode=3',
                f'aq-strength={aq_strength}',
                f'deblock={deblock}',
                f'psy-rd={psy_rd}',
                f'psy-rdoq={psy_rdoq}',
                'rdoq-level=2',
                'merange=57',
                'bframes=8',
                'b-adapt=2',
                'limit-sao=1',
                'frame-threads=3',
                'no-info=1',
                *params_args,
            ]),
            'crf': crf,
            'preset': 'slow',
            'pix_fmt': 'yuv420p',
            'vf': ','.join(vf_args),
            'metadata': 'Yugen',
            'color_range': 1,
            'color_primaries': 1,
            'colorspace': 1,
            'color_trc': 1,
            **extra_args,
        }

    def get_settings(self, subtitles_path, extra_args):
        crf = int(self.config['crf'])
        deblock = self.config['deblock']
        smartblur = self.config['smartblur']
        deinterlace = self.config['deinterlace']
        resolution = self.config['resolution']
        psy_rd = self.config['psy_rd']
        psy_rdoq = self.config['psy_rdoq']
        aq_strength = self.config['aq_strength']
        hardsubs = self.config['hardsubs']

        audio_bitrate, audio_quality, crf, vf_args = self.resolution_settings(
            resolution, crf)
        params_args = []

        if extra_args.get('f') == 'mp4' and not hardsubs:
            vf_args.append(f'subtitles=\'{subtitles_path}\'')

        if smartblur:
            vf_args.append('smartblur=1.5:-0.35:-3.5:0.65:0.25:2.0')

        if deinterlace:
            vf_args.append('yadif=1')
            params_args.append('fps=23976/1000')
            extra_args.update({'framerate': '23976/1000'})

        if not all([audio_bitrate, audio_quality, crf, deblock, psy_rd, psy_rdoq, aq_strength, vf_args]):
            raise Exception('Config value error')

        return self.get_ffmpeg_args(audio_bitrate, audio_quality, crf, deblock, psy_rd, psy_rdoq, aq_strength, vf_args, params_args, extra_args)

    def resolution_settings(self, resolution, crf):
        return {
            480: (
                '96k', 1.1, crf,
                ['scale=848:480:spline16+accurate_rnd+full_chroma_int']
            ),
            720: (
                '128k', 1.4, crf,
                ['scale=1280:720:spline16+accurate_rnd+full_chroma_int']
            ),
            1080: (
                '128k', 1.8, crf,
                ['scale=1920:1080:spline16+accurate_rnd+full_chroma_int']
            ),
        }.get(resolution)

    @property
    def exists(self):
        return os.path.exists(self.output_file_path)

    @property
    def size(self):
        return os.path.getsize(self.output_file_path) if self.exists else 0

    @property
    def valid(self):
        return self.size > 0


class EncodeVideoMP4(BaseEncoder):

    def __init__(self, file_path, output_file_path, config):
        super(EncodeVideoMP4, self).__init__()
        self.config = config
        self.output_file_path = output_file_path
        file_name = os.path.basename(file_path)
        file_path = os.path.abspath(str(file_path)).replace('\\', '\\\\')
        subtitles_path = utils.purify_path(file_path)
        output_file_path = os.path.abspath(
            str(output_file_path)).replace('\\', '\\\\')

        ffmpeg_arguments = self.get_settings(subtitles_path, {
            'f': 'mp4',
        })

        utils.check_and_delete(output_file_path)

        stream = ffmpeg.input(file_path)
        stream = ffmpeg.output(
            stream.video, stream.audio, output_file_path, **ffmpeg_arguments
        )
        stream = ffmpeg.overwrite_output(stream)
        ffmpeg.run(stream)

        if not self.valid:
            raise Exception(f'Episode file named {file_name} not encoded')

        self.file_size = os.path.getsize(self.output_file_path)


class EncodeVideoMKV(BaseEncoder):

    def __init__(self, file_path, output_file_path, config):
        super(EncodeVideoMKV, self).__init__()
        self.config = config
        self.output_file_path = output_file_path
        file_name = os.path.basename(file_path)
        file_path = os.path.abspath(str(file_path)).replace('\\', '\\\\')
        subtitles_path = utils.purify_path(file_path)
        output_file_path = os.path.abspath(
            str(output_file_path)).replace('\\', '\\\\')

        ffmpeg_arguments = self.get_settings(subtitles_path, {
            # 'c:t': 'copy',
            'map': '0:s?',
            # 'map': '0:t',
            # 'metadata:s:t': 'mimetype=application/x-truetype-font',
            'f': 'matroska',
        })

        utils.check_and_delete(output_file_path)

        stream = ffmpeg.input(file_path)
        stream = ffmpeg.output(
            stream.video, stream.audio, output_file_path, **ffmpeg_arguments
        )
        stream = ffmpeg.overwrite_output(stream)
        ffmpeg.run(stream)

        if not self.valid:
            raise Exception(f'Episode file named {file_name} not encoded')

        self.file_size = os.path.getsize(self.output_file_path)


class GenerateScreenshots:

    def __init__(self, file_path, subtype):
        self.output_dir_path = self.get_output_dir
        ofile_path = str(file_path)
        file_name = os.path.basename(file_path)
        file_path = os.path.abspath(str(file_path)).replace('\\', '\\\\')
        subtitles_path = utils.purify_path(file_path)

        file_info = MediaInfo.parse(filename=ofile_path)
        total_frames = int(file_info.video_tracks[0].frame_count)
        output_files, random_times = [], []

        for i in range(6):
            random_time = random.randint(24, total_frames-24)
            while random_time in random_times:
                random_time = random.randint(24, total_frames-24)
            random_times.append(random_time)

        random_times = sorted(random_times)

        for i, t in enumerate(random_times):
            output_file_name = '{}.jpg'.format(str(i).zfill(2))
            output_file_path = os.path.join(
                self.output_dir_path, output_file_name)
            stream = ffmpeg.input(file_path)
            vf_args = [f'select=eq(n\,{t})']

            if subtype == 'softsubs':
                vf_args.append(f'subtitles=\'{subtitles_path}\'')

            stream = ffmpeg.output(
                stream.video,
                output_file_path.replace('\\', '\\\\'),
                **{
                    'vf': ','.join(vf_args),
                    'vframes': 1,
                    'q:v': 2,
                }
            )
            stream = ffmpeg.overwrite_output(stream)
            ffmpeg.run(stream)

            output_files.append(
                (output_file_name, BytesIO(open(output_file_path, 'rb').read()))
            )

        utils.check_and_delete_dir(self.output_dir_path)

        self.output_files = output_files

    @property
    def get_output_dir(self):
        dir_name = str(uuid.uuid4())
        base_dir_path = utils.create_and_get_path(
            os.path.join(settings.BASE_DIR, 'screenshots')
        )
        return utils.create_and_get_path(
            os.path.join(base_dir_path, dir_name)
        )
