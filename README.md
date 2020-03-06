# AWS SDK API ChangeLog

Think of it as developer centric AWS what's new site, ie. just tell me
what's changing in the apis, with field level changes highlighted on
updated apis.

Its a static site generator via git walking and diffing a repo
containing service model files that are contained in aws sdks.

Its deployed as a periodic spot fargate task that pulls the public sdk
repo, walks named tags and performs diff. It keeps a json statefile as
a cache of those diffs, and then renders the site to an s3 bucket with
cloudfront in front. Service icons are assembled into css sprites from
the publicly available svg icon sets.

Types of changes detected.
 - new method
 - new/modified parameter on existing method
 - new service

Semantic Changelogs

 - we use the nodejs sdk repo which produce nice machine
   readable diffs with the service team logs.

This uses https://github.com/casey/just as a replacement for make.


## License

This project is licensed under the Apache-2.0 License.
