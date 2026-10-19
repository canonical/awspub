How to install awspub
=====================

Setup profile configuration
---------------------------

Before using this tool, you need to setup the AWS configuration and credential files. Follow
`CLI configuration documentation`_ to create these two files.

Example config file:

.. code-block::

    $ cat ~/.aws/config
    [default]
    region = us-east-1

Example credential file:

.. code-block::

   $ cat ~/.aws/credentials
   [default]
   aws_secret_access_key = <YOUR SECRET ACCESS KEY>
   aws_access_key_id = <YOUR ACCESS KEY ID>

Install awspub using snap
-------------------------

`awspub` is available in the `Snapstore`_, and it can be installed using:

.. code-block::

    snap install awspub

This will install the latest version in your machine. We would highly recommend you install the latest version, but
refer to this `Snapcraft channel doc`_ for installing a different version or from a specific channel.

Run awspub using Docker
-----------------------

`awspub` is also available as a container image on GitHub Container Registry (GHCR):

.. code-block::

    docker pull ghcr.io/canonical/awspub:latest

To run the container using mounted AWS credentials from your host:

.. code-block::

    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -v ~/.aws:/home/awspub/.aws:ro \
        -v "$(pwd)":/data \
        -w /data \
        ghcr.io/canonical/awspub --help

.. note::

   Passing ``--user "$(id -u):$(id -g)"`` matches the container process UID/GID to your host user,
   allowing it to read host AWS credential files (which typically have strict ``0600`` / ``0700`` permissions).

   The mounted working directory must be writable by that user for logs and output files.
   Keep mounts at ``/data``; mounting over ``/app`` hides the installed application.
   The image sets ``HOME=/home/awspub`` so AWS configuration is found with a numeric UID.

   The read-only AWS mount supports existing credential files but cannot update cached tokens.
   For authentication requiring cache refreshes, obtain fresh temporary credentials on the host
   and use the environment-variable example below. Host credential helper programs are not
   included in the image.

Alternatively, you can authenticate without mounting files by passing standard AWS environment variables directly:

.. code-block::

    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_SESSION_TOKEN \
        -e AWS_DEFAULT_REGION \
        -v "$(pwd)":/data \
        -w /data \
        ghcr.io/canonical/awspub --help

Export these variables in your host shell first. Temporary credentials require ``AWS_SESSION_TOKEN``;
leave it unset when using long-lived access keys.

You can replace ``--help`` with ``list config.yaml``, ``create config.yaml``, or ``publish config.yaml``,
where ``config.yaml`` is a configuration file in the mounted working directory.


CLI usage
---------

The command line interface called ``awspub`` accepts the standard AWS environment variables such as `AWS_PROFILE`.

.. _`CLI configuration documentation`: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html#cli-configure-files-using-profiles
.. _`Snapstore`: https://snapcraft.io/awspub
.. _`snapcraft channel doc`: https://snapcraft.io/docs/channels
