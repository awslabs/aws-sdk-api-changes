
work_dir := "build"
sdk_git_repo := "https://github.com/aws/aws-sdk-js.git"
svg_icon_url := "https://d1.awsstatic.com/webteam/architecture-icons/AWS-Architecture-Icons_SVG_20191031.37913bbe8450d38bc7acc50cc40fe0c2135d650c.zip"
svg_icon_prefix := "AWS-Architecture-Icons_SVG_20191031/SVG\\ Dark/"
website_bucket := "awsapichanges.info"


# Build a docker image
image:
    docker build -t apichanges:latest .

# Clone an aws sdk api repo for introspection.
sdk-repo: cache-get
    #!/usr/bin/env python3
    import os, json, subprocess, datetime, pathlib
    work_dir = pathlib.Path('{{work_dir}}').resolve()
    data = json.load(open(str(work_dir/'cache.json')))
    last = datetime.datetime.fromtimestamp(data[1]['created'])
    cmd = ['git', 'clone', '--shallow-since=%s' % last.isoformat(),
        '{{sdk_git_repo}}', str(work_dir/'sdk_repo')]
    print("run %s" % (' '.join(cmd)))
    subprocess.check_call(cmd)

# Build the website
build:
    #!/usr/bin/env python3
    import logging
    from apichanges.sitebuild import Site
    from pathlib import Path
    logging.basicConfig(level=logging.INFO)
    builder_dir = Path('.').resolve()
    work_dir = Path('{{work_dir}}').resolve()
    site = Site(
         work_dir / 'sdk_repo',
         work_dir / 'cache.json',
         builder_dir / 'templates',
         builder_dir / 'assets')
    site.build(work_dir / 'stage')

# Publish the website
publish: build
    #!/usr/bin/env python3
    import logging
    from pathlib import Path
    from apichanges.publisher import SitePublisher
    logging.basicConfig(level=logging.INFO)
    stage_dir = Path('{{work_dir}}').resolve() / 'stage'
    publisher = SitePublisher(stage_dir, '{{website_bucket}}')
    publisher.publish()


# Get the commit cache file
cache-get:
    #!/bin/bash
    set -ex
    cd {{work_dir}}
    aws s3 cp s3://{{website_bucket}}/cache.json.zst .
    zstd -f -d cache.json.zst

# Upload the commit cache file
cache-upload:
    #!/bin/bash
    set -ex
    cd {{work_dir}}
    zstd -f -19 cache.json
    aws s3 cp cache.json.zst s3://{{website_bucket}}/cache.json.zst

# manual dev - trim cache file to simulate incremental
cache-trim:
    #!/usr/bin/env python3
    import json
    data = json.load(open('cache.json'))
    data = data[4:]
    with open('cache.json', 'w') as fh:
        json.dump(data, fp=fh)

# Build image sprites for aws service icons.
sprites:	
    pip3 -q install glue cairosvg
    curl -s -o aws-svg-icons.zip {{svg_icon_url}}
    unzip -qq -o aws-svg-icons.zip
    python3 tools/icon_build.py -s {{svg_icon_prefix}} -d assets/images --size 64
    glue -q -s assets/images -o assets/sprite
