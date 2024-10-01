awspub - image publication for AWS EC2
--------------------------------------

`awspub` can publish images (AMIs) based on .VMDK files
to AWS EC2.

Documentation
=============

The documentation can be found under https://canonical-awspub.readthedocs-hosted.com/ .

Report issues
=============

Please use https://github.com/canonical/awspub/issues to report problems or ask
questions.

License
=======

The project uses `GPL-3.0` as license.

Doing a new release
===================

New releases are mostly automated.

pypi
----

For a new release on pypi, create a new tag (following semantic versioning)
with a `v` as prefix (eg. `v0.2.1`).

snapstore
---------

The latest git commit will be automatically build and published to the `latest/edge`
channel. Manually promote from `latest/edge` to `latest/stable`.
