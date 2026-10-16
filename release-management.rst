Doing a new release
===================

New releases are mostly automated. A new github release (which includes
creating a new git tag) can be done via the `github web UI <new-release>`_.
In `Choose a tag`, create the new one (with a `v` as prefix, so eg. `v0.1.1`)
and as a `Release title`, use the same name as the tag (so eg. `v0.1.1`).

pypi
----

New releases on pypi happen automatically when a new git tag gets
created. The tag needs to be prefixed with `v` (eg. `v0.10.0`).

snapstore
---------

The latest git commit will be automatically build and published to the `latest/edge`
channel. Promoting to `latest/stable` can be done with:

.. code-block::

   snapcraft promote --from-channel latest/edge --to-channel latest/stable awspub

ghcr.io (Docker)
----------------

Multi-architecture Docker images (amd64 and arm64) are automatically built and published
to GitHub Container Registry (`ghcr.io/canonical/awspub`_):

* Pushes to the ``main`` branch are tagged with the commit SHA, ``main``, and ``latest``.
* Release tags (``v*``) are tagged with the semantic version (e.g. ``0.1.1`` and ``0.1``) and commit SHA.

Only pushes to ``main`` update ``latest``.


.. _new-release: https://github.com/canonical/awspub/releases/new
.. _`ghcr.io/canonical/awspub`: https://github.com/canonical/awspub/pkgs/container/awspub
