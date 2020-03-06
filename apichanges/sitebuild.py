import itertools
import json
import logging
import operator
import os
import shutil
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import arrow
import jinja2
import pygit2
from botocore import hooks, xform_name
from botocore.docs.docstring import ClientMethodDocstring
from dateutil.tz import tzutc
from docutils.core import publish_parts
from docutils.writers.html5_polyglot import HTMLTranslator, Writer
from feedgen.feed import FeedGenerator

from .icons import get_icon, get_icon_style
from .model import ReleaseDelta, ServiceModel
from .record import Commit, ServiceChange  # noqa
from .repo import CommitProcessor, TagWalker

log = logging.getLogger("awschanges.site")

GIT_EMPTY_FILE = "0000000000000000000000000000000000000000"


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)


def bisect_create_age(commits: List[Commit], days: int) -> int:
    marker_date = datetime.now().astimezone(tzutc()).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days)

    for idx, c in enumerate(commits):
        if marker_date > c.created:
            break
    return idx


def bisect_month(commits: List[Commit], month: datetime) -> int:
    for idx, c in enumerate(commits):
        if (c.created.year, c.created.month) == (month.year, month.month):
            continue
        return idx - 1


def group_by_date(
    commits: List[Commit], year: bool = False, month: bool = False
) -> List[Commit]:

    if year:
        key_func = lambda c: c.created.year  # noqa
    elif month:
        key_func = lambda c: (c.created.year, c.created.month)  # noqa
    else:
        raise SyntaxError("one of month or year should be specified")

    # itertools group by seems flaky..
    groups = {}
    for c in commits:
        groups.setdefault(key_func(c), []).append(c)
    return groups


def group_by_service(commits: List[Commit]):
    groups = {}
    for c in commits:
        for s in c.service_changes:
            groups.setdefault(s.name, []).append(c)
    return groups


def chunks(changes, size=20):
    # slightly specialized batching implementation. each change commit
    # can contain n service changes, which contains n operation
    # changes, any page rendered with a large number of operation
    # changes will be fairly heavy weight (mbs). we attempt to size a
    # batch based on the number of service changes, but will treat the
    # change commit as an atomic unit. in practice this may produce a
    # batch with a single change set.
    batch = []
    batch_size = 0
    for c in changes:
        batch_size += c.size
        batch.append(c)
        if batch_size > size:
            yield batch
            batch = []
            batch_size = 0
    if batch:
        yield batch


def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Kb", "Mb", "Gb", "Tb"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s" % (num, suffix)


class TemplateAPI:
    # flyweight used per template render
    def __init__(self, repo, build_time=None):
        self.repo = pygit2.Repository(repo)
        self.service_models = {}
        self.stats = Counter()
        self.build_time = build_time

    def get_service_title(self, service_name, commits):
        for c in commits:
            for s in c:
                if s.name == service_name:
                    return s.title
        return service_name

    def get_service_doc(self, service_change):
        return self._get_service_model(service_change).documentation

    def get_human_age(self, rdate):
        return arrow.get(rdate).humanize()

    def render_operation(self, service_change, op_name):
        # try and reuse botocore's sphinx doc infrastructure.
        m = self._get_service_model(service_change)
        if m is None:
            log.error("couldnt find model %s", service_change)
            return ""
        opm = m.operation_model(op_name)
        method_doc = ClientMethodDocstring(
            operation_model=opm,
            method_name=opm.name,
            event_emitter=hooks.HierarchicalEmitter(),
            method_description=opm.documentation,
            example_prefix="client.%s" % xform_name(opm.name),
            include_signature=False,
        )
        return self._render_docutils(method_doc)

    def _get_service_model(self, service_change):
        if service_change.model_file in self.service_models:
            return self.service_models[service_change.model_file]
        self.stats["model_load"] += 1
        t = time.time()
        if service_change.model_file == GIT_EMPTY_FILE:
            return
        data = json.loads(
            self.repo[service_change.model_file].read_raw().decode("utf8")
        )
        m = ServiceModel(data)
        self.stats["model_load_time"] += time.time() - t
        self.service_models[service_change.model_file] = m
        return m

    def _render_docutils(self, method_doc):
        method_writer = Writer()
        method_writer.translator_class = HTMLTranslator
        self.stats["op_render"] += 1
        t = time.time()
        parts = publish_parts(
            str(method_doc),
            settings_overrides={"report_level": 4},
            writer=method_writer,
        )
        self.stats["op_render_time"] += time.time() - t
        return parts["fragment"]


