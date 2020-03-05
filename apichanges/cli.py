import click
import itertools
import jinja2
import logging
import os
import pygit2

from .model import ReleaseDelta
from .repo import CommitProcessor, TagWalker


log = logging.getLogger('apichanges')


@click.group()
def cli():
    """AWS API ChangeLog"""
    logging.basicConfig(level=logging.INFO)


def _repo_stream_options(func):
    decorators = [
        click.option('--path', required=True,
                     help="Path to AWS SDK git clone"),
        click.option('--since', required=True, help="Start Date or Tag"),
        click.option('--until',
                     help="End Date or Tag, default: last commit date"),
        click.option('--service', multiple=True,
                     help="Filter changes to only these services"),
        click.option('--changes-dir', default='.changes',
                     help="sdk release changes json dir in repo"),
        click.option('--model-path',
                     help="model directory prefix", required=True),
        click.option('--model-suffix',
                     help="suffix for model files", required=True),
    ]
    for d in decorators:
        func = d(func)
    return func


@cli.command(name='build-page')
@click.option('--debug', is_flag=True, default=False)
@click.option('--template', help="Path to Jinja2 Template",
              type=click.Path(exists=True, resolve_path=True))
@click.option('--output', type=click.Path(resolve_path=True))
@_repo_stream_options
def build_page(
        path, since, until, service, template, output,
        changes_dir, model_path, model_suffix, debug):
    """build a single page site"""
    repo = pygit2.Repository(path)
    releases = []
    count = 0

    walker = TagWalker(repo)
    delta_processor = CommitProcessor(
        repo, model_prefix=model_path, model_suffix=model_suffix,
        change_dir=changes_dir, services=service, debug=debug)

    log.info('scanning for api changes since %s until %s',
             since, until or 'latest')

    for prev, cur, commit_info, change_diff in walker.walk(since, until):
        count += 1
        service_changes = delta_processor.process(commit_info, change_diff)
        if service_changes:
            release = ReleaseDelta(commit_info, service_changes)
            log.info(release)
            releases.append(releases)

    log.info(('processed %d/%d releases, '
              '%d svc %d api updates across %d services'),
             len(releases),
             count,
             sum(map(len, releases)),
             sum(map(len,
                     [svc.changes for svc in itertools.chain(
                         *[r for r in releases])])),
             len({s.name for s in itertools.chain(*[r for r in releases])}))

    # sort changes regardless of walk direction by reverse date
    releases = sorted(
        releases, key=lambda c: c.commit['created_at'], reverse=True)

    if template and output:
        log.info('rendering template %s to %s', template, output)
        template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.dirname(str(template))))
        template = template_env.get_template(os.path.basename(str(template)))
        with open(output, 'w') as fh:
            fh.write(template.render(releases=releases))


if __name__ == '__main__':
    cli()
