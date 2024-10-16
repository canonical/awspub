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


.. _new-release: https://github.com/canonical/awspub/releases/new
