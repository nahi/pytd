
import contextlib
import requests
import msgpack
import zlib
import os

from six.moves import urllib

from .version import __version__

def http_get(uri, **kwargs):
    return requests.get(uri, **kwargs)

class ResultProxy(object):
    def __init__(self, context, job_id, download_callback=None):
        self.context = context
        self.job_id = job_id
        self.download_callback = download_callback

    @property
    def job(self):
        if not hasattr(self, '_job'):
            self._job = self.context.client.job(self.job_id)
        return self._job

    def status(self):
        return self.job.status()

    def wait(self, *args, **kwargs):
        return self.job.wait(*args, **kwargs)

    @property
    def result_size(self):
        if not self.job.finished():
            self.job.wait()
        return self.job.result_size

    @property
    def description(self):
        if not self.job.finished():
            self.job.wait()
        return self.job.result_schema

    def get_result(self):
        headers = {
            'Authorization': 'TD1 {0}'.format(self.context.apikey),
            'Accept-Encoding': 'deflate, gzip',
            'User-Agent': "pytd/{0} ({1})".format(__version__, requests.utils.default_user_agent()),
        }
        r = http_get('{endpoint}v3/job/result/{job_id}?format={format}'.format(
            endpoint = self.context.endpoint,
            job_id = self.job_id,
            format = 'msgpack.gz',
        ), headers=headers, stream=True)
        return r

    def iter_content(self, chunk_size):
        current_size = 0
        d = zlib.decompressobj(16+zlib.MAX_WBITS)
        with contextlib.closing(self.get_result()) as r:
            for chunk in r.iter_content(chunk_size):
                current_size += len(chunk)
                if self.download_callback:
                    self.download_callback(self, current_size)
                yield d.decompress(chunk)

    def read(self, size=16384):
        if not hasattr(self, '_iter'):
            self._iter = self.iter_content(size)
        try:
            return next(self._iter)
        except StopIteration:
            return ''

    def __iter__(self):
        # NOTE: Defined as a generator because Pandas DataFrame
        # does not support iterators as data.
        # NOTE: msgpack.Unpacker uses self.read as input here.
        # It does not support iterators unfortunately.
        for row in msgpack.Unpacker(self, encoding='utf-8'):
            yield row


class ResultOutput(object):
    def get_result_url(self):
        raise NotImplemented()


class S3ResultOutput(ResultOutput):
    def __init__(self, bucket, path, aws_access_key_id=None, aws_secret_access_key=None, format='tsv', delimiter=None, quote=None, escape=None, null=None, newline=None, header=None):
        self.bucket = self.bucket
        self.path = self.path
        self.aws_access_key_id = aws_access_key_id or os.environ.get('AWS_ACCESS_KEY_ID')
        self.aws_secret_access_key = aws_secret_access_key or os.environ.get('AWS_SECRET_ACCESS_KEY')
        self.format = 'tsv'
        self.delimiter = delimiter
        self.quote = quote
        self.escape = escape
        self.null = null
        self.newline = newline
        self.header = header

    def get_result_url(self):
        reqs = {}
        for name in ['aws_access_key_id', 'aws_secret_access_key', 'bucket', 'path']:
            if getattr(self, name) is None:
                raise TypeError('missing parameter "{0}" for {1}'.format(name, self))
            reqs[name] = urllib.parse.quote(getattr(self, name))
        params = {
            'format': self.format
        }
        reqs['params'] = urllib.parse.urlencode({key: params[key] for key in params if params[key]})
        return "s3://{aws_access_key_id}:{aws_secret_access_key}@/{bucket}/{path}?{params}".format(**reqs)


class TableauServerResultOutput(ResultOutput):
    def __init__(self, server, server_version, datasource, username=None, password=None, ssl='true', ssl_verify='true', site=None, project=None, mode='replace'):
        self.server = server
        self.server_version = server_version
        self.datasource = datasource
        self.username = username
        self.password = password
        self.ssl = ssl
        self.ssl_verify = ssl_verify
        self.site = site
        self.project = project
        self.mode = mode

    def get_result_url(self):
        reqs = {}
        for name in ['server', 'username', 'password', 'datasource']:
            if getattr(self, name) is None:
                raise TypeError('missing parameter "{0}" for {1}'.format(name, self))
            reqs[name] = urllib.parse.quote(getattr(self, name))
        params = {
            'ssl': self.ssl,
            'ssl_verify': self.ssl_verify,
            'server_version': self.server_version,
            'site': self.site,
            'project': self.project,
            'mode': self.mode,
        }
        reqs['params'] = urllib.parse.urlencode({key: params[key] for key in params if params[key]})
        return "tableau://{username}:{password}@{server}/{datasource}?{params}".format(**reqs)


class TableauOnlineResultOutput(TableauServerResultOutput):
    def __init__(self, datasource, username=None, password=None, site=None, project=None, mode='replace'):
        server = 'online.tableausoftware.com'
        server_version = 'online'
        super(TableauOnlineResultOutput, self).__init__(
            server, server_version, datasource,
            username=username,
            password=password,
            site=site,
            project=project,
            mode=mode,
        )