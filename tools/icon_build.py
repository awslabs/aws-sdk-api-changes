#!/usr/bin/env python

# note we'll use glue to assemble a css sprite
# for now we use this to pickup the images we want, convert
# from svg to png in our preferred size

import click
import cairosvg
import os
from pathlib import Path
from jinja2 import Template

from apichanges.icons import ICON_SERVICE_MAP

CSS_BUILD = """
{% for name, path in icons.items() %}
.{{ name }} {background-image: url('/{{ path }}')}
{% endfor %}
"""


@click.command()
@click.option('-s', '--source', required=True, type=click.Path())
@click.option('-d', '--destination', required=True, type=click.Path())
@click.option('--size', type=int, default=128)
def main(source, destination, size):

    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()

    count = 0
    icons = {}
    used = set()
    icon_2_service = {
        v: k for k, v in ICON_SERVICE_MAP.items()}

    for dirpath, dirnames, filenames in os.walk(str(source)):
        dirpath = Path(dirpath)
        for f in filenames:
            if not f.endswith('_dark-bg.svg'):
                continue
            origin = (dirpath / f)    
            n = origin.name
            name = n[:n.find('_dark')].replace('.', '_')

            service = icon_2_service.get(name)
            if service is None:
                continue
            if name in icons:
                continue
            used.add(name)

            target = destination / ("%s.png" % name.lower())
#            if target.exists():
#                continue
            count += 1          
            target.parent.mkdir(parents=True, exist_ok=True)
#            print('{} -> {}'.format(origin, target))

            cairosvg.svg2png(
                url=str(origin),
                write_to=str(target),
                output_width=size,
                output_height=size)

    if set(icon_2_service).difference(used):
        print('missing service icons %s' % (', '.join(
            set(icon_2_service).difference(used))))
    print('copied %d icons' % count)
    with (destination / 'icons.css').open('w') as fh:
        icons = {k: "icons/%s.png" % v.lower()
                 for k, v in ICON_SERVICE_MAP.items()}
        fh.write(Template(
            CSS_BUILD, lstrip_blocks=True, trim_blocks=True).render(
                icons=icons))


if __name__ == '__main__':
    main()

