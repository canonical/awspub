How to publish images
=====================

To publish a VMDK file as an image (AMI) on AWS EC2 with `awspub`,
a config file is required.
A basic config file (say ``config.yaml``) looks like:

.. literalinclude:: ../config-samples/config-minimal.yaml
   :language: yaml


To publish the image with the name `my-custom-image`, run:

.. code-block:: shell

  awspub create config.yaml
  [snipped output]
  {
    "images": {
      "my-custom-image": {
        "ap-south-2": "ami-015fa46e6ec690c8e",
        "ap-south-1": "ami-0fd9238a64ea231d0",
        "eu-south-1": "ami-0cbb4771743cc81fe",
        "eu-south-2": "ami-0067ee557befd09c2",
        "me-central-1": "ami-023fa019e0ce98e91",
        "il-central-1": "ami-092d3f2a7677b8cf1",
        "ca-central-1": "ami-0d2e897cd1ebecc45",
        "eu-central-1": "ami-0b9ed498e040c69e2",
        "eu-central-2": "ami-0fb0f61690e55ab8e",
        "us-west-1": "ami-069c013403cc15c2f",
        "us-west-2": "ami-06f9d32912a83571b",
        "af-south-1": "ami-0371f67e8905c045a",
        "eu-north-1": "ami-00710b821b31f5c78",
        "eu-west-3": "ami-08b74828e79d0a405",
        "eu-west-2": "ami-0f6f9c073bdb7b731",
        "eu-west-1": "ami-0a07629b25777bf07",
        "ap-northeast-3": "ami-07d680c934126a92b",
        "ap-northeast-2": "ami-01fa9f4862d957b59",
        "me-south-1": "ami-0827faef233b14a29",
        "ap-northeast-1": "ami-0d119806827c3af22",
        "sa-east-1": "ami-07f8dfef0a8855f06",
        "ap-east-1": "ami-047cb2feb00bfc834",
        "ca-west-1": "ami-061003b943c2d6be8",
        "ap-southeast-1": "ami-0a2ca6ffb79999bb5",
        "ap-southeast-2": "ami-0a74f3afdd309dbf2",
        "ap-southeast-3": "ami-091f9d0adaa612bfb",
        "ap-southeast-4": "ami-0ccc7ff1fcaf16948",
        "us-east-1": "ami-0c470d0e3eaf16e67",
        "us-east-2": "ami-02a7417ff5d866f4b"
      }
    },
    "images-by-group": {}
  }

The output shows the published image IDs for each region. Since those images are not
public, they can only be used from within the same account.

.. note::
   The command can be run again without publishing anything new as long as the source path file
   and the config itself doesn't change.


Multiple images
~~~~~~~~~~~~~~~

It's possible to publish multiple images based on the same VMDK file. The configuration looks like:

.. literalinclude:: ../config-samples/config-multiple-images.yaml
   :language: yaml

Running `awspub` using this config file will publish two images in two different regions.

.. code-block:: shell

  awspub --log-file awspub.log create config.yaml
  {
    "images": {
      "my-custom-image": {
        "eu-central-1": "ami-0b9ed498e040c69e2"
      },
      "my-custom-image-2": {
        "eu-central-2": "ami-03889118047373658"
      }
    },
    "images-by-group": {}
  }

Parameter substitution
~~~~~~~~~~~~~~~~~~~~~~

