How to publish images
=====================

To publish a VMDK file as an image (AMI) on AWS EC2 with `awspub`,
a config file is required.
A basic config file looks like:

.. literalinclude:: config-samples/config-minimal.yaml
   :language: yaml


Calling now `awspub` to publish the image with the name `my-custom-image`.

.. code-block:: shell

  awspub create config.yaml
  [snipped output]
  {
    "images": {
      "my-custom-image": {
        "ap-south-2": "ami-09559735ad8b1761d",
        "ap-south-1": "ami-02e2094cfd8b42949",
        "eu-south-1": "ami-06cfa6dcd995d5150",
        "eu-south-2": "ami-01d97f93afb5e98a2",
        "me-central-1": "ami-05a0d68fe810e87e4",
        "il-central-1": "ami-072764990baa35777",
        "ca-central-1": "ami-0759edbde42f0a949",
        "eu-central-1": "ami-0f4de621d30b1b0c2",
        "eu-central-2": "ami-05f98e7422d7f404f",
        "us-west-1": "ami-05746ce8a07b4c85e",
        "us-west-2": "ami-0d823cf81bf9bf104",
        "af-south-1": "ami-0e1a9da16c0d961f1",
        "eu-north-1": "ami-0433695e2c7f30543",
        "eu-west-3": "ami-047e60506ddc081f4",
        "eu-west-2": "ami-0788cc3de6c23ec30",
        "eu-west-1": "ami-0f6ae173f20f3ea90",
        "ap-northeast-3": "ami-068b9688c5dfd6849",
        "ap-northeast-2": "ami-0263f347b044130f0",
        "me-south-1": "ami-0eb49224ec76b84a4",
        "ap-northeast-1": "ami-0ec9a6c229f99542b",
        "sa-east-1": "ami-034ef8539bd913dab",
        "ap-east-1": "ami-0d591e1a25fc8a3fc",
        "ap-southeast-1": "ami-056f8946746cbc928",
        "ap-southeast-2": "ami-08171f5e219711961",
        "ap-southeast-3": "ami-03719171326b5b50b",
        "ap-southeast-4": "ami-05e7e801da60f4054",
        "us-east-1": "ami-06e2de427bb61cdb8",
        "us-east-2": "ami-011d41b2eeb9135bd"
      }
    }
  }

The output shows the published image IDs for each region. Those images are not
public so can only be used from within the same account.

.. note::
   The command can be run again without publishing anything new as long as the source path file
   and the config itself doesn't change.


Multiple images
~~~~~~~~~~~~~~~

It's possible to publish multiple images based on the same VMDK file. The configuration looks like:

.. literalinclude:: config-samples/config-multiple-images.yaml
   :language: yaml

Running `awspub` now will publish 2 images in 2 different regions.

.. code-block:: shell

  awspub --log-file awspub.log create config.yaml
  {
    "images": {
      "my-custom-image": {
        "eu-central-1": "ami-0f4de621d30b1b0c2"
      },
      "my-custom-image-2": {
        "eu-central-2": "ami-0e2350a74c9e6e5c4"
      }
    }
  }

Parameter substitution
~~~~~~~~~~~~~~~~~~~~~~

There are cases where part of the configuration file needs to be dynamic.
`awspub` supports basic template substitution (based on Pythons `string.Template class <https://docs.python.org/3/library/string.html#template-strings>`_) .

.. literalinclude:: config-samples/config-with-parameters.yaml
   :language: yaml

In this config, the identifier which will be replaced is `$serial`. The mapping
that is used to replace an identifier with a actual value is also a yaml file
which contains a mapping structure (dict in Python) that maps identifiers
to values:

.. literalinclude:: config-samples/config-with-parameters.yaml.mapping
   :language: yaml

Using both together now with `awspub`:

.. code-block:: shell

  awspub --log-file awspub.log create config.yaml --config-mapping config-mapping.yaml                
  {
    "images": {
      "my-custom-image-20171022": {
        "eu-central-1": "ami-0df443d5919e31d1b"
      }
    }
  }


Image groups
~~~~~~~~~~~~

There might be cases were the different commands (eg. `awspub create` or `awspub publish`)
should only be applied for a subset of the defined images. That's possible with the `group`
config option:

.. literalinclude:: config-samples/config-minimal-groups.yaml
   :language: yaml

Now the different `awspub` commands do have a `--group` parameter to filter which
images this command should operate on:

.. code-block:: shell

  awspub --log-file awspub.log create configyaml --group group1
  {
    "images": {
      "my-custom-image-1": {
        "us-west-1": "ami-09461116d07dd6604"
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
    }
  }


So the first command only works with images defined in `group1` while the second command only with
images defined within `group2`.

.. note::
   If no `--group` parameter is given, the different commands operate on **all** defined images.


Public images
~~~~~~~~~~~~~

To make images public, the configuration needs to have the `public` flag set for
each image that needs to be public.

.. literalinclude:: config-samples/config-minimal-public.yaml
   :language: yaml

The the image needs to be created and published:

.. code-block:: shell

  awspub create config.yaml
  awspub public config.yaml


Resource tags
~~~~~~~~~~~~~

The different resources (S3 objects, snapshots and AMIs) can have tags.
`awspub` defines some base tags which are prefixed with `awspub:`.
In addition to those tags, there's a `tags` config where tags
for all resources can be defined:

.. literalinclude:: config-samples/config-minimal-tags.yaml
   :language: yaml

This config will add the tag(s) defined to all resources.
It's also possible to define image specific tags:

.. literalinclude:: config-samples/config-minimal-image-tags.yaml
   :language: yaml

"my-custom-image-1" would have the common tag "tag-key" plus the image specific
tag "key1".
"my-custom-image-2" would have the common tag "tag-key" but the value would be
overwritten with "another-value" because image specific tags override the common tags.
