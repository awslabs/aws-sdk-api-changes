import contextlib
import gzip
import logging
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path

import boto3

log = logging.getLogger("apichanges.publish")


@contextlib.contextmanager
def temp_dir():
    try:
        d = tempfile.mkdtemp()
        yield Path(d)
    finally:
        shutil.rmtree(d)


class SitePublisher(object):

    compress_exts = set(("js", "css", "json", "html"))

    def __init__(self, site_dir: Path, s3_bucket, s3_prefix=""):
        self.site_dir = site_dir
        self.bucket = s3_bucket
        self.prefix = s3_prefix.rstrip("/")

    def publish(self):
        client = boto3.client("s3")
        with temp_dir() as staging:
            self.prepare_staging(staging)
            self.transfer_staging(client, staging)

    def transfer_staging(self, client, staging):
        for dirpath, dirnames, files in os.walk(staging):
            dirpath = Path(dirpath)
            for f in files:
                sf = dirpath / f
                tf = sf.relative_to(staging)
                ext = f.rsplit(".", 1)[-1]
                params = {"ACL": "public-read"}
                if ext in self.compress_exts:
                    params["ContentEncoding"] = "gzip"
                if ext == "rss":
                    params["ContentDisposition"] = "inline"
                params["ContentType"], _ = mimetypes.guess_type(f)
                key = str(self.prefix / tf).lstrip("/")
                log.info("upload %s", key)
                client.upload_file(
                    str(sf), Bucket=self.bucket, Key=key, ExtraArgs=params
                )

    def prepare_staging(self, staging):
        tf_count = 0
        tf_size = 0
        for dirpath, dirnames, files in os.walk(self.site_dir):
            dirpath = Path(dirpath)
            stage_dir = staging / dirpath.relative_to(self.site_dir)
            for f in files:
                ext = f.rsplit(".", 1)[-1]
                tf = stage_dir / f
                f = dirpath / f
                tf.parent.mkdir(parents=True, exist_ok=True)
                if ext in self.compress_exts:
                    with gzip.open(tf, "w") as fh:
                        fh.write(f.read_bytes())
                    osize = f.stat().st_size
                    csize = tf.stat().st_size
                    log.debug(
                        "compressed %s -> %s -> %s (%0.0f%%)"
                        % (dirpath / f, osize, csize, csize / float(osize) * 100)
                    )
                    tf_size += csize
                else:
                    shutil.copy2(str(f), str(tf))
                    tf_size += f.stat().st_size
                tf_count += 1

        log.info("prepared stage %d files %d size" % (tf_count, tf_size))