There are cases where parts of the configuration file need to be dynamic. To support that
`awspub` provides basic template substitution (based on Python's `string.Template class <https://docs.python.org/3/library/string.html#template-strings>`_) .

.. literalinclude:: ../config-samples/config-with-parameters.yaml
   :language: yaml

In the config file shown above, the identifier `$serial` which will be replaced with a value that
is defined in another YAML file. This YAML file (say ``config-mapping.yaml``) contains a mapping
structure (dict in python) that maps the identifiers.

.. literalinclude:: ../config-samples/config-with-parameters.yaml.mapping
   :language: yaml

Using both of these config files, the command for `awspub` becomes:

.. code-block:: shell

  awspub --log-file awspub.log create config.yaml --config-mapping config-mapping.yaml                
  {
    "images": {
      "my-custom-image-20171022": {
        "eu-central-1": "ami-0df443d5919e31d1b"
      }
    },
    "images-by-group": {}
  }


Image groups
~~~~~~~~~~~~

There might be cases were the different commands (e.g. `awspub create` or `awspub publish`)
should only be applied on a subset of the defined images. That's possible with the `groups`
config option:

.. literalinclude:: ../config-samples/config-minimal-groups.yaml
   :language: yaml

Use the ``--group`` parameter to filter the images that the `awspub` command should operate on:

.. code-block:: shell

  awspub --log-file awspub.log create config.yaml --group group1
  {
    "images": {
      "my-custom-image-1": {
        "us-west-1": "ami-09461116d07dd6604"
      }
    },
    "images-by-group": {
      "group1": {
        "my-custom-image-1": {
          "us-west-1": "ami-09461116d07dd6604"
        }
      }
    }
  }

  awspub --log-file awspub.log create config.yaml --group group2
  {
    "images": {
      "my-custom-image-2": {
        "us-east-1": "ami-018539227554e51fe",
        "ca-central-1": "ami-071d3602417c28201"
      }
    },
    "images-by-group": {
      "group2": {
        "my-custom-image-2": {
          "us-east-1": "ami-018539227554e51fe",
          "ca-central-1": "ami-071d3602417c28201"
        }
      }
    }
  }

The first command is applied only to images defined in `group1`, while the second one is applied
only to images defined within `group2`.

.. note::
   If no `--group` parameter is given, the different commands operate on **all** defined images.


Publish images
~~~~~~~~~~~~~~

To make images public, the configuration needs to have the `public` flag set for
each image that needs to be public.

.. literalinclude:: ../config-samples/config-minimal-public.yaml
   :language: yaml

The image needs to be created and then published:

.. code-block:: shell

  awspub create config.yaml
  awspub publish config.yaml

Sharing images
~~~~~~~~~~~~~~

Images can be shared with other AWS accounts. For that, the account IDs of the other accounts are needed.

.. literalinclude:: ../config-samples/config-minimal-share.yaml
   :language: yaml

In the above example, the image `my-custom-image` will be shared with the account `1234567890123`
when `awspub` runs in the commercial partition (``aws``, the default). It'll be shared
with the account `456789012345` when `awspub` runs in the the china partition (``aws-cn``).

AWS Marketplace
~~~~~~~~~~~~~~~

It's possible to publish to `AWS Marketplace <https://docs.aws.amazon.com/marketplace/latest/userguide/user-guide-for-sellers.html>`_ if an entity of a `Single-AMI product <https://docs.aws.amazon.com/marketplace/latest/userguide/ami-single-ami-products.html>`_ already exists, an access role ARN is available and an AMI exists in the `us-east-1` region. 

.. literalinclude:: ../config-samples/config-minimal-marketplace.yaml
   :language: yaml

The image needs to be created first and the `publish` command will request a new Marketplace version
for the given entity:

.. code-block:: shell

  awspub create config.yaml
  awspub publish config.yaml

SSM Parameter Store
~~~~~~~~~~~~~~~~~~~

It's possible to push information about published images to the `SSM Parameter Store <https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html>`_. That's
useful e.g. to have a common way to get the latest image ID on different
regions. To push image information to the parameter store, the ``ssm_parameter``
configuration for each image must be filled:

.. literalinclude:: ../config-samples/config-minimal-ssm.yaml
   :language: yaml

along with a corresponding mapping file:

.. literalinclude:: ../config-samples/config-minimal-ssm.yaml.mapping
   :language: yaml

Create the image and use the `publish` command to publish the image and also push information to the parameter store:

.. code-block:: shell

  awspub create config.yaml --config-mapping config.yaml.mapping
  awspub publish config.yaml --config-mapping config.yaml.mapping

SNS Notification
~~~~~~~~~~~~~~~~

It's possible to publish messages through the `Simple Notification Service (SNS) <https://docs.aws.amazon.com/sns/latest/dg/welcome.html>`_.
Delivery to multiple topics is possible, but the topics need to exist in each of the regions where the notification will be sent.

To notify image information to users, the ``sns`` configuration for each image must be filled:

.. literalinclude:: ../config-samples/config-minimal-sns.yaml
   :language: yaml

along with a corresponding mapping file:

.. literalinclude:: ../config-samples/config-minimal-sns.yaml.mapping
   :language: yaml

Currently, the supported protocols are ``default`` and ``email`` only, and the ``default`` key is required to 
send notifications.
The ``default`` message will be used as a fallback message for any protocols.

Also, Regions can also be specified in ``sns`` configuration to indicate where the notification should be sent. If no regions are specified, SNS will default to using all regions in the partition.

Create the image and use the `publish` command to publish the image and also notify the published images to users:

.. code-block:: shell

  awspub create config.yaml --config-mapping config.yaml.mapping
  awspub publish config.yaml --config-mapping config.yaml.mapping

Resource tags
~~~~~~~~~~~~~

The different AWS resources (S3 objects, snapshots and AMIs) can have tags associated with them.
`awspub` defines some base tags which are prefixed with `awspub:`.
In addition to those tags, there's a `tags` config where tags
for all resources can be defined:

.. literalinclude:: ../config-samples/config-minimal-tags.yaml
   :language: yaml

This config will add the tag(s) defined to all resources.
It's also possible to define image specific tags:

.. literalinclude:: ../config-samples/config-minimal-image-tags.yaml
   :language: yaml

"my-custom-image-1" would have the common tag "tag-key" plus the image specific
tag "key1".
"my-custom-image-2" would have the common tag "tag-key" but the value would be
overwritten with "another-value" because image specific tags override the common tags.
