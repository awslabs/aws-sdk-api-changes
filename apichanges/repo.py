import bisect
from datetime import datetime, timedelta
from dateutil.tz import tzoffset, tzutc
from dateutil.parser import parse as parse_date
from distutils.version import LooseVersion
from functools import lru_cache
import json
import logging
import os
import pygit2
import re

from .model import diff_model

log = logging.getLogger('apichanges.repo')


def commit_date(commit):
    tzinfo = tzoffset(None, timedelta(minutes=commit.author.offset))
    return datetime.fromtimestamp(float(commit.author.time), tzinfo)


def commit_dict(commit, committed_date=None):
    return dict(
        commit_id=str(commit.id),
        created_at=committed_date or commit_date(commit),
        author=commit.author.name,
        author_email=commit.author.email,
        committer=commit.committer.name,
        commitetr_email=commit.committer.email,
        message=commit.message,
        parent_count=len(commit.parents))


class CommitProcessor(object):

    def __init__(self, repo, model_prefix, model_suffix, change_dir=None,
                 services=(), debug=False):
        self.repo = repo
        self.model_prefix = model_prefix
        self.model_suffix = model_suffix
        self.change_dir = change_dir
        self.services = services
        self.debug = debug

    def load_change_log(self, fid):
        change_log = {}
        data = json.loads(self.repo[fid].read_raw().decode('utf8'))
        for n in data:
            change_log.setdefault(n['category'].strip('`').lower(), []).append(
                n['description'])
        return change_log

    def process(self, commit, change_diff):
        if self.debug:
            log.debug((
                "commit:{commit_id:.8} tag:{tag} date:{created_at:%Y/%m/%d %H:%M}\n"
                " stats: {stats}"
            ).format(
                    stats=change_diff.stats.format(
                        pygit2.GIT_DIFF_STATS_SHORT, 80).strip(),
                    **commit))
        service_changes = []

        change_path = change_log = None
        if self.change_dir:
            change_path = os.path.join(
                self.change_dir, '%s.json' % commit['tag'].lstrip('v'))

        # Get file map so we can ensure change log first.
        file_map = {d.new_file.path: d for d in change_diff.deltas}
        if change_path and change_path in file_map:
            change_log = self.load_change_log(
                file_map.get(change_path).new_file.id)

        for dpath, d in [
                (f, d) for f, d in file_map.items() if
                f.startswith(self.model_prefix) and
                f.endswith(self.model_suffix)]:
            if self.services:
                found = False
                for s in self.services:
                    if s in dpath:
                        found = True
                if not found:
                    continue
            if self.debug:
                log.debug('api model change {} change: {}'.format(
                    dpath, d.status_char()))
            if d.status_char() == 'A':
                new = json.loads(
                    self.repo[d.new_file.id].read_raw().decode('utf8'))
                old = None
            elif d.status_char() == 'M':
                new = json.loads(
                    self.repo[d.new_file.id].read_raw().decode('utf8'))
                old = json.loads(
                    self.repo[d.old_file.id].read_raw().decode('utf8'))
            else:
                log.warning(
                    'service file unknown change commit:%s file:%s change:%s',
                    commit['commit_id'], dpath, d.status_char())
                continue
            try:
                svc_change = diff_model(new, old)
            except Exception:
                log.error('commit:%s error processing %s', commit['commit_id'], dpath)
                raise
                continue

            if not svc_change:
                continue

            svc_change.model_file = str(d.new_file.id)
            svc_change.commit = commit
            svc_change.associate_logs(change_log)
            log.info(svc_change)
            service_changes.append(svc_change)
        return service_changes


class TagWalker(object):
    """Iter commits and diffs on a git repo.
    """
    # twin peaks styled, not texas ranger
    def __init__(self, repo):
        self.repo = repo

    def walk(self, since, until=None):
        """paramertized iterator.

        since|until: either a date string or a tag

        if given a date resolve to the nearest tag. until
        defaults to last tag. tags are sorted as version
        numbers.
        """
        tags = self.get_tag_set()
        start = self.get_target_tag(tags, since)
        end = self.get_target_tag(tags, until, end=True)

        if start == end:
            log.debug('walker exit start == end')
            return

        for idx, t in enumerate(
                tags[tags.index(start):tags.index(end) + 1], tags.index(start)):
            previous = self.get_tag_commit(tags[idx-1])
            cur = self.get_tag_commit(tags[idx])
            change_diff = self.repo.diff(previous, cur)
            info = commit_dict(cur)
            info['tag'] = str(t).rsplit('/', 1)[-1]
            log.debug('walking tag: %s date:%s' % (t, info['created_at']))
            yield previous, cur, info, change_diff

    def resolve(self, target):
        if target:
            try:
                self.repo.lookup_reference('refs/tags/%s' % target)
            except (KeyError, pygit2.InvalidSpecError):
                target = parse_date(target).astimezone(tzutc())
        return target

    @lru_cache(128)
    def get(self, tag):
        tags = self.get_tag_set()
        idx = bisect.bisect_left(LooseVersion(tag), tags)
        prev = self.get_tag_commit(tags[idx])
        cur = self.get_tag_commit(tag)
        return (commit_dict(cur), self.repo.diff(prev, cur))

    def get_tag_commit(self, tag):
        return self.repo.lookup_reference(str(tag)).peel()

    def get_target_tag(self, tags, target, end=False):
        target = self.resolve(target)
        if target is None and end:
            return tags[-1]
        elif target is None:
            return tags[0]
        # bisect on version
        if not isinstance(target, datetime):
            indexer = end and bisect.bisect_left or bisect.bisect_right
            idx = indexer(tags, LooseVersion('refs/tags/%s' % target))
            if idx == len(tags):
                return tags[-1]
            return tags[idx]

        # date linear traversal from recent to older
        prev = None
        for t in reversed(tags):
            t_date = commit_date(self.get_tag_commit(t))
            if not end:
                if t_date > target:
                    prev = t
                    continue
                if t_date < target:
                    return prev or t
            if end:
                if t_date < target:
                    prev = t
                if t_date > target:
                    return prev or t

    @lru_cache(5)
    def get_tag_set(self):
        regex = re.compile('^refs/tags')
        tags = list(
            map(LooseVersion,
                filter(lambda r: regex.match(r),
                       self.repo.listall_references())))
        tags.sort()
        return tags