class Site:

    site_prefix = ""
    site_url = ""
    default_commit_days = 14

    def __init__(self, repo_path, cache_path, template_dir, assets_dir):
        self.repo_path = repo_path
        self.cache_path = Path(cache_path)
        self.template_dir = Path(template_dir).resolve()
        self.assets_dir = assets_dir

        self.commits = []
        self.env = jinja2.Environment(
            lstrip_blocks=True,
            trim_blocks=True,
            loader=jinja2.FileSystemLoader(str(template_dir)),
        )
        self.pages = []
        self.output = None
        self.build_time = datetime.utcnow()

    def upload(self, output: Path, destination: str):
        pass

    def build(self, output: Path, destination: Optional[str] = None):
        log.info("build site")
        self.output = output
        new_commits = self.load(self.repo_path, self.cache_path)
        self.build_index_pages(self.commits[: bisect_create_age(self.commits, 60)])
        self.build_feed(self.commits[: bisect_create_age(self.commits, days=60)])
        if not new_commits:
            log.info("no changes")
        #            self.build_service_pages(self.commits)
        #            self.build_commit_pages(self.commits[
        #                :bisect_create_age(self.commits, self.default_commit_days)])
        else:
            log.info("incremental build %d commits", len(new_commits))
            self.build_commit_pages(new_commits)
            self.build_service_pages(self.commits, set(group_by_service(new_commits)))
            self.build_search_index(
                self.commits[: bisect_create_age(self.commits, days=365 + 60)]
            )
        self.copy_assets(output)
        pages = list(self.pages)
        self.pages = []
        return pages

    def copy_assets(self, output, incremental=True):
        if not self.assets_dir:
            return
        for atype in ("css", "js", "sprite", "icons"):
            if incremental and atype == "icons":
                continue
            shutil.copytree(
                self.assets_dir / atype, self.output / atype, dirs_exist_ok=True
            )

    @classmethod
    def link(self, relative_path):
        link = self.site_url
        if self.site_prefix:
            link += "/%s" % self.site_prefix
        link += "/%s" % relative_path
        return link

    def render_page(
        self, path, template: Optional[str] = None, force: bool = False, **kw
    ):
        if template:
            tpl = self.env.get_template(template)
        p = self.output / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not force:
            return
        t = time.time()
        with p.open("w") as fh:
            tapi = TemplateAPI(str(self.repo_path), self.build_time)
            kw["icon_style"] = get_icon_style
            kw["icon"] = get_icon
            kw["api"] = tapi
            kw["build_time"] = self.build_time
            if template:
                t = time.time()
                fh.write(tpl.render(**kw))
            else:
                fh.write(kw["content"])
            self.pages.append(path)

        log.debug(
            "page:%s size:%s time:%0.2f mtime:%0.2f models:%d op-time:%0.2f",
            path,
            sizeof_fmt(p.stat().st_size),
            time.time() - t,
            tapi.stats["model_load_time"],
            tapi.stats["model_load"],
            tapi.stats["op_render_time"],
        )

    def build_feed(self, commits: List[Commit]):
        log.info("build feed page %d" % len(commits))
        feed = FeedGenerator()
        feed.id("")
        feed.title("AWS API Changes")
        feed.author(
            {
                "name": "AWSPIChanges",
                "email": "https://github.com/awslabs/aws-sdk-api-changes",
            }
        )
        feed.link(href=self.site_url, rel="alternate")
        feed.link(href="%s/feed/" % self.site_url, rel="self")
        feed.description("AWS API ChangeLog")
        feed.language("en-US")
        feed.generator("artisan-sdk-gitops")
        feed.image(
            url="https://a0.awsstatic.com/main/images/logos/aws_logo_smile_179x109.png"
        )  # noqa
        for c in commits:
            for s in c.service_changes:
                fe = feed.add_entry(order="append")
                fe.title(
                    "{} - {}{}methods".format(
                        s.title,
                        s.count_new and "%d new " % s.count_new or "",
                        s.count_updated and "%d updated " % s.count_updated or "",
                    )
                )
                fe.id("{}-{}".format(c.id, s.name))
                fe.description(s.change_log)
                fe.link(
                    {
                        "href": self.link(
                            "archive/changes/%s-%s.html" % (c.id[:6], s.name)
                        )
                    }
                )
                fe.published(c.created)
        self.render_page(
            "feed/feed.rss",
            force=True,
            content=feed.rss_str(pretty=True).decode("utf8"),
        )

    def build_search_index(self, commits: List[Commit]):
        log.info("build search index %d" % len(commits))
        sd = []
        for c in commits:
            for svc in c:
                sd.append(
                    {
                        "id": c.id,
                        "created": c.created,
                        "svc": svc.name,
                        "t": svc.title,
                        "log": svc.change_log,
                        "new": len(svc.ops_added),
                        "up": len(svc.ops_updated),
                    }
                )
        self.render_page(
            "search_data.json", content=json.dumps(sd, cls=DateTimeEncoder)
        )
        self.render_page("search/index.html", "search.j2")

    def build_commit_pages(self, commits: List[Commit]):
        for c in commits:
            for svc_change in c:
                self.render_page(
                    "archive/changes/{}-{}.html".format(c.id[:6], svc_change.name),
                    "service-commit.j2",
                    service_change=svc_change,
                    commit=c,
                    force=True,
                )

    def build_service_pages(self, commits: List[Commit], services=None):
        groups = group_by_service(commits)
        for svc_name in sorted(groups):
            if services and svc_name not in services:
                continue
            svc_title = list(groups[svc_name][0].select(svc_name))[0].title
            self.render_page(
                "archive/service/{}/index.html".format(svc_name),
                "service.j2",
                service=svc_name,
                service_title=svc_title,
                releases=groups[svc_name],
                force=True,
            )
        self.render_page(
            "archive/service/index.html",
            "service-map.j2",
            services=sorted(groups, key=lambda s: groups[s][0].created, reverse=True),
            changes=groups,
            force=True,
        )

    #    def build_month_archive(self, commits):
    #        for (year, month), mcommits in group_by_date(
    #                commits, month=True).items():
    #            dt = datetime(year=year, month=month, day=1)
    #            self.render_page(
    #                'archive/index/{}/{}/index.html'.format(year, month),
    #                'month.j2',
    #                archive_date=dt,
    #                releases=mcommits)

    def build_index_pages(self, commits: List[Commit]):
        pager = {}
        #        pager = {'size': len(commits),
        #                 'archive': self.link(
        #                     'archive/{:%Y%/m}'.format(commits[-1].created)),
        #                 'pages': [idx for idx, batch in enumerate(pages)]}
        #
        #        log.info('build main pages %d' % len(pager['pages']))
        for idx, batch in [(0, commits)]:
            p = "%s.html" % (idx and "archive/index/%d" % idx or "index")
            log.info(
                "main page: %s commits: %d changes: %d start: %s  period: %s",
                str(p),
                len(batch),
                sum([len(s) for s in itertools.chain(*[c for c in batch])]),
                batch[-1].created.strftime("%Y-%m-%d"),
                (batch[0].created - batch[-1].created).days,
            )
            self.render_page(p, "index.j2", releases=batch, pager=pager, force=True)

    def load(self, repo_path: str, cache_path: str, since: Optional[str] = None):
        log.info("git walking repository")
        commits = []
        if os.path.exists(cache_path):
            with open(cache_path) as fh:
                commits = Commit.schema().loads(fh.read(), many=True)
        commits.sort(key=operator.attrgetter("created"), reverse=True)
        self.commits = commits
        if not commits:
            new_commits = self._load(repo_path, since=since)
            if since is None:  # last commit is typically an import
                new_commits.pop(-1)
        else:
            new_commits = self._load(repo_path, since=commits[0].tag)
        self.commits.extend(new_commits)
        self.commits.sort(key=operator.attrgetter("created"), reverse=True)
        with open(cache_path, "w") as fh:
            fh.write(Commit.schema().dumps(self.commits, many=True))
        return new_commits

    def _load(
        self, repo_path: str, since: Optional[str] = None, until: Optional[str] = None
    ) -> List[Commit]:
        repo = pygit2.Repository(str(Path(repo_path).expanduser().resolve()))
        walker = TagWalker(repo)
        delta = CommitProcessor(
            repo,
            change_dir=".changes",
            model_prefix="apis/",
            model_suffix="normal.json",
        )
        releases = []
        for _, _, commit_info, change_diff in walker.walk(since, until):
            svc_changes = delta.process(commit_info, change_diff)
            if svc_changes:
                releases.append(ReleaseDelta(commit_info, svc_changes))
        return list(Commit.from_commits(releases))
